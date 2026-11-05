"""`DateTime.Actions`のロジック層。

`GetCurrentDateTime`の`System`モードは「PAD実行ホストマシンのローカル時刻」という、
実行環境に依存する概念であり、別マシンで動くPythonとして本質的に再現不可能——この
関数を呼ぶ側(将来のcodegen統合)が`datetime.now()`をそのまま使うのは妥当だが、
それが実機のPAD実行結果と一致するとは限らないことを呼び出し側が理解しておく必要がある。

design/dsl_format_findings.md 知見116(decompile+実機確認済み): `Windows`タイムゾーン
モードは、知見112・115で確立した「DLL総当たりリフレクションで実際のクラス/メソッド/
データを直接取得する」手法で解決した。`Microsoft.Flow.RPA.Desktop.Modules.DateTime.
Actions.dll`を逆コンパイルしたところ、`TimeZoneLocation`列挙(141値)から実際の
Windows `TimeZoneInfo.Id`文字列への対応表(`TimeZoneDictionary._timeZoneDictionary`、
PAD自身が埋め込んでいる実データで、でっち上げではない)がソースにそのまま読める形で
見つかった——これを`_TIME_ZONE_LOCATION_TO_WINDOWS_ID`としてそのまま転記した。
Windows `TimeZoneInfo.Id`文字列自体は`pywin32`(既存の依存関係)の`win32timezone.
TimeZoneInfo(windows_id)`がそのまま`tzinfo`として使えることをVM上の実venvで確認済み
(`datetime.now(win32timezone.TimeZoneInfo('Pacific Standard Time'))`が正しいUTC-8の
オフセット付き現在時刻を返すことを確認した)——IANA名への変換は不要。
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


# design/dsl_format_findings.md 知見116: PADの`Microsoft.Flow.RPA.Desktop.Modules.
# DateTime.Actions.dll`内`TimeZoneDictionary._timeZoneDictionary`から逆コンパイルで
# 確認した実データをそのまま転記(でっち上げではない、PAD自身の対応表)。
_TIME_ZONE_LOCATION_TO_WINDOWS_ID = {
    "DatelineStandardTime": "Dateline Standard Time",
    "UTC11": "UTC-11",
    "AleutianStandardTime": "Aleutian Standard Time",
    "HawaiianStandardTime": "Hawaiian Standard Time",
    "MarquesasStandardTime": "Marquesas Standard Time",
    "AlaskanStandardTime": "Alaskan Standard Time",
    "UTC09": "UTC-09",
    "PacificStandardTimeMexico": "Pacific Standard Time (Mexico)",
    "UTC08": "UTC-08",
    "PacificStandardTime": "Pacific Standard Time",
    "USMountainStandardTime": "US Mountain Standard Time",
    "MountainStandardTimeMexico": "Mountain Standard Time (Mexico)",
    "MountainStandardTime": "Mountain Standard Time",
    "YukonStandardTime": "Yukon Standard Time",
    "CentralAmericaStandardTime": "Central America Standard Time",
    "CentralStandardTime": "Central Standard Time",
    "EasterIslandStandardTime": "Easter Island Standard Time",
    "CentralStandardTimeMexico": "Central Standard Time (Mexico)",
    "CanadaCentralStandardTime": "Canada Central Standard Time",
    "SAPacificStandardTime": "SA Pacific Standard Time",
    "EasternStandardTimeMexico": "Eastern Standard Time (Mexico)",
    "EasternStandardTime": "Eastern Standard Time",
    "HaitiStandardTime": "Haiti Standard Time",
    "CubaStandardTime": "Cuba Standard Time",
    "USEasternStandardTime": "US Eastern Standard Time",
    "TurksAndCaicosStandardTime": "Turks And Caicos Standard Time",
    "ParaguayStandardTime": "Paraguay Standard Time",
    "AtlanticStandardTime": "Atlantic Standard Time",
    "VenezuelaStandardTime": "Venezuela Standard Time",
    "CentralBrazilianStandardTime": "Central Brazilian Standard Time",
    "SAWesternStandardTime": "SA Western Standard Time",
    "PacificSAStandardTime": "Pacific SA Standard Time",
    "NewfoundlandStandardTime": "Newfoundland Standard Time",
    "TocantinsStandardTime": "Tocantins Standard Time",
    "ESouthAmericaStandardTime": "E. South America Standard Time",
    "SAEasternStandardTime": "SA Eastern Standard Time",
    "ArgentinaStandardTime": "Argentina Standard Time",
    "GreenlandStandardTime": "Greenland Standard Time",
    "MontevideoStandardTime": "Montevideo Standard Time",
    "MagallanesStandardTime": "Magallanes Standard Time",
    "SaintPierreStandardTime": "Saint Pierre Standard Time",
    "BahiaStandardTime": "Bahia Standard Time",
    "UTC02": "UTC-02",
    "MidAtlanticStandardTime": "Mid-Atlantic Standard Time",
    "AzoresStandardTime": "Azores Standard Time",
    "CapeVerdeStandardTime": "Cape Verde Standard Time",
    "UTC": "UTC",
    "GMTStandardTime": "GMT Standard Time",
    "GreenwichStandardTime": "Greenwich Standard Time",
    "SaoTomeStandardTime": "Sao Tome Standard Time",
    "MoroccoStandardTime": "Morocco Standard Time",
    "WEuropeStandardTime": "W. Europe Standard Time",
    "CentralEuropeStandardTime": "Central Europe Standard Time",
    "RomanceStandardTime": "Romance Standard Time",
    "CentralEuropeanStandardTime": "Central European Standard Time",
    "WCentralAfricaStandardTime": "W. Central Africa Standard Time",
    "GTBStandardTime": "GTB Standard Time",
    "MiddleEastStandardTime": "Middle East Standard Time",
    "EgyptStandardTime": "Egypt Standard Time",
    "EEuropeStandardTime": "E. Europe Standard Time",
    "SyriaStandardTime": "Syria Standard Time",
    "WestBankStandardTime": "West Bank Standard Time",
    "SouthAfricaStandardTime": "South Africa Standard Time",
    "FLEStandardTime": "FLE Standard Time",
    "IsraelStandardTime": "Israel Standard Time",
    "SouthSudanStandardTime": "South Sudan Standard Time",
    "KaliningradStandardTime": "Kaliningrad Standard Time",
    "SudanStandardTime": "Sudan Standard Time",
    "LibyaStandardTime": "Libya Standard Time",
    "NamibiaStandardTime": "Namibia Standard Time",
    "JordanStandardTime": "Jordan Standard Time",
    "ArabicStandardTime": "Arabic Standard Time",
    "TurkeyStandardTime": "Turkey Standard Time",
    "ArabStandardTime": "Arab Standard Time",
    "BelarusStandardTime": "Belarus Standard Time",
    "RussianStandardTime": "Russian Standard Time",
    "EAfricaStandardTime": "E. Africa Standard Time",
    "VolgogradStandardTime": "Volgograd Standard Time",
    "IranStandardTime": "Iran Standard Time",
    "ArabianStandardTime": "Arabian Standard Time",
    "AstrakhanStandardTime": "Astrakhan Standard Time",
    "AzerbaijanStandardTime": "Azerbaijan Standard Time",
    "RussiaTimeZone3": "Russia Time Zone 3",
    "MauritiusStandardTime": "Mauritius Standard Time",
    "SaratovStandardTime": "Saratov Standard Time",
    "GeorgianStandardTime": "Georgian Standard Time",
    "CaucasusStandardTime": "Caucasus Standard Time",
    "AfghanistanStandardTime": "Afghanistan Standard Time",
    "WestAsiaStandardTime": "West Asia Standard Time",
    "EkaterinburgStandardTime": "Ekaterinburg Standard Time",
    "PakistanStandardTime": "Pakistan Standard Time",
    "QyzylordaStandardTime": "Qyzylorda Standard Time",
    "IndiaStandardTime": "India Standard Time",
    "SriLankaStandardTime": "Sri Lanka Standard Time",
    "NepalStandardTime": "Nepal Standard Time",
    "BangladeshStandardTime": "Bangladesh Standard Time",
    "CentralAsiaStandardTime": "Central Asia Standard Time",
    "OmskStandardTime": "Omsk Standard Time",
    "MyanmarStandardTime": "Myanmar Standard Time",
    "SEAsiaStandardTime": "SE Asia Standard Time",
    "AltaiStandardTime": "Altai Standard Time",
    "WMongoliaStandardTime": "W. Mongolia Standard Time",
    "NorthAsiaStandardTime": "North Asia Standard Time",
    "NCentralAsiaStandardTime": "N. Central Asia Standard Time",
    "TomskStandardTime": "Tomsk Standard Time",
    "ChinaStandardTime": "China Standard Time",
    "NorthAsiaEastStandardTime": "North Asia East Standard Time",
    "SingaporeStandardTime": "Singapore Standard Time",
    "WAustraliaStandardTime": "W. Australia Standard Time",
    "TaipeiStandardTime": "Taipei Standard Time",
    "UlaanbaatarStandardTime": "Ulaanbaatar Standard Time",
    "AusCentralWStandardTime": "Aus Central W. Standard Time",
    "TransbaikalStandardTime": "Transbaikal Standard Time",
    "TokyoStandardTime": "Tokyo Standard Time",
    "NorthKoreaStandardTime": "North Korea Standard Time",
    "KoreaStandardTime": "Korea Standard Time",
    "YakutskStandardTime": "Yakutsk Standard Time",
    "CenAustraliaStandardTime": "Cen. Australia Standard Time",
    "AUSCentralStandardTime": "AUS Central Standard Time",
    "EAustraliaStandardTime": "E. Australia Standard Time",
    "AUSEasternStandardTime": "AUS Eastern Standard Time",
    "WestPacificStandardTime": "West Pacific Standard Time",
    "TasmaniaStandardTime": "Tasmania Standard Time",
    "VladivostokStandardTime": "Vladivostok Standard Time",
    "LordHoweStandardTime": "Lord Howe Standard Time",
    "BougainvilleStandardTime": "Bougainville Standard Time",
    "RussiaTimeZone10": "Russia Time Zone 10",
    "MagadanStandardTime": "Magadan Standard Time",
    "NorfolkStandardTime": "Norfolk Standard Time",
    "SakhalinStandardTime": "Sakhalin Standard Time",
    "CentralPacificStandardTime": "Central Pacific Standard Time",
    "RussiaTimeZone11": "Russia Time Zone 11",
    "NewZealandStandardTime": "New Zealand Standard Time",
    "UTC12": "UTC+12",
    "FijiStandardTime": "Fiji Standard Time",
    "KamchatkaStandardTime": "Kamchatka Standard Time",
    "ChathamIslandsStandardTime": "Chatham Islands Standard Time",
    "UTC13": "UTC+13",
    "TongaStandardTime": "Tonga Standard Time",
    "SamoaStandardTime": "Samoa Standard Time",
    "LineIslandsStandardTime": "Line Islands Standard Time",
}


_SIMPLE_UNITS = {"Seconds": "seconds", "Minutes": "minutes", "Hours": "hours", "Days": "days"}


def get_current_datetime(
    date_time_format: str = "DateAndTime",
    time_zone_mode: str = "System",
    offset: str = "",
    time_zone_location: str = "",
    custom_offset: float = 0.0,
    custom_timezone: str = "",
    input_type: str = "Offset",
) -> datetime:
    """design/dsl_format_findings.md 知見138(VM上で`GetCurrentDateTime.Execute()`を
    直接呼び出して確認済み): `TimeZoneMode.Custom`には実機の`InputType`列挙値
    (`Offset`/`Windows`)で2つの入力方式がある——`Offset`(既定)は従来の`custom_offset`
    (UTC+N時間シフト)、`Windows`は`custom_timezone`に.NETの`TimeZoneInfo.Id`形式の
    文字列(例: `"Tokyo Standard Time"`、スペースを含む——`TimeZoneMode.Windows`の
    `TimeZoneLocation`列挙値のようなハイフン無しキー名ではない)を直接渡す、
    ルックアップテーブルを経由しない経路。`custom_offset=9.0`と
    `custom_timezone="Tokyo Standard Time"`が実機で同一の結果(UTC+9)になることを確認済み。
    """
    if time_zone_mode == "System":
        value = datetime.now()
    elif time_zone_mode == "Custom" and input_type == "Windows":
        try:
            import win32timezone
        except ImportError as exc:
            raise GetCurrentDateTimeError(
                "win32timezone (pywin32) is required for TimeZoneMode.Custom "
                "(InputType.Windows); this only works on Windows"
            ) from exc
        value = datetime.now(win32timezone.TimeZoneInfo(custom_timezone)).replace(tzinfo=None)
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
        windows_id = _TIME_ZONE_LOCATION_TO_WINDOWS_ID.get(time_zone_location)
        if windows_id is None:
            raise CountryOrRegionNotFoundError(f"unknown TimeZoneLocation: {time_zone_location!r}")
        try:
            import win32timezone
        except ImportError as exc:
            raise GetCurrentDateTimeError(
                "win32timezone (pywin32) is required for TimeZoneMode.Windows; this only works on Windows"
            ) from exc
        value = datetime.now(win32timezone.TimeZoneInfo(windows_id)).replace(tzinfo=None)
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
