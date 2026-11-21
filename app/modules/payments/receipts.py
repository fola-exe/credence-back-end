from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import NotFound, UnsupportedFormat
from app.core.money import format_naira
from app.core.time import format_datetime_wat, now_utc
from app.db.enums import PaymentStatus
from app.models import Business, CreditTransaction, Debtor, Payment
from app.modules.public.projection import initials
from app.modules.transactions.balance import balance_for

TEMPLATE_DIR = Path(__file__).parent / "templates"
environment = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


class ReceiptService:
    @staticmethod
    def for_transaction(
        db: Session, transaction_id, payment_id
    ) -> tuple[CreditTransaction, Payment]:
        payment = db.execute(
            select(Payment).where(
                Payment.id == payment_id,
                Payment.transaction_id == transaction_id,
                Payment.status == PaymentStatus.SUCCESSFUL,
            )
        ).scalars().first()
        transaction = db.get(CreditTransaction, transaction_id)
        if payment is None or transaction is None:
            raise NotFound("Receipt not found.")
        return transaction, payment

    @staticmethod
    def for_token(db: Session, token: str, receipt_number: str) -> Payment:
        transaction = db.execute(
            select(CreditTransaction).where(CreditTransaction.public_token == token)
        ).scalars().first()
        if transaction is None:
            raise NotFound("Receipt not found.")
        payment = db.execute(
            select(Payment).where(
                Payment.transaction_id == transaction.id,
                Payment.receipt_number == receipt_number,
                Payment.status == PaymentStatus.SUCCESSFUL,
            )
        ).scalars().first()
        if payment is None:
            raise NotFound("Receipt not found.")
        return payment

    @staticmethod
    def render(
        db: Session, payment: Payment, fmt: str = "html"
    ) -> tuple[bytes, str, str | None]:
        if fmt not in ("html", "pdf"):
            raise UnsupportedFormat()
        if fmt == "pdf" and not settings.receipt_pdf_enabled:
            raise UnsupportedFormat("PDF receipts are disabled.")
        transaction = db.get(CreditTransaction, payment.transaction_id)
        business = db.get(Business, transaction.business_id)
        debtor = db.get(Debtor, transaction.debtor_id)
        balance = balance_for(db, transaction)
        paid_at: datetime = payment.paid_at or payment.created_at
        context = {
            "business": business,
            "business_initials": initials(business.name),
            "debtor": debtor,
            "transaction": transaction,
            "payment": payment,
            "amount_paid": format_naira(payment.amount_kobo),
            "total_paid": format_naira(balance.paid_kobo),
            "outstanding": format_naira(balance.outstanding_kobo),
            "status_label": "SETTLED" if balance.outstanding_kobo == 0 else "Partially paid",
            "paid_at": format_datetime_wat(paid_at),
            "generated_at": format_datetime_wat(now_utc()),
            "format_naira": format_naira,
            "sandbox": payment.provider_mode == "sandbox",
            "balance_caption": "Balance shown as at the time this receipt was viewed.",
        }
        html = environment.get_template("receipt.html").render(**context)
        if fmt == "html":
            return html.encode("utf-8"), "text/html", None
        try:
            from weasyprint import HTML
        except ImportError as exc:
            raise UnsupportedFormat("PDF receipts are unavailable.") from exc
        pdf = HTML(string=html, base_url=str(TEMPLATE_DIR)).write_pdf()
        return pdf, "application/pdf", f"receipt-{payment.receipt_number}.pdf"
