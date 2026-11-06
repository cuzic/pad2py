"""`Variables.Actions`(数値・リスト・DataTable・JSON)のロジック層。

PADのDataTable/List系アクションの多くは対象コレクションを`[InputArgument(Mutable
= true)]`で受け取る——つまり既存の変数をその場で変更する。この層でもその意味論に
合わせ、リスト/DataTableを引数として受け取り、戻り値を返す代わりに**その場で変更
する**関数として実装する(新しいリストを作って返す関数と誤って混用しないよう、
全てのin-place関数は戻り値`None`に統一する)。

`SubtractLists`/`FindCommonListItems`が使うPAD独自の汎用比較エンジン
(`ComparisonCalculator.Compare`)は design/dsl_format_findings.md 知見85で実機確認
済み(文字列は大文字小文字を区別するが、数値を表す文字列と数値は型をまたいで
等価)。知見88で`IF`/`SET`の`=`/`<>`演算子も同じ規則に従うことを実機確認済み
(`pad_action_lib.expr_runtime.pad_equal()`に共通実装、`pad_codegen`側もこれを使うよう
結線済み)。`FilterDataTableAction`のフィルタ条件(`FilterParameters`)のDataTableスキーマ
(`COLUMN`/`OPERATOR`/`VALUE`/`RULE`列)は知見90でdecompile+実機確認済みのため結線済み
(`filter_datatable()`)。`JoinDataTableAction`の結合条件(`JoinParameters`)のDataTable
スキーマ(`"COLUMN 1"`/`OPERATOR`/`"COLUMN 2"`列)も知見91で同じ手法(decompile+実機
確認)で判明したため結線済み(`join_datatable()`)。
"""
from __future__ import annotations

import json
import math

from .expr_runtime import pad_equal as _pad_compare_equal
import random as _random

from .datatable import DataTable, Row, columns_of
from .datatable import datatable_from_csv_text as datatable_from_csv_text
from .datatable import datatable_from_fixed_width_csv as datatable_from_fixed_width_csv
from .datatable import datatable_to_csv_text as datatable_to_csv_text

# --- 数値系 ---------------------------------------------------------------


def truncate_number(number: float, mode: str = "GetIntegerPart", decimal_digits: int = 0) -> float:
    """`Variables.TruncateNumber`の3兄弟セレクタ(表示名`GetIntegerPart`/`GetDecimalPart`/
    `RoundNumber`、実機の`Operation`列挙値は最後だけ`RoundAtNthDecimalDigits`——知見135で
    VM上のリフレクションで確認済み)。

    design/dsl_format_findings.md 知見135(VM上で`TruncateNumber.Execute()`を直接呼び出して
    確認済み): `RoundAtNthDecimalDigits`は0.5を偶数側へ丸める「偶数への丸め」(banker's
    rounding、`2.5`→`2`・`3.5`→`4`)——これはPythonの`round()`の既定動作と一致する。
    **既知の限界**: 実機は.NETの`decimal`型(10進数の正確な演算)で計算するが、この層は
    `float`(2進浮動小数点)を受け取るため、10進数では正確に表現できる値(`2.675`等)が
    2進数では近似値になり、`round()`の結果が実機の`decimal`演算と食い違う可能性がある
    (例: 実機の`2.675`→`2.68`に対し、Pythonの`round(2.675, 2)`は2進近似の影響で`2.67`に
    なる)——元のDSLリテラルの文字列表現を保持して`decimal.Decimal`で計算するよう
    上流から作り直せば解決できるが、今回はこの既知の限界を明記するに留めた。
    """
    if mode == "GetIntegerPart":
        return math.trunc(number)
    if mode == "GetDecimalPart":
        return number - math.trunc(number)
    if mode == "RoundAtNthDecimalDigits":
        return round(number, decimal_digits)
    raise ValueError(f"Unknown TruncateNumber mode: {mode!r}")


def generate_random_number(
    minimum: int,
    maximum: int,
    count: int = 1,
    allow_duplicates: bool = True,
    *,
    rng: object | None = None,
) -> list[int]:
    rand = rng if rng is not None else _random
    if not allow_duplicates:
        pool_size = maximum - minimum + 1
        if count > pool_size:
            # [Throws]タグの外側で素の例外として伝播する(他アクションと不整合)。
            raise ValueError("count exceeds the number of unique values available in range")
        return list(rand.sample(range(minimum, maximum + 1), count))
    return [rand.randint(minimum, maximum) for _ in range(count)]


def increase_variable(value: float, increment: float = 1) -> float:
    return value + increment


def decrease_variable(value: float, decrement: float = 1) -> float:
    return value - decrement


# --- リスト系 ---------------------------------------------------------------


def create_new_list() -> list:
    return []


def add_item_to_list(items: list, item: object) -> None:
    items.append(item)


def remove_item_from_list_by_index(items: list, index: int) -> None:
    del items[index]


def remove_item_from_list_by_value(items: list, value: object, all_occurrences: bool = False) -> None:
    """`ItemMatchAllOccurrences`(知見135でVM上の`RemoveItemFromList.Execute()`直接呼び出しで
    確認済み): `False`(既定)は最初の1件だけ削除(`list.remove()`と同じ)、`True`は
    一致する全ての要素を削除する。
    """
    if all_occurrences:
        items[:] = [item for item in items if item != value]
    else:
        items.remove(value)


def clear_list(items: list) -> None:
    items.clear()


def reverse_list(items: list) -> None:
    items.reverse()


def shuffle_list(items: list, *, rng: object | None = None) -> None:
    (rng if rng is not None else _random).shuffle(items)


def merge_lists(target: list, other: list) -> None:
    target.extend(other)


def subtract_lists(items: list, other: list) -> list:
    return [item for item in items if not any(_pad_compare_equal(item, o) for o in other)]


def find_common_list_items(items: list, other: list) -> list:
    return [item for item in items if any(_pad_compare_equal(item, o) for o in other)]


def remove_duplicate_items_from_list(items: list, ignore_case: bool = False) -> None:
    # IgnoreCaseは全要素が文字列の場合のみ有効、それ以外は黙って無視する。
    use_ignore_case = ignore_case and all(isinstance(v, str) for v in items)
    seen: set = set()
    deduped: list = []
    for value in items:
        key = value.lower() if use_ignore_case else value
        if key not in seen:
            seen.add(key)
            deduped.append(value)
    items[:] = deduped


def sort_list(
    items: list,
    descending: bool = False,
    keys: list[str] | None = None,
    key_descending: list[bool] | None = None,
) -> None:
    """`Variables.SortList`の兄弟セレクタ`SortListByProperty`(最大3キー、各キーが独立した
    昇順/降順を持てる)に対応する。`keys`省略時は単純な値ソート(`Variables.SortList.SortList`、
    実機確認ではこちらに方向指定自体が存在しない)。`keys`指定時、`key_descending`で各キーの
    方向を個別に指定できる(省略時は全キーとも`descending`に従う)。

    design/dsl_format_findings.md 知見134(VM上で`SortListBase.Execute()`を実機の
    `CustomObject`で直接呼び出して確認済み): 実機の多キーソート結果は、Pythonの安定ソートを
    **最下位キーから順に**適用した結果と完全に一致した(各キーを個別の`list.sort()`呼び出しで
    適用し、最後に最上位キーをソートする——標準的な「安定ソートの繰り込み」によるSQLの
    `ORDER BY`相当の多キーソート実装)。
    """
    if not keys:
        items.sort(reverse=descending)
        return
    directions = key_descending if key_descending is not None else [descending] * len(keys)
    for key, desc in reversed(list(zip(keys, directions))):
        items.sort(key=lambda item, k=key: item[k], reverse=desc)


# --- DataTable系 -------------------------------------------------------------


def create_new_datatable(source: DataTable) -> DataTable:
    return [dict(row) for row in source]


def clear_datatable(table: DataTable) -> None:
    table.clear()


def add_row_to_datatable(table: DataTable, row: Row | list[object]) -> None:
    """design/dsl_format_findings.md 知見124(decompile確認済み): PADの実際の
    `AddRowToDataTable.RowToAdd`は`List<object>`(列名との対応は**列の並び順**、
    `DataRow.ItemArray = RowToAdd.ToArray()`)——辞書ではない。知見90・91等で
    「`CreateNewDatatable`+`AddColumnToDataTable`+`CreateNewList`+`AddItemToList`+
    `AddRowToDataTable`だけでTier1アクションのみからDataTableを組み立てる」という
    手法を繰り返し使ってきたが、これは**実機のPAD自体でのみ検証済み**で、
    `pad_action_lib`層(このPythonポート)を経由する codegen→実行の往復では
    一度も検証されていなかった——このdictベースの実装は実際には`list`が渡されると
    クラッシュするバグだったと判明した(知見124)。

    `row`が`list`の場合は`columns_of(table)`(既存の行から推測した列順序)と位置で
    対応付けて辞書に変換する。**この`DataTable`表現(列順序を各行の辞書のキー順序で
    保持する、モジュールdocstring参照)には列だけを独立して追跡する仕組みが無いため、
    行が1件も無い状態(`AddColumnToDataTable`だけ呼ばれた直後)で`list`を渡すと
    列名が全く分からず解決不能**——この場合は明示的な`ValueError`にする(でっち上げた
    列名を使わない)。この限界自体は根本的な表現の見直し(列を行と独立に保持する
    `DataTable`型への変更)が必要な、より大きな構造的課題として残っている
    (design/pad_todo.md参照)。
    """
    table.append(_coerce_row(table, row))


def _coerce_row(table: DataTable, row: Row | list[object]) -> Row:
    if isinstance(row, list):
        columns = columns_of(table)
        if not columns:
            raise ValueError(
                "cannot add a list-shaped row to a table with no rows yet (columns added via "
                "add_column_to_datatable() to an empty table are not tracked independently of "
                "rows in this DataTable representation)"
            )
        if len(row) != len(columns):
            raise ValueError(f"row has {len(row)} values but table has {len(columns)} columns")
        return dict(zip(columns, row))
    return dict(row)


def insert_row_to_datatable(table: DataTable, row: Row | list[object], index: int) -> None:
    """`Variables.AddRowToDataTable`の兄弟セレクタ`InsertItemToDataTable`に対応する。

    design/dsl_format_findings.md 知見135(VM上で`AddRowToDataTable.Execute()`を
    `PositionToAddRow: BeforeRowIndex`で直接呼び出して確認済み): `RowIndex`は0始まり
    (知見133参照)で、Pythonの`list.insert(index, item)`と全く同じ「指定位置の**前**に
    挿入する」セマンティクスだった。`RowToAdd`の型(`List`/辞書どちらも受け付ける)は
    知見124の`AddRowToDataTable`と同じ。
    """
    table.insert(index, _coerce_row(table, row))


def delete_row_from_datatable(table: DataTable, index: int) -> None:
    del table[index]


def _resolve_column_name(table: DataTable, column: str) -> str:
    """`ColumnNameOrIndex`文字列(列名、または数値文字列なら列インデックス)を実際の
    列名へ解決する。

    design/dsl_format_findings.md 知見133(VM上で実機の`IListIndexService`実装
    `Robin.Core.Execution.ListIndexService`を直接インスタンス化・確認済み): 本プロジェクトが
    対象とするクリップボードDSL(`ScriptType.Robin`)では`IsZeroBased=True`で
    `ConvertInput()`は恒等写像(入力をそのまま返す)——つまり列インデックスは常に
    **0始まり**(Pythonのリスト添字と同じ)。1始まりになるのは`ScriptType.PowerFx`
    (`ConvertInput(n) = n - 1`)という別のスクリプト種別のみで、本プロジェクトが変換対象とする
    クリップボードDSLには現れない。知見123・126で「IsZeroBasedが未確認」としていた数値
    インデックス対応は、この確認によりでっち上げではなく解決した。
    """
    if column.lstrip("-").isdigit():
        columns = columns_of(table)
        index = int(column)
        try:
            return columns[index]
        except IndexError:
            raise ValueError(
                f"column index {index} out of range (table has {len(columns)} columns)"
            ) from None
    return column


def modify_datatable_item(table: DataTable, row_index: int, column: str, value: object) -> None:
    """`ColumnNameOrIndex`は実機では列名/列インデックス(`int.TryParse`判定)の両方を
    受け付ける(知見133で0始まりと確認済み、`_resolve_column_name()`参照)。
    """
    table[row_index][_resolve_column_name(table, column)] = value


def _cell_matches(cell: object, find_value: str, is_regex: bool, ignore_case: bool, entire_cell: bool) -> bool:
    import re

    text = str(cell)
    if is_regex:
        # design/dsl_format_findings.md 知見176(decompile確認済みの修正): `FindOrReplaceInDataTable.
        # Match()`のUseRegex分岐は`regex?.IsMatch(text)`のみで、`MatchCase`/`MatchEntireCellContents`
        # を一切参照しない——正規表現は`ValidateAndInitializeRegex()`で`RegexOptions.Compiled`のみ
        # (IgnoreCase無し)でコンパイルされるため常に大文字小文字を区別し、`IsMatch`は部分一致
        # (アンカー無し)。`ignore_case`/`entire_cell`はいずれも無視する(両パラメータは実機でも
        # Regex系セレクタで常にHiddenかつ既定値False)。
        return re.search(find_value, text) is not None
    haystack = text.lower() if ignore_case else text
    needle = find_value.lower() if ignore_case else find_value
    return haystack == needle if entire_cell else needle in haystack


def find_and_replace_in_datatable_everywhere(
    table: DataTable,
    value_to_find: str,
    text_to_replace_with: str,
    *,
    all_matches: bool = True,
    match_case: bool = False,
    match_entire_cell_contents: bool = False,
    use_regex: bool = False,
    column: str | None = None,
) -> list[tuple[int, int]]:
    """design/dsl_format_findings.md 知見176(decompile確認済み): `FindOrReplaceInDataTable`の
    `SearchMode=FindAndReplace`側(`Replace*`系4セレクタ)。マッチ判定自体は`SearchMode=Find`側
    (`find_item_in_datatable_everywhere()`)と全く同じロジック・同じ`DataTableMatches`出力契約
    (`(行, 列)`の0始まりペアのリスト)——マッチしたセルを即座に置換しながらテーブルを
    直接mutateする点のみが異なる。置換の実装は decompile した`FindOrReplaceForCell()`の
    3分岐そのまま: `use_regex`は`regex.Replace(text, TextToReplaceWith)`(常に大文字小文字を
    区別、`_cell_matches()`の修正と同じ理由でMatchCaseは無視)、`match_entire_cell_contents`は
    セル全体をそのまま置換、それ以外は`ReplaceString()`相当(大文字小文字を区別した/しない
    部分文字列置換、置換後の文字列中の元のケースは保持しない——decompile確認済みの通り
    置換文字列自体をそのまま挿入するだけ)。
    """
    import re

    resolved_column = _resolve_column_name(table, column) if column is not None else None
    matches: list[tuple[int, int]] = []
    for row_idx, row in enumerate(table):
        for col_idx, col_name in enumerate(list(row.keys())):
            if resolved_column is not None and col_name != resolved_column:
                continue
            cell = row[col_name]
            if not _cell_matches(cell, value_to_find, use_regex, not match_case, match_entire_cell_contents):
                continue
            matches.append((row_idx, col_idx))
            text = str(cell)
            if use_regex:
                row[col_name] = re.sub(value_to_find, text_to_replace_with, text)
            elif match_entire_cell_contents:
                row[col_name] = text_to_replace_with
            elif match_case:
                row[col_name] = text.replace(value_to_find, text_to_replace_with)
            else:
                row[col_name] = re.sub(
                    re.escape(value_to_find), text_to_replace_with, text, flags=re.IGNORECASE
                )
            if not all_matches:
                return matches
    return matches


def find_item_in_datatable_everywhere(
    table: DataTable,
    value_to_find: str,
    *,
    all_matches: bool = True,
    match_case: bool = False,
    match_entire_cell_contents: bool = False,
    use_regex: bool = False,
    column: str | None = None,
) -> list[tuple[int, int]]:
    """design/dsl_format_findings.md 知見89で実機確認済みの出力契約。

    `DataTableMatches`は`(行インデックス, 列インデックス)`の0始まりペアのリストで、
    行→列の順で走査して見つかった順に並ぶ。`AllMatches: False`でも(スカラーではなく)
    最初の1件だけを含むリストのまま返る(実機のテキスト直列化`"0, 0"`は要素数1の
    リストと要素数2のリスト`"0, 0\\n1, 0"`で同じ"行, 列"形式が繰り返されるのみで、
    型が変わる兆候は無かった)。

    design/dsl_format_findings.md 知見123: `use_regex`/`column`は`FindOrReplaceInDataTable`の
    兄弟セレクタ(`FindItemInDataTableWithRegexEverywhere`/`FindItemInDataTableByColumnIndex`)の
    decompile結果から追加した。`column`は実機のPAD自体が`ColumnNameOrIndex`という
    文字列/数値どちらも受け付けるパラメータを使う(`int.TryParse`成功時は列インデックス、
    失敗時は列名として解釈)——知見133で0始まりと確認済みのため`_resolve_column_name()`で
    数値文字列も列名へ解決する。
    """
    resolved_column = _resolve_column_name(table, column) if column is not None else None
    matches: list[tuple[int, int]] = []
    for row_idx, row in enumerate(table):
        for col_idx, (col_name, cell) in enumerate(row.items()):
            if resolved_column is not None and col_name != resolved_column:
                continue
            if _cell_matches(cell, value_to_find, use_regex, not match_case, match_entire_cell_contents):
                matches.append((row_idx, col_idx))
                if not all_matches:
                    return matches
    return matches


def delete_empty_rows_from_datatable(table: DataTable) -> None:
    table[:] = [row for row in table if any(str(v).strip() for v in row.values())]


def delete_duplicate_rows_from_datatable(table: DataTable) -> None:
    seen: set = set()
    deduped: list[Row] = []
    for row in table:
        key = tuple(sorted(row.items()))
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    table[:] = deduped


def add_column_to_datatable(table: DataTable, column: str, default_value: object = "") -> None:
    for row in table:
        row[column] = default_value


def insert_column_to_datatable(table: DataTable, column: str, index: int, default_value: object = "") -> None:
    """`Variables.AddColumnToDataTable`の兄弟セレクタ`InsertColumnToDataTable`に対応する。

    design/dsl_format_findings.md 知見135(VM上で`AddColumnToDataTableAction.Execute()`を
    `PositionToAddColumn: BeforeColumnIndex`で直接呼び出して確認済み): `ColumnIndex`は
    0始まり(知見133参照)で、指定位置の**前**に新しい列が挿入される(既存列の値は
    空文字列`""`で埋まる、`add_column_to_datatable()`と同じ既定値)。
    """
    for row in table:
        items = list(row.items())
        items.insert(index, (column, default_value))
        row.clear()
        row.update(items)


def delete_column_from_datatable(table: DataTable, column: str | int) -> None:
    """`Variables.DeleteColumnFromDataTable`の兄弟セレクタ`DeleteColumnWithIndex`に対応する
    (`column`が`int`の場合は列インデックス、0始まり、知見133参照)。
    """
    resolved = _resolve_column_name(table, str(column)) if isinstance(column, int) else column
    for row in table:
        row.pop(resolved, None)


def sort_datatable(table: DataTable, column: str | int, descending: bool = False) -> None:
    """`Variables.SortDataTable`の兄弟セレクタ`SortWithColumnName`/`SortWithColumnIndex`両方に
    対応する。`column`が`int`の場合は列インデックス(0始まり、知見133参照)として解決する。
    """
    resolved = _resolve_column_name(table, str(column)) if isinstance(column, int) else column
    table.sort(key=lambda row: row.get(resolved), reverse=descending)


def merge_datatables(target: DataTable, other: DataTable) -> None:
    target.extend(dict(row) for row in other)


def _filter_column_type(table: DataTable, column: str) -> type | None:
    seen: type | None = None
    for row in table:
        value = row.get(column)
        if value is None:
            continue
        value_type = type(value)
        if seen is None:
            seen = value_type
        elif value_type is not seen:
            raise ValueError(f"Column {column!r} has mixed types: {seen} vs {value_type}")
    return seen


def _filter_text_equal(a: object, b: object, match_case: bool) -> bool:
    if isinstance(a, str) and isinstance(b, str) and not match_case:
        return a.lower() == b.lower()
    return a == b


def _filter_condition_matches(row: Row, condition: Row, column_types: dict, match_case: bool) -> bool:
    column = str(condition.get("COLUMN"))
    operator = str(condition.get("OPERATOR"))
    value = condition.get("VALUE")
    cell = row.get(column)
    if operator == "IsBlank":
        return cell is None
    if operator == "IsNotBlank":
        return cell is not None
    if operator == "IsEmpty":
        return cell is None or str(cell) == ""
    if operator == "IsNotEmpty":
        return not (cell is None or str(cell) == "")
    if operator in ("Equal", "NotEqual"):
        # 知見98で実機確認済み: ReadFieldsAsText: Falseで数値型に変換した列を文字列の
        # VALUEでEqualフィルタすると0件になる(型不一致は常に不一致)。
        type_mismatch = cell is not None and value is not None and type(cell) is not type(value)
        if operator == "Equal":
            return False if type_mismatch else _filter_text_equal(cell, value, match_case)
        return True if type_mismatch else (cell is None or not _filter_text_equal(cell, value, match_case))
    if operator in ("GreaterThan", "GreaterThanOrEqual", "LessThan", "LessThanOrEqual"):
        if cell is None:
            return False
        if operator == "GreaterThan":
            return cell > value  # type: ignore[operator]
        if operator == "GreaterThanOrEqual":
            return cell >= value  # type: ignore[operator]
        if operator == "LessThan":
            return cell < value  # type: ignore[operator]
        return cell <= value  # type: ignore[operator]
    text = "" if cell is None else str(cell)
    needle = "" if value is None else str(value)
    if not match_case:
        text, needle = text.lower(), needle.lower()
    if operator == "StartsWith":
        return text.startswith(needle)
    if operator == "EndsWith":
        return text.endswith(needle)
    if operator == "Contains":
        return needle in text
    if operator == "NotContains":
        return needle not in text
    if operator == "NotStartsWith":
        return not text.startswith(needle)
    if operator == "NotEndsWith":
        return not text.endswith(needle)
    raise ValueError(f"Unsupported FilterDataTable operator: {operator!r}")


def filter_datatable(table: DataTable, conditions: DataTable, match_case: bool = True) -> DataTable:
    """design/dsl_format_findings.md 知見90で実機確認済みの出力契約。

    `conditions`(`FilterParameters`)は`COLUMN`/`OPERATOR`/`VALUE`/`RULE`列を持つDataTable
    (decompileした`FilterDataTableUtilities`/`FilterDataTableExtensions`から判明、`Equal`で
    3行(`Age Equal 30 AND Name Equal Carol`)・`Contains`・`RULE: Or`(知見99)を実機のRun
    実行+ファイル書き出しで検証済み)。`RULE`は2行目以降で前の行との結合方法(`"Or"`/
    `"And"`、既定は`"And"`)を表す。標準的な論理演算子の優先順位(ANDがORより強く結合)に
    従い、OR区切りのAND-group群として評価する。`Equal`/`NotEqual`は両辺のPython型が
    一致しない場合、常に不一致(`Equal`→常に偽、`NotEqual`→常に真)という実機特有の挙動
    (decompile済みソースの`flag`判定、知見98で実機確認済み)を再現する。順序比較演算子
    (`GreaterThan`等)は数値変換せず文字列のまま比較する(知見97で実機確認済み)。
    """
    if not conditions:
        return [dict(row) for row in table]
    columns = {str(c.get("COLUMN")) for c in conditions}
    column_types = {col: _filter_column_type(table, col) for col in columns}
    groups: list[list[Row]] = [[]]
    for i, condition in enumerate(conditions):
        if i > 0 and condition.get("RULE") == "Or":
            groups.append([])
        groups[-1].append(condition)

    def row_matches(row: Row) -> bool:
        return any(
            all(_filter_condition_matches(row, cond, column_types, match_case) for cond in group)
            for group in groups
        )

    return [dict(row) for row in table if row_matches(row)]


def _join_condition_matches(row1: Row, row2: Row, condition: Row) -> bool:
    column1 = str(condition.get("COLUMN 1"))
    column2 = str(condition.get("COLUMN 2"))
    operator = str(condition.get("OPERATOR"))
    a, b = row1.get(column1), row2.get(column2)
    if operator == "Equal":
        return _pad_compare_equal(a, b)
    if operator == "NotEqual":
        return not _pad_compare_equal(a, b)
    # design/dsl_format_findings.md 知見97(実機確認済み): 順序比較演算子(GreaterThan等)は
    # `Equal`/`NotEqual`と違いクロス型の数値文字列同値判定をしない——`"9" GreaterThan "10"`
    # が真になる(文字列としての辞書順比較、数値なら偽になるはず)ことを実機で確認した。
    # 以前は数値変換を試みていたが、これは実機の挙動と食い違う誤りだったため削除した。
    if operator == "GreaterThan":
        return a > b  # type: ignore[operator]
    if operator == "GreaterThanOrEqual":
        return a >= b  # type: ignore[operator]
    if operator == "LessThan":
        return a < b  # type: ignore[operator]
    if operator == "LessThanOrEqual":
        return a <= b  # type: ignore[operator]
    raise ValueError(f"Unsupported JoinDataTable operator: {operator!r}")


def join_datatable(
    first: DataTable, second: DataTable, join_parameters: DataTable, join_operation: str = "Inner"
) -> DataTable:
    """design/dsl_format_findings.md 知見91で実機確認済みの出力契約。

    `join_parameters`(`JoinParameters`)は`"COLUMN 1"`/`OPERATOR`/`"COLUMN 2"`列を持つ
    DataTable(decompileした`JoinDataTableExtensions`/`JoinDataTableAction`から判明、
    `Equal`での`Inner`/`Left`/`Full`を実機のRun実行+ファイル書き出しで検証済み)。
    全条件行はAND結合(`FilterParameters`の`RULE`に相当する列は無い)。`OPERATOR`は
    `Equal`/`NotEqual`のみ知見85/88の`pad_equal()`(クロス型の数値文字列同値判定)を
    使い、順序比較系は数値変換できる場合のみ数値として比較する(decompile済みソースが
    `ComparisonCalculator.Compare`に委譲している箇所を`expr_runtime`の既存ヘルパーで
    再現、個別の実機検証はしていない)。両テーブルで列名が重複する場合、2番目の
    テーブル側の列名に`" (2)"`を付けて区別する(実機確認済み)。`Left`/`Full`の
    不一致側は`None`で埋める(CSV変換時は空文字列として書き出される、実機確認済み)。
    """
    first_columns = list(first[0].keys()) if first else []
    second_columns = list(second[0].keys()) if second else []
    renamed_second_columns = [f"{c} (2)" if c in first_columns else c for c in second_columns]

    def rows_match(row1: Row, row2: Row) -> bool:
        return all(_join_condition_matches(row1, row2, cond) for cond in join_parameters)

    def combine(row1: Row | None, row2: Row | None) -> Row:
        result: Row = {col: (row1.get(col) if row1 is not None else None) for col in first_columns}
        for col, renamed in zip(second_columns, renamed_second_columns):
            result[renamed] = row2.get(col) if row2 is not None else None
        return result

    result: DataTable = []
    if join_operation in ("Inner", "Left", "Full"):
        for row1 in first:
            matched = False
            for row2 in second:
                if rows_match(row1, row2):
                    result.append(combine(row1, row2))
                    matched = True
            if not matched and join_operation != "Inner":
                result.append(combine(row1, None))
        if join_operation == "Full":
            for row2 in second:
                if not any(rows_match(row1, row2) for row1 in first):
                    result.append(combine(None, row2))
    else:
        raise ValueError(f"Unsupported JoinDataTable join_operation: {join_operation!r}")
    return result


def _filter_list_condition_matches(item: object, condition: Row, ignore_case: bool) -> bool:
    operator = str(condition.get("OPERATOR"))
    value = condition.get("VALUE")
    text = "" if item is None else str(item)
    value_text = "" if value is None else str(value)
    text_cmp = text.lower() if ignore_case else text
    value_cmp = value_text.lower() if ignore_case else value_text
    if operator == "Contains":
        return value_cmp in text_cmp
    if operator == "NotContains":
        return value_cmp not in text_cmp
    if operator == "StartsWith":
        return text_cmp.startswith(value_cmp)
    if operator == "NotStartsWith":
        return not text_cmp.startswith(value_cmp)
    if operator == "EndsWith":
        return text_cmp.endswith(value_cmp)
    if operator == "NotEndsWith":
        return not text_cmp.endswith(value_cmp)
    if operator == "IsEmpty":
        return text == ""
    if operator == "IsNotEmpty":
        return text != ""
    if operator == "Equal":
        # design/dsl_format_findings.md 知見165(decompile確認済み): `IgnoreCase=True`は
        # 単純な大文字小文字区別無し文字列比較(クロス型の数値文字列同値判定はしない)、
        # `IgnoreCase=False`の場合のみ`pad_equal()`(知見85/88のクロス型同値判定)に
        # 委譲する——`FilterDataTable`/`JoinDataTable`とは異なり`IgnoreCase`が比較
        # アルゴリズム自体を切り替える`FilterList`特有の挙動。
        if ignore_case:
            return text_cmp == value_cmp
        return _pad_compare_equal(item, value)
    if operator == "NotEqual":
        if ignore_case:
            return text_cmp != value_cmp
        return not _pad_compare_equal(item, value)
    # `GreaterThan`/`GreaterThanOrEqual`/`LessThan`/`LessThanOrEqual`(実機のクロス型
    # 比較規則が未確認、知見97のJoinDataTableでの「常に文字列比較」と矛盾しうる)・
    # `IsBlank`/`IsNotBlank`(PADの`Blank`値に対応するPython表現が未確立)は、
    # でっち上げず明示的に未対応とする——呼び出し元の`pad_codegen`はこれらの演算子が
    # 使われている場合、安全にTODOフォールバックへ倒す。
    raise NotImplementedError(f"Unsupported FilterList operator: {operator!r}")


def filter_list(items: list, conditions: DataTable, ignore_case: bool = False) -> list:
    """design/dsl_format_findings.md 知見165(decompile確認済み): `FilterParameters`は
    `FilterDataTable`(知見90)と同じ`OPERATOR`/`VALUE`/`RULE`列を持つDataTableだが、
    `COLUMN`列は無い(各リスト項目そのものが評価対象)。`FilterListUtilities.
    EvaluateFilterConditions()`/`EvaluateSingleCondition()`をdecompileして確認した
    とおり、`FilterDataTable`と同じOR区切りのAND-group群として評価する。
    """
    if not conditions:
        return list(items)
    groups: list[list[Row]] = [[]]
    for i, condition in enumerate(conditions):
        if i > 0 and condition.get("RULE") == "Or":
            groups.append([])
        groups[-1].append(condition)

    def item_matches(item: object) -> bool:
        return any(
            all(_filter_list_condition_matches(item, cond, ignore_case) for cond in group)
            for group in groups
        )

    return [item for item in items if item_matches(item)]


def retrieve_datatable_column_into_list(table: DataTable, column: str) -> list:
    """`ColumnNameOrIndex`は列名/列インデックスの両方を受け付ける(知見133参照)。"""
    resolved = _resolve_column_name(table, column)
    return [row.get(resolved) for row in table]


# CSV<->DataTable変換は`.datatable`の実装をそのまま再公開する(File.Actionsの
# ReadFromCSVFile/WriteToCSVFileと実装を共有するため、ロジック自体はそちらに集約)。


# --- JSON/CustomObject系 -----------------------------------------------------


def json_to_custom_object(json_text: str) -> object:
    return json.loads(json_text)


def custom_object_to_json(value: object, indent: int | None = None) -> str:
    return json.dumps(value, indent=indent)
