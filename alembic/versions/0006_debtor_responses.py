from alembic import op
import sqlalchemy as sa


revision = "0006_debtor_responses"
down_revision = "0005_payments"
branch_labels = None
depends_on = None


RESPONSE_TYPES = ("acknowledge", "promise", "dispute")
PROMISE_STATUSES = ("open", "kept", "missed", "superseded")
DISPUTE_REASONS = ("wrong_amount", "goods_not_received", "already_paid", "other")


def upgrade() -> None:
    op.execute("CREATE TYPE debtor_response_type AS ENUM ('acknowledge','promise','dispute')")
    op.execute("CREATE TYPE promise_status AS ENUM ('open','kept','missed','superseded')")
    op.execute(
        "CREATE TYPE dispute_reason_type AS ENUM "
        "('wrong_amount','goods_not_received','already_paid','other')"
    )
    op.create_table(
        "debtor_responses",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "transaction_id",
            sa.Uuid(),
            sa.ForeignKey("credit_transactions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "type",
            sa.Enum(*RESPONSE_TYPES, name="debtor_response_type", create_type=False),
            nullable=False,
        ),
        sa.Column("promised_date", sa.Date(), nullable=True),
        sa.Column("promised_amount_kobo", sa.BigInteger(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "promise_status",
            sa.Enum(*PROMISE_STATUSES, name="promise_status", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "dispute_reason",
            sa.Enum(*DISPUTE_REASONS, name="dispute_reason_type", create_type=False),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "type <> 'promise' OR (promised_date IS NOT NULL AND promise_status IS NOT NULL)",
            name="ck_dr_promise_fields",
        ),
        sa.CheckConstraint(
            "promised_amount_kobo IS NULL OR promised_amount_kobo > 0",
            name="ck_dr_promise_amount",
        ),
        sa.CheckConstraint("type = 'promise' OR promise_status IS NULL", name="ck_dr_promise_status_scope"),
        sa.CheckConstraint(
            "type <> 'dispute' OR (dispute_reason IS NOT NULL AND message IS NOT NULL "
            "AND char_length(trim(message)) > 0)",
            name="ck_dr_dispute_fields",
        ),
        sa.CheckConstraint("type = 'dispute' OR dispute_reason IS NULL", name="ck_dr_dispute_reason_scope"),
    )
    op.create_index("ix_dr_transaction", "debtor_responses", ["transaction_id", sa.text("created_at DESC")])
    op.create_index("ix_dr_promise_outcome", "debtor_responses", ["type", "promise_status"])
    op.create_index(
        "uq_dr_one_open_promise",
        "debtor_responses",
        ["transaction_id"],
        unique=True,
        postgresql_where=sa.text("type = 'promise' AND promise_status = 'open'"),
    )
    op.create_index(
        "uq_dr_one_open_dispute",
        "debtor_responses",
        ["transaction_id"],
        unique=True,
        postgresql_where=sa.text("type = 'dispute' AND resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_dr_one_open_dispute", table_name="debtor_responses")
    op.drop_index("uq_dr_one_open_promise", table_name="debtor_responses")
    op.drop_index("ix_dr_promise_outcome", table_name="debtor_responses")
    op.drop_index("ix_dr_transaction", table_name="debtor_responses")
    op.drop_table("debtor_responses")
    op.execute("DROP TYPE dispute_reason_type")
    op.execute("DROP TYPE promise_status")
    op.execute("DROP TYPE debtor_response_type")
