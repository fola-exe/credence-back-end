from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0008_transaction_events"
down_revision = "0007_reminders"
branch_labels = None
depends_on = None


EVENT_TYPES = (
    "transaction_created",
    "reminder_sent",
    "reminder_failed",
    "debtor_acknowledged",
    "promise_made",
    "promise_kept",
    "promise_missed",
    "payment_received",
    "payment_failed",
    "dispute_raised",
    "dispute_resolved",
    "note_added",
    "settled",
    "cancelled",
)


def upgrade() -> None:
    op.execute("CREATE TYPE event_actor AS ENUM ('creditor','debtor','system')")
    op.create_table(
        "transaction_events",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "transaction_id",
            sa.Uuid(),
            sa.ForeignKey("credit_transactions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("type", sa.String(48), nullable=False),
        sa.Column(
            "actor",
            sa.Enum("creditor", "debtor", "system", name="event_actor", create_type=False),
            nullable=False,
        ),
        sa.Column("data", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "type IN (" + ",".join("'%s'" % value for value in EVENT_TYPES) + ")",
            name="ck_te_type",
        ),
    )
    op.create_index(
        "ix_te_transaction",
        "transaction_events",
        ["transaction_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_te_transaction", table_name="transaction_events")
    op.drop_table("transaction_events")
    op.execute("DROP TYPE event_actor")
