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

知見139・142(`ActionSelectorBase`一括列挙監査をText.Actions.dllに適用、VM上で
`GetSubtextAction`クラスのプロパティ・`SubtextStartIndex`/`SubtextLength`列挙値を
直接確認): 実際の列挙値は`StartOfText`/`CharacterPosition`(`StartIndex`)・
`EndOfText`/`NumberOfChars`(`Length`)——上記の既存`GetSubtext`結線が使っていた
`"AtSpecificCharacter"`/`"SpecificLength"`という文字列はこの正式な列挙値名と**一致
していなかった**(`get_subtext()`の分岐が`== "StartOfText"`/`== "EndOfText"`の
等値判定だけで、他の文字列は全て「カスタム」側として扱われるため、たまたま挙動には
影響していなかった)。正しい列挙値名に修正し、`StartIndex`×`Length`の4通りの組み合わせ
(`GetSubtextAction`は1クラスで4つの兄弟セレクタ全てを提供する)として
`GetText`(StartOfText×EndOfText、全文そのまま)・`GetSubtextFromStartTo`
(StartOfText×NumberOfChars、先頭からN文字)・`GetSubtextFrom`(CharacterPosition×
EndOfText、指定位置から末尾まで)・`GetSubtext`(既存、CharacterPosition×NumberOfChars)
を結線した。
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

    if action_id == "Text.ConvertTextToDateTime.ToDateTimeCustomFormat":
        # 知見139・148: `ConvertTextToDateTimeAction`の兄弟セレクタ(`DateIsInCustomFormat`
        # =True固定)。既存の`text_to_datetime()`の`date_is_in_custom_format`/
        # `custom_format`引数(`dotnet_format_to_strftime()`経由、実装済み)がそのまま
        # 対応できた。
        text = safe_render(p.get("Text"))
        custom_format = safe_render(p.get("CustomFormat"))
        if text is None or custom_format is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.text_to_datetime({text}, "
            f"date_is_in_custom_format=True, custom_format={custom_format})"
        ]

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

    if action_id == "Text.ConvertDateTimeToText.FromCustomDateTime":
        # 知見139・148: `ConvertDateTimeToTextAction`の兄弟セレクタ(`Format=Custom`固定、
        # `DateTimeConversionFormat`列挙値が`datetime_to_text()`の`format_type`文字列と
        # 完全一致とVM上で確認済み)。
        value = safe_render(p.get("DateTime"))
        custom_format = safe_render(p.get("CustomFormat"))
        if value is None or custom_format is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.datetime_to_text({value}, "
            f"format_type='Custom', custom_format={custom_format})"
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
            f"start_index='CharacterPosition', character_position={character_position}, "
            f"length='NumberOfChars', number_of_chars={number_of_chars})"
        ]

    if action_id == "Text.GetSubtext.GetText":
        # 知見142: `GetSubtextAction`の兄弟セレクタ(StartOfText×EndOfText、全文そのまま)。
        text = safe_render(p.get("Text"))
        if text is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = text_actions.get_subtext({text})"]

    if action_id == "Text.GetSubtext.GetSubtextFromStartTo":
        # 知見142: StartOfText×NumberOfChars(先頭からN文字)。
        text = safe_render(p.get("Text"))
        number_of_chars = safe_render(p.get("NumberOfChars"))
        if text is None or number_of_chars is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.get_subtext({text}, "
            f"length='NumberOfChars', number_of_chars={number_of_chars})"
        ]

    if action_id == "Text.GetSubtext.GetSubtextFrom":
        # 知見142: CharacterPosition×EndOfText(指定位置から末尾まで)。
        text = safe_render(p.get("Text"))
        character_position = safe_render(p.get("CharacterPosition"))
        if text is None or character_position is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.get_subtext({text}, "
            f"start_index='CharacterPosition', character_position={character_position})"
        ]

    _CROP_TEXT_MODES = {
        "Text.CropText.CropTextBeforeFlag": "GetTextBeforeFlag",
        "Text.CropText.CropTextAfterFlag": "GetTextAfterFlag",
    }
    if action_id in _CROP_TEXT_MODES:
        # 知見139・142: `CropTextAction`クラスの兄弟セレクタ(`CropTextMode`列挙値は
        # `GetTextBeforeFlag`/`GetTextAfterFlag`/`GetTextBetweenFlags`で、既存の
        # `crop_text()`の`mode`引数と文字列が完全一致すると実機のリフレクションで確認済み)。
        text = safe_render(p.get("Text"))
        from_flag = safe_render(p.get("ToFlag"))
        ignore_case = safe_render(p.get("IgnoreCase"))
        cropped_var = node.output_vars.get("CroppedText")
        found_var = node.output_vars.get("IsFlagFound")
        if text is None or from_flag is None or ignore_case is None:
            return None
        if not cropped_var and not found_var:
            return None
        mode = _CROP_TEXT_MODES[action_id]
        tmp = "_crop_result"
        lines = [
            f"{prefix}{tmp} = text_actions.crop_text({text}, mode={mode!r}, "
            f"from_flag={from_flag}, ignore_case={ignore_case})"
        ]
        if cropped_var:
            lines.append(f"{prefix}{cropped_var} = {tmp}.cropped_text")
        if found_var:
            lines.append(f"{prefix}{found_var} = {tmp}.is_flag_found")
        return lines

    if action_id == "Text.CropText.CropTextBetweenFlags":
        # 知見142: `GetTextBetweenFlags`モード(`FromFlag`/`ToFlag`両方を使う)。
        text = safe_render(p.get("Text"))
        from_flag = safe_render(p.get("FromFlag"))
        to_flag = safe_render(p.get("ToFlag"))
        ignore_case = safe_render(p.get("IgnoreCase"))
        cropped_var = node.output_vars.get("CroppedText")
        found_var = node.output_vars.get("IsFlagFound")
        if text is None or from_flag is None or to_flag is None or ignore_case is None:
            return None
        if not cropped_var and not found_var:
            return None
        tmp = "_crop_result"
        lines = [
            f"{prefix}{tmp} = text_actions.crop_text({text}, mode='GetTextBetweenFlags', "
            f"from_flag={from_flag}, to_flag={to_flag}, ignore_case={ignore_case})"
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

    if action_id == "Text.JoinText.JoinWithDelimiter":
        # 知見139・142: `JoinTextAction`の兄弟セレクタ(`DelimiterType=Standard`、
        # `JoinTextDelimiter`列挙値`None`/`Standard`/`Custom`は既存の
        # `_resolve_delimiter()`と文字列完全一致と実機確認済み)。
        items = safe_render(p.get("List"))
        standard_delimiter = enum_last(p.get("StandardDelimiter"))
        delimiter_times = safe_render(p.get("DelimiterTimes"))
        if items is None or standard_delimiter is None or delimiter_times is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.join_text({items}, "
            f"delimiter_type='Standard', standard_delimiter={standard_delimiter!r}, "
            f"delimiter_times={delimiter_times})"
        ]

    if action_id == "Text.JoinText.JoinWithCustomDelimiter":
        # 知見142: `DelimiterType=Custom`。
        items = safe_render(p.get("List"))
        custom_delimiter = safe_render(p.get("CustomDelimiter"))
        delimiter_times = safe_render(p.get("DelimiterTimes"))
        if items is None or custom_delimiter is None or delimiter_times is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.join_text({items}, "
            f"delimiter_type='Custom', custom_delimiter={custom_delimiter}, "
            f"delimiter_times={delimiter_times})"
        ]

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

    _PARSE_TEXT_ALL_MATCHES = {
        "Text.ParseText.Parse": False,
        "Text.ParseText.RegexParse": True,
    }
    if action_id in _PARSE_TEXT_ALL_MATCHES:
        # 知見139・142: `ParseTextAction`の兄弟セレクタ(`FirstOccurrenceOnly=False`、
        # 複数マッチを`Matches`/`OccurrencePositions`(いずれもリスト)へ出力する)。
        # 既存の`parse_text()`が`is_regex`/`first_occurrence_only`を既に実装済み。
        text = safe_render(p.get("Text"))
        text_to_find = safe_render(p.get("TextToFind"))
        starting_position = safe_render(p.get("StartingPosition"))
        ignore_case = safe_render(p.get("IgnoreCase"))
        matches_var = node.output_vars.get("Matches")
        positions_var = node.output_vars.get("OccurrencePositions")
        if text is None or text_to_find is None or starting_position is None or ignore_case is None:
            return None
        if not matches_var and not positions_var:
            return None
        is_regex = _PARSE_TEXT_ALL_MATCHES[action_id]
        tmp = "_parse_result"
        lines = [
            f"{prefix}{tmp} = text_actions.parse_text({text}, {text_to_find}, "
            f"is_regex={is_regex}, first_occurrence_only=False, ignore_case={ignore_case}, "
            f"starting_position={starting_position})"
        ]
        if matches_var:
            lines.append(f"{prefix}{matches_var} = {tmp}.matches")
        if positions_var:
            lines.append(f"{prefix}{positions_var} = {tmp}.occurrence_positions")
        return lines

    if action_id == "Text.ParseText.RegexParseForFirstOccurrence":
        # 知見142: `IsRegEx=True`×`FirstOccurrenceOnly=True`(既存の
        # `ParseForFirstOccurrence`のRegex版)。
        text = safe_render(p.get("Text"))
        text_to_find = safe_render(p.get("TextToFind"))
        starting_position = safe_render(p.get("StartingPosition"))
        ignore_case = safe_render(p.get("IgnoreCase"))
        match_var = node.output_vars.get("Match")
        position_var = node.output_vars.get("OccurrencePosition")
        if text is None or text_to_find is None or starting_position is None or ignore_case is None:
            return None
        if not match_var and not position_var:
            return None
        tmp = "_parse_result"
        lines = [
            f"{prefix}{tmp} = text_actions.parse_text({text}, {text_to_find}, "
            f"is_regex=True, ignore_case={ignore_case}, starting_position={starting_position})"
        ]
        if match_var:
            lines.append(f"{prefix}{match_var} = {tmp}.match")
        if position_var:
            lines.append(f"{prefix}{position_var} = {tmp}.occurrence_position")
        return lines

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

    if action_id == "Text.Replace.ReplaceTextWithRegex":
        # 知見139・142: `ReplaceTextAction`の兄弟セレクタ(`IsRegEx=True`、既存の
        # `replace_text()`の`is_regex`引数がそのまま対応できる)。
        text = safe_render(p.get("Text"))
        text_to_find = safe_render(p.get("TextToFind"))
        replace_with = safe_render(p.get("ReplaceWith"))
        ignore_case = safe_render(p.get("IgnoreCase"))
        activate_escape = safe_render(p.get("ActivateEscapeSequences"))
        if None in (text, text_to_find, replace_with, ignore_case, activate_escape):
            return None
        if not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.replace_text({text}, {text_to_find}, {replace_with}, "
            f"is_regex=True, ignore_case={ignore_case}, activate_escape_sequences={activate_escape})"
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

    if action_id == "Text.SplitText.SplitWithDelimiter":
        # 知見139・142: `SplitTextAction`の兄弟セレクタ(`DelimiterType=Custom`、
        # `SplitTextDelimiter`列挙値`Standard`/`Custom`/`NumberOfCharacters`は既存の
        # `split_text()`の`delimiter_type`と文字列完全一致と実機確認済み)。
        text = safe_render(p.get("Text"))
        custom_delimiter = safe_render(p.get("CustomDelimiter"))
        delimiter_times = safe_render(p.get("DelimiterTimes"))
        if text is None or custom_delimiter is None or delimiter_times is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.split_text({text}, "
            f"delimiter_type='Custom', custom_delimiter={custom_delimiter}, "
            f"delimiter_times={delimiter_times})"
        ]

    if action_id == "Text.SplitText.SplitAtNumberOfCharacters":
        # 知見142: `DelimiterType=NumberOfCharacters`(`SplitInterval`ごとに分割)。
        text = safe_render(p.get("Text"))
        split_interval = safe_render(p.get("SplitInterval"))
        if text is None or split_interval is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = text_actions.split_text({text}, "
            f"delimiter_type='NumberOfCharacters', split_interval={split_interval})"
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
