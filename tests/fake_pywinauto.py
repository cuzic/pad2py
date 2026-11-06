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
`.close()`/`.type_keys()`/`.wait()`/`.wait_not()`/`.maximize()`/`.minimize()`/`.restore()`)
のみ——新しい呼び出し形が出てきたら、その都度ここに追加する(未対応の呼び出しをでっち上げて
成功させるのではなく、素直に`AttributeError`で気づけるようにする)。
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


class FakeElementNotFoundError(Exception):
    """`FakeControl.wrapper_object()`を存在しない要素に対して呼んだ場合(pywinautoの
    `ElementNotFoundError`相当)。"""


@dataclass
class FakeWrapperObject:
    handle: int = 0
    active: bool = True

    def is_active(self) -> bool:
        return self.active


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


class FakeRegistry:
    """1テスト分のフェイクUI状態(スクリプト可能)+呼び出しログ。"""

    def __init__(self) -> None:
        self._existing_paths: list[list[dict]] = []
        self._active_overrides: list[tuple[list[dict], bool]] = []
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
        for criteria, active in reversed(self._active_overrides):
            if self._path_matches(criteria, path):
                return FakeWrapperObject(active=active)
        return FakeWrapperObject()

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
