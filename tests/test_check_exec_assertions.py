"""`tools/check_exec_assertions.py`自身の単体テスト。"""
from __future__ import annotations

import tempfile
from pathlib import Path

from tools.check_exec_assertions import check_file


def _write(tmp: str, source: str) -> Path:
    path = Path(tmp) / "test_sample.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_flags_exec_with_no_inspection_afterward() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(
            tmp,
            "def test_something() -> None:\n"
            "    code = 'X = 1'\n"
            "    namespace = {}\n"
            "    exec(code, namespace)\n",
        )
        findings = check_file(path)
    assert len(findings) == 1
    assert findings[0].function_name == "test_something"


def test_does_not_flag_when_namespace_is_subscripted_afterward() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(
            tmp,
            "def test_something() -> None:\n"
            "    code = 'X = 1'\n"
            "    namespace = {}\n"
            "    exec(code, namespace)\n"
            "    assert namespace['X'] == 1\n",
        )
        findings = check_file(path)
    assert findings == []


def test_does_not_flag_when_fake_registry_calls_are_checked() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(
            tmp,
            "def test_something() -> None:\n"
            "    code = 'f()'\n"
            "    exec(code, {})\n"
            "    assert registry.calls == [('f',)]\n",
        )
        findings = check_file(path)
    assert findings == []


def test_does_not_flag_when_condition_is_evaluated_with_eval() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(
            tmp,
            "def test_something() -> None:\n"
            "    code = 'X = 1'\n"
            "    namespace = {}\n"
            "    exec(code, namespace)\n"
            "    assert eval('X == 1', namespace) is True\n",
        )
        findings = check_file(path)
    assert findings == []


def test_ignores_non_test_functions() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = _write(
            tmp,
            "def helper() -> None:\n"
            "    exec('X = 1', {})\n",
        )
        findings = check_file(path)
    assert findings == []
