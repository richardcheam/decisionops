"""Cases, approved local execution and compensation quantity guards."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("orders", sa.Column("compensation_revision", sa.BigInteger, nullable=False, server_default="0"))
    op.create_check_constraint("ck_compensation_revision", "orders", "compensation_revision >= 0")
    op.create_table(
        "commerce_cases",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("order_id", sa.String, sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("request", JSONB, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("generation", sa.Integer, nullable=False),
        sa.Column("investigation_id", sa.String, sa.ForeignKey("commerce_investigations.id")),
        sa.Column("proposal_id", sa.String, sa.ForeignKey("commerce_proposals.id")),
        sa.Column("approval_id", sa.String),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "order_id"),
        sa.CheckConstraint("generation >= 0 AND status IN ('open','awaiting_review','needs_review','blocked','approved','rejected','escalated','executed')"),
        sa.CheckConstraint("status NOT IN ('awaiting_review','approved') OR proposal_id IS NOT NULL"),
        sa.CheckConstraint("status != 'approved' OR approval_id IS NOT NULL"),
    )
    op.create_table(
        "commerce_reviews",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("case_id", sa.String, sa.ForeignKey("commerce_cases.id"), nullable=False),
        sa.Column("generation", sa.Integer, nullable=False),
        sa.Column("proposal_id", sa.String, sa.ForeignKey("commerce_proposals.id"), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("decision", sa.String, nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
        sa.Column("operation_id", sa.String, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "generation"),
        sa.UniqueConstraint("id", "case_id"),
        sa.UniqueConstraint("id", "operation_id"),
        sa.CheckConstraint("generation > 0 AND decision IN ('approve','reject') AND content_hash ~ '^[0-9a-f]{64}$'"),
        sa.CheckConstraint("(decision = 'approve' AND operation_id IS NOT NULL) OR (decision = 'reject' AND operation_id IS NULL)"),
    )
    op.create_table(
        "commerce_case_events",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("sequence", sa.BigInteger, sa.Identity(), nullable=False, unique=True),
        sa.Column("case_id", sa.String, sa.ForeignKey("commerce_cases.id"), nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("details", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "commerce_operations",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("review_id", sa.String, nullable=False, unique=True),
        sa.Column("case_id", sa.String, nullable=False, unique=True),
        sa.Column("order_id", sa.String, nullable=False, unique=True),
        sa.Column("request", JSONB, nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "order_id"),
        sa.ForeignKeyConstraint(["review_id", "case_id"], ["commerce_reviews.id", "commerce_reviews.case_id"]),
        sa.ForeignKeyConstraint(["review_id", "id"], ["commerce_reviews.id", "commerce_reviews.operation_id"]),
        sa.ForeignKeyConstraint(["case_id", "order_id"], ["commerce_cases.id", "commerce_cases.order_id"]),
    )
    op.create_table(
        "commerce_replacement_orders",
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("operation_id", sa.String, sa.ForeignKey("commerce_operations.id"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("id", "operation_id"),
    )
    op.create_table(
        "commerce_replacement_lines",
        sa.Column("replacement_id", sa.String, nullable=False, primary_key=True),
        sa.Column("variant_id", sa.String, nullable=False, primary_key=True),
        sa.Column("operation_id", sa.String, nullable=False),
        sa.Column("order_id", sa.String, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("resolution_id", sa.String, sa.ForeignKey("resolutions.id"), nullable=False, unique=True),
        sa.UniqueConstraint("operation_id", "variant_id", "quantity"),
        sa.ForeignKeyConstraint(["replacement_id", "operation_id"], ["commerce_replacement_orders.id", "commerce_replacement_orders.operation_id"]),
        sa.ForeignKeyConstraint(["operation_id", "order_id"], ["commerce_operations.id", "commerce_operations.order_id"]),
        sa.ForeignKeyConstraint(["order_id", "variant_id"], ["order_lines.order_id", "order_lines.variant_id"]),
        sa.CheckConstraint("quantity BETWEEN 1 AND 1000"),
    )
    op.create_table(
        "commerce_reservations",
        sa.Column("operation_id", sa.String, primary_key=True),
        sa.Column("variant_id", sa.String, primary_key=True),
        sa.Column("store_id", sa.String, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.ForeignKeyConstraint(["operation_id", "variant_id", "quantity"], ["commerce_replacement_lines.operation_id", "commerce_replacement_lines.variant_id", "commerce_replacement_lines.quantity"]),
        sa.ForeignKeyConstraint(["store_id", "variant_id"], ["inventory.store_id", "inventory.variant_id"]),
        sa.CheckConstraint("quantity BETWEEN 1 AND 1000"),
    )

    op.create_foreign_key("fk_case_approval", "commerce_cases", "commerce_reviews", ["approval_id"], ["id"])
    op.add_column("resolutions", sa.Column("operation_id", sa.String))
    op.create_foreign_key("fk_resolution_operation", "resolutions", "commerce_operations", ["operation_id"], ["id"])
    op.create_unique_constraint("uq_resolution_operation_variant", "resolutions", ["operation_id", "variant_id"])
    op.create_check_constraint("ck_resolution_operation_kind", "resolutions", "operation_id IS NULL OR kind = 'replacement'")
    op.execute("""DO $$ BEGIN IF EXISTS (
        SELECT 1 FROM resolutions r JOIN order_lines l USING(order_id,variant_id)
        GROUP BY r.order_id,r.variant_id,l.quantity HAVING SUM(r.quantity)>l.quantity
    ) THEN RAISE EXCEPTION 'Existing compensation exceeds original quantity; review data before migrating';
    END IF; END $$""")
    op.execute("""CREATE FUNCTION commerce_guard_compensation() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE ordered_quantity integer; covered bigint;
    BEGIN
        UPDATE orders SET compensation_revision=compensation_revision+1 WHERE id=NEW.order_id;
        SELECT quantity INTO ordered_quantity FROM order_lines
          WHERE order_id=NEW.order_id AND variant_id=NEW.variant_id FOR UPDATE;
        SELECT COALESCE(SUM(quantity),0) INTO covered FROM resolutions
          WHERE order_id=NEW.order_id AND variant_id=NEW.variant_id;
        IF ordered_quantity IS NULL OR covered+NEW.quantity>ordered_quantity THEN
          RAISE EXCEPTION 'Compensation exceeds original order quantity';
        END IF;
        RETURN NEW;
    END $$""")
    op.execute("CREATE TRIGGER commerce_compensation_limit BEFORE INSERT ON resolutions FOR EACH ROW EXECUTE FUNCTION commerce_guard_compensation()")
    for table in ("commerce_reviews", "commerce_case_events", "commerce_operations",
                  "commerce_replacement_orders", "commerce_replacement_lines", "commerce_reservations",
                  "policy_versions", "resolutions"):
        op.execute(f"CREATE TRIGGER commerce_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION commerce_reject_audit_mutation()")
    op.execute("""CREATE FUNCTION commerce_guard_case_request() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
        IF NEW.request IS DISTINCT FROM OLD.request OR NEW.order_id IS DISTINCT FROM OLD.order_id THEN
            RAISE EXCEPTION 'Case request is immutable; open a new case';
        END IF; RETURN NEW; END $$""")
    op.execute("CREATE TRIGGER commerce_case_request BEFORE UPDATE ON commerce_cases FOR EACH ROW EXECUTE FUNCTION commerce_guard_case_request()")


def downgrade():
    op.execute("DROP TRIGGER commerce_compensation_limit ON resolutions")
    op.execute("DROP FUNCTION commerce_guard_compensation()")
    for table in ("policy_versions", "resolutions"):
        op.execute(f"DROP TRIGGER commerce_immutable ON {table}")
    op.drop_constraint("fk_resolution_operation", "resolutions", type_="foreignkey")
    op.drop_constraint("uq_resolution_operation_variant", "resolutions", type_="unique")
    op.drop_constraint("ck_resolution_operation_kind", "resolutions", type_="check")
    op.drop_column("resolutions", "operation_id")
    op.drop_constraint("fk_case_approval", "commerce_cases", type_="foreignkey")
    for table in ("commerce_reservations", "commerce_replacement_lines", "commerce_replacement_orders",
                  "commerce_operations", "commerce_case_events", "commerce_reviews", "commerce_cases"):
        op.drop_table(table)
    op.execute("DROP FUNCTION commerce_guard_case_request()")
    op.drop_constraint("ck_compensation_revision", "orders", type_="check")
    op.drop_column("orders", "compensation_revision")
