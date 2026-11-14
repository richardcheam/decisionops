import os
from pathlib import Path
import json,hashlib
from decimal import Decimal
from datetime import datetime
from decisionops.commerce.proposals import document_hash
p=Path(os.environ.get('DECISIONOPS_EVIDENCE_ROOT','/home/richard/projects/decisionops-archive/2026-10-16-wrapup/worktrees/stage5-correction'))/'runs/api-verification/manual-nano-evidence';t=json.loads((p/'live/trace.json').read_text());d=json.loads((p/'durable-records.json').read_text());cfg=json.loads((p/'used-config.json').read_text());run=t['run']
assert all(hashlib.sha256((p/r['path']).read_bytes()).hexdigest()==r['sha256'] for r in json.loads((p/'sha256-inventory.json').read_text()))
assert document_hash(cfg)=='8349e81fc3b0805567aa71e5d3f540ac038623e6efec3735a052c9276a244a83'
assert len(d['commerce_adaptive_runs'])==1 and len(d['commerce_provider_budgets'])==1
assert not t['simulation'] and not t['execution_authorized']
assert run['state']=='review' and not d['commerce_proposals'] and not d['commerce_reviews'] and not d['commerce_operations'] and not d['commerce_reservations']
rows=[]
for c in t['decisions']:
 m=next(x for x in t['monetary_reservations'] if x['run_id']==c['id']);u=c['result']['metadata']['usage']
 # Adaptive requests add domain binding fields to the base recommendation record.
 assert all(c['request'][k]==v for k,v in m['request'].items())
 assert document_hash(m['request'])==m['request_hash'] and document_hash(c['request'])==c['request_hash']
 assert m['case_id']==run['case_id'] and datetime.fromisoformat(m['deadline'])==datetime.fromisoformat(c['deadline'])
 assert c['dispatch_count']==m['dispatch_count']==1 and c['state']==m['state']=='settled'
 assert c['result']['metadata']['simulated_transport'] is False
 cost=(Decimal(u['input_tokens'])*Decimal('0.05')+Decimal(u['output_tokens'])*Decimal('0.40'))/1000000
 assert cost==Decimal(m['actual_cost_usd'])
 rows.append({'choice':c['result']['action'],'input_tokens':u['input_tokens'],'output_tokens':u['output_tokens'],'cost_usd':str(cost),'sdk_elapsed_ms':c['result']['elapsed_ms'],'call_id':c['id']})
assert not [s for s in run['steps'] if s['data'].get('fallback')]
start=datetime.fromisoformat(run['created_at']);end=datetime.fromisoformat(run['steps'][-1]['created_at'])
summary={'run_id':run['id'],'case_id':run['case_id'],'status':'safe_early_review; negative proposal-completion result','config_hash':document_hash(cfg),'decisions':rows,'tool_reads':list(run['tool_counts']),'input_tokens':sum(x['input_tokens'] for x in rows),'output_tokens':sum(x['output_tokens'] for x in rows),'usage_based_cost_usd':str(sum((Decimal(x['cost_usd']) for x in rows),Decimal(0))),'historical_reservation_sum_usd':str(sum((Decimal(x['reserved_cost_usd']) for x in t['monetary_reservations']),Decimal(0))),'unresolved_reservations':0,'forced':0,'fallback':0,'uncertain':0,'retries':0,'full_run_seconds':(end-start).total_seconds(),'sdk_elapsed_seconds':sum(x['sdk_elapsed_ms'] for x in rows)/1000,'terminal':run['terminal'],'evidence_inventory_verified':True,'execution_attribution':'Richard reported running prepared terminal commands; retained live records corroborate one investigation. Agent performed offline evidence/hash/accounting review only.','cleanup':'Task-owned container absent; retained JSON/SQL snapshot and hash inventory present. No original-runtime operations.','audit_note':'Initial offline assertion assumed money/adaptive requests identical. They intentionally differ by enriched domain binding fields. Verified common base fields, both document hashes, case and deadline instead. No application behavior changed.'}
out=Path('runs/evidence-review');out.mkdir(parents=True,exist_ok=True)
(out/'nano-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
