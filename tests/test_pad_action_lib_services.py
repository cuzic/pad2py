"""`pad_action_lib.services_actions`の単体テスト。

design/dsl_format_findings.md 知見187: `win32serviceutil`/`win32service`/`winerror`は
Windows以外には存在しないため、`sys.modules`へ偽装注入して(実際のサービス操作を
一切行わず)配線・エラーマッピングのみを検証する。
"""
from __future__ import annotations

import sys
import types

import pytest

from dump_daemon.pad_action_lib import services_actions as sa


def _install_fake_winerror(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_winerror = types.ModuleType("winerror")
    fake_winerror.ERROR_SERVICE_DOES_NOT_EXIST = 1060  # type: ignore[attr-defined]
    fake_winerror.ERROR_SERVICE_ALREADY_RUNNING = 1056  # type: ignore[attr-defined]
    fake_winerror.ERROR_SERVICE_NOT_ACTIVE = 1062  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "winerror", fake_winerror)


class _FakeServiceError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code, "junk", "junk message")


def test_start_service_calls_win32serviceutil(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    fake_win32serviceutil = types.ModuleType("win32serviceutil")
    fake_win32serviceutil.StartService = lambda name: calls.append(name)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32serviceutil", fake_win32serviceutil)

    sa.start_service("Spooler")

    assert calls == ["Spooler"]


def test_start_service_wraps_service_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_winerror(monkeypatch)
    fake_win32serviceutil = types.ModuleType("win32serviceutil")

    def _raise(name: str) -> None:
        raise _FakeServiceError(1060)

    fake_win32serviceutil.StartService = _raise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32serviceutil", fake_win32serviceutil)

    with pytest.raises(sa.ServiceNotFoundError):
        sa.start_service("NoSuchService")


def test_start_service_wraps_already_running(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_winerror(monkeypatch)
    fake_win32serviceutil = types.ModuleType("win32serviceutil")

    def _raise(name: str) -> None:
        raise _FakeServiceError(1056)

    fake_win32serviceutil.StartService = _raise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32serviceutil", fake_win32serviceutil)

    with pytest.raises(sa.ServiceAlreadyRunningError):
        sa.start_service("Spooler")


def test_start_service_wraps_unknown_failure_generically(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_winerror(monkeypatch)
    fake_win32serviceutil = types.ModuleType("win32serviceutil")

    def _raise(name: str) -> None:
        raise _FakeServiceError(5)  # ERROR_ACCESS_DENIED, unrelated to any known mapping

    fake_win32serviceutil.StartService = _raise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32serviceutil", fake_win32serviceutil)

    with pytest.raises(sa.StartServiceError):
        sa.start_service("Spooler")


def test_stop_service_calls_win32serviceutil(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    fake_win32serviceutil = types.ModuleType("win32serviceutil")
    fake_win32serviceutil.StopService = lambda name: calls.append(name)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32serviceutil", fake_win32serviceutil)

    sa.stop_service("Spooler")

    assert calls == ["Spooler"]


def test_stop_service_wraps_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_winerror(monkeypatch)
    fake_win32serviceutil = types.ModuleType("win32serviceutil")

    def _raise(name: str) -> None:
        raise _FakeServiceError(1062)

    fake_win32serviceutil.StopService = _raise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32serviceutil", fake_win32serviceutil)

    with pytest.raises(sa.ServiceNotRunningError):
        sa.stop_service("Spooler")


def test_pause_service_sends_pause_control_code(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    fake_win32service = types.ModuleType("win32service")
    fake_win32service.SERVICE_CONTROL_PAUSE = 2  # type: ignore[attr-defined]
    fake_win32service.SERVICE_CONTROL_CONTINUE = 3  # type: ignore[attr-defined]
    fake_win32serviceutil = types.ModuleType("win32serviceutil")
    fake_win32serviceutil.ControlService = lambda name, code: calls.append((name, code))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32service", fake_win32service)
    monkeypatch.setitem(sys.modules, "win32serviceutil", fake_win32serviceutil)

    sa.pause_service("Spooler")

    assert calls == [("Spooler", 2)]


def test_resume_service_sends_continue_control_code(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    fake_win32service = types.ModuleType("win32service")
    fake_win32service.SERVICE_CONTROL_PAUSE = 2  # type: ignore[attr-defined]
    fake_win32service.SERVICE_CONTROL_CONTINUE = 3  # type: ignore[attr-defined]
    fake_win32serviceutil = types.ModuleType("win32serviceutil")
    fake_win32serviceutil.ControlService = lambda name, code: calls.append((name, code))  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32service", fake_win32service)
    monkeypatch.setitem(sys.modules, "win32serviceutil", fake_win32serviceutil)

    sa.resume_service("Spooler")

    assert calls == [("Spooler", 3)]


def test_start_service_wraps_import_failure() -> None:
    import builtins

    real_import = builtins.__import__

    def _blocked_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "win32serviceutil":
            raise ImportError("no pywin32 on this platform")
        return real_import(name, *args, **kwargs)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr(builtins, "__import__", _blocked_import)
        with pytest.raises(sa.StartServiceError):
            sa.start_service("Spooler")


def test_get_service_status_returns_raw_state_code(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_win32serviceutil = types.ModuleType("win32serviceutil")
    fake_win32serviceutil.QueryServiceStatus = lambda name: (16, sa.SERVICE_RUNNING, 0, 0, 0, 0, 0)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32serviceutil", fake_win32serviceutil)

    assert sa.get_service_status("Spooler") == sa.SERVICE_RUNNING


def test_get_service_status_wraps_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_winerror(monkeypatch)
    fake_win32serviceutil = types.ModuleType("win32serviceutil")

    def _raise(name: str) -> None:
        raise _FakeServiceError(1060)

    fake_win32serviceutil.QueryServiceStatus = _raise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32serviceutil", fake_win32serviceutil)

    with pytest.raises(sa.ServiceNotFoundError):
        sa.get_service_status("NoSuchService")


def test_get_service_status_wraps_unknown_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_winerror(monkeypatch)
    fake_win32serviceutil = types.ModuleType("win32serviceutil")

    def _raise(name: str) -> None:
        raise _FakeServiceError(5)

    fake_win32serviceutil.QueryServiceStatus = _raise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "win32serviceutil", fake_win32serviceutil)

    with pytest.raises(sa.RetrieveStatusForServiceError):
        sa.get_service_status("Spooler")


def test_is_service_installed_matches_by_display_name(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_win32service = types.ModuleType("win32service")
    fake_win32service.SC_MANAGER_ENUMERATE_SERVICE = 4  # type: ignore[attr-defined]
    fake_win32service.SERVICE_WIN32 = 0x30  # type: ignore[attr-defined]
    fake_win32service.SERVICE_STATE_ALL = 3  # type: ignore[attr-defined]
    fake_win32service.OpenSCManager = lambda *a: object()  # type: ignore[attr-defined]
    fake_win32service.CloseServiceHandle = lambda h: None  # type: ignore[attr-defined]
    fake_win32service.EnumServicesStatus = lambda hscm, t, s: [  # type: ignore[attr-defined]
        ("Spooler", "Print Spooler", (0, 0, 0, 0, 0, 0, 0)),
        ("WSearch", "Windows Search", (0, 0, 0, 0, 0, 0, 0)),
    ]
    monkeypatch.setitem(sys.modules, "win32service", fake_win32service)

    assert sa.is_service_installed("Print Spooler") is True
    assert sa.is_service_installed("Spooler") is False
    assert sa.is_service_installed("Nonexistent") is False
