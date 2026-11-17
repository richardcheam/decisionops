"""Opt-in LangSmith event export. No automatic graph/input/output tracing.

Business code only queues allowlisted metadata; network I/O occurs in one daemon
consumer with a bounded queue. A hung/failed exporter never blocks a case.
"""
from datetime import datetime, timezone
import hashlib
import os
from queue import Queue, Empty, Full
import re
from threading import Thread
import time
import uuid

TOOLS={'order_manifest','replacement_policy','payment','fulfilment','carrier_loss','compensation_history','inventory'}
NODES={'identity','bound','order','shipment','terminal','worker'}
EVENTS={'start','resume','node','tool','retry','fallback','stop','failure'}
STATUSES={'active','proposed','review','blocked','success','unavailable','unknown','failed','stale','settled','uncertain','discarded','cancelled','accepted','complete','pending','conflicting','other'}
REASONS={'unknown_evidence','manual_review','run_deadline','worker_error','worker_stopped','source_changed','context_or_deadline_changed','invalid_committed_evidence','conflicting_records','carrier_unavailable','decision_deadline','read_error','invalid_action','tool_retry','fallback','proposal_ready','established_blocker','stale_evidence','case_changed','other'}

class SafeTracer:
    def __init__(self,*,enabled=False,sink=None,max_queue=128):
        self.enabled=bool(enabled and sink);self.sink=sink
        self.queue=Queue(maxsize=max_queue);self.errors=0;self.dropped=0
        if self.enabled:Thread(target=self._consume,daemon=True,name='commerce-safe-traces').start()
    def emit(self,investigation_id,event,**fields):
        if not self.enabled:return
        if event not in EVENTS or not isinstance(investigation_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',investigation_id):return
        record={'investigation_id':investigation_id,'event':event,'time':datetime.now(timezone.utc).isoformat()}
        for key,allowed in (('node',NODES),('tool',TOOLS),('status',STATUSES),('reason',REASONS)):
            value=fields.get(key)
            if isinstance(value,str):record[key]=value if value in allowed else 'other'
        for key in ('attempt','sequence'):
            value=fields.get(key)
            if type(value) is int and 0<=value<=100000:record[key]=value
        try:self.queue.put_nowait(record)
        except Full:self.dropped+=1
    def defer(self,callback):
        if not self.enabled:return
        try:self.queue.put_nowait(callback)
        except Full:self.dropped+=1
    def _consume(self):
        while True:
            record=self.queue.get()
            try:
                if callable(record):record()
                else:self.sink(record)
            except Exception:self.errors+=1  # Never log exporter exceptions or credentials.
            finally:self.queue.task_done()
    def flush(self,timeout=.5):
        end=time.monotonic()+timeout
        while self.queue.unfinished_tasks and time.monotonic()<end:time.sleep(.005)
        return not self.queue.unfinished_tasks

class LangSmithSink:
    """One integration. Never attach prompts, runtime environment or record values."""
    def __init__(self,key):
        from langsmith import Client
        from urllib3.util import Retry
        self.client=Client(api_url='https://api.smith.langchain.com',api_key=key,
            auto_batch_tracing=False,timeout_ms=(250,250),retry_config=Retry(total=0),
            hide_inputs=True,hide_outputs=False,omit_traced_runtime_info=True)
        self.roots=set()
    def __call__(self,record):
        root=uuid.UUID(hashlib.sha256(record['investigation_id'].encode()).hexdigest()[:32])
        now=datetime.now(timezone.utc)
        if root not in self.roots:
            self.client.create_run(name='DecisionOps investigation',inputs={},run_type='chain',id=root,
                trace_id=root,start_time=now,end_time=now,project_name='decisionops-portfolio',
                extra={'metadata':{'investigation_id':record['investigation_id']}})
            self.roots.add(root)
        self.client.create_run(name='DecisionOps '+record['event'],inputs={},outputs=record,run_type='tool',
            id=uuid.uuid4(),trace_id=root,parent_run_id=root,start_time=now,end_time=now,
            project_name='decisionops-portfolio')

_DEFAULT=None

def configured_tracer():
    global _DEFAULT
    enabled=os.environ.get('COMMERCE_LANGSMITH_EXPORT')=='1'
    if not enabled:return SafeTracer()
    if _DEFAULT is None:
        key=os.environ.get('LANGSMITH_API_KEY')
        try:_DEFAULT=SafeTracer(enabled=bool(key),sink=LangSmithSink(key) if key else None)
        except Exception:_DEFAULT=SafeTracer()
    return _DEFAULT


def observe(engine,run_id,*,tracer=None,event='node',node='worker',attempt=1,reason=None):
    """Read committed progress after a node, outside its business transaction.

    Raw source data stays local. Only explicit enums/counts reach emit(). Even
    local inspection failure cannot alter the business outcome.
    """
    trace=tracer if tracer is not None else configured_tracer()
    if not trace.enabled:return
    def enrich():
        try:
            from . import adaptive_investigations as service
            run=service.inspect(engine,run_id)
            trace.emit(run_id,event,node=node,status=run['state'],attempt=attempt,reason=reason)
            counts={}
            for step in run['steps']:
                data=step['data'];tool=data.get('tool')
                if tool in TOOLS:
                    trace.emit(run_id,'tool',tool=tool,status=data.get('status','other'),sequence=step['sequence'],attempt=attempt)
                kind=step['kind']
                if kind in ('read_reserved','specialist_read_reserved') and tool in TOOLS:
                    counts[tool]=counts.get(tool,0)+1
                    if counts[tool]>1:trace.emit(run_id,'retry',tool=tool,reason='tool_retry',sequence=step['sequence'],attempt=attempt)
                if 'retry' in kind or 'interrupted' in kind:trace.emit(run_id,'retry',tool=tool,reason='tool_retry',sequence=step['sequence'],attempt=attempt)
                if any(word in kind for word in ('fallback','rejected','continuation')):
                    trace.emit(run_id,'fallback',reason='fallback',sequence=step['sequence'],attempt=attempt)
            if run['state']!='active':
                terminal=run.get('terminal') or {}
                trace.emit(run_id,'stop',node=node,status=run['state'],reason=terminal.get('reason') or ('proposal_ready' if run['state']=='proposed' else 'other'),attempt=attempt)
        except Exception:trace.emit(run_id,'failure',node=node,reason='worker_error',attempt=attempt)
    trace.defer(enrich)
