"""`Cryptography.*`のcodegen。`pad_action_lib.cryptography_actions`へ委譲する。

パラメータ名は design/dsl_format_findings.md 知見70で実機キャプチャした
`tests/fixtures/tier1_crypto_database_batch7.txt`から確認済み。

`EncryptText`/`EncryptFromFile`/`DecryptText`/`DecryptToFile`/`HashTextWithKey`/
`HashFromFileWithKey`は、鍵パラメータ(`EncryptionKey`/`DecryptionKey`/`HashKey`)が
実機で常にWindows DPAPI保護値(`P'<base64>'`、知見72)としてキャプチャされ、現状の
パーサーでは正当なPython識別子にならない`VarRef`にフォールバックする——
`_support.safe_render()`がこれを検出して`None`を返すため、これらのアクションは
自動的に汎用`# TODO`フォールバックに委ねられる(鍵が無い`HashText`/`HashFromFile`
だけがこのモジュールで変換される)。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Cryptography."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "Cryptography.HashText":
        text = safe_render(p.get("TextToHash"))
        encoding = enum_last(p.get("Encoding"))
        algorithm = enum_last(p.get("HashAlgorithm"))
        if text is None or encoding is None or algorithm is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = cryptography_actions.hash_text({text}, "
            f"encoding={encoding!r}, hash_algorithm={algorithm!r})"
        ]

    if action_id == "Cryptography.HashFromFile":
        path = safe_render(p.get("File"))
        encoding = enum_last(p.get("Encoding"))
        algorithm = enum_last(p.get("HashAlgorithm"))
        if path is None or encoding is None or algorithm is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = cryptography_actions.hash_from_file({path}, "
            f"encoding={encoding!r}, hash_algorithm={algorithm!r})"
        ]

    return None
