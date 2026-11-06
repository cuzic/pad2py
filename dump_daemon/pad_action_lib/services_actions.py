"""`Services.Start`/`Stop`/`Pause`/`Resume`(Windowsサービス制御)のロジック層。

design/dsl_format_findings.md 知見187: `Microsoft.Flow.RPA.Desktop.Modules.
Services.Actions.dll`をdecompileし、`StartService`/`StopService`/`PauseService`/
`ResumeService`の4アクションが、いずれも待機・タイムアウト無しで.NETの
`System.ServiceProcess.ServiceController.Start()`/`.Stop()`/`.Pause()`/
`.Continue()`をそのまま呼ぶだけ(エラーハンドリングのみ、`Start`/`Stop`)と確認した。
`ServiceController`のコンストラクタ(`new ServiceController(serviceName)`)は
サービスの短い名前(ServiceName、例: `"Spooler"`)で解決する——既存の実機キャプチャ
フィクスチャの`Service: $'''Spooler'''`もこの形式と一致する。

pywin32(既存の依存関係、`win32crypt`/`win32timezone`/`win32com.shell`で既に使用)の
`win32serviceutil`/`win32service`は、同じWin32 Service Control Manager API
(`OpenSCManager`+`OpenService`+`ControlService`)を呼ぶため、1対1で対応付けできる
(でっち上げ無し)。エラー時のWin32エラーコード(`ERROR_SERVICE_DOES_NOT_EXIST`=1060・
`ERROR_SERVICE_ALREADY_RUNNING`=1056・`ERROR_SERVICE_NOT_ACTIVE`=1062)は
ローカライズされない数値定数であり、.NET側の(ローカライズ依存の)メッセージ文字列
照合より確実に判定できる。
"""
from __future__ import annotations

from .errors import PadActionError


class ServiceNotFoundError(PadActionError):
    pass


class ServiceAlreadyRunningError(PadActionError):
    pass


class ServiceNotRunningError(PadActionError):
    pass


class StartServiceError(PadActionError):
    pass


class StopServiceError(PadActionError):
    pass


class PauseServiceError(PadActionError):
    pass


class ResumeServiceError(PadActionError):
    pass


def _raise_mapped_error(
    service_name: str,
    exc: Exception,
    generic_error: type[PadActionError],
    *,
    check_already_running: bool = False,
    check_not_active: bool = False,
) -> None:
    import winerror

    code = exc.args[0] if exc.args else None
    if code == winerror.ERROR_SERVICE_DOES_NOT_EXIST:
        raise ServiceNotFoundError(f"Service {service_name!r} was not found") from exc
    if check_already_running and code == winerror.ERROR_SERVICE_ALREADY_RUNNING:
        raise ServiceAlreadyRunningError(f"Service {service_name!r} is already running") from exc
    if check_not_active and code == winerror.ERROR_SERVICE_NOT_ACTIVE:
        raise ServiceNotRunningError(f"Service {service_name!r} is not running") from exc
    raise generic_error(str(exc)) from exc


def start_service(service_name: str) -> None:
    try:
        import win32serviceutil
    except ImportError as exc:
        raise StartServiceError("pywin32 (win32serviceutil) is required; this only works on Windows") from exc

    try:
        win32serviceutil.StartService(service_name)
    except Exception as exc:
        _raise_mapped_error(service_name, exc, StartServiceError, check_already_running=True)


def stop_service(service_name: str) -> None:
    try:
        import win32serviceutil
    except ImportError as exc:
        raise StopServiceError("pywin32 (win32serviceutil) is required; this only works on Windows") from exc

    try:
        win32serviceutil.StopService(service_name)
    except Exception as exc:
        _raise_mapped_error(service_name, exc, StopServiceError, check_not_active=True)


def pause_service(service_name: str) -> None:
    try:
        import win32service
        import win32serviceutil
    except ImportError as exc:
        raise PauseServiceError(
            "pywin32 (win32service/win32serviceutil) is required; this only works on Windows"
        ) from exc

    try:
        win32serviceutil.ControlService(service_name, win32service.SERVICE_CONTROL_PAUSE)
    except Exception as exc:
        _raise_mapped_error(service_name, exc, PauseServiceError, check_not_active=True)


def resume_service(service_name: str) -> None:
    try:
        import win32service
        import win32serviceutil
    except ImportError as exc:
        raise ResumeServiceError(
            "pywin32 (win32service/win32serviceutil) is required; this only works on Windows"
        ) from exc

    try:
        win32serviceutil.ControlService(service_name, win32service.SERVICE_CONTROL_CONTINUE)
    except Exception as exc:
        _raise_mapped_error(service_name, exc, ResumeServiceError, check_not_active=True)
