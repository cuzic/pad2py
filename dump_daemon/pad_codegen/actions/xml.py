"""`XML.*`のcodegen。`pad_action_lib.xml_actions`へ委譲する。

パラメータ名は design/dsl_format_findings.md 知見71で実機キャプチャした
`tests/fixtures/tier1_web_xml_batch8.txt`から確認済み。

`pad_action_lib.xml_actions`の各setter/mutator系関数(`set_xml_element_value()`等)
は新しいXML文字列を**返す**(文字列はイミュータブルなため)。一方、実機DSLでは
これらのアクションに`=>`出力変数が付かず、`Document`に渡した変数自体が書き換わる
——そのため生成コードは戻り値を`Document`に渡したのと同じ変数名へ再代入する
(`Document`パラメータが`VarRef`である場合のみ、安全にLHSの変数名として使える)。

`XML.WriteXmlToFile.WriteToFileFormatted`は意図的に未対応のままフォールバックに
委ねる: 実機キャプチャで`Xml`が知見72のバックティック空文字列未対応構文
(`VarRef(name="``")`)として現れており、`_support.safe_render()`で自動的に
フォールバックする。
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

    if action_id == "XML.GetXmlElementValue.GetElementValue":
        doc = safe_render(p.get("Document"))
        xpath = safe_render(p.get("XPathQuery"))
        if doc is None or xpath is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = xml_actions.get_xml_element_value({doc}, {xpath})"]

    if action_id == "XML.GetXmlElementAttribute.GetElementAttribute":
        doc = safe_render(p.get("Document"))
        xpath = safe_render(p.get("XPathQuery"))
        attribute = safe_render(p.get("AttributeName"))
        if doc is None or xpath is None or attribute is None or not node.output_var:
            return None
        return [
            f"{prefix}{node.output_var} = xml_actions.get_xml_element_attribute({doc}, {xpath}, {attribute})"
        ]

    if action_id == "XML.ExecuteXPathQuery.ExecuteXPath":
        doc = safe_render(p.get("XmlDocument"))
        xpath = safe_render(p.get("XPathQuery"))
        if doc is None or xpath is None or not node.output_var:
            return None
        return [f"{prefix}{node.output_var} = xml_actions.execute_xpath_query({doc}, {xpath})"]

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
