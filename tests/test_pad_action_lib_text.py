"""`pad_action_lib.text_actions`の単体テスト。

逆コンパイル結果からの推測に基づく既定値・非自明な挙動(トラップ)を中心に検証する
——action_idでの呼び出しではなく、このモジュールの関数を直接呼ぶユニットテスト。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from dump_daemon.pad_action_lib import text_actions as ta


def test_append_line_uses_windows_newline() -> None:
    assert ta.append_line("a", "b") == "a\r\nb"
    assert ta.append_line("a") == "a\r\n"


def test_change_case_upper_lower() -> None:
    assert ta.change_case("Hello World", "UpperCase") == "HELLO WORLD"
    assert ta.change_case("Hello World", "LowerCase") == "hello world"


def test_change_case_title_capitalizes_every_word() -> None:
    assert ta.change_case("hELLO wORLD", "TitleCase") == "Hello World"


def test_change_case_sentence_capitalizes_only_first_letter() -> None:
    assert ta.change_case("HELLO WORLD", "SentenceCase") == "Hello world"


def test_create_html_content_is_pass_through() -> None:
    assert ta.create_html_content("<b>hi</b>") == "<b>hi</b>"


def test_create_random_text_swaps_min_max_when_reversed() -> None:
    class FixedRng:
        def randint(self, lo: int, hi: int) -> int:
            assert lo <= hi
            return lo

        def choice(self, seq: str) -> str:
            return seq[0]

    result = ta.create_random_text(10, 5, rng=FixedRng())
    assert len(result) == 5


def test_create_random_text_empty_pool_returns_empty_string() -> None:
    result = ta.create_random_text(
        use_upper_case_letters=False,
        use_lower_case_letters=False,
        use_digits=False,
        use_symbols=False,
    )
    assert result == ""


def test_crop_text_before_flag() -> None:
    result = ta.crop_text("hello-world", mode="GetTextBeforeFlag", from_flag="-")
    assert result.cropped_text == "hello"
    assert result.is_flag_found is True


def test_crop_text_after_flag_with_empty_flag_is_not_found() -> None:
    # 空フラグは「先頭から」にフォールバックせず「見つからない」扱いになる非自明なトラップ。
    result = ta.crop_text("hello-world", mode="GetTextAfterFlag", from_flag="")
    assert result.is_flag_found is False
    assert result.cropped_text == ""


def test_crop_text_between_flags() -> None:
    result = ta.crop_text(
        "<a>middle</a>", mode="GetTextBetweenFlags", from_flag="<a>", to_flag="</a>"
    )
    assert result.cropped_text == "middle"
    assert result.is_flag_found is True


def test_escape_for_regular_expression() -> None:
    assert ta.escape_for_regular_expression("a.b*c") == re_escape("a.b*c")


def re_escape(text: str) -> str:
    import re

    return re.escape(text)


def test_get_subtext_basic() -> None:
    assert ta.get_subtext("hello world", character_position=6, start_index="CharacterPosition") == "world"
    assert ta.get_subtext("hello", number_of_chars=3, length="NumberOfChars") == "hel"


def test_get_subtext_out_of_range_raises() -> None:
    with pytest.raises(ta.StartIndexOrLengthOutOfRangeError):
        ta.get_subtext("hi", start_index="CharacterPosition", character_position=10)
    with pytest.raises(ta.StartIndexOrLengthOutOfRangeError):
        ta.get_subtext("hi", length="NumberOfChars", number_of_chars=-1)


def test_join_text_standard_newline_is_windows_style() -> None:
    result = ta.join_text(["a", "b"], delimiter_type="Standard", standard_delimiter="NewLine")
    assert result == "a\r\nb"


def test_join_text_delimiter_times_repeats_separator() -> None:
    result = ta.join_text(["a", "b"], delimiter_type="Custom", custom_delimiter="-", delimiter_times=3)
    assert result == "a---b"


def test_pad_text_multichar_padding_is_truncated_to_fit() -> None:
    assert ta.pad_text("ab", padding_text="xy", total_length=7) == "xyxyxab"


def test_pad_text_empty_padding_falls_back_to_space() -> None:
    assert ta.pad_text("ab", padding_text="", total_length=5) == "   ab"


def test_pad_text_no_change_when_already_long_enough() -> None:
    assert ta.pad_text("hello world", total_length=5) == "hello world"


def test_parse_text_first_occurrence_only() -> None:
    result = ta.parse_text("abcabc", "bc", first_occurrence_only=True)
    assert result.match == "bc"
    assert result.occurrence_position == 1
    assert result.matches == []
    assert result.occurrence_positions == []


def test_parse_text_all_occurrences() -> None:
    result = ta.parse_text("abcabc", "bc", first_occurrence_only=False)
    assert result.matches == ["bc", "bc"]
    assert result.occurrence_positions == [1, 4]
    assert result.match == ""
    assert result.occurrence_position == -1


def test_parse_text_not_found() -> None:
    result = ta.parse_text("abc", "zz", first_occurrence_only=True)
    assert result.occurrence_position == -1
    assert result.match == ""


def test_parse_text_regex_starting_position_excludes_earlier_matches() -> None:
    # マッチ"開始位置"がStartingPosition未満の候補は、途中からスライスするのと違い
    # 完全に除外される(マッチがStartingPositionをまたいでも復活しない)。
    result = ta.parse_text("aaXaa", "a+", is_regex=True, starting_position=3, first_occurrence_only=False)
    assert result.matches == ["aa"]
    assert result.occurrence_positions == [3]


def test_parse_text_invalid_regex_raises() -> None:
    with pytest.raises(ta.InvalidRegexError):
        ta.parse_text("abc", "(", is_regex=True)


def test_recognize_entities_in_text_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        ta.recognize_entities_in_text("some text", mode="Number")


def test_replace_text_empty_text_to_find_returns_text_to_find_itself() -> None:
    # PADの既知のクセ: TextToFindが空ならTextではなくTextToFind自体(空文字列)を返す。
    assert ta.replace_text("hello", "", "REPLACED") == ""


def test_replace_text_plain() -> None:
    assert ta.replace_text("hello world", "world", "there") == "hello there"


def test_replace_text_ignore_case() -> None:
    assert ta.replace_text("Hello WORLD", "world", "there", ignore_case=True) == "Hello there"


def test_replace_text_regex() -> None:
    assert ta.replace_text("a1b2c3", r"\d", "#", is_regex=True) == "a#b#c#"


def test_replace_text_escape_sequences() -> None:
    result = ta.replace_text("a,b", ",", "\\n", activate_escape_sequences=True)
    assert result == "a\nb"


def test_reverse_text_ascii() -> None:
    assert ta.reverse_text("abc") == "cba"


def test_reverse_text_corrupts_surrogate_pairs() -> None:
    # .NET の UTF-16コードユニット単位反転を再現するため、サロゲートペア(este emoji)を
    # 含む文字列は正しくコードポイント単位で反転されない(Pythonの`[::-1]`とは異なる)。
    emoji = "\U0001F600"  # U+1F600、UTF-16ではサロゲートペア2ユニット
    text = "a" + emoji
    result = ta.reverse_text(text)
    assert result != text[::-1]


def test_split_text_standard_delimiter() -> None:
    assert ta.split_text("a,b,,c", delimiter_type="Custom", custom_delimiter=",") == ["a", "b", "", "c"]


def test_split_text_number_of_characters() -> None:
    assert ta.split_text("abcdefg", delimiter_type="NumberOfCharacters", split_interval=3) == [
        "abc",
        "def",
        "g",
    ]


def test_split_text_regex() -> None:
    assert ta.split_text("a1b22c", delimiter_type="Custom", custom_delimiter=r"\d+", is_regex=True) == [
        "a",
        "b",
        "c",
    ]


def test_trim_text_variants() -> None:
    assert ta.trim_text("  hi  ", "Both") == "hi"
    assert ta.trim_text("  hi  ", "FromStart") == "hi  "
    assert ta.trim_text("  hi  ", "ToEnd") == "  hi"


def test_number_to_text_with_thousands_separator() -> None:
    assert ta.number_to_text(Decimal("1234.5"), decimal_places=2) == "1,234.50"


def test_number_to_text_without_thousands_separator() -> None:
    assert ta.number_to_text(Decimal("1234.5"), decimal_places=1, use_thousands_separator=False) == "1234.5"


def test_text_to_number_strips_thousands_separator() -> None:
    assert ta.text_to_number("1,234.50") == Decimal("1234.50")


def test_text_to_number_invalid_raises() -> None:
    with pytest.raises(ta.TextNotValidNumberError):
        ta.text_to_number("not a number")


def test_dotnet_format_to_strftime_basic_tokens() -> None:
    assert ta.dotnet_format_to_strftime("yyyy-MM-dd") == "%Y-%m-%d"
    assert ta.dotnet_format_to_strftime("HH:mm:ss") == "%H:%M:%S"


def test_dotnet_format_to_strftime_literal_quotes_pass_through() -> None:
    assert ta.dotnet_format_to_strftime("yyyy'年'MM'月'") == "%Y年%m月"


def test_datetime_to_text_custom_format() -> None:
    dt = datetime(2024, 1, 2, 3, 4, 5)
    assert ta.datetime_to_text(dt, format_type="Custom", custom_format="yyyy-MM-dd HH:mm:ss") == (
        "2024-01-02 03:04:05"
    )


def test_datetime_to_text_invalid_format_returns_empty_string() -> None:
    dt = datetime(2024, 1, 2)
    assert ta.datetime_to_text(dt, format_type="Standard", standard_format="not-a-format") == ""


def test_text_to_datetime_custom_format() -> None:
    result = ta.text_to_datetime("2024-01-02", date_is_in_custom_format=True, custom_format="yyyy-MM-dd")
    assert result == datetime(2024, 1, 2)


def test_text_to_datetime_invalid_raises() -> None:
    with pytest.raises(ta.TextNotValidDateTimeError):
        ta.text_to_datetime("not a date", date_is_in_custom_format=True, custom_format="yyyy-MM-dd")
