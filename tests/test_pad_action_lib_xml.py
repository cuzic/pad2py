"""`pad_action_lib.xml_actions`の単体テスト。"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from dump_daemon.pad_action_lib import xml_actions as xa

SAMPLE = "<root><item id=\"1\">hello</item><item id=\"2\">world</item></root>"


def test_read_and_write_xml_round_trip(tmp_path: Path) -> None:
    f = tmp_path / "a.xml"
    xa.write_xml_to_file(str(f), SAMPLE, format_xml=False)
    text = xa.read_xml_from_file(str(f))
    assert "<root>" in text


def test_write_xml_rejects_invalid_xml(tmp_path: Path) -> None:
    f = tmp_path / "a.xml"
    with pytest.raises(xa.InvalidXMLError):
        xa.write_xml_to_file(str(f), "<not valid")


def test_read_xml_rejects_dtd(tmp_path: Path) -> None:
    f = tmp_path / "a.xml"
    f.write_text("<!DOCTYPE root><root/>")
    with pytest.raises(xa.InvalidXMLError):
        xa.read_xml_from_file(str(f))


def test_get_xml_element_value_text() -> None:
    assert xa.get_xml_element_value(SAMPLE, "//item[@id='1']") == "hello"


def test_get_xml_element_value_numeric() -> None:
    xml = "<root><n>42.5</n></root>"
    assert xa.get_xml_element_value(xml, "//n", value_type="Numeric") == Decimal("42.5")


def test_get_xml_element_value_boolean() -> None:
    xml = "<root><b>true</b></root>"
    assert xa.get_xml_element_value(xml, "//b", value_type="Boolean") is True


def test_get_xml_element_value_convert_error() -> None:
    xml = "<root><n>not-a-number</n></root>"
    with pytest.raises(xa.ConvertElementError):
        xa.get_xml_element_value(xml, "//n", value_type="Numeric")


def test_get_xml_element_value_zero_match_raises() -> None:
    with pytest.raises(xa.XPathNoElementError):
        xa.get_xml_element_value(SAMPLE, "//missing")


def test_get_xml_element_value_invalid_xpath_raises() -> None:
    with pytest.raises(xa.InvalidXPathError):
        xa.get_xml_element_value(SAMPLE, "///[[[")


def test_set_xml_element_value_overwrites_text() -> None:
    result = xa.set_xml_element_value(SAMPLE, "//item[@id='1']", "changed")
    assert "<item id=\"1\">changed</item>" in result


def test_get_set_remove_attribute() -> None:
    assert xa.get_xml_element_attribute(SAMPLE, "//item[@id='1']", "id") == "1"
    with pytest.raises(xa.AttributeNotFoundError):
        xa.get_xml_element_attribute(SAMPLE, "//item[@id='1']", "missing")

    added = xa.set_xml_element_attribute(SAMPLE, "//item[@id='1']", "new-attr", "value")
    assert 'new-attr="value"' in added

    removed = xa.remove_xml_element_attribute(SAMPLE, "//item[@id='1']", "id")
    assert 'id="1"' not in removed

    with pytest.raises(xa.AttributeNotFoundError):
        xa.remove_xml_element_attribute(SAMPLE, "//item[@id='1']", "nonexistent")


def test_insert_xml_element_requires_xpath() -> None:
    with pytest.raises(xa.InvalidXPathError):
        xa.insert_xml_element(SAMPLE, "", "<new/>")


def test_insert_xml_element_appends_as_last_child() -> None:
    result = xa.insert_xml_element(SAMPLE, "//root", "<new>added</new>")
    assert result.endswith("<new>added</new></root>")


def test_insert_xml_element_zero_match_raises() -> None:
    with pytest.raises(xa.XPathNoElementError):
        xa.insert_xml_element(SAMPLE, "//missing", "<new/>")


def test_remove_xml_element_removes_all_matches() -> None:
    result = xa.remove_xml_element(SAMPLE, "//item")
    assert "<item" not in result


def test_remove_xml_element_zero_match_is_silent_noop() -> None:
    result = xa.remove_xml_element(SAMPLE, "//missing")
    assert "<root>" in result


def test_execute_xpath_query_returns_all_matches() -> None:
    result = xa.execute_xpath_query(SAMPLE, "//item/text()")
    assert result == ["hello", "world"]


def test_execute_xpath_query_first_value_only() -> None:
    assert xa.execute_xpath_query(SAMPLE, "//item/text()", first_value_only=True) == "hello"


def test_execute_xpath_query_zero_match_is_not_an_error() -> None:
    assert xa.execute_xpath_query(SAMPLE, "//missing") == []
    assert xa.execute_xpath_query(SAMPLE, "//missing", first_value_only=True) is None
