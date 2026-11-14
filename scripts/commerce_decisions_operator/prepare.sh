#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
# No credentials needed and no API client is created by preparation.
unset OPENAI_API_KEY
PYTHONPATH="$PWD" .venv-decisions/bin/python scripts/commerce_decisions_operator/verify_config.py
mkdir "$EVIDENCE"
umask 077
sg docker -c 'docker run -d --pull never --name decisionops-decisions-live --memory 512m --cpus 2 -e POSTGRES_DB=commerce_decisions_test -e POSTGRES_USER=commerce_decisions -e POSTGRES_PASSWORD=decisions-fictional-only -p 127.0.0.1:55446:5432 --tmpfs /var/lib/postgresql/data:rw,size=512m postgres@sha256:0ea6700a3b4f0ae6ce746519073558aed4d88a79d8d07622a9a644946c7319c4 -c shared_buffers=32MB -c max_wal_size=64MB -c min_wal_size=32MB' > "$EVIDENCE/container-id.txt"
ready=0
for i in {1..30}; do
  if sg docker -c 'docker exec decisionops-decisions-live pg_isready -U commerce_decisions -d commerce_decisions_test' > "$EVIDENCE/readiness.log" 2>&1; then ready=1; break; fi
  sleep 1
done
if [ "$ready" != 1 ]; then echo 'Database unavailable; stop. No paid command.'; exit 1; fi
.venv-decisions/bin/python - <<'PY'
from decisionops.commerce.database import database_engine
engine=database_engine()
with engine.connect() as c:
    assert tuple(c.exec_driver_sql('SELECT current_database(), current_user, inet_server_port()').one())==('commerce_decisions_test','commerce_decisions',5432)
engine.dispose()
print('Isolated database identity verified')
PY
.venv-decisions/bin/alembic upgrade head > "$EVIDENCE/migrations.log" 2>&1
.venv-decisions/bin/python -B -m decisionops.commerce.seed > "$EVIDENCE/seed.log" 2>&1
.venv-decisions/bin/python - <<'PY'
import json
from pathlib import Path
from decisionops.commerce.database import database_engine
from decisionops.commerce.cases import open_case
from decisionops.commerce.read_tools import AssessmentRequest
engine=database_engine()
with engine.connect().execution_options(isolation_level='READ COMMITTED') as c,c.begin():
    case=open_case(c,AssessmentRequest('ORD-1042','SHIP-1042',{'shirt-blue-M':1}))
p=Path('runs/decisions-manual-evidence')
(p/'case-id.txt').write_text(case['id']+'\n')
(p/'case-before.json').write_text(json.dumps(case,indent=2,default=str)+'\n')
engine.dispose()
print('One fictional case prepared; no investigation or paid call started')
PY
