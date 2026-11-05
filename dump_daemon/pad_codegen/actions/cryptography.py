"""`Cryptography.*`のcodegen。`pad_action_lib.cryptography_actions`へ委譲する。

パラメータ名は design/dsl_format_findings.md 知見70で実機キャプチャした
`tests/fixtures/tier1_crypto_database_batch7.txt`から確認済み。

`EncryptText`/`EncryptFromFile`/`DecryptText`/`DecryptToFile`/`HashTextWithKey`/
`HashFromFileWithKey`は、実機キャプチャでは鍵パラメータ(`EncryptionKey`/
`DecryptionKey`/`HashKey`)が常にWindows DPAPI保護値(`P'<base64>'`、知見72)として
現れる。知見111で鍵パラメータが(DPAPI保護ではなく)ふつうの変数参照や文字列リテラル
である場合の結線を用意し、知見112で`P'<base64>'`自体も`DpapiSensitiveLiteral`型経由で
`cryptography_actions.decrypt_dpapi_sensitive_value()`へ結線されるようになった
(元の値を作成したWindowsユーザー自身が生成スクリプトを実行する場合のみ実際に
復号できる)。`pad_action_lib.cryptography_actions`(AES-CBC・HMAC実装、decompile調査で
確認済みの弱い既定動作も忠実に再現)へそのまま委譲するだけで、でっち上げは発生しない。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render

_AES_KEY_SIZE_MAP = {"Bits128": 128, "Bits192": 192, "Bits256": 256}


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

    if action_id == "Cryptography.HashTextWithKey":
        text = safe_render(p.get("TextToHash"))
        key = safe_render(p.get("HashKey"))
        encoding = enum_last(p.get("Encoding"))
        algorithm = enum_last(p.get("HashAlgorithm"))
        if text is None or key is None or encoding is None or algorithm is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = cryptography_actions.hash_text_with_key({text}, {key}, "
            f"encoding={encoding!r}, hash_algorithm={algorithm!r})"
        ]

    if action_id == "Cryptography.HashFromFileWithKey":
        path = safe_render(p.get("FileToHash"))
        key = safe_render(p.get("HashKey"))
        encoding = enum_last(p.get("Encoding"))
        algorithm = enum_last(p.get("KeyedHashAlgorithm"))
        if path is None or key is None or encoding is None or algorithm is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = cryptography_actions.hash_from_file_with_key({path}, {key}, "
            f"encoding={encoding!r}, hash_algorithm={algorithm!r})"
        ]

    if action_id == "Cryptography.EncryptText.EncryptTextWithAES":
        text = safe_render(p.get("TextToEncrypt"))
        key = safe_render(p.get("EncryptionKey"))
        encoding = enum_last(p.get("Encoding"))
        padding_mode = enum_last(p.get("PaddingMode"))
        key_size = _AES_KEY_SIZE_MAP.get(enum_last(p.get("KeySize")))
        if (
            text is None
            or key is None
            or encoding is None
            or padding_mode is None
            or key_size is None
            or not node.output_var
        ):
            return None
        return [
            f"{prefix}{node.output_var} = cryptography_actions.encrypt_text({text}, {key}, "
            f"encoding={encoding!r}, key_size={key_size}, padding_mode={padding_mode!r}).encrypted_text"
        ]

    if action_id == "Cryptography.EncryptFromFile.EncryptFromFileWithAES":
        path = safe_render(p.get("FileToEncrypt"))
        key = safe_render(p.get("EncryptionKey"))
        encoding = enum_last(p.get("Encoding"))
        padding_mode = enum_last(p.get("PaddingMode"))
        key_size = _AES_KEY_SIZE_MAP.get(enum_last(p.get("KeySize")))
        if (
            path is None
            or key is None
            or encoding is None
            or padding_mode is None
            or key_size is None
            or not node.output_var
        ):
            return None
        return [
            f"{prefix}{node.output_var} = cryptography_actions.encrypt_from_file({path}, {key}, "
            f"encoding={encoding!r}, key_size={key_size}, padding_mode={padding_mode!r}).encrypted_text"
        ]

    if action_id == "Cryptography.DecryptText.DecryptTextWithAES":
        text = safe_render(p.get("TextToDecrypt"))
        key = safe_render(p.get("DecryptionKey"))
        encoding = enum_last(p.get("Encoding"))
        padding_mode = enum_last(p.get("Padding"))
        key_size = _AES_KEY_SIZE_MAP.get(enum_last(p.get("KeySize")))
        if (
            text is None
            or key is None
            or encoding is None
            or padding_mode is None
            or key_size is None
            or not node.output_var
        ):
            return None
        return [
            f"{prefix}{node.output_var} = cryptography_actions.decrypt_text({text}, {key}, "
            f"encoding={encoding!r}, key_size={key_size}, padding_mode={padding_mode!r})"
        ]

    if action_id == "Cryptography.DecryptToFile.DecryptToFileWithAES":
        text = safe_render(p.get("TextToDecrypt"))
        dest = safe_render(p.get("DecryptToFile"))
        key = safe_render(p.get("DecryptionKey"))
        encoding = enum_last(p.get("Encoding"))
        padding_mode = enum_last(p.get("Padding"))
        key_size = _AES_KEY_SIZE_MAP.get(enum_last(p.get("KeySize")))
        if_file_exists = enum_last(p.get("IfFileExists"))
        if (
            text is None
            or dest is None
            or key is None
            or encoding is None
            or padding_mode is None
            or key_size is None
            or if_file_exists is None
            or not node.output_var
        ):
            return None
        return [
            f"{prefix}{node.output_var} = cryptography_actions.decrypt_to_file({text}, {dest}, {key}, "
            f"encoding={encoding!r}, key_size={key_size}, padding_mode={padding_mode!r}, "
            f"if_file_exists={if_file_exists!r})"
        ]

    return None
