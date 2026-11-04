"""`pad_action_lib.clipboard_actions`の単体テスト(`pyperclip`をモンキーパッチしてOS依存を排除)。"""
from __future__ import annotations

import pytest

from dump_daemon.pad_action_lib import clipboard_actions as cb


class _FakeClipboard:
    def __init__(self) -> None:
        self.value = ""

    def copy(self, text: str) -> None:
        self.value = text

    def paste(self) -> str:
        return self.value


def test_set_then_get_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClipboard()
    monkeypatch.setattr(cb.pyperclip, "copy", fake.copy)
    monkeypatch.setattr(cb.pyperclip, "paste", fake.paste)

    cb.set_clipboard_text("hello")
    assert cb.get_clipboard_text() == "hello"


def test_get_clipboard_text_without_text_returns_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cb.pyperclip, "paste", lambda: None)
    assert cb.get_clipboard_text() == ""


def test_get_clipboard_text_api_failure_raises_retrieve_contents_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom() -> str:
        raise RuntimeError("clipboard locked")

    monkeypatch.setattr(cb.pyperclip, "paste", _boom)
    with pytest.raises(cb.RetrieveContentsError):
        cb.get_clipboard_text()


def test_set_clipboard_text_empty_string_clears(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClipboard()
    fake.value = "previous"
    monkeypatch.setattr(cb.pyperclip, "copy", fake.copy)
    cb.set_clipboard_text("")
    assert fake.value == ""


def test_set_clipboard_text_swallows_all_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_text: str) -> None:
        raise RuntimeError("clipboard locked")

    monkeypatch.setattr(cb.pyperclip, "copy", _boom)
    cb.set_clipboard_text("hello")  # 例外を投げないことを確認するだけ


def test_clear_clipboard_sets_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClipboard()
    fake.value = "previous"
    monkeypatch.setattr(cb.pyperclip, "copy", fake.copy)
    cb.clear_clipboard()
    assert fake.value == ""


def test_clear_clipboard_swallows_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_text: str) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(cb.pyperclip, "copy", _boom)
    cb.clear_clipboard()  # 例外を投げないことを確認するだけ
