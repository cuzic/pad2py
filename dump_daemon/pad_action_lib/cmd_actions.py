"""`Cmd.Actions`(持続的な対話セッション)のロジック層。

ワンショット実行ではなく、`cmd.exe`を標準入出力リダイレクト付きで起動してプロセスを
保持し続けるモデル——Pythonの`subprocess.Popen`(stdin/stdout/stderr=PIPE、persistent)
にそのまま対応する。stdout/stderrを同時に非ブロッキングで読むため、素朴な`readline()`
ループ(デッドロックしうる)ではなくバックグラウンドの読み取りスレッド+キューを使う。

このモジュール自体はシェルコマンドを決め打ちしない(`shell_command`で注入可能)——
実機でのPAD実行対象は`cmd.exe`(Windows専用)だが、このロジック層自体はOS非依存の
テストが書けるようにしている。

知見153(decompile+リフレクション確認済み): `OpenWithCodePage`の`Encoding`パラメータは
単純な文字列ではなく`Microsoft.Flow.RPA.Desktop.Robin.Shared.Runtime.Enums.Encoding`
という専用の列挙型で、各メンバーの基底`int`値がそのままWindowsのコードページ番号
(`utf_8=65001`・`shift_jis=932`等)になっている。`Cmd.Actions.dll`をdecompileした
`OpenCmdSession()`の実装は: `ChangeCodePage=True`の場合のみ`Encoding.GetEncoding(
(int)Encoding)`で`StandardOutputEncoding`/`StandardErrorEncoding`を設定し、プロセス
起動後に`chcp <コードページ番号そのもの>`(コーデック名ではなく整数)を最初のコマンドとして
送信する。`ChangeCodePage=False`(`Open`)の場合は`Encoding`パラメータ自体がDSL上に
存在せず(`Hide<Encoding>()`で隠されている)、常に`Encoding.Default`(OS既定のANSI
コードページ)が使われる。`_ENCODING_CODEPAGES`はこの列挙型の全メンバーをそのまま
転記したもの(でっち上げではなく実機リフレクションの直接確認結果)。
"""
from __future__ import annotations

import queue
import re
import subprocess
import threading
import time
from pathlib import Path

from .errors import PadActionError

# 知見153: `Microsoft.Flow.RPA.Desktop.Robin.Shared.Runtime.Enums.Encoding`の全メンバー
# (列挙名→Windowsコードページ番号)。VM上のリフレクションで確認済み。
_ENCODING_CODEPAGES: dict[str, int] = {
    "IBM037": 37, "IBM437": 437, "IBM500": 500, "ASMO_708": 708, "DOS_720": 720,
    "ibm737": 737, "ibm775": 775, "ibm850": 850, "ibm852": 852, "IBM855": 855,
    "ibm857": 857, "IBM00858": 858, "IBM860": 860, "ibm861": 861, "DOS_862": 862,
    "IBM863": 863, "IBM864": 864, "IBM865": 865, "cp866": 866, "ibm869": 869,
    "IBM870": 870, "windows_874": 874, "cp875": 875, "shift_jis": 932, "gb2312": 936,
    "ks_c_5601_1987": 949, "big5": 950, "IBM1026": 1026, "IBM01047": 1047,
    "IBM01140": 1140, "IBM01141": 1141, "IBM01142": 1142, "IBM01143": 1143,
    "IBM01144": 1144, "IBM01145": 1145, "IBM01146": 1146, "IBM01147": 1147,
    "IBM01148": 1148, "IBM01149": 1149, "utf_16": 1200, "utf_16BE": 1201,
    "windows_1250": 1250, "windows_1251": 1251, "Windows_1252": 1252,
    "windows_1253": 1253, "windows_1254": 1254, "windows_1255": 1255,
    "windows_1256": 1256, "windows_1257": 1257, "windows_1258": 1258, "Johab": 1361,
    "macintosh": 10000, "x_mac_japanese": 10001, "x_mac_chinesetrad": 10002,
    "x_mac_korean": 10003, "x_mac_arabic": 10004, "x_mac_hebrew": 10005,
    "x_mac_greek": 10006, "x_mac_cyrillic": 10007, "x_mac_chinesesimp": 10008,
    "x_mac_romanian": 10010, "x_mac_ukrainian": 10017, "x_mac_thai": 10021,
    "x_mac_ce": 10029, "x_mac_icelandic": 10079, "x_mac_turkish": 10081,
    "x_mac_croatian": 10082, "utf_32": 12000, "utf_32BE": 12001,
    "x_Chinese_CNS": 20000, "x_cp20001": 20001, "x_Chinese_Eten": 20002,
    "x_cp20003": 20003, "x_cp20004": 20004, "x_cp20005": 20005, "x_IA5": 20105,
    "x_IA5_German": 20106, "x_IA5_Swedish": 20107, "x_IA5_Norwegian": 20108,
    "us_ascii": 20127, "x_cp20261": 20261, "x_cp20269": 20269, "IBM273": 20273,
    "IBM277": 20277, "IBM278": 20278, "IBM280": 20280, "IBM284": 20284,
    "IBM285": 20285, "IBM290": 20290, "IBM297": 20297, "IBM420": 20420,
    "IBM423": 20423, "IBM424": 20424, "x_EBCDIC_KoreanExtended": 20833,
    "IBM_Thai": 20838, "koi8_r": 20866, "IBM871": 20871, "IBM880": 20880,
    "IBM905": 20905, "IBM00924": 20924, "EUC_JP_20932": 20932, "x_cp20936": 20936,
    "x_cp20949": 20949, "cp1025": 21025, "koi8_u": 21866, "iso_8859_1": 28591,
    "iso_8859_2": 28592, "iso_8859_3": 28593, "iso_8859_4": 28594, "iso_8859_5": 28595,
    "iso_8859_6": 28596, "iso_8859_7": 28597, "iso_8859_8": 28598, "iso_8859_9": 28599,
    "iso_8859_13": 28603, "iso_8859_15": 28605, "x_Europa": 29001,
    "iso_8859_8_i": 38598, "iso_2022_jp_50220": 50220, "csISO2022JP": 50221,
    "iso_2022_jp_50222": 50222, "iso_2022_kr": 50225, "x_cp50227": 50227,
    "euc_jp_51932": 51932, "EUC_CN": 51936, "euc_kr": 51949, "hz_gb_2312": 52936,
    "GB18030": 54936, "x_iscii_de": 57002, "x_iscii_be": 57003, "x_iscii_ta": 57004,
    "x_iscii_te": 57005, "x_iscii_as": 57006, "x_iscii_or": 57007, "x_iscii_ka": 57008,
    "x_iscii_ma": 57009, "x_iscii_gu": 57010, "x_iscii_pa": 57011, "utf_7": 65000,
    "utf_8": 65001,
}

_POLL_INTERVAL = 0.05


class OpenCmdError(PadActionError):
    pass


class WorkingDirectoryDoesNotExist(PadActionError):
    pass


class SessionClosedError(PadActionError):
    pass


class WriteCmdError(PadActionError):
    pass


class TimeoutExpiredError(PadActionError):
    pass


class CmdSession:
    def __init__(self, process: subprocess.Popen) -> None:
        self._process = process
        self._closed = False
        self._stdout_queue: queue.Queue[str | None] = queue.Queue()
        self._stderr_queue: queue.Queue[str | None] = queue.Queue()
        self._threads = [
            threading.Thread(target=self._pump, args=(process.stdout, self._stdout_queue), daemon=True),
            threading.Thread(target=self._pump, args=(process.stderr, self._stderr_queue), daemon=True),
        ]
        for t in self._threads:
            t.start()

    @staticmethod
    def _pump(stream, q: "queue.Queue[str | None]") -> None:
        try:
            for line in iter(stream.readline, ""):
                q.put(line)
        finally:
            q.put(None)  # ストリーム終了を示す番兵(再度putして後続のdrainでも見えるようにする)

    def write(self, command: str, send_enter: bool = True) -> None:
        if self._closed or self._process.poll() is not None:
            raise SessionClosedError("cmd session is closed")
        try:
            self._process.stdin.write(command + ("\n" if send_enter else ""))
            self._process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise WriteCmdError(str(exc)) from exc

    def _drain(self, q: "queue.Queue[str | None]") -> str:
        lines: list[str] = []
        stream_closed = False
        while True:
            try:
                item = q.get_nowait()
            except queue.Empty:
                break
            if item is None:
                stream_closed = True
                continue
            lines.append(item)
        if stream_closed:
            q.put(None)  # 番兵を戻し、以後のdrainでもストリーム終了を検知できるようにする
        return "".join(lines)

    def read(self, split_output_and_error: bool = False) -> tuple[str, str] | str:
        stdout_text = self._drain(self._stdout_queue)
        stderr_text = self._drain(self._stderr_queue)
        if split_output_and_error:
            return stdout_text, stderr_text
        # falseだと標準出力・標準エラーを合流させてCmdOutputに入れる。
        return stdout_text + stderr_text

    def wait_for_text(
        self, text: str, timeout: float | None = 0, is_regex: bool = False, ignore_case: bool = False
    ) -> str:
        pattern = re.compile(text, re.IGNORECASE if ignore_case else 0) if is_regex else None
        buffer = ""
        start = time.monotonic()
        while True:
            buffer += self._drain(self._stdout_queue) + self._drain(self._stderr_queue)
            found = pattern.search(buffer) if pattern else (text in buffer)
            if found:
                return buffer
            # Timeoutが0/未指定は既知の[WaitAction]と同じ「無期限ポーリング」パターン。
            if timeout:
                if time.monotonic() - start > timeout:
                    raise TimeoutExpiredError(f"text {text!r} not seen within {timeout}s")
            time.sleep(_POLL_INTERVAL)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._process.terminate()
            self._process.wait(timeout=2)
        except Exception:
            pass  # ベストエフォートでプロセスを終了、失敗は静かに無視(TryFuncIgnoreException)


def open_cmd_session(
    directory: str | None = None,
    change_code_page: bool = False,
    encoding: str = "utf_8",
    *,
    shell_command: list[str] | None = None,
) -> CmdSession:
    if directory is not None and not Path(directory).is_dir():
        raise WorkingDirectoryDoesNotExist(str(directory))
    command = shell_command if shell_command is not None else ["cmd.exe"]
    if change_code_page:
        # 知見153(decompile確認済み): `encoding`は`Encoding`列挙型のメンバー名
        # (`_ENCODING_CODEPAGES`のキー)。実際のコードページ番号へ変換し、
        # Pythonの`cp<番号>`コーデック名として使う。
        codepage = _ENCODING_CODEPAGES.get(encoding)
        if codepage is None:
            raise OpenCmdError(f"Unsupported encoding: {encoding!r}")
        python_encoding = f"cp{codepage}"
    else:
        # `ChangeCodePage=False`(`Open`)では`Encoding`パラメータ自体がDSL上に
        # 存在せず、常にOS既定のANSIコードページ(`Encoding.Default`)が使われる
        # (知見153)。ホスト依存のため、安全な既定値として`utf-8`を使う。
        codepage = None
        python_encoding = "utf-8"
    try:
        process = subprocess.Popen(
            command,
            cwd=directory,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=python_encoding,
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, LookupError) as exc:
        raise OpenCmdError(str(exc)) from exc
    session = CmdSession(process)
    if change_code_page:
        # ChangeCodePageなら最初のコマンドとして`chcp <コードページ番号>`を送信する
        # (知見153: コーデック名ではなく整数のコードページ番号そのもの)。
        session.write(f"chcp {codepage}", send_enter=True)
    return session
