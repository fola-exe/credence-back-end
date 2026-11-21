from alembic import op
import sqlalchemy as sa

revision = "0010_payment_attempt_count"
down_revision = "0009_kora_webhook_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("payments", "attempt_count")
