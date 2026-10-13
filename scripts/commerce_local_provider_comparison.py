"""Small offline integration comparison; not a model-quality benchmark."""
import argparse
import itertools
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from decisionops.commerce.database import database_engine
from decisionops.commerce.seed import seed
from decisionops.commerce.eligibility import REQUIREMENTS
from decisionops.commerce.providers import permitted_choices


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Output exists; preserve previous results')
    url=os.environ.get('COMMERCE_TEST_DATABASE_URL')
    if not url:parser.error('Set COMMERCE_TEST_DATABASE_URL to a separate fictional database')
    schema='local_provider_'+uuid.uuid4().hex;admin=database_engine(url)
    engine=database_engine(make_url(url).update_query_dict({'options':'-csearch_path='+schema}))
    (ROOT/'runs').mkdir(exist_ok=True);directory=Path(tempfile.mkdtemp(prefix='local-provider-',dir=ROOT/'runs'))
    created=False;rows=[]
    try:
        with admin.begin() as c:c.exec_driver_sql(f'CREATE SCHEMA "{schema}"');created=True
        config=Config(str(ROOT/'alembic.ini'))
        with engine.begin() as c:config.attributes['connection']=c;command.upgrade(config,'head')
        seed(engine)
        env=dict(os.environ,COMMERCE_DATABASE_URL=engine.url.render_as_string(hide_password=False),
                 HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false')
        def cli(name,module,*arguments,expected=0):
            done=subprocess.run([sys.executable,'-B','-m','decisionops.commerce.'+module,*arguments],
                cwd=ROOT,env=env,text=True,capture_output=True,timeout=135)
            (directory/(name+'.json')).write_text(done.stdout);(directory/(name+'.stderr.log')).write_text(done.stderr)
            if done.returncode!=expected:raise RuntimeError(f'{name} exit {done.returncode}; inspect {directory}')
            return json.loads(done.stdout)
        cli('budget','provider_demo','budget-create','--budget','LOCAL-COMPARISON','--accounting','local','--max-requests','10','--max-cost-usd','0')
        for family in ('rules','gliclass','laya'):
            for name,order,reference in (('eligible','ORD-1042','present_replacement'),('history_unknown','ORD-HISTORY','staff_review')):
                case=cli(f'{family}-{name}-open','case_demo','open','--order',order,
                         '--shipment','SHIP-'+order.removeprefix('ORD-'),'--item','shirt-blue-M:1')
                arguments=['investigate','--mode',family,'--case',case['id'],'--run',family+'-'+name]
                if family!='rules':arguments+=['--budget','LOCAL-COMPARISON','--deadline-seconds','120']
                routed=cli(f'{family}-{name}-route','provider_demo',*arguments)
                trace=routed.get('trace');result=trace['result'] if trace else None
                effect=trace['effective_choice'] if trace else ('present_replacement' if routed['case']['status']=='awaiting_review' else 'staff_review')
                rows.append({'provider':family,'input':name,'reference_choice':reference,'choice':effect,
                    'reference_agreement':effect==reference,'case_status':routed['case']['status'],
                    'approval_present':routed['case']['approval'] is not None,
                    'dispatch_count':trace['dispatch_count'] if trace else 0,'result':result,
                    'ledger_state':trace['state'] if trace else None,
                    'actual_api_charge_usd':trace['actual_cost_usd'] if trace else '0'})
        budget=cli('budget-inspect','provider_demo','budget','--budget','LOCAL-COMPARISON')
        with engine.connect() as c:
            assert c.exec_driver_sql('SELECT count(*) FROM commerce_operations').scalar_one()==0
            assert c.exec_driver_sql("SELECT reserved FROM inventory WHERE variant_id='shirt-blue-M'").scalar_one()==1
        vectors=list(itertools.product((True,False,None),repeat=7))
        scored=sum(len(permitted_choices(dict(zip(REQUIREMENTS,v)),'awaiting_review' if all(x is True for x in v) else 'needs_review'))>1 for v in vectors)
        report={'kind':'offline_commerce_integration_comparison','evidence_level':'integration_and_reference_policy_agreement',
            'meaningful_scored_inputs':scored,'possible_tri_state_vectors':len(vectors),'forced_vectors':len(vectors)-scored,
            'measured_scored_inputs_per_model':1,'held_out_generalisation':False,'business_value_measured':False,
            'feature_policy':'Only task, normalized facts and allowed choices; no identifiers/hashes/evaluator labels',
            'no_api_charge':True,'tokens':'not reported; no invented usage','rows':rows,'budget':budget,
            'implementation_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ('decisionops/commerce/local_provider.py','decisionops/commerce/local_model_worker.py','decisionops/backends.py','decisionops/commerce/provider_service.py','decisionops/commerce/providers.py')},
            'git_head_at_measurement':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'working_tree_modified':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
            'proof':'zero operations, stock reservation unchanged, no approval created',
            'trace_directory':str(directory.relative_to(ROOT)),'limitations':[
                'All true evidence yields exactly one distinct scored input; repeats are not independent quality samples.',
                'One unknown-history state demonstrates forced review without inference.',
                'Native input formats differ; this does not isolate model architecture.',
                'Scores/confidence are uncalibrated; action heads never authorize execution.',
                'Load includes imports, model/tokenizer loading; wall includes worker startup and cleanup.',
                'RSS is child-process peak in KiB, not total system memory or incremental model memory.',
                'Measured reference-policy disagreement is retained; no prompt tuning on these outputs.']}
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
        print(json.dumps({'report':str(args.output),'rows':[{k:r[k] for k in ('provider','input','choice','case_status','reference_agreement')} for r in rows],'meaningful_scored_inputs':scored,'proof':report['proof']},indent=2))
    finally:
        engine.dispose()
        if created:
            with admin.begin() as c:c.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


if __name__=='__main__':main()
