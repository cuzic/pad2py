"""`pad_action_lib.datetime_actions`の単体テスト。"""
from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal

import pytest

from dump_daemon.pad_action_lib import datetime_actions as da


def test_get_current_datetime_system_mode_returns_now() -> None:
    before = datetime.now()
    result = da.get_current_datetime(time_zone_mode="System")
    after = datetime.now()
    assert before <= result <= after


def test_get_current_datetime_date_only_zeroes_time() -> None:
    result = da.get_current_datetime(date_time_format="DateOnly", time_zone_mode="System")
    assert result.hour == 0 and result.minute == 0 and result.second == 0


def test_get_current_datetime_custom_offset_ignores_dst() -> None:
    result = da.get_current_datetime(time_zone_mode="Custom", custom_offset=3.0)
    # UTC+3時間シフトなので、UTC現在時刻との差はおよそ3時間(数秒の実行時間ずれは許容)。
    from datetime import timezone

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    delta = (result - now_utc).total_seconds() - 3 * 3600
    assert abs(delta) < 5


def test_get_current_datetime_specific_zone() -> None:
    from datetime import timezone

    result = da.get_current_datetime(time_zone_mode="Specific", offset="UTC")
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((result - now_utc).total_seconds()) < 5


def test_get_current_datetime_unknown_zone_raises() -> None:
    with pytest.raises(da.CountryOrRegionNotFoundError):
        da.get_current_datetime(time_zone_mode="Specific", offset="Not/AZone")


def test_get_current_datetime_windows_mode_unknown_location_raises() -> None:
    # design/dsl_format_findings.md 知見116: `time_zone_location`はPAD自身の
    # `TimeZoneLocation`列挙名(例: "TokyoStandardTime"、スペース無し)で渡す
    # ——実機DSLでの直列化形式自体は未確認のため、`pad_codegen`側はまだ結線していない。
    with pytest.raises(da.CountryOrRegionNotFoundError):
        da.get_current_datetime(time_zone_mode="Windows", time_zone_location="NotARealTimeZone")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows専用(win32timezone)")
def test_get_current_datetime_windows_mode_resolves_known_location() -> None:
    # design/dsl_format_findings.md 知見116(decompile+実機確認済み): PAD自身の
    # Microsoft.Flow.RPA.Desktop.Modules.DateTime.Actions.dllから逆コンパイルで
    # 確認したTimeZoneLocation→Windows TimeZoneInfo.Id対応表+win32timezone経由で
    # 実際にタイムゾーン変換ができることを確認する。
    from datetime import timezone

    result = da.get_current_datetime(time_zone_mode="Windows", time_zone_location="TokyoStandardTime")
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    delta = (result - now_utc).total_seconds() - 9 * 3600
    assert abs(delta) < 5


def test_add_to_datetime_simple_units() -> None:
    base = datetime(2024, 1, 1, 0, 0, 0)
    assert da.add_to_datetime(base, 90, "Seconds") == datetime(2024, 1, 1, 0, 1, 30)
    assert da.add_to_datetime(base, 2, "Days") == datetime(2024, 1, 3, 0, 0, 0)


def test_add_to_datetime_months_clamps_end_of_month() -> None:
    # 1/31 + 1ヶ月 = 2/28or29(オーバーフローや例外にならない)。
    base = datetime(2024, 1, 31)
    assert da.add_to_datetime(base, 1, "Months") == datetime(2024, 2, 29)


def test_add_to_datetime_years() -> None:
    base = datetime(2020, 2, 29)
    assert da.add_to_datetime(base, 1, "Years") == datetime(2021, 2, 28)


def test_subtract_dates_days_positive_when_from_date_is_later() -> None:
    later = datetime(2024, 1, 3)
    earlier = datetime(2024, 1, 1)
    assert da.subtract_dates(later, earlier, "Days") == Decimal("2")


def test_subtract_dates_hours() -> None:
    later = datetime(2024, 1, 1, 3)
    earlier = datetime(2024, 1, 1, 0)
    assert da.subtract_dates(later, earlier, "Hours") == Decimal("3")
