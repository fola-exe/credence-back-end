from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

WAT = ZoneInfo("Africa/Lagos")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


def today_wat(now: datetime | None = None) -> date:
    current = _require_aware(now or now_utc())
    return current.astimezone(WAT).date()


def at_9am_wat(day: date) -> datetime:
    return datetime.combine(day, time(9, 0), tzinfo=WAT).astimezone(timezone.utc)


def format_date_wat(value: date | datetime) -> str:
    if isinstance(value, datetime):
        return _require_aware(value).astimezone(WAT).strftime("%a %d %b %Y")
    return value.strftime("%a %d %b %Y")


def format_datetime_wat(value: datetime) -> str:
    return _require_aware(value).astimezone(WAT).strftime("%a %d %b %Y, %H:%M WAT")
