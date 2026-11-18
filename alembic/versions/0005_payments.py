from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0005_payments"
down_revision = "0004_credit_transactions"
branch_labels = None
depends_on = None


STATUS_VALUES = ("initiated", "pending", "successful", "failed", "reversed")


def upgrade() -> None:
    op.execute("CREATE TYPE payment_status AS ENUM ('initiated','pending','successful','failed','reversed')")
    op.execute("CREATE SEQUENCE payment_receipt_seq START 1 INCREMENT 1")
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "transaction_id",
            sa.Uuid(),
            sa.ForeignKey("credit_transactions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kora_reference", sa.String(80), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("amount_kobo", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*STATUS_VALUES, name="payment_status", create_type=False),
            server_default="initiated",
            nullable=False,
        ),
        sa.Column("checkout_url", sa.Text(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("receipt_number", sa.String(20), nullable=True),
        sa.Column("raw_webhook", JSONB(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("overpaid_kobo", sa.BigInteger(), nullable=True),
        sa.Column("review_reason", sa.String(32), nullable=True),
        sa.Column("provider_mode", sa.String(8), server_default=sa.text("'sandbox'"), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("kora_reference", name="uq_pay_kora_reference"),
        sa.UniqueConstraint("receipt_number", name="uq_pay_receipt_number"),
        sa.UniqueConstraint("transaction_id", "attempt_number", name="uq_pay_attempt"),
        sa.CheckConstraint("amount_kobo > 0", name="ck_pay_amount"),
        sa.CheckConstraint(
            "status <> 'successful' OR "
            "(paid_at IS NOT NULL AND receipt_number IS NOT NULL AND verified_at IS NOT NULL)",
            name="ck_pay_success_fields",
        ),
        sa.CheckConstraint("overpaid_kobo IS NULL OR overpaid_kobo >= 0", name="ck_pay_overpaid"),
        sa.CheckConstraint(
            "review_reason IS NULL OR review_reason IN ('overpaid','paid_cancelled_transaction')",
            name="ck_pay_review_reason",
        ),
        sa.CheckConstraint("provider_mode IN ('sandbox','live')", name="ck_pay_provider_mode"),
    )
    op.create_index("ix_pay_transaction", "payments", ["transaction_id", "status"])
    op.create_index(
        "ix_pay_received",
        "payments",
        ["transaction_id", sa.text("paid_at DESC")],
        postgresql_where=sa.text("status = 'successful'"),
    )
    op.create_index(
        "ix_pay_stale",
        "payments",
        ["created_at"],
        postgresql_where=sa.text("status IN ('initiated','pending')"),
    )
    op.create_index(
        "uq_pay_idempotency",
        "payments",
        ["transaction_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "ix_pay_review",
        "payments",
        [sa.text("created_at DESC")],
        postgresql_where=sa.text("review_reason IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_pay_review", table_name="payments")
    op.drop_index("uq_pay_idempotency", table_name="payments")
    op.drop_index("ix_pay_stale", table_name="payments")
    op.drop_index("ix_pay_received", table_name="payments")
    op.drop_index("ix_pay_transaction", table_name="payments")
    op.drop_table("payments")
    op.execute("DROP SEQUENCE payment_receipt_seq")
    op.execute("DROP TYPE payment_status")
