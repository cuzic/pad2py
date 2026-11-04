"""`Web.Actions`(DownloadFromWeb/InvokeWebServiceBase/InvokeSoapServiceAction)のロジック層。

生の`HttpWebRequest`/`HttpWebResponse`ベース。この層はプロジェクトが既に依存している
`httpx`で実装する(新規HTTPクライアント依存を増やさない)。

`UserAgent`の既定値はデコンパイル調査で「ハードコードされたFirefox 3.6のUA文字列」と
分かっているが、その**正確なバイト列**は未確認のため、ここでは実在しない文字列を
でっち上げて埋め込むことはしない——`user_agent=None`(既定)は「PADの既定UAを再現しない」
を意味し、呼び出し側が実機確認済みの文字列を得たら明示的に渡す。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .errors import PadActionError


class DownloadFromWebError(PadActionError):
    pass


class DirectoryDoesNotExistError(PadActionError):
    pass


class InvokeWebServiceError(PadActionError):
    pass


class InvalidCustomHeaderError(PadActionError):
    pass


def _parse_custom_headers(text: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" not in line:
            raise InvalidCustomHeaderError(line)
        key, _, value = line.partition(":")
        headers[key.strip()] = value.strip()
    return headers


def download_from_web(
    url: str,
    method: str = "Get",
    parameters: dict[str, str] | None = None,
    save_response: str = "ToVariable",
    destination_path: str | None = None,
    follow_redirection: bool = True,
    connection_timeout: float = 30,
    user_agent: str | None = None,
    use_credentials: bool = False,
    username: str = "",
    password: str = "",
    encoding: str | None = None,
    accept_untrusted_certificates: bool = False,
    *,
    client: httpx.Client | None = None,
) -> str | None:
    headers = {"User-Agent": user_agent} if user_agent else {}
    auth = (username, password) if use_credentials else None
    owns_client = client is None
    http_client = client or httpx.Client(
        follow_redirects=follow_redirection,
        verify=not accept_untrusted_certificates,
        timeout=connection_timeout,
        auth=auth,
    )
    try:
        if method == "Post":
            response = http_client.post(url, data=parameters or {}, headers=headers)
        else:
            response = http_client.get(url, params=parameters or {}, headers=headers)
        if encoding:
            response.encoding = encoding
        if save_response == "ToFile":
            if destination_path is None:
                raise DownloadFromWebError("destination_path is required when SaveResponse=ToFile")
            dest = Path(destination_path)
            if not dest.parent.is_dir():
                raise DirectoryDoesNotExistError(str(dest.parent))
            dest.write_bytes(response.content)
            return None
        return response.text
    except httpx.HTTPError as exc:
        raise DownloadFromWebError(str(exc)) from exc
    finally:
        if owns_client:
            http_client.close()


@dataclass(frozen=True)
class InvokeWebServiceResult:
    response: str
    response_headers: list[str] = field(default_factory=list)
    status_code: int = 0
    downloaded_file: str | None = None


def invoke_web_service(
    url: str,
    method: str = "Get",
    accept: str = "application/xml",
    content_type: str = "application/xml",
    custom_headers: str = "",
    request_body: str = "",
    fail_on_error_status: bool = False,
    trim_request_body: bool = True,
    use_credentials: bool = False,
    username: str = "",
    password: str = "",
    connection_timeout: float = 30,
    accept_untrusted_certificates: bool = False,
    *,
    client: httpx.Client | None = None,
) -> InvokeWebServiceResult:
    headers = _parse_custom_headers(custom_headers)
    headers.setdefault("Accept", accept)
    if content_type:
        headers.setdefault("Content-Type", content_type)
    body = request_body.strip() if trim_request_body else request_body
    auth = (username, password) if use_credentials else None
    owns_client = client is None
    http_client = client or httpx.Client(
        timeout=connection_timeout, auth=auth, verify=not accept_untrusted_certificates
    )
    try:
        response = http_client.request(
            method.upper(), url, headers=headers, content=body.encode("utf-8") if body else None
        )
        if fail_on_error_status:
            response.raise_for_status()
        return InvokeWebServiceResult(
            response=response.text,
            response_headers=[f"{k}: {v}" for k, v in response.headers.items()],
            status_code=response.status_code,
        )
    except httpx.HTTPError as exc:
        raise InvokeWebServiceError(str(exc)) from exc
    finally:
        if owns_client:
            http_client.close()


def invoke_soap_service(
    endpoint: str,
    request_body: str = "",
    custom_headers: str = "",
    connection_timeout: float = 30,
    *,
    client: httpx.Client | None = None,
) -> InvokeWebServiceResult:
    # SOAPエンベロープ構築ロジックは無く、単純なPOSTの薄いラッパー。
    return invoke_web_service(
        endpoint,
        method="Post",
        content_type="text/xml",
        custom_headers=custom_headers,
        request_body=request_body,
        connection_timeout=connection_timeout,
        client=client,
    )
