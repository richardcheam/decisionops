import os
"""Offline review of Richard's sole authorized Decisions investigation."""
from pathlib import Path
from decimal import Decimal
from datetime import datetime
import json,hashlib
from decisionops.commerce.proposals import document_hash
p=Path(os.environ.get('DECISIONOPS_EVIDENCE_ROOT','/home/richard/projects/decisionops-archive/2026-10-16-wrapup/worktrees/stage5-correction'))/'runs/decisions-manual-evidence';t=json.loads((p/'live/trace.json').read_text());d=json.loads((p/'durable-records.json').read_text());r=t['run'];cfg=json.loads((p/'used-config.json').read_text())
assert all(hashlib.sha256((p/x['path']).read_bytes()).hexdigest()==x['sha256'] for x in json.loads((p/'sha256-inventory.json').read_text()))
assert document_hash(cfg)=='b318cc81100b474bf1cad6815bd9ed8f39a064db9f1cdf55debff8eb2a54da09'
assert len(d['commerce_adaptive_runs'])==len(d['commerce_provider_budgets'])==1
assert not t['simulation'] and not t['execution_authorized']
assert r['state']=='review' and r['terminal']['unknowns']==['stock_available']
assert all(not d[name] for name in ('commerce_proposals','commerce_reviews','commerce_operations','commerce_reservations','commerce_replacement_orders','commerce_replacement_lines'))
rows=[]
for call in t['decisions']:
 money=next(m for m in t['monetary_reservations'] if m['run_id']==call['id'])
 assert call['state']==money['state']=='settled' and call['dispatch_count']==money['dispatch_count']==1
 assert call['application_status']==money['application_status']=='applied'
 assert document_hash(money['request'])==money['request_hash'] and document_hash(call['request'])==call['request_hash']
 assert all(call['request'][k]==v for k,v in money['request'].items())
 assert money['case_id']==r['case_id'] and datetime.fromisoformat(money['deadline'])==datetime.fromisoformat(call['deadline'])
 result=call['result'];meta=result['metadata'];native=meta['native_usage']
 assert meta['model']=='gpt-6-luna' and meta['endpoint']=='/v1/decisions' and meta['question']=='investigation_action'
 assert meta['simulated_transport'] is False and meta['inference_performed'] is True
 assert native['output_tokens']==native['output_tokens_details']['reasoning_tokens']==0
 assert native['total_tokens']==native['input_tokens']==meta['usage']['input_tokens']
 expected=Decimal(native['input_tokens'])*Decimal('0.10')/1000000
 assert Decimal(money['actual_cost_usd'])==expected
 actions=call['request']['features']['allowed_actions'];choice=meta['selected_choice'];mapping={f'c{i:03d}':a for i,a in enumerate(actions)}
 assert mapping[choice]==result['action']
 rows.append({'call_id':call['id'],'selected_choice':choice,'action':result['action'],'native_usage':native,'cost_usd':str(expected),'elapsed_ms':result['elapsed_ms'],'confidence':meta['confidence'],'probabilities':meta['probabilities'],'allowed_actions':actions})
assert not any(s['data'].get('fallback') for s in r['steps'])
assert rows[-1]['allowed_actions'][0]=={'kind':'read','tool':'inventory'}
summary={'attribution':'Richard reported executing the prepared SSH scripts. Agent reviewed retained files/hashes/accounting offline; no new API or database operations.','run_id':r['id'],'case_id':r['case_id'],'model':'gpt-6-luna','endpoint':'/v1/decisions','configuration_sha256':document_hash(cfg),'outcome':'safe early review; negative proposal-completion result','decisions':rows,'reads':list(r['tool_counts']),'requirements':r['assessment']['facts'],'terminal':r['terminal'],'native_input_tokens':sum(x['native_usage']['input_tokens'] for x in rows),'native_output_tokens':0,'native_reasoning_tokens':0,'usage_based_cost_usd':str(sum((Decimal(x['cost_usd']) for x in rows),Decimal(0))),'historical_reserved_sum_usd':str(sum((Decimal(m['reserved_cost_usd']) for m in t['monetary_reservations']),Decimal(0))),'uncertain_or_unresolved_reservations':0,'forced':0,'fallbacks':0,'retries':0,'run_wall_seconds':(datetime.fromisoformat(r['steps'][-1]['created_at'])-datetime.fromisoformat(r['created_at'])).total_seconds(),'sdk_elapsed_seconds':sum(x['elapsed_ms'] for x in rows)/1000,'file_inventory_verified':True,'single_run_and_budget_verified':True,'cleanup':'JSON and SQL export preserved; dedicated live container absent; original runtime untouched','limitations':['No proposal, approval or execution path exercised by this live run','Model internal rationale is not recorded','Cost estimate uses approved standard-global input rate, not invoice reconciliation','One run does not establish held-out quality, efficiency or business value','No further live investigation or retry authorized']}
out=Path('runs/evidence-review');out.mkdir(parents=True,exist_ok=True)
(out/'decisions-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print('Verified one run, seven settled inferred decisions, six reads, no proposal/approval/execution.')
print('Input/output/reasoning:',summary['native_input_tokens'],0,0,'USD:',summary['usage_based_cost_usd'])
print('Historical reserved sum:',summary['historical_reserved_sum_usd'],'SDK seconds:',summary['sdk_elapsed_seconds'],'run seconds:',summary['run_wall_seconds'])
print('Terminal:',r['terminal'])
