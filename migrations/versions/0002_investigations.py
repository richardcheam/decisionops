"""Append-only investigation snapshots and immutable proposal documents."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("commerce_investigations",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("order_id", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assessment", JSONB, nullable=False),
        sa.CheckConstraint("jsonb_typeof(assessment) = 'object'"))
    op.create_table("commerce_proposals",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("investigation_id", sa.String, sa.ForeignKey("commerce_investigations.id"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("document", JSONB, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("jsonb_typeof(document) = 'object' AND content_hash ~ '^[0-9a-f]{64}$'"))
    op.execute("""CREATE FUNCTION commerce_reject_audit_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'Commerce audit snapshots are immutable; create a new investigation';
        END; $$""")
    for table in ("commerce_investigations", "commerce_proposals"):
        op.execute(f"CREATE TRIGGER commerce_immutable BEFORE UPDATE OR DELETE ON {table} "
                   "FOR EACH ROW EXECUTE FUNCTION commerce_reject_audit_mutation()")


def downgrade():
    # Destructive audit removal, never an outage/recovery procedure.
    op.drop_table("commerce_proposals")
    op.drop_table("commerce_investigations")
    op.execute("DROP FUNCTION commerce_reject_audit_mutation()")
