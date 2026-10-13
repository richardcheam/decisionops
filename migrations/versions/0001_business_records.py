"""Initial frozen business record schema."""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("policy_versions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("store_id", sa.String, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("allow_confirmed_loss", sa.Boolean, nullable=False),
        sa.Column("max_units", sa.Integer, nullable=False),
        sa.Column("carrier_max_age_seconds", sa.Integer, nullable=False),
        sa.UniqueConstraint("store_id", "id"), sa.UniqueConstraint("store_id", "version"),
        sa.CheckConstraint("version > 0 AND max_units BETWEEN 1 AND 1000 AND carrier_max_age_seconds > 0"))
    op.create_table("orders",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("store_id", sa.String, nullable=False),
        sa.Column("policy_id", sa.String, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("resolution_history_complete", sa.Boolean, nullable=False),
        sa.ForeignKeyConstraint(["store_id", "policy_id"], ["policy_versions.store_id", "policy_versions.id"]),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'"))
    op.create_table("order_lines",
        sa.Column("order_id", sa.String, sa.ForeignKey("orders.id"), primary_key=True),
        sa.Column("variant_id", sa.String, primary_key=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("unit_price_minor", sa.BigInteger, nullable=False),
        sa.CheckConstraint("quantity BETWEEN 1 AND 1000 AND unit_price_minor >= 0"))
    op.create_table("payments",
        sa.Column("order_id", sa.String, sa.ForeignKey("orders.id"), primary_key=True),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.CheckConstraint("status IN ('paid', 'pending', 'failed') AND amount_minor >= 0"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'"))
    op.create_table("shipments",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("order_id", sa.String, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("fulfilment_status", sa.String, nullable=False),
        sa.Column("carrier_status", sa.String, nullable=False),
        sa.Column("carrier_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "order_id"),
        sa.CheckConstraint("fulfilment_status IN ('shipped', 'prepared')"),
        sa.CheckConstraint("carrier_status IN ('lost', 'in_transit', 'delivered', 'unknown')"))
    op.create_table("shipment_lines",
        sa.Column("shipment_id", sa.String, primary_key=True),
        sa.Column("order_id", sa.String, nullable=False),
        sa.Column("variant_id", sa.String, primary_key=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(["shipment_id", "order_id"], ["shipments.id", "shipments.order_id"]),
        sa.ForeignKeyConstraint(["order_id", "variant_id"], ["order_lines.order_id", "order_lines.variant_id"]),
        sa.CheckConstraint("quantity BETWEEN 1 AND 1000"))
    op.create_table("inventory",
        sa.Column("store_id", sa.String, primary_key=True),
        sa.Column("variant_id", sa.String, primary_key=True),
        sa.Column("on_hand", sa.Integer, nullable=False),
        sa.Column("reserved", sa.Integer, nullable=False),
        sa.CheckConstraint("on_hand >= 0 AND reserved >= 0 AND reserved <= on_hand"))
    op.create_table("resolutions",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("order_id", sa.String, nullable=False),
        sa.Column("variant_id", sa.String, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.ForeignKeyConstraint(["order_id", "variant_id"], ["order_lines.order_id", "order_lines.variant_id"]),
        sa.CheckConstraint("quantity BETWEEN 1 AND 1000 AND kind IN ('refund', 'replacement')"))
    op.create_table("seed_versions", sa.Column("id", sa.String, primary_key=True))


def downgrade():
    for name in ("seed_versions", "resolutions", "inventory", "shipment_lines",
                 "shipments", "payments", "order_lines", "orders", "policy_versions"):
        op.drop_table(name)
