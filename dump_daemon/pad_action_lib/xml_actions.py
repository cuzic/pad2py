"""`XML.Actions`(`System.Xml.XmlDocument`+XPath 1.0)のロジック層。

全てのXML解析箇所でDTD処理禁止・外部エンティティ解決禁止(XXE対策)——`lxml`は
XPath 1.0をフルサポートする数少ないPythonライブラリであり、`resolve_entities=False`
/`no_network=True`/`load_dtd=False`で構成したパーサーを使う。DOCTYPE宣言自体が
含まれるXMLは(内部サブセットの外部エンティティが無くても)安全側に倒して拒否する。
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from dateutil import parser as dateutil_parser
from lxml import etree

from .errors import PadActionError

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False)


class InvalidFileError(PadActionError):
    pass


class InvalidXMLError(PadActionError):
    pass


class InvalidXPathError(PadActionError):
    pass


class XPathNoElementError(PadActionError):
    pass


class ConvertElementError(PadActionError):
    pass


class SetElementError(PadActionError):
    pass


class AttributeNotFoundError(PadActionError):
    pass


def _parse_xml(text: str) -> etree._Element:
    try:
        root = etree.fromstring(text.encode("utf-8"), parser=_PARSER)
    except etree.XMLSyntaxError as exc:
        raise InvalidXMLError(str(exc)) from exc
    docinfo = root.getroottree().docinfo
    if docinfo.doctype:
        raise InvalidXMLError("DTD declarations are not allowed (XXE hardening)")
    return root


def _select(root: etree._Element, xpath_query: str) -> list:
    try:
        return root.xpath(xpath_query) if xpath_query else [root]
    except etree.XPathEvalError as exc:
        raise InvalidXPathError(str(exc)) from exc


def _get_single_element(root: etree._Element, xpath_query: str) -> etree._Element:
    results = _select(root, xpath_query)
    if not results:
        raise XPathNoElementError(xpath_query)
    return results[0]


def read_xml_from_file(path: str, encoding: str = "utf-8") -> str:
    try:
        text = Path(path).read_text(encoding=encoding)
    except OSError as exc:
        raise InvalidFileError(str(exc)) from exc
    _parse_xml(text)  # 型別の例外再マップ(XmlException相当)——不正なXMLは即座にエラー
    return text


def write_xml_to_file(path: str, xml: str, format_xml: bool = True, indentation: int = 2) -> None:
    root = _parse_xml(xml)  # 書き込み前に再パースされるので不正なXMLは即座にエラー
    if format_xml:
        etree.indent(root, space=" " * indentation)
    text = etree.tostring(root, encoding="unicode")
    Path(path).write_text(text, encoding="utf-8")  # 常に上書き


def get_xml_element_value(xml: str, xpath_query: str, value_type: str = "Text") -> object:
    root = _parse_xml(xml)
    element = _get_single_element(root, xpath_query)
    text = element.text or ""
    try:
        if value_type == "Text":
            return text
        if value_type == "Numeric":
            return Decimal(text)
        if value_type == "DateTime":
            return dateutil_parser.parse(text)
        if value_type == "Boolean":
            return text.strip().lower() in ("true", "1")
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ConvertElementError(str(exc)) from exc
    raise ValueError(f"Unknown ValueType: {value_type!r}")


def set_xml_element_value(xml: str, xpath_query: str, value: object) -> str:
    root = _parse_xml(xml)
    element = _get_single_element(root, xpath_query)
    try:
        element.text = str(value)  # 子要素構造は上書きされる、常に文字列として書き込み
    except Exception as exc:
        raise SetElementError(str(exc)) from exc
    return etree.tostring(root, encoding="unicode")


def get_xml_element_attribute(xml: str, xpath_query: str, attribute_name: str) -> str:
    root = _parse_xml(xml)
    element = _get_single_element(root, xpath_query)
    if attribute_name not in element.attrib:
        raise AttributeNotFoundError(attribute_name)
    return element.attrib[attribute_name]


def set_xml_element_attribute(xml: str, xpath_query: str, attribute_name: str, value: object) -> str:
    root = _parse_xml(xml)
    element = _get_single_element(root, xpath_query)
    element.set(attribute_name, str(value))  # 存在しなくてもエラーにならず新規作成する(非対称)
    return etree.tostring(root, encoding="unicode")


def remove_xml_element_attribute(xml: str, xpath_query: str, attribute_name: str) -> str:
    root = _parse_xml(xml)
    element = _get_single_element(root, xpath_query)
    if attribute_name not in element.attrib:
        raise AttributeNotFoundError(attribute_name)
    del element.attrib[attribute_name]
    return etree.tostring(root, encoding="unicode")


def insert_xml_element(xml: str, xpath_query: str, fragment: str) -> str:
    if not xpath_query:
        # Insertは必須——空でもルートにフォールバックしない(他アクションと違う)。
        raise InvalidXPathError("XPathQuery is required for InsertElement")
    root = _parse_xml(xml)
    target = _get_single_element(root, xpath_query)
    new_element = etree.fromstring(fragment.encode("utf-8"), parser=_PARSER)
    target.append(new_element)  # 最初にマッチしたノードの最後の子として挿入(位置は固定)
    return etree.tostring(root, encoding="unicode")


def remove_xml_element(xml: str, xpath_query: str) -> str:
    root = _parse_xml(xml)
    matches = _select(root, xpath_query)
    for node in matches:  # マッチした全ノードを削除。ゼロマッチはエラーにならない静かなno-op。
        parent = node.getparent()
        if parent is not None:
            parent.remove(node)
    return etree.tostring(root, encoding="unicode")


def execute_xpath_query(xml: str, xpath_query: str, first_value_only: bool = False) -> list[str] | str | None:
    root = _parse_xml(xml)
    try:
        results = root.xpath(xpath_query)
    except etree.XPathEvalError as exc:
        raise InvalidXPathError(str(exc)) from exc
    values = [r if isinstance(r, str) else etree.tostring(r, encoding="unicode") for r in results]
    if first_value_only:
        # この操作だけはゼロマッチがエラーにならない(モジュール内で唯一のスタンス)。
        return values[0] if values else None
    return values
