"""Real worker restart in the explicitly isolated local specialist demo, no inference."""
import argparse,base64,json,os,subprocess,time,urllib.request
from pathlib import Path

BASE='http://127.0.0.1:8123'
PROJECT='decisionops-multi-agent-demo'
WORKER=PROJECT+'-staff-investigator-1'

def docker(*args):
    return subprocess.run(['docker',*args],check=True,capture_output=True,text=True,timeout=15).stdout

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='runs/multi-agent/worker-restart');args=p.parse_args()
    password=os.environ['COMMERCE_MULTI_AGENT_PASSWORD']
    headers={'Authorization':'Basic '+base64.b64encode(('visitor:'+password).encode()).decode(),'Content-Type':'application/json'}
    def request(path,data=None):
        body=None if data is None else json.dumps(data).encode()
        with urllib.request.urlopen(urllib.request.Request(BASE+path,body,headers=headers),timeout=5) as response:return json.load(response)
    actual=docker('inspect','--format','{{index .Config.Labels "com.docker.compose.project"}}',WORKER).strip()
    if actual!=PROJECT:raise ValueError('Worker identity mismatch')
    compensated=docker('exec',PROJECT+'-postgres-1','psql','-U','portfolio','-d','portfolio','-Atc',
        "SELECT count(*) FROM resolutions WHERE order_id='ORD-1042'").strip()
    if compensated!='0':raise ValueError('Restart rehearsal requires a fresh uncompensated fictional ORD-1042; preserve evidence before operator reset')
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    case=request('/api/cases',{'order_id':'ORD-1042','shipment_id':'SHIP-1042','items':{'shirt-blue-M':1}})
    admitted=request('/api/cases/'+case['id']+'/shipment-investigation',{'report':'Customer reports missing parcel. Check the evidence.','request_id':'RESTART-'+case['id'],'expected_generation':case['generation']})
    begin=time.monotonic();boundary=None
    while time.monotonic()-begin<15:
        detail=request('/api/cases/'+case['id']);run=detail['shipment_investigation']
        if any(b['name']=='order' and b['state']=='complete' for b in run['specialists']):boundary=detail;break
        time.sleep(.03)
    if boundary is None:raise AssertionError('Order commit boundary not reached')
    docker('stop','--time','5',WORKER)
    try:
        paused=request('/api/cases/'+case['id'])
        if paused['shipment_investigation']['state']!='active':raise AssertionError('Stop missed active boundary')
        retained={r['source']['observation_id'] for r in boundary['shipment_investigation']['evidence'] if r['tool'] in ('payment','fulfilment') and r['applicability']=='current'}
        if len(retained)!=2:raise AssertionError('Order branch did not commit')
        # Let the previous immutable ownership lease expire; no token clearing/reset.
        time.sleep(31)
    finally:docker('start',WORKER)
    end=time.monotonic()+60
    while time.monotonic()<end:
        final=request('/api/cases/'+case['id'])
        if final['shipment_investigation']['state']!='active':break
        time.sleep(.2)
    for name,value in [('before',boundary),('paused',paused),('after',final)]:
        (out/(name+'.json')).write_text(json.dumps(value,indent=2)+'\n')
    assert final['shipment_investigation']['state']=='proposed',final['shipment_investigation']['reason']
    assert retained<={r['source']['observation_id'] for r in final['shipment_investigation']['evidence']}
    assert len(final['shipment_investigation']['evidence'])==7
    assert final['approval'] is None and final['operation'] is None
    script="from decisionops.commerce.database import database_engine;from decisionops.commerce.multi_agent import trace;import json;print(json.dumps(trace(database_engine(),"+repr(admitted['run_id'])+"),default=str))"
    trace=json.loads(docker('exec',WORKER,'python','-B','-c',script))
    assert trace['budgets']['tool_attempts']==7
    assert len(trace['calls'])==3 and all(c['dispatch_count']==1 for c in trace['calls'])
    (out/'trace.json').write_text(json.dumps(trace,indent=2)+'\n')
    print(json.dumps({'state':trace['state'],'retained_order_observations':len(retained),'tools':trace['budgets']['tool_attempts'],
        'specialist_calls':len(trace['calls']),'duplicate_dispatches':0,'approval':None,'operation':None,'evidence':str(out),'elapsed_seconds':round(time.monotonic()-begin,2)},indent=2))
if __name__=='__main__':main()
