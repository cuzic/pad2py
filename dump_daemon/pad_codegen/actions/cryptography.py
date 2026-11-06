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

知見139・143(`ActionSelectorBase`一括列挙監査をCryptography.Actions.dllに適用、VM上で
`EncryptTextAction`/`EncryptFromFileAction`/`DecryptTextAction`/`DecryptToFileAction`
各クラスのプロパティを確認): いずれも`UseSalt: Boolean`/`UseIV: Boolean`/
`Salt: String`/`InitializationVector: String`プロパティを持ち、各兄弟セレクタ
(`...UseSalt`/`...UseIV`/`...UseSaltAndIV`)はこの2つのBooleanの組み合わせを
セレクタ自体で固定する(`Database.Connect.ConnectOracle`と同じパターン)。
既存の`encrypt_text()`/`encrypt_from_file()`の`use_salt`/`use_iv`引数、
`decrypt_text()`/`decrypt_to_file()`の`salt`/`iv`引数がそのまま対応する——
暗号化側は`EncryptResult`が`salt`/`initialization_vector`を**生成結果として
出力**する(ランダム生成されるため、後で復号する際にこの値を保存しておく
必要がある)のに対し、復号側は`Salt`/`InitializationVector`を**入力として
受け取る**という非対称性に注意。
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

    # 知見143: Encrypt系の兄弟セレクタ(UseSalt/UseIVの組み合わせ、`EncryptResult`の
    # `salt`/`initialization_vector`を生成結果として出力する)。
    _ENCRYPT_SALT_IV = {
        "Cryptography.EncryptText.EncryptTextWithAESUseSalt": (True, False),
        "Cryptography.EncryptText.EncryptTextWithAESUseIV": (False, True),
        "Cryptography.EncryptText.EncryptTextWithAESUseSaltAndIV": (True, True),
    }
    if action_id in _ENCRYPT_SALT_IV:
        text = safe_render(p.get("TextToEncrypt"))
        key = safe_render(p.get("EncryptionKey"))
        encoding = enum_last(p.get("Encoding"))
        padding_mode = enum_last(p.get("PaddingMode"))
        key_size = _AES_KEY_SIZE_MAP.get(enum_last(p.get("KeySize")))
        encrypted_var = node.output_vars.get("EncryptedText")
        if text is None or key is None or encoding is None or padding_mode is None or key_size is None:
            return None
        if not encrypted_var:
            return None
        use_salt, use_iv = _ENCRYPT_SALT_IV[action_id]
        salt_var = node.output_vars.get("Salt")
        iv_var = node.output_vars.get("InitializationVector")
        tmp = "_encrypt_result"
        lines = [
            f"{prefix}{tmp} = cryptography_actions.encrypt_text({text}, {key}, "
            f"encoding={encoding!r}, key_size={key_size}, padding_mode={padding_mode!r}, "
            f"use_salt={use_salt}, use_iv={use_iv})",
            f"{prefix}{encrypted_var} = {tmp}.encrypted_text",
        ]
        if salt_var:
            lines.append(f"{prefix}{salt_var} = {tmp}.salt")
        if iv_var:
            lines.append(f"{prefix}{iv_var} = {tmp}.initialization_vector")
        return lines

    _ENCRYPT_FROM_FILE_SALT_IV = {
        "Cryptography.EncryptFromFile.EncryptFromFileWithAESUseSalt": (True, False),
        "Cryptography.EncryptFromFile.EncryptFromFileWithAESUseIV": (False, True),
        "Cryptography.EncryptFromFile.EncryptFromFileWithAESUseSaltAndIV": (True, True),
    }
    if action_id in _ENCRYPT_FROM_FILE_SALT_IV:
        path = safe_render(p.get("FileToEncrypt"))
        key = safe_render(p.get("EncryptionKey"))
        encoding = enum_last(p.get("Encoding"))
        padding_mode = enum_last(p.get("PaddingMode"))
        key_size = _AES_KEY_SIZE_MAP.get(enum_last(p.get("KeySize")))
        encrypted_var = node.output_vars.get("EncryptedText")
        if path is None or key is None or encoding is None or padding_mode is None or key_size is None:
            return None
        if not encrypted_var:
            return None
        use_salt, use_iv = _ENCRYPT_FROM_FILE_SALT_IV[action_id]
        salt_var = node.output_vars.get("Salt")
        iv_var = node.output_vars.get("InitializationVector")
        tmp = "_encrypt_result"
        lines = [
            f"{prefix}{tmp} = cryptography_actions.encrypt_from_file({path}, {key}, "
            f"encoding={encoding!r}, key_size={key_size}, padding_mode={padding_mode!r}, "
            f"use_salt={use_salt}, use_iv={use_iv})",
            f"{prefix}{encrypted_var} = {tmp}.encrypted_text",
        ]
        if salt_var:
            lines.append(f"{prefix}{salt_var} = {tmp}.salt")
        if iv_var:
            lines.append(f"{prefix}{iv_var} = {tmp}.initialization_vector")
        return lines

    # 知見143: Decrypt系の兄弟セレクタ(Salt/InitializationVectorは暗号化時に生成された
    # 値を復号側が入力として受け取る——Encrypt側とは非対称)。
    _DECRYPT_TEXT_SALT_IV = {
        "Cryptography.DecryptText.DecryptTextWithAESUseSalt": (True, False),
        "Cryptography.DecryptText.DecryptTextWithAESUseIV": (False, True),
        "Cryptography.DecryptText.DecryptTextWithAESUseSaltAndIV": (True, True),
    }
    if action_id in _DECRYPT_TEXT_SALT_IV:
        text = safe_render(p.get("TextToDecrypt"))
        key = safe_render(p.get("DecryptionKey"))
        encoding = enum_last(p.get("Encoding"))
        padding_mode = enum_last(p.get("Padding"))
        key_size = _AES_KEY_SIZE_MAP.get(enum_last(p.get("KeySize")))
        needs_salt, needs_iv = _DECRYPT_TEXT_SALT_IV[action_id]
        salt = safe_render(p.get("Salt")) if needs_salt else "''"
        iv = safe_render(p.get("InitializationVector")) if needs_iv else "''"
        if (
            text is None
            or key is None
            or encoding is None
            or padding_mode is None
            or key_size is None
            or salt is None
            or iv is None
            or not node.output_var
        ):
            return None
        return [
            f"{prefix}{node.output_var} = cryptography_actions.decrypt_text({text}, {key}, "
            f"encoding={encoding!r}, key_size={key_size}, padding_mode={padding_mode!r}, "
            f"salt={salt}, iv={iv})"
        ]

    _DECRYPT_TO_FILE_SALT_IV = {
        "Cryptography.DecryptToFile.DecryptToFileWithAESUseSalt": (True, False),
        "Cryptography.DecryptToFile.DecryptToFileWithAESUseIV": (False, True),
        "Cryptography.DecryptToFile.DecryptToFileWithAESUseSaltAndIV": (True, True),
    }
    if action_id in _DECRYPT_TO_FILE_SALT_IV:
        text = safe_render(p.get("TextToDecrypt"))
        dest = safe_render(p.get("DecryptToFile"))
        key = safe_render(p.get("DecryptionKey"))
        encoding = enum_last(p.get("Encoding"))
        padding_mode = enum_last(p.get("Padding"))
        key_size = _AES_KEY_SIZE_MAP.get(enum_last(p.get("KeySize")))
        if_file_exists = enum_last(p.get("IfFileExists"))
        needs_salt, needs_iv = _DECRYPT_TO_FILE_SALT_IV[action_id]
        salt = safe_render(p.get("Salt")) if needs_salt else "''"
        iv = safe_render(p.get("InitializationVector")) if needs_iv else "''"
        if (
            text is None
            or dest is None
            or key is None
            or encoding is None
            or padding_mode is None
            or key_size is None
            or if_file_exists is None
            or salt is None
            or iv is None
            or not node.output_var
        ):
            return None
        return [
            f"{prefix}{node.output_var} = cryptography_actions.decrypt_to_file({text}, {dest}, {key}, "
            f"encoding={encoding!r}, key_size={key_size}, padding_mode={padding_mode!r}, "
            f"if_file_exists={if_file_exists!r}, salt={salt}, iv={iv})"
        ]

    return None
