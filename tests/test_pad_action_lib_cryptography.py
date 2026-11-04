"""`pad_action_lib.cryptography_actions`の単体テスト。"""
from __future__ import annotations

from pathlib import Path

import pytest

from dump_daemon.pad_action_lib import cryptography_actions as ca


def test_encrypt_decrypt_round_trip_no_salt_no_iv() -> None:
    result = ca.encrypt_text("hello world", "secret-key")
    assert result.salt == ""
    assert result.initialization_vector == ""
    assert ca.decrypt_text(result.encrypted_text, "secret-key") == "hello world"


def test_encrypt_without_iv_is_deterministic_for_same_prefix() -> None:
    # UseIV無しは固定の全ゼロIV——同じ鍵・同じ平文なら常に同じ暗号文になる既知の弱点。
    r1 = ca.encrypt_text("same text", "key")
    r2 = ca.encrypt_text("same text", "key")
    assert r1.encrypted_text == r2.encrypted_text


def test_encrypt_with_iv_is_random() -> None:
    r1 = ca.encrypt_text("same text", "key", use_iv=True)
    r2 = ca.encrypt_text("same text", "key", use_iv=True)
    assert r1.encrypted_text != r2.encrypted_text
    assert r1.initialization_vector != r2.initialization_vector


def test_encrypt_decrypt_round_trip_with_salt_and_iv() -> None:
    result = ca.encrypt_text("hello world", "secret-key", use_salt=True, use_iv=True)
    decrypted = ca.decrypt_text(
        result.encrypted_text,
        "secret-key",
        salt=result.salt,
        iv=result.initialization_vector,
    )
    assert decrypted == "hello world"


def test_encrypt_decrypt_with_zeros_padding() -> None:
    # UTF8でエンコードした16バイト境界に揃うASCIIテキスト(末尾が\x00にならないもの)。
    result = ca.encrypt_text("exactly16bytes!!", "key", encoding="UTF8", padding_mode="Zeros")
    assert (
        ca.decrypt_text(result.encrypted_text, "key", encoding="UTF8", padding_mode="Zeros")
        == "exactly16bytes!!"
    )


def test_encrypt_decrypt_with_ansix923_padding() -> None:
    result = ca.encrypt_text("short", "key", encoding="UTF8", padding_mode="ANSIX923")
    assert ca.decrypt_text(result.encrypted_text, "key", encoding="UTF8", padding_mode="ANSIX923") == "short"


def test_encrypt_decrypt_with_iso10126_padding() -> None:
    result = ca.encrypt_text("short", "key", encoding="UTF8", padding_mode="ISO10126")
    assert ca.decrypt_text(result.encrypted_text, "key", encoding="UTF8", padding_mode="ISO10126") == "short"


def test_encrypt_none_padding_requires_block_aligned_text() -> None:
    with pytest.raises(ca.EncryptTextError):
        ca.encrypt_text("not16bytes", "key", encoding="UTF8", padding_mode="None")


def test_encrypt_from_file(tmp_path: Path) -> None:
    # EncryptFromFileはファイルの生バイトをそのまま暗号化する(Encodingはテキストへの
    # 再デコードには使わない、鍵のバイト化にのみ使う)。DecryptTextはEncoding="Unicode"
    # (UTF-16LE)でバイト列をデコードしようとするため、生ASCIIバイトをそのまま戻すには
    # DecryptToFileで生バイトとして書き出す必要がある。
    f = tmp_path / "secret.txt"
    f.write_bytes(b"binary content")
    result = ca.encrypt_from_file(str(f), "key")
    out = tmp_path / "out.bin"
    ca.decrypt_to_file(result.encrypted_text, str(out), "key")
    assert out.read_bytes() == b"binary content"


def test_encrypt_from_file_missing_raises() -> None:
    with pytest.raises(ca.FileNotFoundError):
        ca.encrypt_from_file("/nonexistent.txt", "key")


def test_decrypt_to_file_writes_bytes(tmp_path: Path) -> None:
    dest = tmp_path / "out.txt"
    result = ca.encrypt_text("payload", "key", encoding="UTF8")
    written = ca.decrypt_to_file(result.encrypted_text, str(dest), "key", encoding="UTF8")
    assert written == str(dest)
    assert dest.read_text() == "payload"


def test_decrypt_to_file_do_not_modify_existing(tmp_path: Path) -> None:
    dest = tmp_path / "out.txt"
    dest.write_text("original")
    result = ca.encrypt_text("payload", "key", encoding="UTF8")
    written = ca.decrypt_to_file(
        result.encrypted_text, str(dest), "key", encoding="UTF8", if_file_exists="DoNotModifyFiles"
    )
    assert written is None
    assert dest.read_text() == "original"


def test_decrypt_to_file_add_sequential_suffix(tmp_path: Path) -> None:
    dest = tmp_path / "out.txt"
    dest.write_text("original")
    result = ca.encrypt_text("payload", "key", encoding="UTF8")
    written = ca.decrypt_to_file(result.encrypted_text, str(dest), "key", encoding="UTF8")
    assert written == str(tmp_path / "out (1).txt")


def test_hash_text_sha256() -> None:
    import base64
    import hashlib

    expected = base64.b64encode(hashlib.sha256("hello".encode("utf-16-le")).digest()).decode()
    assert ca.hash_text("hello") == expected


def test_hash_text_with_key_hmac() -> None:
    import base64
    import hmac as hmac_mod

    expected = base64.b64encode(
        hmac_mod.new("key".encode("utf-16-le"), "hello".encode("utf-16-le"), "sha256").digest()
    ).decode()
    assert ca.hash_text_with_key("hello", "key") == expected


def test_hash_from_file_round_trips_through_text_decode(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-16-le")
    assert ca.hash_from_file(str(f)) == ca.hash_text("hello")


def test_hash_from_file_with_key(tmp_path: Path) -> None:
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-16-le")
    assert ca.hash_from_file_with_key(str(f), "key") == ca.hash_text_with_key("hello", "key")
