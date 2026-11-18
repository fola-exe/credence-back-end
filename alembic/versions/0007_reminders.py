from alembic import op
import sqlalchemy as sa


revision = "0007_reminders"
down_revision = "0006_debtor_responses"
branch_labels = None
depends_on = None


KINDS = ("new_credit", "upcoming", "due_today", "overdue_1", "overdue_followup", "manual")
STATUSES = ("scheduled", "sent", "failed", "cancelled", "skipped")


def upgrade() -> None:
    op.execute(
        "CREATE TYPE reminder_kind AS ENUM "
        "('new_credit','upcoming','due_today','overdue_1','overdue_followup','manual')"
    )
    op.execute(
        "CREATE TYPE reminder_status AS ENUM "
        "('scheduled','sent','failed','cancelled','skipped')"
    )
    op.create_table(
        "reminders",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "transaction_id",
            sa.Uuid(),
            sa.ForeignKey("credit_transactions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum(*KINDS, name="reminder_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("channel", sa.String(16), server_default=sa.text("'email'"), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(*STATUSES, name="reminder_status", create_type=False),
            server_default="scheduled",
            nullable=False,
        ),
        sa.Column("skip_reason", sa.String(40), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.String(120), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("channel IN ('email')", name="ck_rem_channel"),
        sa.CheckConstraint("status <> 'sent' OR sent_at IS NOT NULL", name="ck_rem_sent_fields"),
        sa.CheckConstraint(
            "status <> 'skipped' OR skip_reason IS NOT NULL", name="ck_rem_skip_reason"
        ),
    )
    op.create_index(
        "ix_rem_due",
        "reminders",
        ["scheduled_for"],
        postgresql_where=sa.text("status = 'scheduled'"),
    )
    op.create_index("ix_rem_transaction", "reminders", ["transaction_id", "status", "scheduled_for"])


def downgrade() -> None:
    op.drop_index("ix_rem_transaction", table_name="reminders")
    op.drop_index("ix_rem_due", table_name="reminders")
    op.drop_table("reminders")
    op.execute("DROP TYPE reminder_status")
    op.execute("DROP TYPE reminder_kind")
