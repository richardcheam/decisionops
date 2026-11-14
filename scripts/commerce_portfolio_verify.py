"""Local-only fictional browser/restart proof for decisionops-portfolio-verify.

Requires the already-started dedicated stack and cached browser image. Never builds,
seeds, calls models, resets a ledger or targets the original/staff demo projects.
"""
import argparse,copy,json,os,re,shlex,subprocess,time,urllib.request,urllib.error,base64
from urllib.parse import urlsplit
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PROJECT='decisionops-portfolio-verify'
OUT=ROOT/'runs/portfolio-demo'
ENV={k:v for k,v in os.environ.items() if k in ('PATH','HOME','USER','LOGNAME','LANG','LC_ALL','COMMERCE_PORTFOLIO_PASSWORD','COMMERCE_PORTFOLIO_PORT','COMMERCE_PORTFOLIO_ORIGIN','COMMERCE_PORTFOLIO_POSTGRES_IMAGE')}
WEB='http://127.0.0.1:8091'
PUBLIC='http://127.0.0.1:8094'
COMPOSE=['docker','compose','--project-directory',str(ROOT),'--env-file','/dev/null','-f',str(ROOT/'tests/compose/portfolio.yaml'),'-p',PROJECT]

def docker(args,**kwargs):
    return subprocess.run(['sg','docker','-c',shlex.join(args)],env=ENV,check=True,text=True,capture_output=True,timeout=20,**kwargs).stdout

def snapshot():
    tables=('commerce_cases','commerce_proposals','commerce_reviews','commerce_operations','commerce_reservations','commerce_replacement_orders','commerce_adaptive_runs','commerce_adaptive_jobs','commerce_adaptive_steps','commerce_adaptive_observations','commerce_adaptive_calls')
    pairs=','.join("'%s',(SELECT COALESCE(json_agg(t),'[]'::json) FROM %s t)"%(t,t) for t in tables)
    sql="BEGIN READ ONLY; SELECT json_build_object("+pairs+"); COMMIT;"
    raw=docker(COMPOSE+['exec','-T','postgres','psql','-qAt','-U','portfolio','-d','portfolio','-v','ON_ERROR_STOP=1','-c',sql])
    return json.loads(raw)

def save(name,value):
    (OUT/name).write_text(json.dumps(value,indent=2)+'\n')

def verify_public_boundary():
    public=PUBLIC
    results=[];before=snapshot()
    for origin in (public,WEB):
        for path in ('/api/cases','/api/cases/not-a-case/shipment-investigation','/api/cases/not-a-case/review','/api/cases/not-a-case/execute','/reset','/api/reset'):
            for method in ('POST','DELETE'):
                headers={'Content-Type':'application/json'}
                request=urllib.request.Request(origin+path,data=b'{}',headers=headers,method=method)
                try:
                    with urllib.request.urlopen(request,timeout=3) as response:status=response.status
                except urllib.error.HTTPError as error:status=error.code
                assert status in (401,403,404,405),(origin,path,status)
                results.append({'origin':origin,'method':method,'path':path,'status':status})
    old=base64.b64encode(b'visitor:fictional-portfolio-visitor').decode()
    try:urllib.request.urlopen(urllib.request.Request(WEB+'/api/cases',headers={'Authorization':'Basic '+old}),timeout=3)
    except urllib.error.HTTPError as error:assert error.code==401
    else:raise AssertionError('Old public fixture password still grants access')
    with urllib.request.urlopen(public+'/',timeout=3) as response:
        page=response.read();assert b'fictional-portfolio-visitor' not in page and b'read-only' in page
    assert snapshot()==before,'Rejected public requests changed business/investigation records'
    save('public-access.json',{'requests':results,'old_default_rejected':True,'durable_records_unchanged':True})

def restart_staff_worker():
    docker(COMPOSE+['stop','staff-investigator'])
    try:
        save('restart-stopped.json',snapshot())
        with urllib.request.urlopen(WEB+'/health',timeout=3) as response:assert response.status==200
    finally:
        # A failed health/snapshot check must not leave our owned worker stopped.
        (OUT/'worker-restart.log').write_text(docker(COMPOSE+['start','staff-investigator']))

PROTECTED_PORTS={8080,8091,8093,8094,8095}

def rehearsal_config(argv=None):
    """Validate target selection without Docker, network or filesystem writes."""
    parser=argparse.ArgumentParser(description=__doc__)
    target=parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--release',action='store_true')
    target.add_argument('--project')
    parser.add_argument('--port',type=int)
    parser.add_argument('--public-url')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--compose-override',type=Path)
    args=parser.parse_args(argv)
    if args.release:
        if any(value is not None for value in (args.port,args.public_url,args.output,args.compose_override)):
            parser.error('--release cannot be combined with RC target options')
        return {'project':'decisionops-portfolio-release','port':8093,
                'public_url':'http://127.0.0.1:8094','output':ROOT/'runs/portfolio-release',
                'compose_override':None,'release':True}
    if not re.fullmatch(r'decisionops-portfolio-(?:rc|rehearsal)(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?',args.project):
        parser.error('Use a new decisionops-portfolio-rc[-suffix] or decisionops-portfolio-rehearsal[-suffix] project')
    if args.port is None or args.public_url is None or args.output is None:
        parser.error('--project requires --port, --public-url and --output')
    if not 1024<=args.port<=65535 or args.port in PROTECTED_PORTS:
        parser.error('RC port must be an unprivileged port outside the protected original ports')
    try:
        public=urlsplit(args.public_url)
        public_port=public.port
    except ValueError:
        parser.error('Invalid public URL port')
    if (public.scheme!='http' or public.hostname not in ('127.0.0.1','localhost')
            or public.username is not None or public.password is not None
            or public.path not in ('','/') or public.query or public.fragment
            or public_port is None or not 1024<=public_port<=65535
            or public_port in PROTECTED_PORTS or public_port==args.port):
        parser.error('Public URL must select a separate unprivileged loopback HTTP port outside protected ports')
    output=args.output.resolve()
    if output in ((ROOT/'runs/portfolio-demo').resolve(),(ROOT/'runs/portfolio-release').resolve()):
        parser.error('RC output must not overwrite original portfolio evidence')
    return {'project':args.project,'port':args.port,'public_url':args.public_url.rstrip('/'),
            'output':output,'compose_override':args.compose_override.resolve() if args.compose_override else None,
            'release':False}

def main():
    global PROJECT,OUT,COMPOSE,WEB,PUBLIC
    config=rehearsal_config()
    PROJECT=config['project'];OUT=config['output'];WEB='http://127.0.0.1:'+str(config['port'])
    PUBLIC=config['public_url']
    COMPOSE=['docker','compose','--project-directory',str(ROOT),'--env-file','/dev/null','-f',str(ROOT/'tests/compose/portfolio.yaml')]
    if config['compose_override'] is not None:COMPOSE+=['-f',str(config['compose_override'])]
    COMPOSE+=['-p',PROJECT]
    if not config['release']:
        ENV['COMMERCE_PORTFOLIO_PORT']=str(config['port'])
        ENV['COMMERCE_PORTFOLIO_ORIGIN']=WEB
    if len(ENV.get('COMMERCE_PORTFOLIO_PASSWORD',''))<16:raise SystemExit('Set an explicit invitation password of at least 16 characters')
    if ENV.get('COMMERCE_PORTFOLIO_PORT',WEB.rsplit(':',1)[1])!=WEB.rsplit(':',1)[1]:raise SystemExit('Rehearsal port mismatch')
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'restart-before.json').exists():raise SystemExit('Evidence already exists; do not repeat a completed fixture')
    config=json.loads(docker(COMPOSE+['config','--format','json']))
    assert config['name']==PROJECT
    assert config['networks']['default']['internal']
    for name,service in config['services'].items():
        assert 'OPENAI_API_KEY' not in service.get('environment',{})
        if name!='web':assert not service.get('ports') and 'ingress' not in service.get('networks',{})
    assert config['services']['api']['environment']['COMMERCE_STAFF_INVESTIGATION_MODE']=='rules'
    assert snapshot()['commerce_adaptive_runs']==[], 'Requires fresh fictional verification records; no reset performed'
    public_config=copy.deepcopy(config)
    for service in public_config['services'].values():
        for key in service.get('environment',{}):
            if 'PASSWORD' in key or key=='COMMERCE_DATABASE_URL':service['environment'][key]='<redacted>'
    save('compose-config.json',public_config)
    verify_public_boundary()
    # Only the explicitly supplied invitation password reaches browser auth,
    # through the environment, never argv/logs/traces or checkpoint features.
    args=['docker','run','--rm','--pull','never','--network','host','--name',PROJECT+'-browser',
          '-e','COMMERCE_WEB_URL='+WEB,'-e','COMMERCE_STAFF_USERNAME=visitor',
          '-e','COMMERCE_STAFF_PASSWORD','-e','COMMERCE_STAFF_TEST_MODE=rules',
          '-e','COMMERCE_STAFF_RESTART_TEST=1',
          '-v',str(ROOT/'frontend/staff-tests')+':/workspace/staff-tests:ro',
          '-v',str(ROOT/'frontend/playwright.staff.config.ts')+':/workspace/playwright.staff.config.ts:ro',
          '-v',str(OUT/'browser')+':/workspace/artifacts','--entrypoint','sh','decisionops-commerce-browser:local',
          '-c','npx --no-install playwright test --config playwright.staff.config.ts --timeout 90000']
    began=time.monotonic()
    with (OUT/'browser.log').open('w') as log:
        browser=subprocess.Popen(['sg','docker','-c',shlex.join(args)],env={**ENV,'COMMERCE_STAFF_PASSWORD':ENV['COMMERCE_PORTFOLIO_PASSWORD']},stdout=log,stderr=subprocess.STDOUT)
        try:
            until=time.monotonic()+35
            while time.monotonic()<until:
                before=snapshot()
                candidate=next((r for r in before['commerce_adaptive_runs'] if r['state']=='active' and r['tool_attempts']>=1 and not r['pending_token']),None)
                if candidate:break
                if browser.poll() is not None:raise RuntimeError('Browser exited before restart boundary; inspect browser.log')
                time.sleep(.05)
            else:raise RuntimeError('Committed-read restart boundary not reached')
            save('restart-before.json',before)
            restart_staff_worker()
            status=browser.wait(timeout=100)
            after=snapshot();save('restart-after.json',after)
            assert status==0,'Browser business assertions failed; preserved browser.log and records'
        finally:
            if browser.poll() is None:
                docker(['docker','stop','-t','3',PROJECT+'-browser']);browser.wait(timeout=10)
    runs=after['commerce_adaptive_runs'];assert len(runs)==2
    eligible=next(r for r in runs if r['id']==candidate['id']);assert eligible['state']=='proposed'
    assert eligible['deadline']==candidate['deadline']
    assert eligible['tool_attempts']==7
    assert len(after['commerce_proposals'])==1
    assert len(after['commerce_operations'])==len(after['commerce_reservations'])==len(after['commerce_replacement_orders'])==1
    job=next(j for j in after['commerce_adaptive_jobs'] if j['run_id']==candidate['id'])
    assert job['claims']==2 and job['status']=='completed'
    calls={c['id']:c for c in after['commerce_adaptive_calls']}
    assert all(c['dispatch_count']<=1 for c in calls.values())
    # Settled effects/history recorded before shutdown remain byte-for-byte immutable.
    for table in ('commerce_adaptive_steps','commerce_adaptive_observations'):
        existing={json.dumps(r,sort_keys=True) for r in after[table]}
        assert all(json.dumps(r,sort_keys=True) in existing for r in before[table])
    for c in before['commerce_adaptive_calls']:
        if c['state']=='settled':assert calls[c['id']]['result']==c['result']
    summary={'source':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
             'project':PROJECT,'mode':'rules; zero model/API dispatches','browser_passed':2,'browser_skipped':0,
             'restart_run':candidate['id'],'tools_before_restart':candidate['tool_attempts'],'tools_after':eligible['tool_attempts'],
             'claims':job['claims'],'unchanged_deadline':eligible['deadline'],'single_proposal':True,'single_replacement':True,
             'all_dispatch_counts_at_most_one':True,'immutable_history_preserved':True,'wall_seconds':round(time.monotonic()-began,3)}
    save('summary.json',summary);print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
