"""Immutable simulated pricing/limits and restart-safe provider reservations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision='0005'
down_revision='0004'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table(
        'commerce_provider_budgets',
        sa.Column('id',sa.String(128),primary_key=True),
        sa.Column('limits',JSONB,nullable=False),sa.Column('pricing',JSONB,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
    )
    op.create_table(
        'commerce_provider_calls',
        sa.Column('run_id',sa.String(128),primary_key=True),
        sa.Column('case_id',sa.String,sa.ForeignKey('commerce_cases.id'),nullable=False),
        sa.Column('budget_id',sa.String(128),sa.ForeignKey('commerce_provider_budgets.id'),nullable=False),
        sa.Column('request',JSONB,nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('state',sa.String,nullable=False),
        sa.Column('reserved_cost_usd',sa.Numeric(20,8),nullable=False),
        sa.Column('actual_cost_usd',sa.Numeric(20,8)),
        sa.Column('dispatch_count',sa.Integer,nullable=False,server_default='0'),
        sa.Column('result',JSONB),sa.Column('effective_choice',sa.String),
        sa.Column('application_status',sa.String,nullable=False,server_default='pending'),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('deadline',sa.DateTime(timezone=True),nullable=False),
        sa.Column('finished_at',sa.DateTime(timezone=True)),
        sa.CheckConstraint("state IN ('reserved','dispatching','settled','uncertain','denied')"),
        sa.CheckConstraint("application_status IN ('pending','applied','fallback','stale')"),
        sa.CheckConstraint("effective_choice IS NULL OR effective_choice IN ('present_replacement','staff_review')"),
        sa.CheckConstraint('reserved_cost_usd >= 0 AND (actual_cost_usd IS NULL OR actual_cost_usd >= 0)'),
        sa.CheckConstraint('dispatch_count BETWEEN 0 AND 1'),
        sa.CheckConstraint("state != 'settled' OR (result IS NOT NULL AND actual_cost_usd IS NOT NULL)"),
        sa.CheckConstraint("state != 'uncertain' OR actual_cost_usd IS NULL"),
        sa.CheckConstraint("state != 'denied' OR (dispatch_count=0 AND reserved_cost_usd=0)"),
    )
    op.execute('CREATE TRIGGER commerce_immutable BEFORE UPDATE OR DELETE ON commerce_provider_budgets FOR EACH ROW EXECUTE FUNCTION commerce_reject_audit_mutation()')
    op.execute("""CREATE FUNCTION commerce_guard_provider_request() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Provider ledger cannot be deleted'; END IF;
      IF NEW.run_id IS DISTINCT FROM OLD.run_id OR NEW.case_id IS DISTINCT FROM OLD.case_id
         OR NEW.budget_id IS DISTINCT FROM OLD.budget_id OR NEW.request IS DISTINCT FROM OLD.request
         OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
         OR NEW.reserved_cost_usd IS DISTINCT FROM OLD.reserved_cost_usd
         OR NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.deadline IS DISTINCT FROM OLD.deadline
      THEN RAISE EXCEPTION 'Provider request/reservation binding is immutable'; END IF;
      RETURN NEW;
    END $$""")
    op.execute('CREATE TRIGGER commerce_provider_binding BEFORE UPDATE OR DELETE ON commerce_provider_calls FOR EACH ROW EXECUTE FUNCTION commerce_guard_provider_request()')


def downgrade():
    op.drop_table('commerce_provider_calls')
    op.execute('DROP FUNCTION commerce_guard_provider_request()')
    op.drop_table('commerce_provider_budgets')
