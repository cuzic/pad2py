"""`Cryptography.Actions`(AES対称暗号・ハッシュ)のロジック層。

常にAES-CBC・128ビットブロック。`UseSalt`無しは鍵導出(KDF)無し、鍵文字列を
指定エンコーディングでバイト化してゼロパディングするだけ(弱い)。`UseIV`無しは
固定の全ゼロIV(同じ鍵なら同じ平文接頭辞が常に同じ暗号文になる既知の弱点)。
この「弱いが決定的」な挙動は確認済みの仕様であり、改善せず忠実に再現する
(でっち上げた安全策に変えると実機の出力と一致しなくなる)。

`Encoding="Unicode"`はバイト配列への直接エンコード(`Encoding.Unicode.GetBytes`)
であり、ファイル書き込み時のBOM付きUTF-16とは違い**BOM無し**のUTF-16LEになる
(`"utf-16-le"`を使う。`file_actions`の`"utf-16"`——BOM付き——とは意図的に別)。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .errors import PadActionError

_BLOCK_SIZE = 16
_ZERO_IV = b"\x00" * _BLOCK_SIZE

_ENCRYPTION_ENCODINGS = {"Unicode": "utf-16-le", "UTF8": "utf-8", "ASCII": "ascii", "Default": "utf-8"}

_HASH_ALGORITHMS = {"SHA1": "sha1", "SHA256": "sha256", "SHA384": "sha384", "SHA512": "sha512"}
_HMAC_ALGORITHMS = {"HMACSHA256": "sha256", "HMACSHA384": "sha384", "HMACSHA512": "sha512"}
_PBKDF2_HASHES = {"SHA1": hashes.SHA1, "SHA256": hashes.SHA256, "SHA384": hashes.SHA384, "SHA512": hashes.SHA512}


class EncryptTextError(PadActionError):
    pass


class EncryptFileError(PadActionError):
    pass


class DecryptTextError(PadActionError):
    pass


class DecryptToFileError(PadActionError):
    pass


_OS_FILE_NOT_FOUND_ERROR = FileNotFoundError


class FileNotFoundError(PadActionError):  # noqa: A001
    pass


def _resolve_encoding(encoding: str) -> str:
    return _ENCRYPTION_ENCODINGS.get(encoding, encoding)


def _pkcs7_pad(data: bytes) -> bytes:
    padder = padding.PKCS7(_BLOCK_SIZE * 8).padder()
    return padder.update(data) + padder.finalize()


def _pkcs7_unpad(data: bytes) -> bytes:
    unpadder = padding.PKCS7(_BLOCK_SIZE * 8).unpadder()
    return unpadder.update(data) + unpadder.finalize()


def _zeros_pad(data: bytes) -> bytes:
    pad_len = (-len(data)) % _BLOCK_SIZE
    return data + b"\x00" * pad_len


def _zeros_unpad(data: bytes) -> bytes:
    return data.rstrip(b"\x00")


def _ansix923_pad(data: bytes) -> bytes:
    pad_len = _BLOCK_SIZE - (len(data) % _BLOCK_SIZE)
    return data + b"\x00" * (pad_len - 1) + bytes([pad_len])


def _ansix923_unpad(data: bytes) -> bytes:
    return data[: -data[-1]]


def _iso10126_pad(data: bytes) -> bytes:
    pad_len = _BLOCK_SIZE - (len(data) % _BLOCK_SIZE)
    return data + os.urandom(pad_len - 1) + bytes([pad_len])


def _iso10126_unpad(data: bytes) -> bytes:
    return data[: -data[-1]]


def _none_pad(data: bytes) -> bytes:
    if len(data) % _BLOCK_SIZE != 0:
        raise ValueError("PaddingMode 'None' requires plaintext length to be a multiple of 16 bytes")
    return data


def _none_unpad(data: bytes) -> bytes:
    return data


_PAD_FUNCS = {
    "PKCS7": (_pkcs7_pad, _pkcs7_unpad),
    "Zeros": (_zeros_pad, _zeros_unpad),
    "ANSIX923": (_ansix923_pad, _ansix923_unpad),
    "ISO10126": (_iso10126_pad, _iso10126_unpad),
    "None": (_none_pad, _none_unpad),
}


def _derive_key(
    key_material: bytes,
    key_size: int,
    use_salt: bool,
    salt: bytes | None,
    iterations: int,
    hash_algorithm: str,
) -> tuple[bytes, bytes | None]:
    key_bytes = key_size // 8
    if use_salt:
        salt = salt if salt is not None else os.urandom(16)
        kdf = PBKDF2HMAC(
            algorithm=_PBKDF2_HASHES[hash_algorithm](),
            length=key_bytes,
            salt=salt,
            iterations=iterations,
        )
        return kdf.derive(key_material), salt
    # KDF無し: 鍵文字列をゼロパディング/切り詰めするだけ(弱い、意図的な忠実再現)。
    return key_material[:key_bytes].ljust(key_bytes, b"\x00"), None


@dataclass(frozen=True)
class EncryptResult:
    encrypted_text: str
    salt: str = ""
    initialization_vector: str = ""


def _encrypt_bytes(
    plaintext: bytes,
    encryption_key: str,
    encoding: str = "Unicode",
    key_size: int = 256,
    padding_mode: str = "PKCS7",
    use_salt: bool = False,
    use_iv: bool = False,
    iterations: int = 100000,
    hash_algorithm: str = "SHA256",
) -> EncryptResult:
    codec = _resolve_encoding(encoding)
    key_material = encryption_key.encode(codec)
    key, salt = _derive_key(key_material, key_size, use_salt, None, iterations, hash_algorithm)
    iv = os.urandom(_BLOCK_SIZE) if use_iv else _ZERO_IV
    pad_fn, _ = _PAD_FUNCS[padding_mode]
    padded = pad_fn(plaintext)
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return EncryptResult(
        encrypted_text=base64.b64encode(ciphertext).decode("ascii"),
        salt=base64.b64encode(salt).decode("ascii") if salt else "",
        initialization_vector=base64.b64encode(iv).decode("ascii") if use_iv else "",
    )


def encrypt_text(
    text_to_encrypt: str,
    encryption_key: str,
    encoding: str = "Unicode",
    key_size: int = 256,
    padding_mode: str = "PKCS7",
    use_salt: bool = False,
    use_iv: bool = False,
    iterations: int = 100000,
    hash_algorithm: str = "SHA256",
) -> EncryptResult:
    plaintext = text_to_encrypt.encode(_resolve_encoding(encoding))
    try:
        return _encrypt_bytes(
            plaintext, encryption_key, encoding, key_size, padding_mode, use_salt, use_iv, iterations, hash_algorithm
        )
    except ValueError as exc:
        raise EncryptTextError(str(exc)) from exc


def encrypt_from_file(
    file_to_encrypt: str,
    encryption_key: str,
    encoding: str = "Unicode",
    key_size: int = 256,
    padding_mode: str = "PKCS7",
    use_salt: bool = False,
    use_iv: bool = False,
    iterations: int = 100000,
    hash_algorithm: str = "SHA256",
) -> EncryptResult:
    """ファイルの生バイトをそのまま暗号化する(`Encoding`は鍵のバイト化にのみ使う)。

    `HashFromFile`のような「テキストとして読み直してから再エンコード」する
    ラウンドトリップは、Encryptについては逆コンパイル調査で指摘されていない
    (Hashでのみ明示的に言及されている)ため、ここでは行わない。
    """
    try:
        plaintext = Path(file_to_encrypt).read_bytes()
    except _OS_FILE_NOT_FOUND_ERROR as exc:
        raise FileNotFoundError(str(exc)) from exc
    try:
        return _encrypt_bytes(
            plaintext, encryption_key, encoding, key_size, padding_mode, use_salt, use_iv, iterations, hash_algorithm
        )
    except ValueError as exc:
        raise EncryptFileError(str(exc)) from exc


def _decrypt_bytes(
    ciphertext: bytes,
    encryption_key: str,
    encoding: str = "Unicode",
    key_size: int = 256,
    padding_mode: str = "PKCS7",
    salt: str = "",
    iv: str = "",
    iterations: int = 100000,
    hash_algorithm: str = "SHA256",
) -> bytes:
    codec = _resolve_encoding(encoding)
    key_material = encryption_key.encode(codec)
    use_salt = bool(salt)
    salt_bytes = base64.b64decode(salt) if salt else None
    key, _ = _derive_key(key_material, key_size, use_salt, salt_bytes, iterations, hash_algorithm)
    iv_bytes = base64.b64decode(iv) if iv else _ZERO_IV
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv_bytes)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    _, unpad_fn = _PAD_FUNCS[padding_mode]
    return unpad_fn(padded)


def decrypt_text(
    encrypted_text: str,
    encryption_key: str,
    encoding: str = "Unicode",
    key_size: int = 256,
    padding_mode: str = "PKCS7",
    salt: str = "",
    iv: str = "",
    iterations: int = 100000,
    hash_algorithm: str = "SHA256",
) -> str:
    try:
        ciphertext = base64.b64decode(encrypted_text)
        plaintext = _decrypt_bytes(
            ciphertext, encryption_key, encoding, key_size, padding_mode, salt, iv, iterations, hash_algorithm
        )
        return plaintext.decode(_resolve_encoding(encoding))
    except Exception as exc:
        raise DecryptTextError(str(exc)) from exc


def _next_sequential_path(path: Path) -> Path:
    stem, suffix = path.stem, path.suffix
    n = 1
    candidate = path
    while candidate.exists():
        candidate = path.with_name(f"{stem} ({n}){suffix}")
        n += 1
    return candidate


def decrypt_to_file(
    encrypted_text: str,
    destination_path: str,
    encryption_key: str,
    encoding: str = "Unicode",
    key_size: int = 256,
    padding_mode: str = "PKCS7",
    salt: str = "",
    iv: str = "",
    iterations: int = 100000,
    hash_algorithm: str = "SHA256",
    if_file_exists: str = "AddSequentialSuffix",
) -> str | None:
    dest = Path(destination_path)
    if dest.exists():
        if if_file_exists == "DoNotModifyFiles":
            # エラーにならず、何もせず空のFileObjectを返すだけ。
            return None
        if if_file_exists == "AddSequentialSuffix":
            dest = _next_sequential_path(dest)
        elif if_file_exists != "Overwrite":
            raise ValueError(f"Unknown IfFileExists mode: {if_file_exists!r}")
    try:
        ciphertext = base64.b64decode(encrypted_text)
        plaintext = _decrypt_bytes(
            ciphertext, encryption_key, encoding, key_size, padding_mode, salt, iv, iterations, hash_algorithm
        )
        dest.write_bytes(plaintext)
    except Exception as exc:
        raise DecryptToFileError(str(exc)) from exc
    return str(dest)


def hash_text(text_to_hash: str, encoding: str = "Unicode", hash_algorithm: str = "SHA256") -> str:
    data = text_to_hash.encode(_resolve_encoding(encoding))
    digest = hashlib.new(_HASH_ALGORITHMS[hash_algorithm], data).digest()
    return base64.b64encode(digest).decode("ascii")


def hash_from_file(path: str, encoding: str = "Unicode", hash_algorithm: str = "SHA256") -> str:
    # ファイル内容をテキストとして指定エンコーディングで読み直し、再エンコードしてから
    # ハッシュする(生バイトを直接ハッシュしない)——宣言エンコーディングと実バイトが
    # 食い違うファイルでは結果が変わる。
    codec = _resolve_encoding(encoding)
    try:
        text = Path(path).read_text(encoding=codec)
    except _OS_FILE_NOT_FOUND_ERROR as exc:
        raise FileNotFoundError(str(exc)) from exc
    return hash_text(text, encoding=encoding, hash_algorithm=hash_algorithm)


def hash_text_with_key(
    text_to_hash: str, hash_key: str, encoding: str = "Unicode", hash_algorithm: str = "HMACSHA256"
) -> str:
    codec = _resolve_encoding(encoding)
    data = text_to_hash.encode(codec)
    key_bytes = hash_key.encode(codec)
    digest = hmac.new(key_bytes, data, _HMAC_ALGORITHMS[hash_algorithm]).digest()
    return base64.b64encode(digest).decode("ascii")


def hash_from_file_with_key(
    path: str, hash_key: str, encoding: str = "Unicode", hash_algorithm: str = "HMACSHA256"
) -> str:
    codec = _resolve_encoding(encoding)
    try:
        text = Path(path).read_text(encoding=codec)
    except _OS_FILE_NOT_FOUND_ERROR as exc:
        raise FileNotFoundError(str(exc)) from exc
    return hash_text_with_key(text, hash_key, encoding=encoding, hash_algorithm=hash_algorithm)
