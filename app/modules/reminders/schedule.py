from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.core.time import at_9am_wat, today_wat
from app.db.enums import ReminderKind

REMINDER_HOUR_WAT = 9


@dataclass(frozen=True)
class ReminderPlan:
    kind: ReminderKind
    scheduled_for: datetime


def next_tick_instant(now: datetime) -> datetime:
    base = now.replace(minute=0, second=0, microsecond=0)
    return base + timedelta(minutes=((now.minute // 15) + 1) * 15)


def next_overdue_slot(now: datetime) -> datetime:
    return at_9am_wat(today_wat(now) + timedelta(days=1))


def _kind_value(kind: ReminderKind | str) -> str:
    return kind.value if isinstance(kind, ReminderKind) else str(kind)


def build_schedule(
    issue_date: date,
    due_date: date,
    now: datetime,
    reference_today: date | None = None,
    existing_kinds: tuple[ReminderKind | str, ...] = (),
) -> list[ReminderPlan]:
    today = reference_today or today_wat(now)
    already = {_kind_value(kind) for kind in existing_kinds}
    overdue_pending = any(kind.startswith("overdue") for kind in already)

    candidates = (
        (ReminderKind.UPCOMING, due_date - timedelta(days=3)),
        (ReminderKind.DUE_TODAY, due_date),
        (ReminderKind.OVERDUE_1, due_date + timedelta(days=3)),
        (ReminderKind.OVERDUE_FOLLOWUP, due_date + timedelta(days=7)),
    )
    plans: list[ReminderPlan] = []
    for kind, day in candidates:
        if _kind_value(kind) in already or day < today:
            continue
        slot = at_9am_wat(day)
        if slot <= now:
            slot = next_tick_instant(now)
        plans.append(ReminderPlan(kind=kind, scheduled_for=slot))
        if _kind_value(kind).startswith("overdue"):
            overdue_pending = True

    if due_date < today and not overdue_pending:
        plans.append(
            ReminderPlan(
                kind=ReminderKind.OVERDUE_FOLLOWUP,
                scheduled_for=next_overdue_slot(now),
            )
        )
    return plans
