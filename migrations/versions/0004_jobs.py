"""Durable job ownership, bounded retries and fencing leases."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision="0004"
down_revision="0003"
branch_labels=None
depends_on=None


def upgrade():
    op.create_table(
        "commerce_jobs",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("case_id", sa.String, sa.ForeignKey("commerce_cases.id"), nullable=False),
        sa.Column("action", sa.String, nullable=False),
        sa.Column("operation_id", sa.String),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("token", sa.String),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("outcome", JSONB),
        sa.Column("error_kind", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('investigate','execute') AND status IN ('queued','running','completed','failed') AND attempts BETWEEN 0 AND 3"),
        sa.CheckConstraint("(action='investigate' AND operation_id IS NULL) OR (action='execute' AND operation_id IS NOT NULL)"),
        sa.CheckConstraint("status != 'running' OR (token IS NOT NULL AND lease_until IS NOT NULL)"),
        sa.CheckConstraint("status != 'completed' OR outcome IS NOT NULL"),
    )
    op.create_index("uq_commerce_inflight_case","commerce_jobs",["case_id"],unique=True,
                    postgresql_where=sa.text("status IN ('queued','running')"))


def downgrade():
    op.drop_table("commerce_jobs")
