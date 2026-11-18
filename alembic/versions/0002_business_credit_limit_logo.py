from alembic import op
import sqlalchemy as sa


revision = "0002_business_credit_limit_logo"
down_revision = "fe6a8d47a7b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("businesses", sa.Column("credit_limit_kobo", sa.BigInteger(), nullable=True))
    op.add_column("businesses", sa.Column("logo_url", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_businesses_credit_limit_positive",
        "businesses",
        "credit_limit_kobo IS NULL OR credit_limit_kobo > 0",
    )
    op.execute("ALTER TABLE businesses ALTER COLUMN id SET DEFAULT gen_random_uuid()")


def downgrade() -> None:
    op.execute("ALTER TABLE businesses ALTER COLUMN id DROP DEFAULT")
    op.drop_constraint("ck_businesses_credit_limit_positive", "businesses", type_="check")
    op.drop_column("businesses", "logo_url")
    op.drop_column("businesses", "credit_limit_kobo")
