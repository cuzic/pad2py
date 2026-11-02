"""F1/F2/F3: 依存パッケージのインストール・インポート可否の検証。"""
from __future__ import annotations

import importlib
import sys

import pytest

DEPENDENCIES = [
    "mss",
    "fastapi",
    "uvicorn",
    "jsonschema",
    "psutil",
    "PIL",
]

# pywinauto/comtypes は import 時点でWindows固有API(ctypes.windll等)に依存するため、
# 非Windows環境ではインポート自体が失敗する。Windows専用グループとして扱う。
WINDOWS_ONLY_DEPENDENCIES = ["pywinauto", "comtypes", "win32api", "win32gui", "win32con"]


@pytest.mark.parametrize("module_name", DEPENDENCIES)
def test_dependency_importable(module_name: str) -> None:
    importlib.import_module(module_name)


@pytest.mark.parametrize("module_name", WINDOWS_ONLY_DEPENDENCIES)
def test_windows_only_dependency_importable(module_name: str) -> None:
    if sys.platform != "win32":
        pytest.skip("Windows専用モジュール(pywin32)")
    importlib.import_module(module_name)


def test_python_version_supported() -> None:
    assert sys.version_info >= (3, 10)
