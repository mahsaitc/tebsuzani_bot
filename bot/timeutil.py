"""Parsing and formatting of schedule times (Jalali and Gregorian)."""

import re
from datetime import datetime, timedelta, tzinfo

import jdatetime

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

_FULL = re.compile(r"^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\s+(\d{1,2}):(\d{2})$")
_TIME_ONLY = re.compile(r"^(\d{1,2}):(\d{2})$")


class TimeParseError(ValueError):
    pass


def parse_schedule_time(raw: str, tz: tzinfo, now: datetime | None = None) -> datetime:
    """Parse a user-entered time into an aware datetime in ``tz``.

    Accepted formats (Persian or Latin digits):
      * ``1405/07/28 18:30``  - Jalali (Shamsi) date, detected by year < 1700
      * ``2026-10-20 18:30``  - Gregorian date
      * ``18:30``             - today at that time, or tomorrow if it has already passed
    """
    text = raw.strip().translate(_PERSIAN_DIGITS)
    now = (now or datetime.now(tz)).astimezone(tz)

    m = _TIME_ONLY.match(text)
    if m:
        hour, minute = int(m[1]), int(m[2])
        _check_clock(hour, minute)
        result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if result <= now:
            result += timedelta(days=1)
        return result

    m = _FULL.match(text)
    if not m:
        raise TimeParseError("bad format")
    year, month, day, hour, minute = (int(g) for g in m.groups())
    _check_clock(hour, minute)
    try:
        if year < 1700:
            g = jdatetime.date(year, month, day).togregorian()
            year, month, day = g.year, g.month, g.day
        return datetime(year, month, day, hour, minute, tzinfo=tz)
    except ValueError as exc:
        raise TimeParseError("invalid date") from exc


def format_jalali(dt: datetime, tz: tzinfo) -> str:
    local = dt.astimezone(tz)
    j = jdatetime.datetime.fromgregorian(datetime=local.replace(tzinfo=None))
    return j.strftime("%Y/%m/%d %H:%M")


def _check_clock(hour: int, minute: int) -> None:
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise TimeParseError("invalid time")
