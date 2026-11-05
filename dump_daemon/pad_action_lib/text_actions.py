"""`Text.Actions`(文字列操作)のロジック層。

`pad_codegen`のaction_idディスパッチとは独立——各アクションの入出力をPythonの値として
直接受け取る純粋関数として実装し、action_id/パラメータの直列化形式(知見66・67で
実機キャプチャした`tests/fixtures/tier1_text_variables_batch1.txt`・`batch4.txt`から
確認済み)に基づいて`pad_codegen/actions/text.py`が個別に結線する。

PADの`CaseOption`/`CropTextMode`/`DelimiterType`等のenumは、DSL上`Text.CaseOption.
UpperCase`のような完全修飾名で直列化され(知見66で実機確認済み)、`enum_last()`で
取り出した最後のセグメント(`"UpperCase"`等)をそのままこの層の引数値として使う
——実機確認済みの値のみ。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

from dateutil import parser as dateutil_parser

from .errors import PadActionError

NEWLINE = "\r\n"  # Environment.NewLine はWindows固定で \r\n(design/の既存知見と同じ前提)。

_SYMBOL_POOL = ",.<>?-_+!#$^"


class StartIndexOrLengthOutOfRangeError(PadActionError):
    pass


class InvalidRegexError(PadActionError):
    pass


class TextNotValidNumberError(PadActionError):
    pass


class TextNotValidDateTimeError(PadActionError):
    pass


def append_line(text: str, line_to_append: str = "") -> str:
    return text + NEWLINE + line_to_append


_WORD_RE = re.compile(r"(\w+)")


def _capitalize_first(word: str) -> str:
    return word[:1].upper() + word[1:] if word else word


def change_case(text: str, new_case: str = "UpperCase") -> str:
    if new_case == "UpperCase":
        return text.upper()
    if new_case == "LowerCase":
        return text.lower()
    lowered = text.lower()
    if new_case == "TitleCase":
        return _WORD_RE.sub(lambda m: _capitalize_first(m.group(1)), lowered)
    if new_case == "SentenceCase":
        m = _WORD_RE.search(lowered)
        if m is None:
            return lowered
        start, end = m.span(1)
        return lowered[:start] + _capitalize_first(m.group(1)) + lowered[end:]
    raise ValueError(f"Unknown CaseOption: {new_case!r}")


def create_html_content(html_editor: str) -> str:
    return html_editor


def create_random_text(
    minimum_length: int = 6,
    maximum_length: int = 10,
    use_upper_case_letters: bool = True,
    use_lower_case_letters: bool = True,
    use_digits: bool = True,
    use_symbols: bool = True,
    *,
    rng: object | None = None,
) -> str:
    import random as _random

    rand = rng if rng is not None else _random
    if minimum_length > maximum_length:
        minimum_length, maximum_length = maximum_length, minimum_length
    pool = ""
    if use_upper_case_letters:
        pool += "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if use_lower_case_letters:
        pool += "abcdefghijklmnopqrstuvwxyz"
    if use_digits:
        pool += "0123456789"
    if use_symbols:
        pool += _SYMBOL_POOL
    if not pool:
        return ""
    length = rand.randint(minimum_length, maximum_length)
    return "".join(rand.choice(pool) for _ in range(length))


@dataclass(frozen=True)
class CropTextResult:
    cropped_text: str
    is_flag_found: bool


def _culture_find(haystack: str, needle: str, ignore_case: bool) -> int:
    # 空フラグは「見つからない」扱い(「先頭/末尾から」にはフォールバックしない)。
    if needle == "":
        return -1
    if ignore_case:
        return haystack.lower().find(needle.lower())
    return haystack.find(needle)


def crop_text(
    text: str,
    mode: str = "GetTextBeforeFlag",
    from_flag: str = "",
    to_flag: str = "",
    ignore_case: bool = False,
) -> CropTextResult:
    if mode == "GetTextBeforeFlag":
        idx = _culture_find(text, from_flag, ignore_case)
        if idx == -1:
            return CropTextResult("", False)
        return CropTextResult(text[:idx], True)
    if mode == "GetTextAfterFlag":
        idx = _culture_find(text, from_flag, ignore_case)
        if idx == -1:
            return CropTextResult("", False)
        return CropTextResult(text[idx + len(from_flag) :], True)
    if mode == "GetTextBetweenFlags":
        idx1 = _culture_find(text, from_flag, ignore_case)
        if idx1 == -1:
            return CropTextResult("", False)
        start = idx1 + len(from_flag)
        idx2 = _culture_find(text[start:], to_flag, ignore_case)
        if idx2 == -1:
            return CropTextResult("", False)
        return CropTextResult(text[start : start + idx2], True)
    raise ValueError(f"Unknown CropTextMode: {mode!r}")


def escape_for_regular_expression(text: str) -> str:
    return re.escape(text)


def get_subtext(
    text: str,
    start_index: str = "StartOfText",
    character_position: int = 0,
    length: str = "EndOfText",
    number_of_chars: int = 0,
) -> str:
    start = 0 if start_index == "StartOfText" else character_position
    if start < 0 or start > len(text):
        raise StartIndexOrLengthOutOfRangeError(
            f"start index {start} out of range for text of length {len(text)}"
        )
    if length == "EndOfText":
        return text[start:]
    if number_of_chars < 0 or start + number_of_chars > len(text):
        raise StartIndexOrLengthOutOfRangeError(
            f"length {number_of_chars} out of range from start {start} "
            f"for text of length {len(text)}"
        )
    return text[start : start + number_of_chars]


_STANDARD_DELIMITERS = {"Space": " ", "Tab": "\t", "NewLine": NEWLINE}


def _resolve_delimiter(delimiter_type: str, standard_delimiter: str, custom_delimiter: str) -> str:
    if delimiter_type == "None":
        return ""
    if delimiter_type == "Standard":
        return _STANDARD_DELIMITERS[standard_delimiter]
    if delimiter_type == "Custom":
        return custom_delimiter
    raise ValueError(f"Unknown DelimiterType: {delimiter_type!r}")


def join_text(
    items: list[str],
    delimiter_type: str = "None",
    standard_delimiter: str = "Space",
    custom_delimiter: str = "",
    delimiter_times: int = 1,
) -> str:
    sep = _resolve_delimiter(delimiter_type, standard_delimiter, custom_delimiter) * delimiter_times
    return sep.join(items)


def pad_text(
    text: str = "",
    pad_position: str = "Left",
    padding_text: str = "",
    total_length: int = 10,
) -> str:
    fill_text = padding_text if padding_text else " "
    needed = total_length - len(text)
    if needed <= 0:
        return text
    repeats = needed // len(fill_text) + 1
    fill = (fill_text * repeats)[:needed]
    return fill + text if pad_position == "Left" else text + fill


@dataclass(frozen=True)
class ParseTextResult:
    match: str = ""
    matches: list[str] = field(default_factory=list)
    occurrence_position: int = -1
    occurrence_positions: list[int] = field(default_factory=list)


def parse_text(
    text: str,
    text_to_find: str,
    is_regex: bool = False,
    first_occurrence_only: bool = True,
    ignore_case: bool = False,
    starting_position: int = 0,
) -> ParseTextResult:
    if is_regex:
        try:
            pattern = re.compile(text_to_find, re.IGNORECASE if ignore_case else 0)
        except re.error as exc:
            raise InvalidRegexError(str(exc)) from exc
        # StartingPosition以降に"開始する"マッチのみを候補にする(`text[StartingPosition:]`へ
        # スライスしてから検索するのとは異なり、それより前で始まる候補は完全に除外される)。
        found = [m for m in pattern.finditer(text) if m.start() >= starting_position]
    else:
        hay = text.lower() if ignore_case else text
        needle = text_to_find.lower() if ignore_case else text_to_find
        positions: list[int] = []
        pos = starting_position
        if needle:
            while True:
                idx = hay.find(needle, pos)
                if idx == -1:
                    break
                positions.append(idx)
                pos = idx + len(needle)
        found = [(p, text[p : p + len(text_to_find)]) for p in positions]  # type: ignore[assignment]

    if is_regex:
        values = [(m.start(), m.group(0)) for m in found]  # type: ignore[union-attr]
    else:
        values = found  # type: ignore[assignment]

    if not values:
        return ParseTextResult()
    if first_occurrence_only:
        pos, text_val = values[0]
        return ParseTextResult(match=text_val, occurrence_position=pos)
    return ParseTextResult(
        matches=[v for _, v in values],
        occurrence_positions=[p for p, _ in values],
    )


def recognize_entities_in_text(text: str, mode: str, language: str = "English") -> list[dict]:
    # Microsoft.Recognizers.Text(公式Python版recognizers-text-suite)への委譲が必要だが、
    # 本プロジェクトはまだこの重量級の外部NLPライブラリを依存に加えるか決めていない。
    # でっち上げた正規表現ベースの代替実装は実機/公式ライブラリの出力と食い違うため、
    # 未実装であることを明示する。
    raise NotImplementedError(
        "RecognizeEntitiesInText requires the recognizers-text-suite library "
        "(not yet added as a dependency); not implemented"
    )


_ESCAPE_SEQUENCES = {
    "\\n": "\n",
    "\\r": "\r",
    "\\t": "\t",
    "\\\\": "\\",
}
_ESCAPE_RE = re.compile("|".join(re.escape(k) for k in sorted(_ESCAPE_SEQUENCES, key=len, reverse=True)))


def _unescape(text: str) -> str:
    return _ESCAPE_RE.sub(lambda m: _ESCAPE_SEQUENCES[m.group(0)], text)


def replace_text(
    text: str,
    text_to_find: str,
    replace_with: str,
    is_regex: bool = False,
    ignore_case: bool = False,
    activate_escape_sequences: bool = False,
    comparison_type: str = "CultureSensitive",
) -> str:
    if text_to_find == "":
        # PADの既知のクセ: TextToFindが空文字列なら、Textではなく TextToFind自体(空文字列)を返す。
        return text_to_find
    rw = _unescape(replace_with) if activate_escape_sequences else replace_with
    if is_regex:
        try:
            flags = re.IGNORECASE if ignore_case else 0
            return re.sub(text_to_find, lambda _m: rw, text, flags=flags)
        except re.error as exc:
            raise InvalidRegexError(str(exc)) from exc
    if ignore_case:
        return re.sub(re.escape(text_to_find), lambda _m: rw, text, flags=re.IGNORECASE)
    return text.replace(text_to_find, rw)


def reverse_text(text: str) -> str:
    # .NETの`string.Concat(Text.Reverse())`はUTF-16コードユニット単位の反転であり、
    # サロゲートペア(絵文字等)を破損させる。Pythonの`text[::-1]`はコードポイント単位で
    # 反転するためこの"バグ"を再現しない——PAD互換を優先し、コードユニット単位で反転する。
    units = text.encode("utf-16-le")
    pairs = [units[i : i + 2] for i in range(0, len(units), 2)]
    reversed_bytes = b"".join(reversed(pairs))
    return reversed_bytes.decode("utf-16-le", errors="surrogatepass")


def split_text(
    text: str,
    delimiter_type: str = "Standard",
    standard_delimiter: str = "Space",
    custom_delimiter: str = "",
    delimiter_times: int = 1,
    is_regex: bool = False,
    split_interval: int = 1,
) -> list[str]:
    if delimiter_type == "NumberOfCharacters":
        if split_interval <= 0:
            return [text]
        return [text[i : i + split_interval] for i in range(0, len(text), split_interval)]
    delim = _resolve_delimiter(delimiter_type, standard_delimiter, custom_delimiter) * delimiter_times
    if is_regex:
        try:
            return re.split(delim, text)
        except re.error as exc:
            raise InvalidRegexError(str(exc)) from exc
    return text.split(delim)


def trim_text(text: str = "", trim_option: str = "Both") -> str:
    if trim_option == "FromStart":
        return text.lstrip()
    if trim_option == "ToEnd":
        return text.rstrip()
    if trim_option == "Both":
        return text.strip()
    raise ValueError(f"Unknown TrimOption: {trim_option!r}")


def number_to_text(
    number: Decimal | float | int,
    decimal_places: int = 2,
    use_thousands_separator: bool = True,
) -> str:
    value = Decimal(str(number))
    quantum = Decimal(1).scaleb(-decimal_places) if decimal_places > 0 else Decimal(1)
    quantized = value.quantize(quantum)
    return format(quantized, ",f") if use_thousands_separator else format(quantized, "f")


def text_to_number(text: str) -> Decimal:
    cleaned = text.strip().replace(",", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise TextNotValidNumberError(f"{text!r} is not a valid number") from exc


_DOTNET_TOKENS: list[tuple[str, str]] = sorted(
    {
        "yyyy": "%Y", "yyy": "%Y", "yy": "%y", "y": "%y",
        "MMMM": "%B", "MMM": "%b", "MM": "%m", "M": "%m",
        "dddd": "%A", "ddd": "%a", "dd": "%d", "d": "%d",
        "HH": "%H", "H": "%H",
        "hh": "%I", "h": "%I",
        "mm": "%M", "m": "%M",
        "ss": "%S", "s": "%S",
        "tt": "%p",
    }.items(),
    key=lambda kv: -len(kv[0]),
)

_STANDARD_DATETIME_FORMATS = {
    "d": "%m/%d/%Y",
    "D": "%A, %B %d, %Y",
    "t": "%I:%M %p",
    "T": "%I:%M:%S %p",
    "f": "%A, %B %d, %Y %I:%M %p",
    "F": "%A, %B %d, %Y %I:%M:%S %p",
    "g": "%m/%d/%Y %I:%M %p",
    "G": "%m/%d/%Y %I:%M:%S %p",
    "s": "%Y-%m-%dT%H:%M:%S",
}


def dotnet_format_to_strftime(fmt: str) -> str:
    """.NETカスタム日時書式トークン(`yyyy-MM-dd`等)をPythonの`strftime`書式に変換する。

    シングルクォートで囲まれた区間はリテラルとして素通しする。小数秒(`f`/`ff`/`fff`)は
    strftimeに直接対応するものが無いため削除する(近似)。単一文字トークン(`M`/`d`等、
    .NETでは「ゼロ埋めしない」の意味)も、対応する複数文字トークンと同じゼロ埋め済み
    strftime指定子にマップする(近似、ゼロ埋め有無の区別は再現しない)。
    """
    result: list[str] = []
    i = 0
    n = len(fmt)
    while i < n:
        ch = fmt[i]
        if ch == "'":
            end = fmt.find("'", i + 1)
            if end == -1:
                result.append(fmt[i + 1 :].replace("%", "%%"))
                break
            result.append(fmt[i + 1 : end].replace("%", "%%"))
            i = end + 1
            continue
        if ch == "f":
            j = i
            while j < n and fmt[j] == "f":
                j += 1
            i = j
            continue
        matched = False
        for token, strftime_token in _DOTNET_TOKENS:
            if fmt.startswith(token, i):
                result.append(strftime_token)
                i += len(token)
                matched = True
                break
        if not matched:
            result.append("%%" if ch == "%" else ch)
            i += 1
    return "".join(result)


def datetime_to_text(
    value: datetime,
    format_type: str = "Standard",
    standard_format: str = "G",
    custom_format: str = "",
) -> str:
    try:
        py_fmt = (
            dotnet_format_to_strftime(custom_format)
            if format_type == "Custom"
            else _STANDARD_DATETIME_FORMATS[standard_format]
        )
        return value.strftime(py_fmt)
    except (ValueError, KeyError):
        # .NETの`FormatException`は呼び出し元に伝播せず、黙って空文字列を返す。
        return ""


def text_to_datetime(
    text: str,
    date_is_in_custom_format: bool = False,
    custom_format: str = "",
) -> datetime:
    try:
        if date_is_in_custom_format:
            return datetime.strptime(text, dotnet_format_to_strftime(custom_format))
        return dateutil_parser.parse(text)
    except (ValueError, OverflowError) as exc:
        raise TextNotValidDateTimeError(f"{text!r} is not a valid date/time") from exc
