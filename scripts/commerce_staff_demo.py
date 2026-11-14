"""Start/stop only the isolated fictional staff assistant; never paid transport."""
import argparse,json,os,signal,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
DIRECTORY=ROOT/'runs/staff-assistant'
URL='postgresql+psycopg://staff_demo:fictional-staff-demo-only@127.0.0.1:55520/commerce_staff_demo'

def app():
    from decisionops.commerce.api import create_app
    from starlette.staticfiles import StaticFiles
    value=create_app();value.mount('/',StaticFiles(directory=DIRECTORY/'web-dist',html=True),name='staff-interface');return value

def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=('start','stop','status'))
    p.add_argument('--mode',choices=('rules','mock-decisions'),default='rules')
    p.add_argument('--schema',default='public')
    p.add_argument('--port',type=int,default=55521,help='Loopback web port for this checkout (default: 55521)')
    args=p.parse_args(argv)
    if not 1024<=args.port<=65535:p.error('Use an unprivileged port from 1024 through 65535')
    return args

def main():
    args=parse_args()
    web_url='http://127.0.0.1:'+str(args.port)
    DIRECTORY.mkdir(parents=True,exist_ok=True);pidfile=DIRECTORY/'services.json'
    if args.command in ('stop','status'):
        if not pidfile.exists():print('No task-owned processes recorded');return
        saved=json.loads(pidfile.read_text())
        for proc in saved['processes']:
            # Refuse to signal a recycled PID; never target unrelated work.
            path=Path('/proc')/str(proc['pid'])/'cmdline'
            if not path.exists():continue
            command=path.read_bytes().replace(b'\0',b' ').decode()
            if proc['module'] not in command:raise SystemExit('PID no longer belongs to this demo; refusing signal')
            if args.command=='stop':os.kill(proc['pid'],signal.SIGTERM)
        if args.command=='stop':pidfile.unlink();time.sleep(1);print('Only recorded staff-demo processes stopped; database/volume retained')
        else:print(json.dumps(saved,indent=2))
        return
    if pidfile.exists():raise SystemExit('Demo already recorded; inspect status/stop before restart')
    if args.schema!='public' and not args.schema.startswith('staff_demo_'):raise SystemExit('Use public or an owned staff_demo_ schema')
    if not (DIRECTORY/'web-dist/index.html').exists():raise SystemExit('Build cached frontend first; see runbook')
    import socket
    with socket.socket() as probe:
        # Match Uvicorn's restart semantics: TIME_WAIT is not a live owner.
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:probe.bind(('127.0.0.1',args.port))
        except OSError:raise SystemExit('Selected web port unavailable; choose another --port')
    from sqlalchemy.engine import make_url
    from decisionops.commerce.database import database_engine
    from decisionops.commerce.seed import seed
    from decisionops.commerce.workflow import setup_checkpoints
    from alembic import command
    from alembic.config import Config
    url=make_url(URL).update_query_dict({'options':'-csearch_path='+args.schema});engine=database_engine(url)
    with engine.connect() as c:
        assert tuple(c.exec_driver_sql('SELECT current_database(),current_user,inet_server_port()').one())==('commerce_staff_demo','staff_demo',5432)
    # Caller creates only its explicit disposable test schema; demo uses public.
    config=Config(str(ROOT/'alembic.ini'))
    with engine.begin() as c:config.attributes['connection']=c;command.upgrade(config,'head')
    with engine.connect() as c:seeded=c.exec_driver_sql('SELECT count(*) FROM seed_versions').scalar_one()
    if not seeded:seed(engine)
    setup_checkpoints(engine);engine.dispose()
    env={k:v for k,v in os.environ.items() if k in ('PATH','HOME','LANG','LC_ALL','TMPDIR','SYSTEMROOT')}
    env.update(COMMERCE_DATABASE_URL=url.render_as_string(hide_password=False),COMMERCE_STAFF_USERNAME='operator',COMMERCE_STAFF_PASSWORD='fictional-staff-demo-password',COMMERCE_STAFF_INVESTIGATION_MODE=args.mode,COMMERCE_ORIGINS=web_url,PYTHONPATH=str(ROOT),PYTHONDONTWRITEBYTECODE='1',LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false')
    commands=[('uvicorn',['scripts.commerce_staff_demo:app','--factory','--host','127.0.0.1','--port',str(args.port)]),('decisionops.commerce.worker',['run']),('decisionops.commerce.staff_investigations',['--step-delay','0.4'])]
    processes=[]
    try:
        for module,arguments in commands:
            log=(DIRECTORY/(module.split('.')[-1]+'.log')).open('a')
            proc=subprocess.Popen([sys.executable,'-B','-m',module,*arguments],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);log.close();processes.append({'pid':proc.pid,'module':module})
        pidfile.write_text(json.dumps({'schema':args.schema,'mode':args.mode,'url':web_url,'processes':processes},indent=2)+'\n')
        import urllib.request
        for _ in range(50):
            try:
                with urllib.request.urlopen(web_url+'/health',timeout=1) as r:assert r.status==200
                print('Isolated staff app ready: '+web_url+'; operator / fictional-staff-demo-password (fictional demo credentials only)');break
            except Exception:time.sleep(.2)
        else:raise RuntimeError('Demo readiness failed; inspect runs/staff-assistant/uvicorn.log')
    except Exception:
        for proc in processes:
            try:os.kill(proc['pid'],signal.SIGTERM)
            except ProcessLookupError:pass
        if pidfile.exists():pidfile.unlink()
        raise
if __name__=='__main__':main()
