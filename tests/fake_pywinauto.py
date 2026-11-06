"""`pywinauto.Desktop`の最小限のフェイク実装。

design/common_rpa_framework_roadmap.md 層7(検証基盤・シミュレータ)の第一歩。
生成されたPythonコード(pywinautoのUI Automation操作を含む)を、実Windows・実アプリ
無しで`exec()`して検証できるようにする——PADやpywinauto自身の挙動を推測で再現する
ものではなく、「pad_codegenが正しい形のpywinauto呼び出し列を組み立てているか」だけを
確認する用途に限定する(でっち上げ禁止の方針はここでも守る: フェイクが知らない呼び出し
形は`AttributeError`で失敗させ、黙ってでっち上げた値を返さない)。

使い方(`fake_pywinauto_desktop()`経由、推奨):
    registry = FakeRegistry()
    registry.register_window(title="Untitled - Notepad")
    with fake_pywinauto_desktop(registry):
        exec(code, namespace)  # 生成コードの`from pywinauto import Desktop`がこのフェイクを拾う
    assert registry.calls == [("click_input", [...], {})]

対応しているAPI表面は`dump_daemon/pad_codegen/actions/*.py`が実際に生成する呼び出し
(`.exists()`/`.wrapper_object()`/`.child_window()`/`.click_input()`/`.set_focus()`/
`.close()`/`.type_keys()`/`.wait()`/`.wait_not()`/`.maximize()`/`.minimize()`/`.restore()`/
`.window_text()`/`.capture_as_image().save()`/`.invoke()`/`.select()`/`.toggle()`/
`.get_toggle_state()`/`.drag_mouse_input(dst=...)`/`.is_enabled()`)のみ——新しい呼び出し形が
出てきたら、その都度ここに追加する(未対応の呼び出しをでっち上げて成功させるのではなく、
素直に`AttributeError`で気づけるようにする)。
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


class FakeElementNotFoundError(Exception):
    """`FakeControl.wrapper_object()`を存在しない要素に対して呼んだ場合(pywinautoの
    `ElementNotFoundError`相当)。"""


class FakeImage:
    """`FakeControl.capture_as_image()`の戻り値(pywinauto実装はPIL Imageを返す、
    `.save(path, format=...)`だけをフェイクする——画像の内容自体は検証対象外)。"""

    def __init__(self, registry: "FakeRegistry", path: list[dict]) -> None:
        self._registry = registry
        self._path = path

    def save(self, fp: object, format: str | None = None) -> None:
        self._registry.record("capture_as_image.save", self._path, {"fp": fp, "format": format})


@dataclass
class FakeWrapperObject:
    handle: int = 0
    active: bool = True
    enabled: bool = True

    def is_active(self) -> bool:
        return self.active

    def is_enabled(self) -> bool:
        return self.enabled


class FakeControl:
    """フェイクUIツリー上の1ノード(トップレベルウィンドウまたは子孫コントロール)。"""

    def __init__(self, registry: "FakeRegistry", criteria: dict, parent: "FakeControl | None" = None):
        self._registry = registry
        self.criteria = criteria
        self._parent = parent

    def _full_path(self) -> list[dict]:
        path = [] if self._parent is None else self._parent._full_path()
        return [*path, self.criteria]

    def exists(self) -> bool:
        return self._registry.exists(self._full_path())

    def wrapper_object(self) -> FakeWrapperObject:
        if not self.exists():
            raise FakeElementNotFoundError(self._full_path())
        return self._registry.wrapper_for(self._full_path())

    def child_window(self, **criteria: object) -> "FakeControl":
        return FakeControl(self._registry, criteria, parent=self)

    def click_input(self, **kwargs: object) -> None:
        self._registry.record("click_input", self._full_path(), kwargs)

    def set_focus(self) -> None:
        self._registry.record("set_focus", self._full_path(), {})

    def invoke(self) -> None:
        self._registry.record("invoke", self._full_path(), {})

    def select(self) -> None:
        self._registry.record("select", self._full_path(), {})

    def get_toggle_state(self) -> int:
        return self._registry.toggle_state_for(self._full_path())

    def toggle(self) -> None:
        self._registry.record("toggle", self._full_path(), {})
        current = self._registry.toggle_state_for(self._full_path())
        self._registry._set_toggle_state(self._full_path(), 0 if current else 1)

    def drag_mouse_input(self, dst: "FakeControl") -> None:
        self._registry.record("drag_mouse_input", self._full_path(), {"dst": dst._full_path()})

    def close(self) -> None:
        self._registry.record("close", self._full_path(), {})

    def maximize(self) -> None:
        self._registry.record("maximize", self._full_path(), {})

    def minimize(self) -> None:
        self._registry.record("minimize", self._full_path(), {})

    def restore(self) -> None:
        self._registry.record("restore", self._full_path(), {})

    def type_keys(self, keys: str, **kwargs: object) -> None:
        self._registry.record("type_keys", self._full_path(), {"keys": keys, **kwargs})

    def wait(self, criteria: str, timeout: float | None = None) -> "FakeControl":
        self._registry.record("wait", self._full_path(), {"criteria": criteria, "timeout": timeout})
        return self

    def wait_not(self, criteria: str, timeout: float | None = None) -> "FakeControl":
        self._registry.record("wait_not", self._full_path(), {"criteria": criteria, "timeout": timeout})
        return self

    def window_text(self) -> str:
        return self._registry.window_text_for(self._full_path())

    def capture_as_image(self) -> FakeImage:
        self._registry.record("capture_as_image", self._full_path(), {})
        return FakeImage(self._registry, self._full_path())


class FakeRegistry:
    """1テスト分のフェイクUI状態(スクリプト可能)+呼び出しログ。"""

    def __init__(self) -> None:
        self._existing_paths: list[list[dict]] = []
        self._active_overrides: list[tuple[list[dict], bool]] = []
        self._enabled_overrides: list[tuple[list[dict], bool]] = []
        self._window_text_overrides: list[tuple[list[dict], str]] = []
        self._toggle_states: list[list[object]] = []
        self.calls: list[tuple[str, list[dict], dict]] = []

    def register_window(self, **criteria: object) -> None:
        """既知の(存在する)トップレベルウィンドウを1つ登録する。"""
        self._existing_paths.append([criteria])

    def register_descendant(self, *path_criteria: dict) -> None:
        """既知の(存在する)子孫コントロールへのパスを登録する(例:
        ウィンドウ条件+コントロール条件の2段)。"""
        self._existing_paths.append(list(path_criteria))

    def set_active(self, path_criteria: list[dict], active: bool) -> None:
        """指定したパスの`wrapper_object().is_active()`が返す値を設定する
        (既定は`True`)。`wrapper_object()`は呼ぶたびに新しいオブジェクトを返すため、
        状態はここ(レジストリ側)で保持する。"""
        self._active_overrides.append((path_criteria, active))

    def set_enabled(self, path_criteria: list[dict], enabled: bool) -> None:
        """指定したパスの`wrapper_object().is_enabled()`が返す値を設定する
        (既定は`True`)、`set_active()`と同じ仕組み。"""
        self._enabled_overrides.append((path_criteria, enabled))

    def set_window_text(self, path_criteria: list[dict], text: str) -> None:
        """指定したパスの`.window_text()`が返す値を設定する(既定は空文字列、
        `set_active()`と同じくレジストリ側で状態を保持する)。"""
        self._window_text_overrides.append((path_criteria, text))

    def window_text_for(self, path: list[dict]) -> str:
        for criteria, text in reversed(self._window_text_overrides):
            if self._path_matches(criteria, path):
                return text
        return ""

    def set_toggle_state(self, path_criteria: list[dict], state: int) -> None:
        """`get_toggle_state()`の初期値を設定する(既定は`0`=unchecked、UIAの
        `ToggleState`表現(0=unchecked/1=checked)と同じ)。"""
        self._toggle_states.append([path_criteria, state])

    def toggle_state_for(self, path: list[dict]) -> int:
        for entry in reversed(self._toggle_states):
            if self._path_matches(entry[0], path):
                return entry[1]
        return 0

    def _set_toggle_state(self, path: list[dict], state: int) -> None:
        for entry in reversed(self._toggle_states):
            if self._path_matches(entry[0], path):
                entry[1] = state
                return
        self._toggle_states.append([path, state])

    def exists(self, path: list[dict]) -> bool:
        return any(self._path_matches(existing, path) for existing in self._existing_paths)

    @staticmethod
    def _path_matches(existing: list[dict], path: list[dict]) -> bool:
        if len(existing) != len(path):
            return False
        return all(
            all(existing_step.get(key) == value for key, value in step.items())
            for existing_step, step in zip(existing, path)
        )

    def wrapper_for(self, path: list[dict]) -> FakeWrapperObject:
        active = True
        for criteria, value in reversed(self._active_overrides):
            if self._path_matches(criteria, path):
                active = value
                break
        enabled = True
        for criteria, value in reversed(self._enabled_overrides):
            if self._path_matches(criteria, path):
                enabled = value
                break
        return FakeWrapperObject(active=active, enabled=enabled)

    def record(self, action: str, path: list[dict], kwargs: dict) -> None:
        self.calls.append((action, path, kwargs))


class _FakeDesktopHandle:
    def __init__(self, registry: FakeRegistry) -> None:
        self._registry = registry

    def window(self, **criteria: object) -> FakeControl:
        return FakeControl(self._registry, criteria)

    def windows(self, **_kwargs: object) -> list[FakeControl]:
        return [FakeControl(self._registry, path[0]) for path in self._registry._existing_paths if len(path) == 1]


def make_fake_desktop(registry: FakeRegistry):
    """`pywinauto.Desktop`に差し替えるファクトリ関数を返す。"""

    def fake_desktop(backend: str = "uia") -> _FakeDesktopHandle:
        return _FakeDesktopHandle(registry)

    return fake_desktop


@contextmanager
def fake_pywinauto_desktop(registry: FakeRegistry | None = None) -> Iterator[FakeRegistry]:
    """`pywinauto.Desktop`を(省略時は新規作成した)`registry`に基づくフェイクへ差し替える
    (ブロックを抜けたら元の状態に戻す)。`pywinauto`パッケージ自体はLinuxでも`import`
    できるが`Desktop`属性(`pywinauto.application`経由、Windows専用)は無いため、
    `tests/fake_win32.py`の`sys.modules`注入方式とは違い属性の差し替えで対応できる。
    """
    import pywinauto

    reg = registry if registry is not None else FakeRegistry()
    had_desktop = hasattr(pywinauto, "Desktop")
    original_desktop = getattr(pywinauto, "Desktop", None)
    pywinauto.Desktop = make_fake_desktop(reg)
    try:
        yield reg
    finally:
        if had_desktop:
            pywinauto.Desktop = original_desktop
        else:
            del pywinauto.Desktop
