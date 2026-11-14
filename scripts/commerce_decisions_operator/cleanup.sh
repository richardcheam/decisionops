#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
umask 077
# Do not clean up while run-once.sh is still running.
.venv-decisions/bin/python scripts/commerce_decisions_operator/export_evidence.py
# Preserve a restoreable snapshot before deleting the disposable tmpfs database.
test ! -e "$EVIDENCE/fictional-database.sql"
sg docker -c 'docker exec decisionops-decisions-live pg_dump -U commerce_decisions -d commerce_decisions_test --no-owner --no-privileges' > "$EVIDENCE/fictional-database.sql"
test -s "$EVIDENCE/fictional-database.sql"
sg docker -c 'docker logs decisionops-decisions-live' > "$EVIDENCE/database.log" 2>&1
sg docker -c 'docker rm -f decisionops-decisions-live'
python3 - <<'PY'
from pathlib import Path
import hashlib,json
p=Path('runs/decisions-manual-evidence')
rows=[{'path':str(f.relative_to(p)),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in sorted(p.rglob('*')) if f.is_file() and f.name!='sha256-inventory.json']
(p/'sha256-inventory.json').write_text(json.dumps(rows,indent=2)+'\n')
PY
printf 'Evidence preserved in %s\n' "$EVIDENCE"
