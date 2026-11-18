from enum import Enum
from typing import Type


class CreditTransactionStatus(str, Enum):
    PENDING_ACK = "pending_ack"
    ACTIVE = "active"
    PARTIALLY_PAID = "partially_paid"
    DISPUTED = "disputed"
    SETTLED = "settled"
    CANCELLED = "cancelled"


class DisplayStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    PARTIALLY_PAID = "partially_paid"
    OVERDUE = "overdue"
    DISPUTED = "disputed"
    SETTLED = "settled"
    CANCELLED = "cancelled"


class PaymentStatus(str, Enum):
    INITIATED = "initiated"
    PENDING = "pending"
    SUCCESSFUL = "successful"
    FAILED = "failed"
    REVERSED = "reversed"


class DebtorResponseType(str, Enum):
    ACKNOWLEDGE = "acknowledge"
    PROMISE = "promise"
    DISPUTE = "dispute"


class PromiseStatus(str, Enum):
    OPEN = "open"
    KEPT = "kept"
    MISSED = "missed"
    SUPERSEDED = "superseded"


class DisputeReasonType(str, Enum):
    WRONG_AMOUNT = "wrong_amount"
    GOODS_NOT_RECEIVED = "goods_not_received"
    ALREADY_PAID = "already_paid"
    OTHER = "other"


class ReminderKind(str, Enum):
    NEW_CREDIT = "new_credit"
    UPCOMING = "upcoming"
    DUE_TODAY = "due_today"
    OVERDUE_1 = "overdue_1"
    OVERDUE_FOLLOWUP = "overdue_followup"
    MANUAL = "manual"


class ReminderStatus(str, Enum):
    SCHEDULED = "scheduled"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class EventActor(str, Enum):
    CREDITOR = "creditor"
    DEBTOR = "debtor"
    SYSTEM = "system"


def pg_values(enum_cls: Type[Enum]) -> list[str]:
    return [member.value for member in enum_cls]
