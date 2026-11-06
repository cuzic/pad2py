"""`XML.*`のcodegen。`pad_action_lib.xml_actions`へ委譲する。

パラメータ名は design/dsl_format_findings.md 知見71で実機キャプチャした
`tests/fixtures/tier1_web_xml_batch8.txt`から確認済み。

`pad_action_lib.xml_actions`の各setter/mutator系関数(`set_xml_element_value()`等)
は新しいXML文字列を**返す**(文字列はイミュータブルなため)。一方、実機DSLでは
これらのアクションに`=>`出力変数が付かず、`Document`に渡した変数自体が書き換わる
——そのため生成コードは戻り値を`Document`に渡したのと同じ変数名へ再代入する
(`Document`パラメータが`VarRef`である場合のみ、安全にLHSの変数名として使える)。

`XML.WriteXmlToFile.WriteToFileFormatted`の`Xml`は知見74でパーサーが空のバック
ティック文字列``を正しく空文字列として解釈するようになったため結線できる(実機
キャプチャではXMLを編集しなかったため常に空文字列)。

知見139(`ActionSelectorBase`一括列挙監査をXML.Actions.dllに適用): `GetElementValue`
クラスには`GetElementValue`(Text、既存結線)の兄弟セレクタ`GetElementValueAsNumeric`/
`AsBoolean`/`AsDateTime`があり、いずれも同一クラス・同一`get_xml_element_value()`の
`value_type`引数(既に実装済みの`"Text"`/`"Numeric"`/`"Boolean"`/`"DateTime"`の
4択)に対応する——各セレクタは`ValueType`パラメータをDSLから読むのではなく、
セレクタ自体がモードを固定する(`Database.Connect.ConnectOracle`と同じ構造的パターン)。
`ExecuteXPathQuery`クラスも同様に`ExecuteXPathAndGetFirstValueOnly`という兄弟セレクタ
があり、既存の`execute_xpath_query()`の`first_value_only=True`引数で対応できる。
`WriteXmlToFile`クラスの`WriteToFile`(非フォーマット版)も既存の`write_xml_to_file()`の
`format_xml=False`で対応できる。`GetElementAttribute`クラスの`AsNumeric`/`AsBoolean`/
`AsDateTime`系3セレクタは、`get_xml_element_attribute()`自体が`value_type`引数を
まだ持たない(実装追加が必要)ため、本tickでは見送った。
"""
from __future__ import annotations

from ...pad_dsl import ActionRecord, VarRef
from ..context import CodegenContext
from ..render import INDENT
from ._support import enum_last, safe_render


def generate(node: ActionRecord, indent: int, ctx: CodegenContext) -> list[str] | None:
    action_id = node.action_id
    if not action_id.startswith("XML."):
        return None
    prefix = INDENT * indent
    p = node.params

    if action_id == "XML.ReadFromFile":
        path = safe_render(p.get("File"))
        encoding = enum_last(p.get("Encoding"))
        if path is None or encoding is None or not node.output_var:
            return None
        if encoding != "DefaultEncoding":
            return None
        return [f"{prefix}{node.output_var} = xml_actions.read_xml_from_file({path})"]

    if action_id == "XML.WriteXmlToFile.WriteToFileFormatted":
        path = safe_render(p.get("File"))
        xml = safe_render(p.get("Xml"))
        encoding = enum_last(p.get("Encoding"))
        indentation = safe_render(p.get("Indentation"))
        if path is None or xml is None or encoding is None or indentation is None:
            return None
        if encoding != "DefaultEncoding":
            return None
        return [
            f"{prefix}xml_actions.write_xml_to_file({path}, {xml}, format_xml=True, "
            f"indentation={indentation})"
        ]

    if action_id == "XML.WriteXmlToFile.WriteToFile":
        # 知見139: `WriteToFileFormatted`の兄弟セレクタ(非フォーマット版、`Indentation`
        # パラメータ自体がDSL上に無い)。
        path = safe_render(p.get("File"))
        xml = safe_render(p.get("Xml"))
        encoding = enum_last(p.get("Encoding"))
        if path is None or xml is None or encoding is None:
            return None
        if encoding != "DefaultEncoding":
            return None
        return [f"{prefix}xml_actions.write_xml_to_file({path}, {xml}, format_xml=False)"]

    if action_id == "XML.GetXmlElementValue.GetElementValue":
        doc = safe_render(p.get("Document"))
        xpath = safe_render(p.get("XPathQuery"))
        if doc is None or xpath is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = xml_actions.get_xml_element_value({doc}, {xpath})"]

    _VALUE_TYPE_SELECTORS = {
        "XML.GetXmlElementValue.GetElementValueAsNumeric": "Numeric",
        "XML.GetXmlElementValue.GetElementValueAsBoolean": "Boolean",
        "XML.GetXmlElementValue.GetElementValueAsDateTime": "DateTime",
    }
    if action_id in _VALUE_TYPE_SELECTORS:
        # 知見139: `GetElementValue`の兄弟セレクタ(`value_type`はセレクタ自体が固定する、
        # DSLパラメータとしては現れない)。
        doc = safe_render(p.get("Document"))
        xpath = safe_render(p.get("XPathQuery"))
        if doc is None or xpath is None or not node.output_var:
            return None
        value_type = _VALUE_TYPE_SELECTORS[action_id]
        return [
            f"{prefix}{node.output_var} = xml_actions.get_xml_element_value("
            f"{doc}, {xpath}, value_type={value_type!r})"
        ]

    if action_id == "XML.GetXmlElementAttribute.GetElementAttribute":
        doc = safe_render(p.get("Document"))
        xpath = safe_render(p.get("XPathQuery"))
        attribute = safe_render(p.get("AttributeName"))
        if doc is None or xpath is None or attribute is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = xml_actions.get_xml_element_attribute({doc}, {xpath}, {attribute})"
        ]

    _ATTRIBUTE_VALUE_TYPE_SELECTORS = {
        "XML.GetXmlElementAttribute.GetElementAttributeAsNumeric": ("Numeric", "NumericValue"),
        "XML.GetXmlElementAttribute.GetElementAttributeAsBoolean": ("Boolean", "BooleanValue"),
        "XML.GetXmlElementAttribute.GetElementAttributeAsDateTime": ("DateTime", "DateTimeValue"),
    }
    if action_id in _ATTRIBUTE_VALUE_TYPE_SELECTORS:
        # 知見139・149: `GetElementAttribute`の兄弟セレクタ。VM上で`GetXmlElementAttribute`
        # クラスが`TextValue`/`NumericValue`/`DateTimeValue`/`BooleanValue`という
        # モードごとに別々の出力プロパティを持つと確認し(`GetElementValue`とは異なる
        # 構造)、`ValueType`列挙値(`Text`/`Numeric`/`DateTime`/`Boolean`)が
        # `GetElementValue`と共通の型だと確認した。既存の`get_xml_element_value()`の
        # 変換ロジックを`_convert_xml_text_value()`として共通化し、
        # `get_xml_element_attribute()`にも`value_type`引数を追加して対応した。
        doc = safe_render(p.get("Document"))
        xpath = safe_render(p.get("XPathQuery"))
        attribute = safe_render(p.get("AttributeName"))
        if doc is None or xpath is None or attribute is None:
            return None
        value_type, output_name = _ATTRIBUTE_VALUE_TYPE_SELECTORS[action_id]
        output_var = node.output_vars.get(output_name)
        if not output_var:
            return None
        return [
            f"{prefix}{output_var} = xml_actions.get_xml_element_attribute("
            f"{doc}, {xpath}, {attribute}, value_type={value_type!r})"
        ]

    if action_id == "XML.ExecuteXPathQuery.ExecuteXPath":
        doc = safe_render(p.get("XmlDocument"))
        xpath = safe_render(p.get("XPathQuery"))
        if doc is None or xpath is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = xml_actions.execute_xpath_query({doc}, {xpath})"]

    if action_id == "XML.ExecuteXPathQuery.ExecuteXPathAndGetFirstValueOnly":
        # 知見139: `ExecuteXPath`の兄弟セレクタ(`first_value_only=True`、既存の
        # `execute_xpath_query()`がそのまま対応できる)。
        doc = safe_render(p.get("XmlDocument"))
        xpath = safe_render(p.get("XPathQuery"))
        if doc is None or xpath is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = xml_actions.execute_xpath_query("
            f"{doc}, {xpath}, first_value_only=True)"
        ]

    _MUTATORS = {
        "XML.SetElementValue": ("set_xml_element_value", ("XPathQuery", "ElementValue")),
        "XML.SetElementAttribute": ("set_xml_element_attribute", ("XPathQuery", "AttributeName", "AttributeValue")),
        "XML.RemoveElementAttribute": ("remove_xml_element_attribute", ("XPathQuery", "AttributeName")),
        "XML.InsertElement": ("insert_xml_element", ("XPathQuery", "Element")),
        "XML.RemoveElement": ("remove_xml_element", ("XPathQuery",)),
    }
    if action_id in _MUTATORS:
        func_name, extra_param_names = _MUTATORS[action_id]
        doc = p.get("Document")
        if not isinstance(doc, VarRef) or not doc.name.isidentifier():
            return None
        extra_args = [safe_render(p.get(name)) for name in extra_param_names]
        if None in extra_args:
            return None
        args = ", ".join([doc.name, *extra_args])
        return [f"{prefix}{doc.name} = xml_actions.{func_name}({args})"]

    return None
