from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_kora_webhook_events"
down_revision = "0008_transaction_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kora_webhook_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("kora_reference", sa.String(length=80), nullable=False),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("signature_ok", sa.Boolean(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kora_reference", "event", name="uq_kwe_ref_event"),
    )
    op.create_index("ix_kwe_created", "kora_webhook_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_kwe_created", table_name="kora_webhook_events")
    op.drop_table("kora_webhook_events")
