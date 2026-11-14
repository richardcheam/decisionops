"""Durable model-free specialist calls; existing business runtime stays separate."""
from alembic import op

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def _replace_job_action_check(actions):
    # Older migrations used an anonymous combined action/status/claims check.
    # Find only checks bound to the action column on the current schema's table.
    op.execute("""DO $$
    DECLARE checks text[]; action_column smallint;
    BEGIN
      SELECT attnum INTO STRICT action_column FROM pg_attribute
        WHERE attrelid='commerce_adaptive_jobs'::regclass AND attname='action' AND NOT attisdropped;
      SELECT array_agg(conname) INTO checks FROM pg_constraint
        WHERE conrelid='commerce_adaptive_jobs'::regclass AND contype='c'
          AND action_column=ANY(conkey)
          AND pg_get_constraintdef(oid) LIKE '%adaptive_investigate/v1%';
      IF coalesce(array_length(checks,1),0) != 1 THEN
        RAISE EXCEPTION 'Expected exactly one adaptive job action check';
      END IF;
      EXECUTE format('ALTER TABLE commerce_adaptive_jobs DROP CONSTRAINT %I',checks[1]);
    END $$""")
    op.create_check_constraint(
        'ck_adaptive_jobs_action', 'commerce_adaptive_jobs',
        "action IN (" + actions + ") AND status IN ('queued','running','completed','cancelled','failed') AND claims BETWEEN 0 AND 16")


def upgrade():
    _replace_job_action_check("'adaptive_investigate/v1','multi_agent_investigate/v1'")
    op.execute("""CREATE TABLE commerce_specialist_calls (
      id VARCHAR PRIMARY KEY, run_id VARCHAR NOT NULL REFERENCES commerce_adaptive_runs(id),
      specialist VARCHAR NOT NULL, ordinal INTEGER NOT NULL,
      created_token VARCHAR NOT NULL, dispatch_token VARCHAR,
      generation INTEGER NOT NULL, case_revision BIGINT NOT NULL,
      request JSONB NOT NULL, request_hash VARCHAR(64) NOT NULL,
      state VARCHAR NOT NULL, dispatch_count INTEGER NOT NULL DEFAULT 0,
      decision JSONB, tool VARCHAR, tool_state VARCHAR NOT NULL DEFAULT 'none',
      observation JSONB, disposition VARCHAR NOT NULL DEFAULT 'pending',
      deadline TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ NOT NULL,
      elapsed_ms INTEGER, error VARCHAR, UNIQUE(run_id,specialist,ordinal),
      CHECK(specialist IN ('order','shipment') AND ordinal BETWEEN 1 AND 4),
      CHECK(generation > 0 AND case_revision >= 0 AND request_hash ~ '^[0-9a-f]{64}$'),
      CHECK(state IN ('reserved','dispatching','settled','uncertain') AND dispatch_count BETWEEN 0 AND 1),
      CHECK(tool_state IN ('none','reserved','reading','completed','interrupted')),
      CHECK(disposition IN ('pending','applied','discarded')),
      CHECK(elapsed_ms IS NULL OR elapsed_ms >= 0),
      CHECK((dispatch_count=0 AND dispatch_token IS NULL AND state NOT IN ('dispatching','uncertain'))
        OR (dispatch_count=1 AND dispatch_token IS NOT NULL AND state!='reserved')))""")
    op.execute("""CREATE FUNCTION commerce_guard_specialist_call() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION 'Specialist history immutable'; END IF;
      IF ROW(NEW.id,NEW.run_id,NEW.specialist,NEW.ordinal,NEW.created_token,NEW.generation,
             NEW.case_revision,NEW.request,NEW.request_hash,NEW.deadline,NEW.created_at)
         IS DISTINCT FROM ROW(OLD.id,OLD.run_id,OLD.specialist,OLD.ordinal,OLD.created_token,OLD.generation,
             OLD.case_revision,OLD.request,OLD.request_hash,OLD.deadline,OLD.created_at)
        THEN RAISE EXCEPTION 'Specialist binding immutable'; END IF;
      IF NEW.dispatch_count < OLD.dispatch_count
         OR (OLD.dispatch_token IS NOT NULL AND NEW.dispatch_token IS DISTINCT FROM OLD.dispatch_token)
         OR (NEW.state IS DISTINCT FROM OLD.state AND NOT (
              (OLD.state='reserved' AND NEW.state IN ('dispatching','settled'))
              OR (OLD.state='dispatching' AND NEW.state IN ('settled','uncertain'))))
        THEN RAISE EXCEPTION 'Specialist dispatch cannot reset'; END IF;
      IF (OLD.decision IS NOT NULL AND NEW.decision IS DISTINCT FROM OLD.decision)
         OR (OLD.state IN ('settled','uncertain') AND NEW.decision IS DISTINCT FROM OLD.decision)
         OR (OLD.observation IS NOT NULL AND NEW.observation IS DISTINCT FROM OLD.observation)
         OR (OLD.tool IS NOT NULL AND NEW.tool IS DISTINCT FROM OLD.tool)
         OR (OLD.disposition!='pending' AND NEW.disposition IS DISTINCT FROM OLD.disposition)
        THEN RAISE EXCEPTION 'Specialist outcome immutable'; END IF;
      IF NEW.tool_state IS DISTINCT FROM OLD.tool_state AND NOT (
           (OLD.tool_state='none' AND NEW.tool_state='reserved')
           OR (OLD.tool_state='reserved' AND NEW.tool_state='reading')
           OR (OLD.tool_state='reading' AND NEW.tool_state IN ('completed','interrupted')))
        THEN RAISE EXCEPTION 'Specialist read cannot reset'; END IF;
      RETURN NEW;
    END $$""")
    op.execute('CREATE TRIGGER commerce_specialist_binding BEFORE UPDATE OR DELETE ON commerce_specialist_calls FOR EACH ROW EXECUTE FUNCTION commerce_guard_specialist_call()')


def downgrade():
    # Adding the old check first refuses downgrade if multi-agent jobs still exist.
    _replace_job_action_check("'adaptive_investigate/v1'")
    op.drop_table('commerce_specialist_calls')
    op.execute('DROP FUNCTION commerce_guard_specialist_call()')
