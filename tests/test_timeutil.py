from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from bot.timeutil import TimeParseError, format_jalali, parse_schedule_time

TZ = ZoneInfo("Asia/Tehran")
NOW = datetime(2026, 10, 15, 20, 0, tzinfo=TZ)


def test_jalali_date():
    assert parse_schedule_time("1405/07/28 18:30", TZ, NOW) == datetime(2026, 10, 20, 18, 30, tzinfo=TZ)


def test_persian_digits():
    assert parse_schedule_time("۱۴۰۵/۰۷/۲۸ ۱۸:۳۰", TZ, NOW) == datetime(2026, 10, 20, 18, 30, tzinfo=TZ)


def test_gregorian_date():
    assert parse_schedule_time("2026-10-20 9:05", TZ, NOW) == datetime(2026, 10, 20, 9, 5, tzinfo=TZ)


def test_time_only_rolls_to_tomorrow():
    assert parse_schedule_time("18:30", TZ, NOW) == datetime(2026, 10, 16, 18, 30, tzinfo=TZ)
    assert parse_schedule_time("21:00", TZ, NOW) == datetime(2026, 10, 15, 21, 0, tzinfo=TZ)


@pytest.mark.parametrize("raw", ["tomorrow", "1405/13/01 10:00", "25:00", "2026-02-30 10:00"])
def test_invalid(raw):
    with pytest.raises(TimeParseError):
        parse_schedule_time(raw, TZ, NOW)


def test_format_jalali():
    assert format_jalali(datetime(2026, 10, 20, 15, 0, tzinfo=ZoneInfo("UTC")), TZ) == "1405/07/28 18:30"
