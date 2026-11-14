"""Read-only export; no SDK/provider invocation and no credential reads."""
import json
from pathlib import Path
from decisionops.commerce.database import database_engine
from decisionops.commerce import schema as db
p=Path('runs/decisions-manual-evidence')
engine=database_engine()
try:
    with engine.connect() as c,c.begin():
        c.exec_driver_sql('SET TRANSACTION READ ONLY')
        c.exec_driver_sql("SET LOCAL statement_timeout='10s'")
        assert tuple(c.exec_driver_sql('SELECT current_database(),current_user,inet_server_port()').one())==('commerce_decisions_test','commerce_decisions',5432)
        records={t.name:[dict(r) for r in c.execute(t.select()).mappings()] for t in db.metadata.sorted_tables}
    # This isolated store contains only the freshly seeded fictional records.
    (p/'durable-records.json').write_text(json.dumps(records,indent=2,default=str)+'\n')
finally:engine.dispose()
print('Durable fictional evidence exported; no API request')
