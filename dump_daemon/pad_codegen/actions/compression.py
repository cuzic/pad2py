"""`Compression.*`のcodegen。`pad_action_lib.compression_actions`へ委譲する。

パラメータ名は design/dsl_format_findings.md 知見66/知見71で実機キャプチャした
`tests/fixtures/tier1_datetime_folder_clipboard_batch2.txt`・
`tier1_web_xml_batch8.txt`から確認済み。

実機キャプチャでは`Password`が常にWindows DPAPI保護値(`P'<base64>'`、知見72)で
現れる。知見109でパスワード無しの圧縮/展開フローの結線を用意し、知見112で
`P'<base64>'`自体も`DpapiSensitiveLiteral`型経由で
`cryptography_actions.decrypt_dpapi_sensitive_value()`へ結線されるようになった
(元の値を作成したWindowsユーザー自身が生成スクリプトを実行する場合のみ実際に
復号できる)。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render

_COMPRESSION_LEVEL_MAP = {"BestBalanceOfSpeedAndCompression": 6}


def _as_list_expr(rendered: str) -> str:
    return f"({rendered} if isinstance({rendered}, list) else [{rendered}])"


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Compression."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "Compression.ZipFiles":
        archive_path = safe_render(p.get("ArchivePath"))
        files = safe_render(p.get("FilesOrFoldersToZip"))
        level_name = enum_last(p.get("CompressionLevel"))
        password = safe_render(p.get("Password", ""))
        comment = safe_render(p.get("ArchiveComment"))
        if archive_path is None or files is None or level_name is None or password is None or comment is None:
            return None
        level = _COMPRESSION_LEVEL_MAP.get(level_name)
        if level is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = compression_actions.zip_files({archive_path}, "
            f"{_as_list_expr(files)}, compression_level={level}, password={password}, "
            f"archive_comment={comment})"
        ]

    if action_id == "Compression.UnzipFiles":
        archive_path = safe_render(p.get("ArchivePath"))
        dest = safe_render(p.get("DestinationFolder"))
        password = safe_render(p.get("Password", ""))
        include_mask = safe_render(p.get("IncludeMask"))
        exclude_mask = safe_render(p.get("ExcludeMask"))
        if None in (archive_path, dest, password, include_mask, exclude_mask) or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = compression_actions.unzip_files({archive_path}, {dest}, "
            f"password={password}, include_mask={include_mask}, exclude_mask={exclude_mask})"
        ]

    return None
