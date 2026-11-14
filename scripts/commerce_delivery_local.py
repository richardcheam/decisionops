"""Run the same Commerce app and workers without Docker, using an isolated database.

Setup first: migrate, delivery_seed, npm ci && npm run build. No paid adapters.
The caller owns the database and explicitly supplies its URL and demo password.
"""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8155)
    args=parser.parse_args()
    if not os.environ.get('COMMERCE_DATABASE_URL'):parser.error('Set an isolated COMMERCE_DATABASE_URL')
    if len(os.environ.get('COMMERCE_STAFF_PASSWORD',''))<16:parser.error('Set an explicit fictional COMMERCE_STAFF_PASSWORD of at least 16 characters')
    env=dict(os.environ,COMMERCE_WEB_DIST=str(ROOT/'frontend/dist'),COMMERCE_STAFF_INVESTIGATION_MODE='mock-specialists',
        COMMERCE_ORIGINS=f'http://127.0.0.1:{args.port}',LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false')
    children=[]
    def stop(*_):
        for child in children:
            if child.poll() is None:child.terminate()
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    try:
        for command in ([sys.executable,'-B','-m','decisionops.commerce.worker','run'],
                        [sys.executable,'-B','-m','decisionops.commerce.staff_investigations','--step-delay','0.1'],
                        [sys.executable,'-B','-m','uvicorn','decisionops.commerce.api:create_app','--factory','--host','127.0.0.1','--port',str(args.port)]):
            children.append(subprocess.Popen(command,cwd=ROOT,env=env))
        while all(child.poll() is None for child in children):
            try:children[-1].wait(timeout=.5)
            except subprocess.TimeoutExpired:pass
    finally:
        stop()
        for child in children:
            try:child.wait(timeout=8)
            except subprocess.TimeoutExpired:child.kill();child.wait()
    return 0

if __name__=='__main__':raise SystemExit(main())
