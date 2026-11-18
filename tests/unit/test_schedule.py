from datetime import date, datetime, timezone

from app.core.time import at_9am_wat
from app.db.enums import ReminderKind
from app.modules.reminders.schedule import (
    build_schedule,
    next_overdue_slot,
    next_tick_instant,
)


def test_next_tick_instant_rounds_up_to_quarter():
    now = datetime(2026, 11, 18, 8, 17, 30, tzinfo=timezone.utc)

    assert next_tick_instant(now) == datetime(
        2026, 11, 18, 8, 30, tzinfo=timezone.utc
    )


def test_next_overdue_slot_is_tomorrow_9am_wat():
    now = datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc)

    assert next_overdue_slot(now) == at_9am_wat(date(2026, 11, 19))


def test_build_schedule_future_dates():
    now = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)

    plans = build_schedule(date(2026, 11, 18), date(2026, 11, 25), now)

    assert [plan.kind for plan in plans] == [
        ReminderKind.UPCOMING,
        ReminderKind.DUE_TODAY,
        ReminderKind.OVERDUE_1,
        ReminderKind.OVERDUE_FOLLOWUP,
    ]
    assert plans[0].scheduled_for == at_9am_wat(date(2026, 11, 22))


def test_build_schedule_bumps_past_slot_to_next_tick():
    now = datetime(2026, 11, 25, 8, 5, tzinfo=timezone.utc)

    plans = build_schedule(date(2026, 11, 22), date(2026, 11, 25), now)

    due_today = next(plan for plan in plans if plan.kind == ReminderKind.DUE_TODAY)
    assert due_today.scheduled_for == datetime(
        2026, 11, 25, 8, 15, tzinfo=timezone.utc
    )


def test_build_schedule_already_overdue_inserts_followup_once():
    now = datetime(2026, 11, 25, 8, 0, tzinfo=timezone.utc)

    plans = build_schedule(date(2026, 11, 17), date(2026, 11, 20), now)

    assert [plan.kind for plan in plans] == [ReminderKind.OVERDUE_FOLLOWUP]
    assert plans[0].scheduled_for == at_9am_wat(date(2026, 11, 27))
    assert (
        build_schedule(
            date(2026, 11, 17),
            date(2026, 11, 20),
            now,
            existing_kinds=(ReminderKind.OVERDUE_FOLLOWUP,),
        )
        == []
    )
