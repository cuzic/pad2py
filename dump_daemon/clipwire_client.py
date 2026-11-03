"""clipwire(対話的Windowsセッション内で動くリモート実行デーモン)のHTTPクライアント。

design/ci_verification_findings.md で確認した通り、WinRM経由のコマンド実行は
非対話的セッションで動くため、実際のデスクトップ(PADのウィンドウ等)にアクセスできない。
clipwire.exe を対話的RDPセッション内で起動しておけば、その`/exec`で生成される子プロセスは
同じウィンドウステーションを継承するため、スクリーンショット・UIAツリー走査・pywinautoによる
実際のウィンドウ操作が可能になる。

このモジュールは、clipwireの`/register`・`/exec`エンドポイントを呼び出し、
PowerShellの `-EncodedCommand` 経由でスクリプトを実行するための薄いラッパーを提供する。
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ClipwireClient:
    """clipwireサーバーへのHTTPクライアント。

    base_url: 例 "http://100.78.219.30:9999" (Tailscale IP) または
              "http://localhost:19999" (IAPトンネル経由)。
    token: サーバー起動時の CLIPD_TOKEN と一致させる。
    """

    base_url: str
    token: str

    def _headers(self, content_type: str | None = "application/json") -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.token}"}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def health(self) -> bool:
        import httpx

        resp = httpx.get(f"{self.base_url}/health", timeout=10)
        return resp.status_code == 200

    def register_powershell_target(
        self,
        name: str,
        ps_script: str,
        timeout: str = "30s",
    ) -> dict[str, Any]:
        """PowerShellスクリプトを -EncodedCommand 化してターゲット登録する。

        -EncodedCommand を使うことで、JSON/シェルのクォーティング問題を回避できる。
        """
        import httpx

        encoded = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")
        payload = {
            "name": name,
            "target": {
                "steps": [["powershell", "-NoProfile", "-EncodedCommand", encoded]],
                "timeout": timeout,
            },
        }
        resp = httpx.post(
            f"{self.base_url}/register",
            headers=self._headers(),
            content=json.dumps(payload),
            timeout=30,
        )
        resp.raise_for_status()
        return {"status_code": resp.status_code, "text": resp.text}

    def exec_target(self, name: str, timeout: float = 60.0) -> "ExecResult":
        import httpx

        resp = httpx.post(
            f"{self.base_url}/exec",
            headers=self._headers(),
            content=json.dumps({"name": name}),
            timeout=timeout,
        )
        return ExecResult(
            status_code=resp.status_code,
            exit_code=resp.headers.get("x-exit-code"),
            job_state=resp.headers.get("x-job-state"),
            raw_text=resp.text,
        )

    def exec_screenshot(self, name: str = "screenshot", timeout: float = 60.0) -> bytes:
        """スクリーンショット用ターゲットを実行し、デコード済みPNGバイト列を返す。

        対象ターゲットは、スクリーンショットをBase64文字列として標準出力に書き出す
        PowerShellスクリプトである前提(register_powershell_targetで事前登録しておく)。
        """
        result = self.exec_target(name, timeout=timeout)
        return result.extract_png()


@dataclass
class ExecResult:
    status_code: int
    exit_code: str | None
    job_state: str | None
    raw_text: str

    def extract_base64_payload(self) -> str:
        """Windows PowerShellの出力に混入するCLIXML進捗ストリームを取り除き、
        標準出力のBase64本体だけを取り出す。

        実機検証で判明した挙動: `powershell -EncodedCommand` 経由の出力は、
        `#< CLIXML` ヘッダーに続けてBase64本体が来て、末尾にCLIXMLの
        `<Objs ...>...</Objs>` 進捗ブロックが付加される(ストリームが混在するため)。
        """
        body = self.raw_text.split("#< CLIXML", 1)[-1].lstrip("\r\n")
        xml_start = body.find("<Objs")
        if xml_start != -1:
            body = body[:xml_start]
        return body.strip()

    def extract_png(self) -> bytes:
        data = base64.b64decode(self.extract_base64_payload())
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("デコード結果がPNGシグネチャと一致しない")
        return data

    def save_png(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_bytes(self.extract_png())
        return path
