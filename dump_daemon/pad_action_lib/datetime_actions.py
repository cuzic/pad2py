"""`DateTime.Actions`のロジック層。

`GetCurrentDateTime`の`System`モードは「PAD実行ホストマシンのローカル時刻」という、
実行環境に依存する概念であり、別マシンで動くPythonとして本質的に再現不可能——この
関数を呼ぶ側(将来のcodegen統合)が`datetime.now()`をそのまま使うのは妥当だが、
それが実機のPAD実行結果と一致するとは限らないことを呼び出し側が理解しておく必要がある。
`Windows`タイムゾーンモードはWindowsタイムゾーン名→IANA名の対応表が無いと実装できない
ため、`NotImplementedError`で明示する(でっち上げた対応表は作らない)。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.relativedelta import relativedelta

from .errors import PadActionError


class GetCurrentDateTimeError(PadActionError):
    pass


class CountryOrRegionNotFoundError(PadActionError):
    pass


_SIMPLE_UNITS = {"Seconds": "seconds", "Minutes": "minutes", "Hours": "hours", "Days": "days"}


def get_current_datetime(
    date_time_format: str = "DateAndTime",
    time_zone_mode: str = "System",
    offset: str = "",
    time_zone_location: str = "",
    custom_offset: float = 0.0,
    custom_timezone: str = "",
) -> datetime:
    if time_zone_mode == "System":
        value = datetime.now()
    elif time_zone_mode == "Custom":
        # DSTを無視した単純なUTC+Nシフト。
        value = (datetime.now(timezone.utc) + timedelta(hours=custom_offset)).replace(tzinfo=None)
    elif time_zone_mode == "Specific":
        try:
            tz = ZoneInfo(offset)
        except ZoneInfoNotFoundError as exc:
            raise CountryOrRegionNotFoundError(f"unknown IANA zone: {offset!r}") from exc
        value = datetime.now(tz).replace(tzinfo=None)
    elif time_zone_mode == "Windows":
        raise NotImplementedError(
            "Windows timezone name -> IANA mapping table not implemented "
            f"(time_zone_location={time_zone_location!r})"
        )
    else:
        raise ValueError(f"Unknown TimeZoneMode: {time_zone_mode!r}")

    if date_time_format == "DateOnly":
        value = value.replace(hour=0, minute=0, second=0, microsecond=0)
    return value


def add_to_datetime(value: datetime, time_to_add: int, time_unit: str = "Seconds") -> datetime:
    if time_unit in _SIMPLE_UNITS:
        return value + timedelta(**{_SIMPLE_UNITS[time_unit]: time_to_add})
    if time_unit == "Months":
        return value + relativedelta(months=time_to_add)
    if time_unit == "Years":
        return value + relativedelta(years=time_to_add)
    raise ValueError(f"Unknown TimeUnit: {time_unit!r}")


_SUBTRACT_UNITS = {
    "Seconds": lambda delta: Decimal(str(delta.total_seconds())),
    "Minutes": lambda delta: Decimal(str(delta.total_seconds() / 60)),
    "Hours": lambda delta: Decimal(str(delta.total_seconds() / 3600)),
    "Days": lambda delta: Decimal(str(delta.total_seconds() / 86400)),
}


def subtract_dates(from_date: datetime, subtract_date: datetime, time_unit: str = "Days") -> Decimal:
    try:
        convert = _SUBTRACT_UNITS[time_unit]
    except KeyError as exc:
        raise ValueError(f"Unknown TimeUnit: {time_unit!r}") from exc
    return convert(from_date - subtract_date)
