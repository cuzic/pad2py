"""`pad_codegen.actions`配下のTier1/Tier2(`pad_action_lib`)結線の単体テスト。

design/dsl_format_findings.md 知見66-72で実機キャプチャした`tests/fixtures/
tier1_*.txt`を実際に`generate_python()`へ通し、(a)構文的に正しいPythonが生成
されること、(b)結線したアクションが`# TODO`に倒れず実コードになること、
(c)意図的に未対応としたアクション(DPAPI保護値・バックティック/`{ }`未対応構文・
比較/フィルタ/結合エンジン未確認等)は正直に`# TODO`のまま残ること、の両方を
確認する(`dump_daemon/codegen_coverage.py`が集計する分岐点のソースコード側の
裏付け)。

これらのフィクスチャは実機キャプチャ時に全てのテキスト入力欄へ同じ`"sample"`を
埋めたものなので、生成コードの値側は(変数参照ではなく)`'sample'`という文字列
リテラルになる——アサーションはそれに合わせている。
"""
from __future__ import annotations

from pathlib import Path

from dump_daemon.pad_codegen import generate_python
from dump_daemon.pad_dsl import build_block_tree, parse_dsl

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _generate(fixture_name: str) -> str:
    text = (FIXTURES_DIR / fixture_name).read_text(encoding="utf-8")
    tree = build_block_tree(parse_dsl(text))
    code = generate_python(tree)
    compile(code, "<generated>", "exec")
    return code


def _todo(action_id: str) -> str:
    return f"# TODO: map PAD action: {action_id}"


def test_text_variables_batch1_all_actions_convert_without_todo() -> None:
    code = _generate("tier1_text_variables_batch1.txt")
    assert "# TODO: map PAD action:" not in code
    assert "TrimmedText = text_actions.trim_text('helloworld', trim_option='Both')" in code
    assert "TextWithNewCase = text_actions.change_case('sample', new_case='UpperCase')" in code
    assert "variables_actions.reverse_list('sample')" in code
    assert "PaddedText = text_actions.pad_text('sample', pad_position='Left', " in code
    assert "JoinedText = text_actions.join_text('sample')" in code
    assert "Result = text_actions.append_line('sample', 'sample')" in code
    assert "EscapedText = text_actions.escape_for_regular_expression('sample')" in code
    assert "ReversedText = text_actions.reverse_text('sample')" in code
    assert "_crop_result = text_actions.crop_text('sample', mode='GetTextBeforeFlag', " in code
    assert "CroppedText = _crop_result.cropped_text" in code
    assert "IsFlagFound = _crop_result.is_flag_found" in code
    assert "Subtext = text_actions.get_subtext('sample', start_index='AtSpecificCharacter', " in code
    assert "TextList = text_actions.split_text('sample', standard_delimiter='Space', delimiter_times=1)" in code
    assert "TextAsNumber = text_actions.text_to_number('sample')" in code
    assert "FormattedNumber = text_actions.number_to_text('sample', decimal_places=2, " in code
    assert "RandomText = text_actions.create_random_text(minimum_length=6, maximum_length=10, " in code
    assert "RandomNumber = variables_actions.generate_random_number(0, 100)[0]" in code


def test_datetime_folder_clipboard_batch2_converts_including_dpapi_zip_password() -> None:
    # design/dsl_format_findings.md 知見112: Passwordは`P'<base64>'`(DPAPI保護値)だが、
    # 以前のVarRefフォールバックとは違い`decrypt_dpapi_sensitive_value()`へ結線される。
    code = _generate("tier1_datetime_folder_clipboard_batch2.txt")
    assert "CurrentDateTime = datetime_actions.get_current_datetime(date_time_format='DateAndTime')" in code
    assert "ResultedDate = datetime_actions.add_to_datetime('sample', 'sample', time_unit='Seconds')" in code
    assert "TimeDifference = datetime_actions.subtract_dates('sample', 'sample', time_unit='Days')" in code
    assert "Files = folder_actions.get_files_in_folder('sample', file_filter='*', " in code
    assert "ClipboardText = clipboard_actions.get_clipboard_text()" in code
    assert "clipboard_actions.set_clipboard_text('sample')" in code
    assert "clipboard_actions.clear_clipboard()" in code
    assert "cryptography_actions.decrypt_dpapi_sensitive_value('AQAAANCMnd8B" in code
    assert "ZipFile = compression_actions.zip_files(" in code


def test_variables_list_datatable_batch3_converts_except_unverified_engines() -> None:
    code = _generate("tier1_variables_list_datatable_batch3.txt")
    assert "List = variables_actions.create_new_list()" in code
    assert "variables_actions.add_item_to_list('sample', 'sample')" in code
    assert "variables_actions.remove_item_from_list_by_index('sample', 'sample')" in code
    assert "variables_actions.clear_list('sample')" in code
    assert "variables_actions.shuffle_list('sample')" in code
    assert "OutputList = 'sample' + 'sample'" in code
    assert "variables_actions.remove_duplicate_items_from_list('sample', ignore_case=False)" in code
    assert "variables_actions.sort_list('sample')" in code
    assert "variables_actions.add_row_to_datatable('sample', 'sample')" in code
    assert "variables_actions.delete_empty_rows_from_datatable('sample')" in code
    assert "variables_actions.modify_datatable_item('sample', row_index='sample', " in code
    assert "variables_actions.add_column_to_datatable('sample', 'sample')" in code
    assert "variables_actions.delete_column_from_datatable('sample', 'sample')" in code
    assert "variables_actions.delete_duplicate_rows_from_datatable('sample')" in code
    assert "variables_actions.clear_datatable('sample')" in code
    assert "variables_actions.sort_datatable('sample', 'sample', descending=False)" in code
    assert "variables_actions.merge_datatables('sample', 'sample')" in code
    assert "ColumnAsList = variables_actions.retrieve_datatable_column_into_list('sample', 'sample')" in code
    assert "variables_actions.delete_row_from_datatable('sample', 'sample')" in code
    # `InputTable: { }` now parses as an empty list, so this is wired (knowledge 74).
    assert "DataTable = variables_actions.create_new_datatable([])" in code
    # ヘッダー無しCSV変換(knowledge 84): IncludeColumnNames: Falseでも結線される。
    # knowledge 127: ColumnsSeparatorの実区切り文字(SystemDefault=",")も渡すようになった。
    assert (
        "CSVText = variables_actions.datatable_to_csv_text('sample', delimiter=',', "
        "include_column_names=False)" in code
    )
    # 比較エンジンの意味論を実機確認(knowledge 85)したため結線される。
    assert "ListDifference = variables_actions.subtract_lists('sample', 'sample')" in code
    assert "IntersectionList = variables_actions.find_common_list_items('sample', 'sample')" in code
    # 出力契約(行,列のペアのリスト)を実機確認(knowledge 89)したため結線される。
    assert (
        "DataTableMatches = variables_actions.find_item_in_datatable_everywhere('sample', 'sample', "
        "all_matches=True, match_case=False, match_entire_cell_contents=False)" in code
    )
    # FilterParametersが空バックティック文字列(未設定)のため[]に読み替えて結線される(knowledge 90)。
    assert (
        "FilteredDataTable = variables_actions.filter_datatable('sample', [], match_case=True)" in code
    )
    # JoinParametersが空バックティック文字列(未設定)のため[]に読み替えて結線される(knowledge 91)。
    assert (
        "JoinedDataTable = variables_actions.join_datatable('sample', 'sample', [], "
        "join_operation='Inner')" in code
    )
    # ReadFieldsAsText: False(knowledge 92)・TrimFields(knowledge 93)の挙動を実機確認したため結線される。
    # knowledge 127: ColumnsSeparatorの実区切り文字(SystemDefault=",")も渡すようになった。
    assert (
        "CSVTable = variables_actions.datatable_from_csv_text('sample', delimiter=',', "
        "first_line_contains_column_names=False, read_fields_as_text=False, "
        "trim_fields=True)" in code
    )


def test_text_variables_batch4_converts_except_unverified_ones() -> None:
    code = _generate("tier1_text_variables_batch4.txt")
    assert "_parse_result = text_actions.parse_text('sample', 'sample', ignore_case=False, " in code
    assert "Position = _parse_result.occurrence_position" in code
    assert "Replaced = text_actions.replace_text('sample', 'sample', 'sample', " in code
    assert "FormattedDateTime = text_actions.datetime_to_text('sample', standard_format='d')" in code
    assert "TextAsDateTime = text_actions.text_to_datetime('sample')" in code
    assert "TruncatedValue = variables_actions.truncate_number('sample', mode='GetIntegerPart')" in code
    assert "JsonAsCustomObject = variables_actions.json_to_custom_object('sample')" in code
    assert "CustomObjectAsJson = variables_actions.custom_object_to_json('sample')" in code
    # RecognizeEntitiesInText always raises NotImplementedError in pad_action_lib -> never wired.
    assert _todo("Text.RecognizeEntitiesInText") in code
    # HtmlEditor: `` now parses as an empty string, so this is wired (knowledge 74).
    assert "HtmlContent = text_actions.create_html_content('')" in code
    # Value is captured as a literal placeholder string (not a variable) in this fixture,
    # so there is no variable to reassign the increased/decreased value back into.
    assert _todo("Variables.IncreaseVariable") in code
    assert _todo("Variables.DecreaseVariable") in code


def test_folder_batch5_converts_all_actions_and_if_folder_exists_condition() -> None:
    code = _generate("tier1_folder_batch5.txt")
    assert "# TODO: map PAD action:" not in code
    assert "CopiedFolder = folder_actions.copy_folder('sample', 'sample', if_file_exists='DoNothing')" in code
    assert "NewFolder = folder_actions.create_folder('sample', 'sample')" in code
    assert "folder_actions.delete_folder('sample')" in code
    assert "folder_actions.empty_folder('sample')" in code
    assert "MovedFolder = folder_actions.move_folder('sample', 'sample')" in code
    assert "RenamedFolder = str(folder_actions.rename_folder('sample', 'sample'))" in code
    assert "Folders = folder_actions.get_subfolders_in_folder('sample', folder_filter='*', " in code
    assert "SpecialFolderPath = folder_actions.get_special_folder('Desktop')" in code
    assert "if folder_actions.if_folder_exists('sample'):" in code


def test_file_batch6_converts_all_actions_including_csv_header_less_case() -> None:
    # design/dsl_format_findings.md 知見84: ヘッダー無しCSV(FirstLineContainsColumnNames/
    # IncludeColumnNames: False)の列名規則("Column#1"等)を実機確認し結線した。
    code = _generate("tier1_file_batch6.txt")
    assert "CopiedFiles = file_actions.copy_files((" in code
    assert "MovedFiles = file_actions.move_files((" in code
    assert "file_actions.delete_files((" in code
    assert "RenamedFiles = []" in code
    assert "_rename_dir, _rename_base = os.path.split(_rename_src)" in code
    assert "file_actions.rename_set_new_name(_rename_base, 'sample', keep_extension=True)" in code
    assert "file_actions.apply_rename(_rename_dir, _rename_base, _rename_new_base, " in code
    assert "Base64Text = file_actions.file_to_base64('sample')" in code
    assert "file_actions.base64_to_file('sample', 'sample', if_file_exists='DoNothing')" in code
    assert "BinaryData = file_actions.file_to_binary('sample')" in code
    assert "FileContents = file_actions.read_text_from_file('sample', encoding='UTF8')" in code
    assert "file_actions.write_text_to_file('sample', 'sample', append_new_line=True, " in code
    assert "_path_part = file_actions.get_file_path_part('sample')" in code
    assert "RootPath = _path_part['RootPath']" in code
    assert "FileNameNoExtension = _path_part['FileNameWithoutExtension']" in code
    assert "if file_actions.if_file_exists('sample'):" in code
    assert "while not file_actions.if_file_exists('sample'):" in code
    assert "import os" in code
    assert (
        "CSVTable = file_actions.read_from_csv_file('sample', encoding='UTF8', "
        "first_line_contains_column_names=False, trim_fields=True)" in code
    )
    assert (
        "file_actions.write_to_csv_file('sample', 'sample', if_file_exists='Overwrite', "
        "encoding='UTF8', include_column_names=False)" in code
    )
    assert "# TODO" not in code


def test_crypto_database_batch7_converts_all_actions_including_dpapi_keys() -> None:
    # design/dsl_format_findings.md 知見112(decompile+実機確認済み): `P'<base64>'`の
    # DPAPI保護値(鍵/パスワード)は、以前はVarRefへフォールバックしTODOのままだったが、
    # `DpapiSensitiveLiteral`型+`cryptography_actions.decrypt_dpapi_sensitive_value()`
    # (生成スクリプト実行時にWindows DPAPIで復号)への結線で実コードが生成されるように
    # なった——「元の値を作成したWindowsユーザー自身が実行する」場合のみ実際に動く
    # コードだが、でっち上げではなく本物の復号呼び出し。
    code = _generate("tier1_crypto_database_batch7.txt")
    assert "file_actions.binary_to_file('sample', 'sample', if_file_exists='DoNothing')" in code
    assert "TempFile = file_actions.get_temp_file_path()" in code
    assert "HashedText = cryptography_actions.hash_text('sample', encoding='Unicode', " in code
    assert "HashedText2 = cryptography_actions.hash_from_file('sample', encoding='Unicode', " in code
    assert "SQLConnection = database_actions.open_connection('sample')" in code
    assert "# TODO" not in code
    assert "cryptography_actions.decrypt_dpapi_sensitive_value('AQAAANCMnd8B" in code
    assert (
        "EncryptedText = cryptography_actions.encrypt_text('sample', "
        "cryptography_actions.decrypt_dpapi_sensitive_value('AQAAANCMnd8B" in code
    )
    # Statement: `` now parses as an empty string, so this is wired (knowledge 74).
    assert "QueryResult = database_actions.execute_sql_statement(SQLConnection, '', timeout=30)" in code


def test_web_xml_batch8_converts_except_unzip_missing_output_var() -> None:
    # knowledge 93以前はUserAgent/FollowRedirectionが`web_actions`側で未対応
    # (httpxの既定follow_redirects=Falseのまま実機の既定True と食い違っていた)。
    # 実機キャプチャ済みのUA文字列(ハードコードされたFirefox 3.6)も結線する。
    _UA = "Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.21) Gecko/20100312 Firefox/3.6"
    code = _generate("tier1_web_xml_batch8.txt")
    assert "database_actions.close_connection(SQLConnection)" in code
    assert (
        "WebPageText = web_actions.download_from_web('sample', connection_timeout=30, "
        f"follow_redirection=True, user_agent={_UA!r}, accept_untrusted_certificates=False)" in code
    )
    assert (
        "_web_service_result = web_actions.invoke_web_service('sample', method='Get', " in code
    )
    assert (
        f"encode_request_body=True, follow_redirection=True, user_agent={_UA!r}, "
        "accept_untrusted_certificates=False)" in code
    )
    assert "WebServiceResponse = _web_service_result.response" in code
    assert "WebServiceResponseHeaders = _web_service_result.response_headers" in code
    assert "StatusCode = _web_service_result.status_code" in code
    assert (
        "_soap_service_result = web_actions.invoke_soap_service('sample', "
        "request_body='sample', custom_headers='sample', connection_timeout=30, "
        f"follow_redirection=True, user_agent={_UA!r}, fail_on_error_status=False, "
        "trim_request_body=True, accept_untrusted_certificates=False)" in code
    )
    assert "SoapServiceResponse = _soap_service_result.response" in code
    assert "StatusCode2 = _soap_service_result.status_code" in code
    assert "XmlDocument = xml_actions.read_xml_from_file('sample')" in code
    assert "XmlElementValue = xml_actions.get_xml_element_value(XmlDocument, 'sample')" in code
    assert "XmlDocument = xml_actions.set_xml_element_value(XmlDocument, 'sample', 'sample')" in code
    assert "XmlAttributeValue = xml_actions.get_xml_element_attribute(XmlDocument, 'sample', 'sample')" in code
    assert "XmlDocument = xml_actions.set_xml_element_attribute(XmlDocument, 'sample', 'sample', 'sample')" in code
    assert "XmlDocument = xml_actions.remove_xml_element_attribute(XmlDocument, 'sample', 'sample')" in code
    assert "XmlDocument = xml_actions.insert_xml_element(XmlDocument, 'sample', 'sample')" in code
    assert "XmlDocument = xml_actions.remove_xml_element(XmlDocument, 'sample')" in code
    assert "XPathResults = xml_actions.execute_xpath_query('sample', 'sample')" in code
    # design/dsl_format_findings.md 知見112以降もTODOのまま——Passwordの復号自体は
    # 結線済みだが、この実機キャプチャには`=>`出力変数束縛が無いため(知見112参照)。
    assert _todo("Compression.UnzipFiles") in code
    # Xml: `` now parses as an empty string, so this is wired (knowledge 74).
    assert "xml_actions.write_xml_to_file('sample', '', format_xml=True, indentation=2)" in code


def test_cmd_batch9_converts_all_actions_as_session_method_calls() -> None:
    code = _generate("tier1_cmd_batch9.txt")
    assert "# TODO: map PAD action:" not in code
    assert "CmdSession = cmd_actions.open_cmd_session('sample')" in code
    assert "CmdSession.write('sample', send_enter=True)" in code
    assert "CmdOutput = CmdSession.read()" in code
    assert "CmdSession.wait_for_text('sample', timeout=0, is_regex=False, ignore_case=True)" in code
    assert "CmdSession.close()" in code


def test_folder_get_files_falls_back_to_todo_when_secondary_sort_key_specified() -> None:
    # SortBy1だけでなくSortBy2/3もNoSortであることを確認するゲート(知見94の追補)。
    # SortBy1: NoSortでもSortBy2に実際の並べ替えキーが指定されている場合は
    # でっち上げたコードを出力せずTODOへ倒れる。
    dsl = (
        "Folder.GetFiles Folder: $'''sample''' FileFilter: $'''*''' "
        "IncludeSubfolders: False FailOnAccessDenied: True "
        "SortBy1: Folder.SortBy.NoSort SortDescending1: False "
        "SortBy2: Folder.SortBy.Name SortDescending2: False "
        "SortBy3: Folder.SortBy.NoSort SortDescending3: False Files=> Files"
    )
    tree = build_block_tree(parse_dsl(dsl))
    code = generate_python(tree)
    assert "folder_actions.get_files_in_folder" not in code
    assert _todo("Folder.GetFiles") in code
