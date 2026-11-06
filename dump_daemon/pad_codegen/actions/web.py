"""`Web.*`のcodegen。`pad_action_lib.web_actions`へ委譲する。

パラメータ名は design/dsl_format_findings.md 知見71で実機キャプチャした
`tests/fixtures/tier1_web_xml_batch8.txt`から確認済み。`Encoding:
Web.Encoding.AutoDetect`は「エンコーディングを強制しない」ことを意味するため、
`encoding`引数自体を渡さない(httpxの自動検出に委ねる)。

`UserAgent`(実機キャプチャで確認済みの固定UA文字列、`web_actions`モジュール
docstring参照)・`FollowRedirection`はDownloadFromWeb/InvokeWebService/
InvokeSoapServiceの全てで結線した(知見93以前は`invoke_web_service()`/
`invoke_soap_service()`が`follow_redirection`/`user_agent`を一切受け付けず、
httpxの既定`follow_redirects=False`のままPADの既定`True`と食い違っていた)。

`EncodeRequestBody`は知見96でdecompile確認済み(`HttpUtility.UrlEncode`相当、
`TrimRequestBody`より先に適用)のため`Web.InvokeWebService`で結線した
(`web_actions.invoke_web_service()`の`encode_request_body`引数に委譲)。
`InvokeSoapService`には存在しないパラメータ(SOAPボディは常にXMLのため不要)。

知見139・144(`ActionSelectorBase`一括列挙監査をWeb.Actions.dllに適用、VM上で
`DownloadFromWeb`クラスのプロパティ・`SaveResponse`/`DownloadMethod`/`FileName`
列挙値を確認): `Download`系12セレクタは全て**同一の`DownloadFromWeb`クラス**で、
`SaveResponse`(`ToVariable`/`ToFile`)×`Method`(`Get`/`Post`)×`UseCredentials`
(Boolean)の組み合わせをセレクタ自体が固定する。このうち`SaveResponse=ToFile`
かつ`FileName=SpecifyFullPath`(`FilePath`プロパティで直接パス指定)の8通り
(`ToVariable`/`ToFile`×`Get`/`Post`×認証有無)を既存の`download_from_web()`
(`save_response`/`destination_path`/`method`/`use_credentials`引数が元から
対応済み)で結線した。`FileName=KeepOriginal`(フォルダ指定+レスポンスから
ファイル名を自動決定、`DownloadToFolder`系4セレクタ)は、PADが実際に
どうファイル名を決定するか(Content-Dispositionヘッダ?URLパスの末尾?)が
実機/decompile未確認のため見送った——`download_from_web()`は呼び出し側が
渡した正確なパスへ書き込むだけで、ファイル名の自動決定ロジックは持たない。
副産物として、既存の`download_from_web()`が`SaveResponse=ToFile`時に常に`None`
を返していた(`DownloadedFile`出力が使われていなかったため今まで気づかれな
かった)潜在バグを発見・修正した——他の出力ファイルパス系アクション
(知見129のZipFile等)と同じ「呼び出し側が指定したパスをそのまま返す」規約に
揃えた。

`ClearCookies`は依然意図的に未対応としてフォールバックに委ねる(でっち上げを
避ける): 知見96のdecompileで`CompiledJob.CookieContainer`というフロー実行
全体で共有される永続的なCookieジャーの存在を確認した(`ClearCookies: True`で
リセットし、各レスポンスのCookieは常にこのジャーへ蓄積される)。`pad_action_lib`
側は呼び出し毎に新規`httpx.Client`を作る設計のためこのような永続化が無く、
対応するには`CodegenContext`へセッション状態を持たせる等の設計変更を伴う
大きな決定になるため、意味論が判明した今でも後回しにする。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Web."):
        return None
    prefix = INDENT * indent
    p = node.params

    # 知見139・144: `DownloadFromWeb`クラスの兄弟セレクタ8件(ToVariable/ToFile(exact
    # path)×Get/Post×認証有無)。既存の`Download`(ToVariable/Get/NoAuth)もこの
    # ディスパッチ表に統合する。
    _DOWNLOAD_VARIANTS = {
        "Web.DownloadFromWeb.Download": ("ToVariable", "Get", False),
        "Web.DownloadFromWeb.DownloadUseAuth": ("ToVariable", "Get", True),
        "Web.DownloadFromWeb.DownloadUsePost": ("ToVariable", "Post", False),
        "Web.DownloadFromWeb.DownloadUsePostAndAuth": ("ToVariable", "Post", True),
        "Web.DownloadFromWeb.DownloadToFile": ("ToFile", "Get", False),
        "Web.DownloadFromWeb.DownloadToFileUseAuth": ("ToFile", "Get", True),
        "Web.DownloadFromWeb.DownloadToFileUsePost": ("ToFile", "Post", False),
        "Web.DownloadFromWeb.DownloadToFileUsePostAndAuth": ("ToFile", "Post", True),
    }
    if action_id in _DOWNLOAD_VARIANTS:
        save_response, method, use_auth = _DOWNLOAD_VARIANTS[action_id]
        url = safe_render(p.get("Url"))
        timeout = safe_render(p.get("ConnectionTimeout"))
        follow = safe_render(p.get("FollowRedirection"))
        user_agent = safe_render(p.get("UserAgent"))
        accept_untrusted = safe_render(p.get("AcceptUntrustedCertificates"))
        encoding = enum_last(p.get("Encoding"))
        if None in (url, timeout, follow, user_agent, accept_untrusted, encoding):
            return None
        if encoding != "AutoDetect":
            return None
        extra_args = ""
        if method == "Post":
            extra_args += ", method='Post'"
        if use_auth:
            username = safe_render(p.get("UserName"))
            password = safe_render(p.get("Password"))
            if username is None or password is None:
                return None
            extra_args += f", use_credentials=True, username={username}, password={password}"
        if save_response == "ToFile":
            dest_var = node.output_vars.get("DownloadedFile")
            file_path = safe_render(p.get("FilePath"))
            if not dest_var or file_path is None:
                return None
            return [
                f"{prefix}{dest_var} = web_actions.download_from_web({url}, "
                f"save_response='ToFile', destination_path={file_path}, "
                f"connection_timeout={timeout}, follow_redirection={follow}, "
                f"user_agent={user_agent}, accept_untrusted_certificates={accept_untrusted}"
                f"{extra_args})"
            ]
        text_var = node.output_vars.get("WebPageText")
        if not text_var:
            return None
        return [
            f"{prefix}{text_var} = web_actions.download_from_web({url}, "
            f"connection_timeout={timeout}, follow_redirection={follow}, "
            f"user_agent={user_agent}, accept_untrusted_certificates={accept_untrusted}"
            f"{extra_args})"
        ]

    if action_id == "Web.InvokeWebService.InvokeWebService":
        url = safe_render(p.get("Url"))
        method = enum_last(p.get("Method"))
        accept = safe_render(p.get("Accept"))
        content_type = safe_render(p.get("ContentType"))
        custom_headers = safe_render(p.get("CustomHeaders"))
        request_body = safe_render(p.get("RequestBody"))
        timeout = safe_render(p.get("ConnectionTimeout"))
        fail_on_error = safe_render(p.get("FailOnErrorStatus"))
        trim_body = safe_render(p.get("TrimRequestBody"))
        encode_body = safe_render(p.get("EncodeRequestBody"))
        follow = safe_render(p.get("FollowRedirection"))
        user_agent = safe_render(p.get("UserAgent"))
        accept_untrusted = safe_render(p.get("AcceptUntrustedCertificates"))
        encoding = enum_last(p.get("Encoding"))
        values = (url, method, accept, content_type, custom_headers, request_body, timeout,
                  fail_on_error, trim_body, encode_body, follow, user_agent, accept_untrusted, encoding)
        if None in values:
            return None
        # DownloadFromWebと同じ扱い: `AutoDetect`は「エンコーディングを強制しない」こと
        # を意味するため確認のみ行い値は渡さない。他の値は実機確認が無いためTODOへ倒す
        # (従来はEncodingを一切読み取らず、設定されていても無条件に進めてしまっていた)。
        if encoding != "AutoDetect":
            return None
        response_var = node.output_vars.get("Response")
        headers_var = node.output_vars.get("ResponseHeaders")
        status_var = node.output_vars.get("StatusCode")
        if not (response_var or headers_var or status_var):
            return None
        tmp = "_web_service_result"
        lines = [
            f"{prefix}{tmp} = web_actions.invoke_web_service({url}, method={method!r}, "
            f"accept={accept}, content_type={content_type}, custom_headers={custom_headers}, "
            f"request_body={request_body}, connection_timeout={timeout}, "
            f"fail_on_error_status={fail_on_error}, trim_request_body={trim_body}, "
            f"encode_request_body={encode_body}, follow_redirection={follow}, "
            f"user_agent={user_agent}, accept_untrusted_certificates={accept_untrusted})"
        ]
        if response_var:
            lines.append(f"{prefix}{response_var} = {tmp}.response")
        if headers_var:
            lines.append(f"{prefix}{headers_var} = {tmp}.response_headers")
        if status_var:
            lines.append(f"{prefix}{status_var} = {tmp}.status_code")
        return lines

    if action_id == "Web.InvokeSoapService.InvokeSoapService":
        endpoint = safe_render(p.get("Endpoint"))
        custom_headers = safe_render(p.get("CustomHeaders"))
        request_body = safe_render(p.get("RequestBody"))
        timeout = safe_render(p.get("ConnectionTimeout"))
        follow = safe_render(p.get("FollowRedirection"))
        user_agent = safe_render(p.get("UserAgent"))
        fail_on_error = safe_render(p.get("FailOnErrorStatus"))
        trim_body = safe_render(p.get("TrimRequestBody"))
        accept_untrusted = safe_render(p.get("AcceptUntrustedCertificates"))
        encoding = enum_last(p.get("Encoding"))
        values = (endpoint, custom_headers, request_body, timeout, follow, user_agent,
                  fail_on_error, trim_body, accept_untrusted, encoding)
        if None in values:
            return None
        if encoding != "AutoDetect":
            return None
        response_var = node.output_vars.get("Response")
        headers_var = node.output_vars.get("ResponseHeaders")
        status_var = node.output_vars.get("StatusCode")
        if not (response_var or headers_var or status_var):
            return None
        tmp = "_soap_service_result"
        lines = [
            f"{prefix}{tmp} = web_actions.invoke_soap_service({endpoint}, "
            f"request_body={request_body}, custom_headers={custom_headers}, "
            f"connection_timeout={timeout}, follow_redirection={follow}, "
            f"user_agent={user_agent}, fail_on_error_status={fail_on_error}, "
            f"trim_request_body={trim_body}, accept_untrusted_certificates={accept_untrusted})"
        ]
        if response_var:
            lines.append(f"{prefix}{response_var} = {tmp}.response")
        if headers_var:
            lines.append(f"{prefix}{headers_var} = {tmp}.response_headers")
        if status_var:
            lines.append(f"{prefix}{status_var} = {tmp}.status_code")
        return lines

    return None
