"""Frozen Stage 5 integration on owned schemas only; models strictly opt-in."""
import argparse,contextlib,hashlib,json,os,signal,sys,threading,time,uuid
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from alembic import command
from alembic.config import Config as MigrationConfig
from decisionops.commerce import schema as db,adaptive_jobs as jobs,adaptive_sessions as sessions,adaptive_investigations as service,adaptive_tools as tools,adaptive_accounting as ledger
from decisionops.commerce.adaptive_runner import tick
from decisionops.commerce.adaptive_evaluation import load_manifest,judge,exact_key,state_key,admit_baselines,experiment_deadline
from decisionops.commerce.session_protocol import Config
from decisionops.commerce.database import database_engine
from decisionops.commerce.seed import seed
from decisionops.commerce.cases import open_case,escalate_case
from decisionops.commerce.read_tools import AssessmentRequest

def dump(p,value):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,indent=2,default=str)+'\n')
def memory():
    return int(next(l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:')))//1024

def execute(admin,url,scenario,mode,directory,anchor,limit_end):
    if mode not in ('fixed','cue','fake'):raise ValueError('Native work remains blocked pending supervisor review of the Stage 5 correctness correction')
    name='stage5_'+uuid.uuid4().hex;directory.mkdir(parents=True,exist_ok=False)
    with admin.begin() as c:c.exec_driver_sql('CREATE SCHEMA "'+name+'"')
    engine=database_engine(url.update_query_dict({'options':'-csearch_path='+name}));stop=threading.Event();monitor_done=threading.Event();peak=0;minimum=memory();reason=None;started=time.monotonic();adapter=None
    try:
        cfg=MigrationConfig(str(ROOT/'alembic.ini'))
        with engine.begin() as c:cfg.attributes['connection']=c;command.upgrade(cfg,'head')
        seed(engine,observed_at=anchor)
        with engine.begin() as c:
            for sql in scenario['setup']:c.exec_driver_sql(sql)
            case=open_case(c,AssessmentRequest(**scenario['request']))
        with engine.connect() as c:
            records={table.name:[dict(r) for r in c.execute(sa.select(table)).mappings()] for table in (db.orders,db.order_lines,db.payments,db.shipments,db.shipment_lines,db.inventory,db.resolutions,db.policies)}
        dump(directory/'fictional-records.json',records)
        session=Config(mode,'fake-v1' if mode=='fake' else pins()[mode]).record() if mode in ('fake','laya','gliclass') else None
        job=jobs.enqueue(engine,case['id'],scenario['report'],policy='cue' if mode=='cue' else 'fixed',session=session)
        owned=jobs.claim(engine,job_id=job['id']);fence=jobs.Fence(owned['id'],owned['token'])
        original=tools.projected_rows;failed=False;queries=[];injected=False
        def projected(c,table,columns,condition):
            nonlocal failed
            queries.append({'table':table.name,'columns':list(columns)})
            if scenario['fault']=='payment_unavailable_once' and table.name=='payments' and not failed:
                failed=True;raise SQLAlchemyError('Stage 5 deterministic unavailable payment read')
            result=original(c,table,columns,condition)
            if scenario['fault']=='conflicting_payment_projection' and table.name=='payments' and result:return result+[{**result[0],'status':'failed'}]
            if scenario['fault']=='missing_policy_projection' and table.name=='policy_versions':return []
            return result
        def monitor():
            nonlocal peak,minimum,reason
            while not monitor_done.wait(.05):
                if mode not in ('laya','gliclass'):continue
                available=memory();minimum=min(minimum,available)
                if time.monotonic()>=limit_end:reason='experiment_or_family_deadline'
                if available<512:reason='host_memory_floor'
                child=adapter.child if adapter else None
                if child and child.process:
                    try:
                        lines=Path('/proc/'+str(child.process.pid)+'/status').read_text().splitlines()
                        rss=int(next(l.split()[1] for l in lines if l.startswith('VmRSS:')));peak=max(peak,rss)
                        if rss>({'laya':3072,'gliclass':1024}[mode]*1024):reason='child_rss_cap'
                    except (OSError,StopIteration):pass
                if reason:stop.set();return
        thread=threading.Thread(target=monitor,daemon=True);thread.start()
        with patch.object(tools,'projected_rows',side_effect=projected),sessions.scope(engine,fence,stop) as current:
            adapter=current;outcome=None
            for _ in range(36):
                state=service.inspect(engine,job['run_id'])
                if state['state']!='active':break
                if scenario['fault']=='staff_escalate_before_publication' and state['assessment']['decision']['status']=='eligible_to_propose' and not injected:
                    with engine.begin() as c:escalate_case(c,case['id'],'Independent staff escalation')
                    service.advance(engine,job['run_id'],{'kind':'request_review','reason':'manual_review'},expected_context=state['context_version'],fence=fence);injected=True;continue
                outcome=tick(engine,fence,adapter=adapter,cancel=stop)
                if outcome.get('event') in ('uncertain_decision','uncertain_session','worker_stopped','session_requires_review'):break
            else:raise AssertionError('Runner did not stop within durable caps')
        monitor_done.set();thread.join(.2)
        state=service.inspect(engine,job['run_id'])
        with engine.connect() as c:
            calls=[dict(r) for r in c.execute(sa.select(db.adaptive_calls).where(db.adaptive_calls.c.run_id==job['run_id']).order_by(db.adaptive_calls.c.created_at)).mappings()]
            phases=sessions.records(c,job['run_id'])
            approvals=c.execute(sa.select(sa.func.count()).select_from(db.reviews)).scalar_one();operations=c.execute(sa.select(sa.func.count()).select_from(db.operations)).scalar_one()
            end_records={table.name:[dict(r) for r in c.execute(sa.select(table)).mappings()] for table in (db.orders,db.order_lines,db.payments,db.shipments,db.shipment_lines,db.inventory,db.resolutions,db.policies)}
        visibility=[]
        for call in calls:
            f=call['request']['features'];text=json.dumps(f)
            leaked=any(scenario['id']==v for v in f.values() if isinstance(v,str)) or scenario['request']['order_id'] in text or case['id'] in text or job['run_id'] in text
            visibility.append({'exact_hash':exact_key(f),'meaningful_hash':state_key(f),'features':f,'forbidden_binding_leak':leaked})
        attestation={'proposals':[],'investigations':[],'checks':[]}
        with engine.connect() as c:
            attestation['proposals']=[dict(r) for r in c.execute(sa.select(db.proposals)).mappings()]
            attestation['investigations']=[dict(r) for r in c.execute(sa.select(db.investigations)).mappings()]
            if state['state']=='proposed':
                from decisionops.commerce.investigations import recheck
                attestation['checks']=[recheck(c,state['terminal']['proposal_id'],datetime.now(timezone.utc))]
        dump(directory/'attestations.json',attestation)
        attested=bool(attestation['checks']) and all(c['status']=='valid_for_review' for c in attestation['checks'])
        verdict=judge(scenario,state,approvals=approvals,operations=operations,attestation_valid=attested)
        verdict['admissible']=verdict['admissible'] and records==end_records and not any(v['forbidden_binding_leak'] for v in visibility)
        selected=[s['data']['action']['tool'] for s in state['steps'] if s['kind']=='decision_reserved' and s['data']['action']['kind']=='read']
        result={**verdict,'scenario':scenario['id'],'mode':mode,'run_state':state['state'],'terminal':state['terminal'],'tools':selected,'declared_query_groups':{t:tools.PROJECTIONS[t] for t in set(selected)},'projection_queries_including_private_safety':queries,'mandatory_coverage':len(set(selected)),'retry_count':len(selected)-len(set(selected)),
            'forced_decisions':sum(len(c['request']['features']['allowed_actions'])==1 for c in calls),'inferred_decisions':sum(bool(c['result'] and (c['result'].get('metadata') or {}).get('inference_performed') and not (c['result'].get('metadata') or {}).get('simulated')) for c in calls),'simulated_decisions':sum(bool(c['result'] and (c['result'].get('metadata') or {}).get('inference_performed') and (c['result'].get('metadata') or {}).get('simulated')) for c in calls),'fallbacks':sum(c['request']['configuration'].get('source')=='rules' for c in calls),'rejections':sum(s['kind']=='choice_rejected' for s in state['steps']),'uncertain_calls':sum(c['state']=='uncertain' for c in calls),'duplicate_dispatches':sum(max(0,c['dispatch_count']-1) for c in calls),'wall_seconds':time.monotonic()-started,'peak_polled_rss_kib':peak,'minimum_host_available_mib':minimum,'stop_reason':reason,'simulated':mode=='fake','api_charge_usd':'0','input_truncation':'not instrumented in native library; inspect preserved stderr; no host-side feature truncation','business_records_unchanged':records==end_records,'last_outcome':outcome}
        for filename,value in [('run.json',state),('calls.json',calls),('sessions.json',phases),('policy-states.json',visibility),('result.json',result)]:dump(directory/filename,value)
        return result,visibility
    finally:
        monitor_done.set();engine.dispose()
        with admin.begin() as c:c.exec_driver_sql('DROP SCHEMA "'+name+'" CASCADE')

def pins():
    from decisionops.backends import parse_revision_pins,REPOSITORIES
    values=parse_revision_pins(ROOT/'model-revisions.env');return {f:values[REPOSITORIES[f][1]] for f in ('laya','gliclass')}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mode',choices=('baselines','pilot','comparison'),required=True);p.add_argument('--family',choices=('laya','gliclass'));p.add_argument('--baseline-summary',type=Path);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if args.mode!='baselines':p.error('Stage 5 native work requires supervisor review of the correctness correction; no model dispatch')
    if args.output.exists():p.error('Output exists; preserve previous evidence')
    manifest=load_manifest();url=make_url(os.environ['COMMERCE_TEST_DATABASE_URL'])
    if (url.host,url.port,url.database)!=('127.0.0.1',55441,'commerce_stage5_test'):p.error('Requires isolated Stage 5 loopback 55441 database')
    admin=database_engine(url)
    with admin.connect() as c:
        identity=tuple(c.exec_driver_sql('SELECT current_database(),current_user,inet_server_port()').one())
    if identity!=('commerce_stage5_test','commerce_stage5',5432):raise ValueError('Wrong isolated database identity')
    experiment_end=time.monotonic()+1200
    budget=None;ledger_path=args.output.parent/'stage5-model-budget.json'
    if args.mode!='baselines':
        if args.baseline_summary is None:p.error('Model work requires --baseline-summary')
        baseline=json.loads(args.baseline_summary.read_text());admit_baselines(baseline,manifest)
        expected_hash=hashlib.sha256((ROOT/'data/commerce/adaptive-evaluation-v1/manifest.json').read_bytes()).hexdigest()
        if baseline['manifest_sha256']!=expected_hash:raise ValueError('Baseline belongs to another frozen manifest')
        boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();now=time.monotonic()
        if ledger_path.exists():budget=json.loads(ledger_path.read_text())
        else:
            initial=now-max(0,time.time()-(args.baseline_summary.parent/'identity.json').stat().st_mtime)
            budget={'started':initial,'end':initial+1200,'boot':boot,'attempted':[],'family_started':{},'pilots':{}}
            ledger_path.parent.mkdir(parents=True,exist_ok=True)
            with ledger_path.open('x') as f:json.dump(budget,f,indent=2)
        experiment_end=experiment_deadline(budget,boot,now)
        marker=args.mode+':'+str(args.family)
        if marker in budget['attempted']:raise ValueError('This experiment attempt already exists; no automatic retry')
        if args.mode=='comparison' and budget['pilots'].get(args.family)!='passed':raise ValueError('Family requires a successful real compatibility pilot')
        budget['attempted'].append(marker);budget['family_started'].setdefault(args.family,now);dump(ledger_path,budget)
    args.output.mkdir(parents=True);dump(args.output/'identity.json',identity)
    anchor=datetime.now(timezone.utc);start=time.monotonic();results=[];states={};status='complete'
    modes=('fixed','cue','fake') if args.mode=='baselines' else (args.family,)
    if None in modes:p.error('Local model execution requires --family')
    try:
        for mode in modes:
            if mode in ('laya','gliclass') and memory()<manifest['limits']['preflight_available_mib'][mode]:
                results.append({'mode':mode,'status':'resource_unavailable_no_dispatch','available_mib':memory(),'required_available_mib':manifest['limits']['preflight_available_mib'][mode]});continue
            for scenario in manifest['scenarios'][:1] if args.mode=='pilot' else manifest['scenarios']:
                row,visible=execute(admin,url,scenario,mode,args.output/(mode+'-'+scenario['id']),anchor,min(experiment_end,budget['family_started'][mode]+600) if budget else start+1200);results.append(row)
                for s in visible:states.setdefault(s['meaningful_hash'],s)
                dump(args.output/'partial-results.json',results)
                if args.mode=='pilot' and (not row['inferred_decisions'] or row['fallbacks'] or row['uncertain_calls']):
                    status='compatibility_pilot_failed';break
                if not row['admissible']:
                    status='correctness_failure';raise AssertionError('Stop: inadmissible '+mode+'/'+scenario['id'])
                if row['stop_reason'] or args.mode=='pilot' and row['run_state'] not in ('proposed','review','blocker_reported'):
                    status='bounded_failure';break
        dump(args.output/'states.json',list(states.values()))
    except Exception:
        if status=='complete':status='execution_error'
        raise
    finally:
        if budget is not None:
            if args.mode=='pilot':budget['pilots'][args.family]='passed' if status=='complete' and results and results[-1].get('inferred_decisions',0)>0 else 'failed_or_unavailable'
            dump(ledger_path,budget)
        dump(args.output/'summary.json',{'mode':args.mode,'family':args.family,'status':status,'manifest_sha256':hashlib.sha256((ROOT/'data/commerce/adaptive-evaluation-v1/manifest.json').read_bytes()).hexdigest(),'results':results,'distinct_meaningful_policy_states':len(states),'wall_seconds':time.monotonic()-start,'agent_executed':True});admin.dispose()
    print(json.dumps({'status':status,'runs':len(results),'distinct_meaningful_states':len(states),'output':str(args.output)},indent=2))
    return int(status!='complete')
if __name__=='__main__':raise SystemExit(main())
