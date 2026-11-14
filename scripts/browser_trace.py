#!/usr/bin/env python3
"""Local-only allowlisted investigation trace. No SDK, exporter or network imports."""
import argparse
import hashlib
import html
import json
from datetime import datetime
from pathlib import Path

SAFE_ACTIONS={'open','observe','act','finish'}
SAFE_ERRORS={'navigation_failure','blocked_request','budget_exhausted','wrong_binding','invalid_citation','stale_reference','invalid_result'}
SAFE_STATES={'admitted','completed','stopped','reserved','dispatched','uncertain','settled','known_result_unknown_usage','usage_bound_breach','not_dispatched'}

def number(value):return value if type(value) in (int,float) and 0<=value<10**10 else None

def project(payload):
 ledger=payload.get('ledger',payload)
 result=payload.get('result',{})
 audit=payload.get('browser_audit',{}).get('audit',payload.get('audit',[]))
 calls=ledger.get('calls',[])
 decisions=[]
 for call in calls:
  usage=call.get('usage') or {}
  action=call.get('validated_action',{}).get('action')
  item={'ordinal':number(call.get('ordinal')),'status':call.get('state') if call.get('state') in SAFE_STATES else 'unknown',
        'action':action if action in SAFE_ACTIONS else 'unapplied',
        'latency_seconds':number(call.get('latency_seconds')),
        'reserved_usd':call.get('reserved_usd') if isinstance(call.get('reserved_usd'),str) and all(c in '0123456789.' for c in call['reserved_usd']) else None,
        'input_tokens':number(usage.get('input_tokens')),'output_tokens':number(usage.get('output_tokens')),
        'resources':'simulated' if usage.get('simulated') is True else 'recorded native usage'}
  outputs=call.get('response',{}).get('output',[])
  item['validation']='applied or validated' if action in SAFE_ACTIONS else 'ambiguous_response' if len(outputs)>1 else 'unapplied'
  decisions.append(item)
 events=[]
 for event in audit:
  kind=event.get('kind');data=event.get('data',{})
  if kind not in ('observation','request_allowed','request_denied','tool_error','finished'):continue
  item={'sequence':len(events)+1,'kind':kind}
  try:item['recorded_at']=datetime.fromisoformat(event.get('at','').replace('Z','+00:00')).isoformat()
  except (ValueError,TypeError,AttributeError):pass
  if kind=='observation':
   item.update(visible_bytes=len(str(data.get('text','')).encode()),content_sha256=hashlib.sha256(str(data.get('text','')).encode()).hexdigest(),control_count=len(data.get('controls',[])))
  if kind in ('tool_error','request_denied'):item['outcome']=data.get('kind') if data.get('kind') in SAFE_ERRORS else 'other_error'
  if kind=='finished':item['outcome']=data.get('result',{}).get('outcome') if data.get('result',{}).get('outcome') in ('evidence_found','missing_evidence','wrong_binding','tool_unavailable','blocked_request','budget_exhausted') else 'unknown'
  events.append(item)
 stop=ledger.get('stop_type')
 return {'contract':'local-redacted-browser-trace/v1','export_enabled':False,
         'state':ledger.get('state') if ledger.get('state') in SAFE_STATES else result.get('outcome') if result.get('outcome') in ('finished','operational_stop','invalid_finish','model_budget_exhausted') else 'unknown',
         'stop_reason':stop if stop in ('ValueError','RuntimeError','TimeoutError','KeyboardInterrupt') else None,
         'decisions':decisions,'events':events,'business_execution_authorized':False}

def render(value):
 rows=''.join('<tr>'+''.join('<td>'+html.escape(str(d.get(k)))+'</td>' for k in ('ordinal','action','validation','status','latency_seconds','reserved_usd','input_tokens','output_tokens','resources'))+'</tr>' for d in value['decisions'])
 events=''.join('<li>'+html.escape(json.dumps(e,sort_keys=True))+'</li>' for e in value['events'])
 return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Local investigation trace</title><style>body{font:16px system-ui;max-width:1100px;margin:3rem auto;padding:1rem;color:#1e293b}table{border-collapse:collapse;width:100%}td,th{padding:.6rem;border-bottom:1px solid #ddd;text-align:left}li{margin:1rem 0;overflow-wrap:anywhere}</style><h1>Local investigation trace</h1><p>Redacted local projection. Export disabled. Model choices do not authorise business execution. Simulated resources are not actual API usage or costs.</p><p>State: '''+html.escape(str(value['state']))+' · Stop: '+html.escape(str(value['stop_reason']))+'''</p><h2>Decisions and budget</h2><table><tr><th>#</th><th>Action</th><th>Validation</th><th>Status</th><th>Seconds</th><th>Reserved USD</th><th>Input</th><th>Output</th><th>Resource evidence</th></tr>'''+rows+'</table><h2>Browser events</h2><ol>'+events+'</ol><p>Raw evidence remains in the operator-controlled ignored runs directory; page content, order IDs, URLs, credentials, headers and provider error text are excluded here.</p></html>'

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);p.add_argument('--output',required=True,type=Path);args=p.parse_args()
 value=project(json.loads(args.input.read_text()));args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(render(value));print(args.output)

if __name__=='__main__':main()
