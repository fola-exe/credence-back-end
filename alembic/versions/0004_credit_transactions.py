from alembic import op
import sqlalchemy as sa


revision = "0004_credit_transactions"
down_revision = "0003_debtors"
branch_labels = None
depends_on = None


STATUS_VALUES = ("pending_ack", "active", "partially_paid", "disputed", "settled", "cancelled")


def upgrade() -> None:
    op.execute(
        "CREATE TYPE credit_transaction_status AS ENUM "
        "('pending_ack','active','partially_paid','disputed','settled','cancelled')"
    )
    op.execute("CREATE SEQUENCE credit_transaction_reference_seq START 1 INCREMENT 1")
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "business_id",
            sa.Uuid(),
            sa.ForeignKey("businesses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "debtor_id",
            sa.Uuid(),
            sa.ForeignKey("debtors.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("reference", sa.String(20), nullable=False),
        sa.Column("invoice_number", sa.String(50), nullable=True),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("amount_kobo", sa.BigInteger(), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(*STATUS_VALUES, name="credit_transaction_status", create_type=False),
            server_default="pending_ack",
            nullable=False,
        ),
        sa.Column("public_token", sa.String(64), nullable=False),
        sa.Column("capacity_override", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_business_id",
            sa.Uuid(),
            sa.ForeignKey("businesses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("reference", name="uq_ct_reference"),
        sa.UniqueConstraint("public_token", name="uq_ct_public_token"),
        sa.CheckConstraint("amount_kobo > 0", name="ck_ct_amount"),
        sa.CheckConstraint("due_date >= issue_date", name="ck_ct_due_after_issue"),
        sa.CheckConstraint(
            "(capacity_override = false AND override_reason IS NULL) OR "
            "(capacity_override = true AND override_reason IS NOT NULL "
            "AND char_length(trim(override_reason)) > 0)",
            name="ck_ct_override_reason",
        ),
        sa.CheckConstraint(
            "(status = 'settled') = (settled_at IS NOT NULL)", name="ck_ct_settled_at"
        ),
    )
    op.create_index("ix_ct_business_status", "credit_transactions", ["business_id", "status"])
    op.create_index("ix_ct_business_due", "credit_transactions", ["business_id", "due_date"])
    op.create_index("ix_ct_debtor", "credit_transactions", ["debtor_id"])
    op.create_index(
        "ix_ct_business_created",
        "credit_transactions",
        ["business_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_ct_open_by_business",
        "credit_transactions",
        ["business_id"],
        postgresql_where=sa.text("status NOT IN ('settled','cancelled')"),
    )


def downgrade() -> None:
    op.drop_index("ix_ct_open_by_business", table_name="credit_transactions")
    op.drop_index("ix_ct_business_created", table_name="credit_transactions")
    op.drop_index("ix_ct_debtor", table_name="credit_transactions")
    op.drop_index("ix_ct_business_due", table_name="credit_transactions")
    op.drop_index("ix_ct_business_status", table_name="credit_transactions")
    op.drop_table("credit_transactions")
    op.execute("DROP SEQUENCE credit_transaction_reference_seq")
    op.execute("DROP TYPE credit_transaction_status")
