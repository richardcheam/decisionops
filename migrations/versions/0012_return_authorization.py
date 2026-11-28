"""Fictional one-item return authorization and exact staff approval."""

from alembic import op

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE commerce_return_cases (
        id VARCHAR PRIMARY KEY, store_id VARCHAR NOT NULL,
        customer_id VARCHAR(128) NOT NULL, order_id VARCHAR NOT NULL,
        variant_id VARCHAR NOT NULL, conversation_id VARCHAR NOT NULL,
        status VARCHAR NOT NULL, reason VARCHAR NOT NULL, evidence JSONB NOT NULL,
        proposal_hash VARCHAR(64), approved_by VARCHAR(128), updated_at TIMESTAMPTZ NOT NULL,
        UNIQUE(order_id, variant_id),
        FOREIGN KEY(store_id, order_id) REFERENCES orders(store_id, id),
        FOREIGN KEY(customer_id, order_id) REFERENCES commerce_customer_orders(customer_id, order_id),
        FOREIGN KEY(conversation_id, customer_id) REFERENCES commerce_customer_conversations(id, customer_id),
        FOREIGN KEY(order_id, variant_id) REFERENCES order_lines(order_id, variant_id),
        CHECK (status IN ('requested', 'review', 'ineligible', 'proposed', 'approved', 'authorized')),
        CHECK (jsonb_typeof(evidence) = 'object'),
        CHECK ((status IN ('proposed', 'approved', 'authorized')) = (proposal_hash IS NOT NULL)),
        CHECK ((status IN ('approved', 'authorized')) = (approved_by IS NOT NULL))
    )""")
    op.execute("""CREATE TABLE commerce_return_authorizations (
        id VARCHAR PRIMARY KEY, case_id VARCHAR NOT NULL UNIQUE REFERENCES commerce_return_cases(id),
        proposal_hash VARCHAR(64) NOT NULL, quantity INTEGER NOT NULL CHECK (quantity = 1),
        confirmed_by VARCHAR(128) NOT NULL, created_at TIMESTAMPTZ NOT NULL
    )""")
    op.execute("""CREATE TRIGGER commerce_immutable BEFORE UPDATE OR DELETE
        ON commerce_return_authorizations FOR EACH ROW EXECUTE FUNCTION commerce_reject_audit_mutation()""")


def downgrade():
    op.drop_table('commerce_return_authorizations')
    op.drop_table('commerce_return_cases')
