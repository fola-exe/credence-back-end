from datetime import date

from app.db.enums import CreditTransactionStatus


def choose_template(
    status: CreditTransactionStatus | str, due_date: date, today: date
) -> str:
    value = status.value if hasattr(status, "value") else str(status)
    if value == CreditTransactionStatus.PENDING_ACK.value:
        return "new_credit"
    days_overdue = (today - due_date).days
    if days_overdue < 0:
        return "upcoming"
    if days_overdue == 0:
        return "due_today"
    if days_overdue <= 6:
        return "overdue_1"
    return "overdue_followup"
