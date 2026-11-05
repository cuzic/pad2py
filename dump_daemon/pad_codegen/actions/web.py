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

`ClearCookies`/`EncodeRequestBody`は依然意図的に未対応としてフォールバックに
委ねる(でっち上げを避ける): `ClearCookies`はPAD側がフロー実行全体で永続的な
Cookieセッションを持つ前提の挙動と推測されるが、`pad_action_lib`側は呼び出し
毎に新規`httpx.Client`を作る設計のためそもそもCookie永続化という概念自体が
存在せず、安易に対応すると設計変更(`CodegenContext`へセッション状態を
持たせる等)を伴う大きな決定になる。`EncodeRequestBody`(リクエスト本文の
URLエンコード有無と推測)はdecompile調査が未着手のため意味論が未確認。
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

    if action_id == "Web.DownloadFromWeb.Download":
        url = safe_render(p.get("Url"))
        timeout = safe_render(p.get("ConnectionTimeout"))
        follow = safe_render(p.get("FollowRedirection"))
        user_agent = safe_render(p.get("UserAgent"))
        accept_untrusted = safe_render(p.get("AcceptUntrustedCertificates"))
        encoding = enum_last(p.get("Encoding"))
        if None in (url, timeout, follow, user_agent, accept_untrusted, encoding) or not node.output_var:
            return None
        if encoding != "AutoDetect":
            return None
        return [
            f"{prefix}{node.output_var} = web_actions.download_from_web({url}, "
            f"connection_timeout={timeout}, follow_redirection={follow}, "
            f"user_agent={user_agent}, accept_untrusted_certificates={accept_untrusted})"
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
        follow = safe_render(p.get("FollowRedirection"))
        user_agent = safe_render(p.get("UserAgent"))
        accept_untrusted = safe_render(p.get("AcceptUntrustedCertificates"))
        encoding = enum_last(p.get("Encoding"))
        values = (url, method, accept, content_type, custom_headers, request_body, timeout,
                  fail_on_error, trim_body, follow, user_agent, accept_untrusted, encoding)
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
            f"follow_redirection={follow}, user_agent={user_agent}, "
            f"accept_untrusted_certificates={accept_untrusted})"
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
