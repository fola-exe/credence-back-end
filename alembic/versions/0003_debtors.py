from alembic import context, op
import sqlalchemy as sa


revision = "0003_debtors"
down_revision = "0002_business_credit_limit_logo"
branch_labels = None
depends_on = None


def _create_debtors_table() -> None:
    op.create_table(
        "debtors",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "business_id",
            sa.Uuid(),
            sa.ForeignKey("businesses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("contact_person", sa.String(120), nullable=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("credit_limit_kobo", sa.BigInteger(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("char_length(name) >= 2", name="ck_debtors_name_len"),
        sa.CheckConstraint(
            "credit_limit_kobo IS NULL OR credit_limit_kobo > 0",
            name="ck_debtors_credit_limit",
        ),
        sa.CheckConstraint(
            "phone ~ '^\\+[1-9][0-9]{9,14}$'", name="ck_debtors_phone_e164"
        ),
    )
    op.create_index(
        "uq_debtors_business_email",
        "debtors",
        ["business_id", sa.text("lower(email)")],
        unique=True,
    )
    op.create_index(
        "ix_debtors_business_name",
        "debtors",
        ["business_id", sa.text("lower(name)")],
    )


def upgrade() -> None:
    if not context.is_offline_mode():
        connection = op.get_bind()
        exists = connection.execute(
            sa.text("SELECT to_regclass('public.debtors')")
        ).scalar()
        if exists is not None:
            row_count = connection.execute(sa.text("SELECT count(*) FROM debtors")).scalar()
            if row_count:
                raise RuntimeError("debtors table has rows; manual migration required")
            op.drop_table("debtors")
    _create_debtors_table()


def downgrade() -> None:
    op.drop_index("ix_debtors_business_name", table_name="debtors")
    op.drop_index("uq_debtors_business_email", table_name="debtors")
    op.drop_table("debtors")
