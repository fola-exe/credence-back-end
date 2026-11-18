from datetime import date, datetime, timezone

import pytest
import time_machine

from app.core.time import (
    WAT,
    at_9am_wat,
    format_date_wat,
    format_datetime_wat,
    now_utc,
    today_wat,
)


def test_today_wat_rolls_over_at_lagos_midnight():
    instant = datetime(2026, 11, 18, 23, 30, tzinfo=timezone.utc)

    assert today_wat(instant) == date(2026, 11, 19)


def test_at_9am_wat_is_08_00_utc():
    assert at_9am_wat(date(2026, 11, 18)) == datetime(
        2026, 11, 18, 8, 0, tzinfo=timezone.utc
    )


def test_format_date_wat_uses_lagos_calendar_date():
    instant = datetime(2026, 11, 18, 23, 30, tzinfo=timezone.utc)

    assert format_date_wat(instant) == "Thu 19 Nov 2026"


def test_format_datetime_wat_includes_zone_label():
    instant = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)

    assert format_datetime_wat(instant) == "Wed 18 Nov 2026, 09:00 WAT"


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        today_wat(datetime(2026, 11, 18, 9, 0))


@time_machine.travel("2026-11-18T10:15:00Z")
def test_now_utc_is_aware():
    current = now_utc()

    assert current.tzinfo is timezone.utc
    assert current.astimezone(WAT).hour == 11
