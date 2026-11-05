"""`Text.*`(文字列操作)のcodegen。

`pad_action_lib.text_actions`へ委譲する。各action_idのパラメータ名・列挙値は
design/dsl_format_findings.md 知見66-67で実機キャプチャした`tests/fixtures/
tier1_text_variables_batch1.txt`・`tier1_text_variables_batch4.txt`から確認済み。

`Text.CreateHTMLContent`の`HtmlEditor`は知見74でパーサーが空のバックティック文字列
``を正しく空文字列として解釈するようになったため結線できる(実機キャプチャでは
リッチテキストエディタの内容を編集しなかったため常に空文字列)。

以下は意図的に未対応としてフォールバックに委ねる(でっち上げを避ける):
- `Text.RecognizeEntitiesInText`: `pad_action_lib`側が常に`NotImplementedError`
  (外部NLPライブラリ未導入)を投げる——呼び出しコードを生成すると「生成できたように
  見えて実行時に必ず壊れる」という、TODOコメントより悪い結果になる。

`Text.ConvertDateTimeToText.FromDateTime`の`StandardFormat`は、実機で確認できた
`ShortDate`の1値だけを.NETの標準書式指定子`"d"`(`ShortDatePattern`、パブリックに
確認できる.NET仕様で、PAD固有のデコンパイル知識ではない)へ対応付け、他の値は
未確認としてフォールバックに委ねる(`_STANDARD_FORMAT_MAP`)。

`Text.GetSubtext.GetSubtext`は実機DSLに`StartIndexType`/`LengthType`相当のモード
列挙値が出力されないが、`CharacterPosition`/`NumberOfChars`が明示的に指定されている
(実機キャプチャで両方が現れている)ことから「特定位置から指定文字数」モードが
選ばれていたと判断し、`pad_action_lib.text_actions.get_subtext()`の`"StartOfText"`/
`"EndOfText"`以外の任意の文字列で"カスタム"分岐を選ぶ既定動作を使って変換する。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render

# .NETの標準日時書式指定子は`ShortDatePattern`="d"等、一般に確認されたパブリックな仕様
# (PAD固有のデコンパイル調査結果ではない)。実機で確認できた`WellKnownDateTimeFormat`の
# 値のうちこの1つだけをマッピングし、他は未確認としてフォールバックに委ねる。
_STANDARD_FORMAT_MAP = {"ShortDate": "d"}


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("Text."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "Text.AppendLine":
        text = safe_render(p.get("Text"))
        line = safe_render(p.get("LineToAppend"))
        if text is None or line is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = text_actions.append_line({text}, {line})"]

    if action_id == "Text.ChangeCase":
        text = safe_render(p.get("Text"))
        new_case = enum_last(p.get("NewCase"))
        if text is None or new_case is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = text_actions.change_case({text}, new_case={new_case!r})"]

    if action_id == "Text.ConvertTextToDateTime.ToDateTime":
        text = safe_render(p.get("Text"))
        if text is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = text_actions.text_to_datetime({text})"]

    if action_id == "Text.ConvertDateTimeToText.FromDateTime":
        value = safe_render(p.get("DateTime"))
        standard_format = enum_last(p.get("StandardFormat"))
        if value is None or standard_format is None or not node.output_var:
            return None
        mapped = _STANDARD_FORMAT_MAP.get(standard_format)
        if mapped is None:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.datetime_to_text({value}, "
            f"standard_format={mapped!r})"
        ]

    if action_id == "Text.GetSubtext.GetSubtext":
        text = safe_render(p.get("Text"))
        character_position = safe_render(p.get("CharacterPosition"))
        number_of_chars = safe_render(p.get("NumberOfChars"))
        if text is None or character_position is None or number_of_chars is None:
            return None
        if not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.get_subtext({text}, "
            f"start_index='AtSpecificCharacter', character_position={character_position}, "
            f"length='SpecificLength', number_of_chars={number_of_chars})"
        ]

    if action_id == "Text.CropText.CropTextBeforeFlag":
        text = safe_render(p.get("Text"))
        to_flag = safe_render(p.get("ToFlag"))
        ignore_case = safe_render(p.get("IgnoreCase"))
        cropped_var = node.output_vars.get("CroppedText")
        found_var = node.output_vars.get("IsFlagFound")
        if text is None or to_flag is None or ignore_case is None:
            return None
        if not cropped_var and not found_var:
            return None
        tmp = "_crop_result"
        lines = [
            f"{prefix}{tmp} = text_actions.crop_text({text}, mode='GetTextBeforeFlag', "
            f"from_flag={to_flag}, ignore_case={ignore_case})"
        ]
        if cropped_var:
            lines.append(f"{prefix}{cropped_var} = {tmp}.cropped_text")
        if found_var:
            lines.append(f"{prefix}{found_var} = {tmp}.is_flag_found")
        return lines

    if action_id == "Text.CreateHTMLContent":
        html_editor = safe_render(p.get("HtmlEditor"))
        if html_editor is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = text_actions.create_html_content({html_editor})"]

    if action_id == "Text.EscapeForRegularExpression":
        text = safe_render(p.get("Text"))
        if text is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = text_actions.escape_for_regular_expression({text})"]

    if action_id == "Text.FromNumber":
        number = safe_render(p.get("Number"))
        decimal_places = safe_render(p.get("DecimalPlaces"))
        use_separator = safe_render(p.get("UseThousandsSeparator"))
        if number is None or decimal_places is None or use_separator is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.number_to_text({number}, "
            f"decimal_places={decimal_places}, use_thousands_separator={use_separator})"
        ]

    if action_id == "Text.JoinText.Join":
        items = safe_render(p.get("List"))
        if items is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = text_actions.join_text({items})"]

    if action_id == "Text.Pad":
        text = safe_render(p.get("Text"))
        pad_position = enum_last(p.get("PadPosition"))
        padding_text = safe_render(p.get("PaddingText"))
        total_length = safe_render(p.get("TotalLength"))
        if text is None or pad_position is None or padding_text is None or total_length is None:
            return None
        if not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.pad_text({text}, pad_position={pad_position!r}, "
            f"padding_text={padding_text}, total_length={total_length})"
        ]

    if action_id == "Text.ParseText.ParseForFirstOccurrence":
        text = safe_render(p.get("Text"))
        text_to_find = safe_render(p.get("TextToFind"))
        starting_position = safe_render(p.get("StartingPosition"))
        ignore_case = safe_render(p.get("IgnoreCase"))
        position_var = node.output_vars.get("OccurrencePosition")
        if text is None or text_to_find is None or starting_position is None or ignore_case is None:
            return None
        if not position_var:
            return None
        tmp = "_parse_result"
        return [
            f"{prefix}{tmp} = text_actions.parse_text({text}, {text_to_find}, "
            f"ignore_case={ignore_case}, starting_position={starting_position})",
            f"{prefix}{position_var} = {tmp}.occurrence_position",
        ]

    if action_id == "Text.Replace.ReplaceText":
        text = safe_render(p.get("Text"))
        text_to_find = safe_render(p.get("TextToFind"))
        replace_with = safe_render(p.get("ReplaceWith"))
        ignore_case = safe_render(p.get("IgnoreCase"))
        activate_escape = safe_render(p.get("ActivateEscapeSequences"))
        comparison_type = enum_last(p.get("ComparisonType"))
        if None in (text, text_to_find, replace_with, ignore_case, activate_escape, comparison_type):
            return None
        if not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.replace_text({text}, {text_to_find}, {replace_with}, "
            f"ignore_case={ignore_case}, activate_escape_sequences={activate_escape}, "
            f"comparison_type={comparison_type!r})"
        ]

    if action_id == "Text.Reverse":
        text = safe_render(p.get("Text"))
        if text is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = text_actions.reverse_text({text})"]

    if action_id == "Text.SplitText.Split":
        text = safe_render(p.get("Text"))
        standard_delimiter = enum_last(p.get("StandardDelimiter"))
        delimiter_times = safe_render(p.get("DelimiterTimes"))
        if text is None or standard_delimiter is None or delimiter_times is None:
            return None
        if not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.split_text({text}, "
            f"standard_delimiter={standard_delimiter!r}, delimiter_times={delimiter_times})"
        ]

    if action_id == "Text.ToNumber":
        text = safe_render(p.get("Text"))
        if text is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = text_actions.text_to_number({text})"]

    if action_id == "Text.Trim":
        text = safe_render(p.get("Text"))
        trim_option = enum_last(p.get("TrimOption"))
        if text is None or trim_option is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = text_actions.trim_text({text}, trim_option={trim_option!r})"]

    if action_id == "Text.Random":
        min_len = safe_render(p.get("MinimumLength"))
        max_len = safe_render(p.get("MaximumLength"))
        upper = safe_render(p.get("UseUpperCaseLetters"))
        lower = safe_render(p.get("UseLowerCaseLetters"))
        digits = safe_render(p.get("UseDigits"))
        symbols = safe_render(p.get("UseSymbols"))
        if None in (min_len, max_len, upper, lower, digits, symbols) or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.create_random_text("
            f"minimum_length={min_len}, maximum_length={max_len}, "
            f"use_upper_case_letters={upper}, use_lower_case_letters={lower}, "
            f"use_digits={digits}, use_symbols={symbols})"
        ]

    return None
