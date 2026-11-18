import re
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import DebtorExists, NotFound, ValidationFailed
from app.core.pagination import build_meta, normalize_pagination
from app.core.time import today_wat
from app.db.enums import (
    DebtorResponseType,
    PaymentStatus,
    PromiseStatus,
)
from app.models import CreditTransaction, Debtor, DebtorResponse, Payment
from app.modules.businesses.queries import debtor_outstanding
from app.modules.debtors.queries import debtor_flags_by_ids, debtor_money_by_ids
from app.modules.debtors.schemas import DebtorCreate, DebtorUpdate

PHONE_PATTERN = re.compile(r"^\+[1-9][0-9]{9,14}$")

NO_HISTORY_SCORE = {
    "value": None,
    "label": "No history yet",
    "category": "no_history",
}

NO_HISTORY_FACTS = {
    "value": None,
    "label": "No history yet",
    "category": "no_history",
    "facts": {
        "transactions_counted": 0,
        "paid_on_time": 0,
        "paid_late": 0,
        "avg_days_late": 0,
        "promises_kept": 0,
        "promises_missed": 0,
        "partial_payments": 0,
        "open_disputes": 0,
    },
    "note": "Based on verified payments and recorded promise outcomes.",
}


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_phone(value: str) -> str:
    candidate = re.sub(r"[\s\-()]", "", value)
    if candidate.startswith("+"):
        normalized = candidate
    elif candidate.startswith("234"):
        normalized = "+" + candidate
    elif candidate.startswith("0"):
        normalized = "+234" + candidate[1:]
    else:
        raise ValueError("phone must be a valid phone number")
    if not PHONE_PATTERN.fullmatch(normalized):
        raise ValueError("phone must be in E.164 format")
    return normalized


class DebtorService:
    @staticmethod
    def _normalize(values: dict) -> dict:
        result = dict(values)
        if "email" in result and result["email"] is not None:
            result["email"] = normalize_email(str(result["email"]))
        if "phone" in result and result["phone"] is not None:
            result["phone"] = normalize_phone(str(result["phone"]))
        if "name" in result and result["name"] is not None:
            result["name"] = result["name"].strip()
        if "contact_person" in result and result["contact_person"] is not None:
            result["contact_person"] = result["contact_person"].strip() or None
        if "address" in result and result["address"] is not None:
            result["address"] = result["address"].strip() or None
        return result

    @staticmethod
    def _existing_by_email(db: Session, business_id: UUID, email: str) -> Debtor | None:
        return db.execute(
            select(Debtor).where(
                Debtor.business_id == business_id,
                func.lower(Debtor.email) == email.lower(),
            )
        ).scalar_one_or_none()

    @staticmethod
    def _as_summary(
        debtor: Debtor,
        *,
        outstanding_kobo: int = 0,
        overdue_kobo: int = 0,
        open_disputes: int = 0,
        has_open_promise: bool = False,
    ) -> dict:
        return {
            "id": debtor.id,
            "name": debtor.name,
            "contact_person": debtor.contact_person,
            "email": debtor.email,
            "phone": debtor.phone,
            "credit_limit_kobo": debtor.credit_limit_kobo,
            "outstanding_kobo": outstanding_kobo,
            "overdue_kobo": overdue_kobo,
            "open_disputes": open_disputes,
            "has_open_promise": has_open_promise,
            "score": dict(NO_HISTORY_SCORE),
            "created_at": debtor.created_at,
        }

    @staticmethod
    def _raise_exists(existing: Debtor) -> None:
        raise DebtorExists(
            "A debtor with this email already exists for your business.",
            fields={"email": "Already in use."},
            extra={
                "existing_debtor": {
                    "id": str(existing.id),
                    "name": existing.name,
                    "email": existing.email,
                }
            },
        )

    @classmethod
    def create(cls, db: Session, business_id: UUID, payload: DebtorCreate) -> dict:
        values = cls._normalize(payload.model_dump(exclude_unset=True))
        try:
            normalize_phone(values["phone"])
        except ValueError as exc:
            raise ValidationFailed(
                "The request is invalid.", fields={"phone": str(exc)}
            ) from exc

        existing = cls._existing_by_email(db, business_id, values["email"])
        if existing is not None:
            cls._raise_exists(existing)

        debtor = Debtor(business_id=business_id, **values)
        db.add(debtor)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            existing = cls._existing_by_email(db, business_id, values["email"])
            if existing is not None:
                cls._raise_exists(existing)
            raise exc
        db.refresh(debtor)
        return cls._as_summary(debtor)

    @classmethod
    def resolve_or_create(
        cls,
        db: Session,
        business_id: UUID,
        debtor_id: UUID | None,
        new_debtor: DebtorCreate | None,
    ) -> Debtor:
        if debtor_id is not None:
            debtor = db.execute(
                select(Debtor).where(
                    Debtor.id == debtor_id, Debtor.business_id == business_id
                )
            ).scalar_one_or_none()
            if debtor is None:
                raise NotFound("Debtor not found")
            return debtor

        if new_debtor is None:
            raise ValidationFailed(
                "The request is invalid.",
                fields={"debtor_id": "Send debtor_id or new_debtor."},
            )

        values = cls._normalize(new_debtor.model_dump(exclude_unset=True))
        try:
            normalize_phone(values["phone"])
        except ValueError as exc:
            raise ValidationFailed(
                "The request is invalid.", fields={"phone": str(exc)}
            ) from exc

        existing = cls._existing_by_email(db, business_id, values["email"])
        if existing is not None:
            cls._raise_exists(existing)

        debtor = Debtor(business_id=business_id, **values)
        db.add(debtor)
        db.flush()
        return debtor

    @staticmethod
    def get_scoped(db: Session, business_id: UUID, debtor_id: UUID) -> Debtor:
        debtor = db.execute(
            select(Debtor).where(
                Debtor.id == debtor_id, Debtor.business_id == business_id
            )
        ).scalar_one_or_none()
        if debtor is None:
            raise NotFound("Debtor not found")
        return debtor

    @classmethod
    def update(
        cls, db: Session, business_id: UUID, debtor_id: UUID, payload: DebtorUpdate
    ) -> dict:
        debtor = cls.get_scoped(db, business_id, debtor_id)
        values = cls._normalize(payload.model_dump(exclude_unset=True))
        if "phone" in values:
            try:
                normalize_phone(values["phone"])
            except ValueError as exc:
                raise ValidationFailed(
                    "The request is invalid.", fields={"phone": str(exc)}
                ) from exc

        if "email" in values:
            existing = cls._existing_by_email(db, business_id, values["email"])
            if existing is not None and existing.id != debtor.id:
                cls._raise_exists(existing)

        for key, value in values.items():
            setattr(debtor, key, value)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise DebtorExists("A debtor with this email already exists for your business.") from exc
        db.refresh(debtor)
        outstanding = debtor_outstanding(db, business_id, debtor.id)
        return cls._as_summary(debtor, outstanding_kobo=outstanding)

    @classmethod
    def list(
        cls,
        db: Session,
        business_id: UUID,
        q: str | None,
        page: int | None,
        limit: int | None,
    ) -> dict:
        pagination = normalize_pagination(page, limit)
        filters = [Debtor.business_id == business_id]
        if q:
            pattern = f"%{q.lower()}%"
            filters.append(
                func.lower(Debtor.name).like(pattern)
                | func.lower(Debtor.email).like(pattern)
            )

        total = db.execute(
            select(func.count()).select_from(Debtor).where(*filters)
        ).scalar_one()
        debtors = db.execute(
            select(Debtor)
            .where(*filters)
            .order_by(func.lower(Debtor.name))
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).scalars().all()

        ids = [debtor.id for debtor in debtors]
        money = debtor_money_by_ids(db, business_id, ids, today_wat())
        flags = debtor_flags_by_ids(db, business_id, ids)
        data = [
            cls._as_summary(
                debtor,
                outstanding_kobo=money.get(debtor.id, {}).get("outstanding_kobo", 0),
                overdue_kobo=money.get(debtor.id, {}).get("overdue_kobo", 0),
                open_disputes=flags.get(debtor.id, {}).get("open_disputes", 0),
                has_open_promise=flags.get(debtor.id, {}).get("has_open_promise", False),
            )
            for debtor in debtors
        ]
        return {
            "data": data,
            "meta": build_meta(
                page=pagination.page, limit=pagination.limit, total=int(total)
            ),
        }

    @classmethod
    def get_profile(
        cls,
        db: Session,
        business_id: UUID,
        debtor_id: UUID,
        page: int | None = None,
        limit: int | None = None,
    ) -> dict:
        debtor = cls.get_scoped(db, business_id, debtor_id)
        outstanding = debtor_outstanding(db, business_id, debtor.id)
        money = debtor_money_by_ids(db, business_id, [debtor.id], today_wat()).get(
            debtor.id, {}
        )
        flags = debtor_flags_by_ids(db, business_id, [debtor.id]).get(debtor.id, {})
        pagination = normalize_pagination(page, limit)

        extended = db.execute(
            select(func.coalesce(func.sum(CreditTransaction.amount_kobo), 0)).where(
                CreditTransaction.business_id == business_id,
                CreditTransaction.debtor_id == debtor.id,
            )
        ).scalar_one()
        collected = db.execute(
            select(func.coalesce(func.sum(Payment.amount_kobo), 0))
            .join(CreditTransaction, Payment.transaction_id == CreditTransaction.id)
            .where(
                CreditTransaction.business_id == business_id,
                CreditTransaction.debtor_id == debtor.id,
                Payment.status == PaymentStatus.SUCCESSFUL,
            )
        ).scalar_one()

        open_promise = db.execute(
            select(DebtorResponse)
            .join(CreditTransaction, DebtorResponse.transaction_id == CreditTransaction.id)
            .where(
                CreditTransaction.business_id == business_id,
                CreditTransaction.debtor_id == debtor.id,
                DebtorResponse.type == DebtorResponseType.PROMISE,
                DebtorResponse.promise_status == PromiseStatus.OPEN,
            )
            .order_by(DebtorResponse.created_at.desc())
        ).scalars().first()

        tx_total = db.execute(
            select(func.count()).select_from(CreditTransaction).where(
                CreditTransaction.business_id == business_id,
                CreditTransaction.debtor_id == debtor.id,
            )
        ).scalar_one()
        transactions = db.execute(
            select(CreditTransaction)
            .where(
                CreditTransaction.business_id == business_id,
                CreditTransaction.debtor_id == debtor.id,
            )
            .order_by(CreditTransaction.created_at.desc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        ).scalars().all()
        payments = db.execute(
            select(Payment)
            .join(CreditTransaction, Payment.transaction_id == CreditTransaction.id)
            .where(
                CreditTransaction.business_id == business_id,
                CreditTransaction.debtor_id == debtor.id,
            )
            .order_by(Payment.created_at.desc())
            .limit(50)
        ).scalars().all()

        return {
            "debtor": {
                "id": debtor.id,
                "name": debtor.name,
                "contact_person": debtor.contact_person,
                "email": debtor.email,
                "phone": debtor.phone,
                "credit_limit_kobo": debtor.credit_limit_kobo,
                "address": debtor.address,
                "created_at": debtor.created_at,
            },
            "totals": {
                "outstanding_kobo": outstanding,
                "overdue_kobo": money.get("overdue_kobo", 0),
                "total_extended_kobo": int(extended or 0),
                "total_collected_kobo": int(collected or 0),
                "open_disputes": flags.get("open_disputes", 0),
                "open_promise": (
                    {
                        "promised_date": open_promise.promised_date,
                        "promised_amount_kobo": open_promise.promised_amount_kobo,
                    }
                    if open_promise
                    else None
                ),
            },
            "score": dict(NO_HISTORY_FACTS),
            "capacity": {
                "limit": debtor.credit_limit_kobo,
                "outstanding": outstanding,
                "available": (
                    debtor.credit_limit_kobo - outstanding
                    if debtor.credit_limit_kobo is not None
                    else None
                ),
            },
            "transactions": {
                "data": [
                    {
                        "id": tx.id,
                        "reference": tx.reference,
                        "description": tx.description,
                        "amount_kobo": tx.amount_kobo,
                        "due_date": tx.due_date,
                        "status": tx.status.value,
                        "created_at": tx.created_at,
                    }
                    for tx in transactions
                ],
                "meta": build_meta(
                    page=pagination.page,
                    limit=pagination.limit,
                    total=int(tx_total),
                ),
            },
            "payments": [
                {
                    "id": payment.id,
                    "amount_kobo": payment.amount_kobo,
                    "status": payment.status.value,
                    "paid_at": payment.paid_at,
                    "receipt_number": payment.receipt_number,
                    "created_at": payment.created_at,
                }
                for payment in payments
            ],
        }
