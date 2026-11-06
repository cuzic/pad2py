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

知見152(decompileソース直読み): `SaveResponse=ToFile`かつ`FileName=KeepOriginal`
(`DownloadToFolder`/`InvokeWebService*SaveToFolder*`系)のファイル名自動決定は、
`WebActions.GetDownloadFilePath()`の実装を`_get_download_file_path()`として
そのまま再現した——`Content-Disposition`ヘッダの`filename=`を最優先し、無ければ
レスポンスURLの最後のパスセグメント、ルートパス(`/`)の場合はホスト名+`.html`に
フォールバックする。ファイル名のサニタイズ処理自体(`Utilities.SanitizeFileName`)
は別の共有SDK DLLにあり未decompileのため、Windowsのファイル名として不正な文字集合
(`Path.GetInvalidFileNameChars()`相当)を`_`に置換する一般的な実装で代替した
——これだけが実機/decompile未確認の箇所であることを明記する。

知見152(decompileソース直読み): `UploadAttachments=True`系(`InvokeWebService*
Upload`接尾辞、12セレクタ)は`WebActions.FormulateWebRequest()`内のmultipart/
form-data構築ロジックをそのまま再現した——`Attachments`(`NAME`/`ATTACHMENT`列の
DataTable)の各行を`--<boundary>\r\n`区切り・`Content-Type: application/
octet-stream`固定のパートとして書き出す。`UploadType.FilePath`(ファイルパスから
読み込む)のみ実装し、`UploadType.Binary`(`BinaryObject`型の変数)はこのプロジェクト
に`BinaryObject`相当の型が無いため未実装でTODOへ倒す。
"""
from __future__ import annotations

import re
import time
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


class EmptyAttachmentsError(PadActionError):
    pass


_INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_file_name(name: str, replacement: str = "_") -> str:
    return _INVALID_FILENAME_CHARS_RE.sub(replacement, name)


def _get_download_file_path(
    response: httpx.Response,
    keep_original_file_name: bool,
    destination_folder: str | None,
    file_path: str | None,
) -> str:
    """`WebActions.GetDownloadFilePath()`(decompile確認済み、知見152)の再現。"""
    if not keep_original_file_name:
        return file_path  # type: ignore[return-value]
    extension = ""
    file_name = ""
    content_disposition = response.headers.get("Content-Disposition")
    if content_disposition:
        match = re.search(
            r'filename\s*\*?=(?:\s*UTF-\d+)?\s*"([^"]*)"', content_disposition, re.IGNORECASE
        )
        file_name = match.group(1) if match else ""
    if not file_name:
        path = response.url.path or "/"
        if path == "/":
            extension = ".html"
            file_name = response.url.host
        elif path.endswith("/"):
            # セルフレビューで発見: .NETの`Uri.Segments`は末尾が`/`の非ルートパス
            # (例: "/downloads/")でも最後のセグメント自体に末尾の`/`を含める
            # (segments=["/", "downloads/"])——`rsplit("/", 1)[-1]`だけだと空文字列に
            # なってしまう(`_sanitize_file_name()`で`/`自体はどちらにせよ`_`に置換
            # されるため、最終的な見た目は`downloads_`になる)。
            file_name = path[:-1].rsplit("/", 1)[-1] + "/"
        else:
            file_name = path.rsplit("/", 1)[-1]
    file_name = _sanitize_file_name(file_name)
    return str(Path(destination_folder) / (file_name + extension))  # type: ignore[arg-type]


def _build_multipart_body(attachments: list[dict[str, object]], upload_type: str) -> tuple[bytes, str]:
    """`WebActions.FormulateWebRequest()`のmultipart/form-data構築(decompile確認済み、知見152)の再現。"""
    boundary = "---------------------------" + format(time.time_ns() // 100, "x")
    parts: list[bytes] = []
    for row in attachments:
        name = row.get("NAME")
        if upload_type == "FilePath":
            path = str(row.get("ATTACHMENT"))
            file_name = Path(path).name
            data = Path(path).read_bytes()
        else:
            raise InvokeWebServiceError(f"Unsupported UploadType: {upload_type!r}")
        disposition = f'form-data; name="{name}"; filename="{file_name}"'
        header = f"Content-Disposition: {disposition}\r\nContent-Type: application/octet-stream\r\n\r\n"
        parts.append(f"--{boundary}\r\n".encode("utf-8") + header.encode("utf-8") + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), boundary


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
    destination_folder: str | None = None,
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
            if destination_folder is not None:
                # 知見152(decompile確認済み): `DownloadToFolder`系(`FileName=KeepOriginal`)
                # はContent-Disposition/URLからファイル名を自動決定する。
                dest_path = _get_download_file_path(response, True, destination_folder, None)
            elif destination_path is not None:
                dest_path = destination_path
            else:
                raise DownloadFromWebError(
                    "destination_path or destination_folder is required when SaveResponse=ToFile"
                )
            dest = Path(dest_path)
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
    save_response: str = "ToVariable",
    destination_path: str | None = None,
    destination_folder: str | None = None,
    upload_attachments: bool = False,
    attachments: list[dict[str, object]] | None = None,
    upload_type: str = "FilePath",
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
        if upload_attachments and method.upper() in ("POST", "PUT"):
            # design/dsl_format_findings.md 知見152(decompile確認済み): `UploadAttachments`
            # はmultipart/form-dataでContentTypeを上書きし、RequestBodyは送らない。
            if not attachments:
                raise EmptyAttachmentsError("attachments must be non-empty when upload_attachments=True")
            content, boundary = _build_multipart_body(attachments, upload_type)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        else:
            content = body.encode("utf-8") if body else None
        response = http_client.request(method.upper(), url, headers=headers, content=content)
        if fail_on_error_status:
            response.raise_for_status()
        downloaded_file = None
        if save_response == "ToFile":
            # design/dsl_format_findings.md 知見144・150・152と同じパターン
            # (`download_from_web()`の`SaveResponse=ToFile`): `DownloadedFile`出力は
            # 呼び出し側が指定したパスをそのまま返す。`destination_folder`が指定された
            # 場合(`SaveToFolder`系)はContent-Disposition/URLからファイル名を自動決定する。
            if destination_folder is not None:
                dest_path = _get_download_file_path(response, True, destination_folder, None)
            elif destination_path is not None:
                dest_path = destination_path
            else:
                raise InvokeWebServiceError(
                    "destination_path or destination_folder is required when save_response=ToFile"
                )
            dest = Path(dest_path)
            if not dest.parent.is_dir():
                raise DirectoryDoesNotExistError(str(dest.parent))
            dest.write_bytes(response.content)
            downloaded_file = str(dest)
        return InvokeWebServiceResult(
            response=response.text,
            response_headers=[f"{k}: {v}" for k, v in response.headers.items()],
            status_code=response.status_code,
            downloaded_file=downloaded_file,
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
