"""`Web.Actions`(DownloadFromWeb/InvokeWebServiceBase/InvokeSoapServiceAction)のロジック層。

生の`HttpWebRequest`/`HttpWebResponse`ベース。この層はプロジェクトが既に依存している
`httpx`で実装する(新規HTTPクライアント依存を増やさない)。

`UserAgent`の既定値は`tests/fixtures/tier1_web_xml_batch8.txt`の実機キャプチャで
正確なバイト列(`"Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.21) Gecko/
20100312 Firefox/3.6"`)まで確認済み——`DownloadFromWeb`/`InvokeWebService`/
`InvokeSoapService`いずれも同一の値だった。`pad_codegen`側は実機DSLに出現した
この文字列リテラルをそのまま渡すだけで、でっち上げる必要は無い。`user_agent=None`
(既定)は値が実機未確認の場合のための安全弁として残す。

`FollowRedirection`(実機既定`True`)は`invoke_web_service()`/`invoke_soap_service()`
では知見93以前は未対応(httpxの既定`follow_redirects=False`のまま食い違っていた)
だったが、`follow_redirection`引数を追加し`DownloadFromWeb`と同じ扱いに統一した。

`EncodeRequestBody`は知見96で`Microsoft.Flow.RPA.Desktop.Modules.Web.Actions.dll`
をdecompileして確認済み: `True`の場合、`RequestBody`全体に`HttpUtility.UrlEncode`
(`application/x-www-form-urlencoded`形式、空白は`+`——Pythonの`urllib.parse.
quote_plus()`と同じ規則)を適用してから`TrimRequestBody`の処理(文字列全体の
`.strip()`)を行う、という順序だった(実機確認では無くdecompileソースの直読みに
基づく、`EncodeRequestBody`自体は`InvokeWebService`のみに存在)。
"""
from __future__ import annotations

import urllib.parse
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
            # 知見129・130と同じパターン: `DownloadedFile`出力は呼び出し側が指定した
            # 保存先そのものを指す(他に特定する手段が無い)——Noneを返すと出力変数が
            # 常にNoneになる潜在バグになる。
            return str(dest)
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
    encode_request_body: bool = False,
    follow_redirection: bool = True,
    user_agent: str | None = None,
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
    if user_agent:
        headers.setdefault("User-Agent", user_agent)
    # design/dsl_format_findings.md 知見96(decompile確認済み): `EncodeRequestBody`は
    # `HttpUtility.UrlEncode(RequestBody)`(application/x-www-form-urlencoded形式、
    # 空白は`+`)を`TrimRequestBody`より先に適用する——両方`True`の場合、エンコード後の
    # 文字列をさらにtrimする(エンコード結果に空白は残らないため実害は無いが順序を再現)。
    body = urllib.parse.quote_plus(request_body) if encode_request_body else request_body
    body = body.strip() if trim_request_body else body
    auth = (username, password) if use_credentials else None
    owns_client = client is None
    http_client = client or httpx.Client(
        timeout=connection_timeout,
        auth=auth,
        verify=not accept_untrusted_certificates,
        follow_redirects=follow_redirection,
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
    follow_redirection: bool = True,
    user_agent: str | None = None,
    fail_on_error_status: bool = False,
    trim_request_body: bool = True,
    accept_untrusted_certificates: bool = False,
    use_credentials: bool = False,
    username: str = "",
    password: str = "",
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
        follow_redirection=follow_redirection,
        user_agent=user_agent,
        fail_on_error_status=fail_on_error_status,
        trim_request_body=trim_request_body,
        accept_untrusted_certificates=accept_untrusted_certificates,
        use_credentials=use_credentials,
        username=username,
        password=password,
        client=client,
    )
