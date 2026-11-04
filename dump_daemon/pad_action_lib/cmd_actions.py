"""`Cmd.Actions`(持続的な対話セッション)のロジック層。

ワンショット実行ではなく、`cmd.exe`を標準入出力リダイレクト付きで起動してプロセスを
保持し続けるモデル——Pythonの`subprocess.Popen`(stdin/stdout/stderr=PIPE、persistent)
にそのまま対応する。stdout/stderrを同時に非ブロッキングで読むため、素朴な`readline()`
ループ(デッドロックしうる)ではなくバックグラウンドの読み取りスレッド+キューを使う。

このモジュール自体はシェルコマンドを決め打ちしない(`shell_command`で注入可能)——
実機でのPAD実行対象は`cmd.exe`(Windows専用)だが、このロジック層自体はOS非依存の
テストが書けるようにしている。
"""
from __future__ import annotations

import queue
import re
import subprocess
import threading
import time
from pathlib import Path

from .errors import PadActionError

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
    encoding: str = "utf-8",
    *,
    shell_command: list[str] | None = None,
) -> CmdSession:
    if directory is not None and not Path(directory).is_dir():
        raise WorkingDirectoryDoesNotExist(str(directory))
    command = shell_command if shell_command is not None else ["cmd.exe"]
    try:
        process = subprocess.Popen(
            command,
            cwd=directory,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=encoding,
            bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise OpenCmdError(str(exc)) from exc
    session = CmdSession(process)
    if change_code_page:
        # ChangeCodePageなら最初のコマンドとして`chcp <codepage>`を送信する。
        session.write(f"chcp {encoding}", send_enter=True)
    return session
