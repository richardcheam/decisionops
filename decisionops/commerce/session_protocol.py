"""Bounded POSIX reusable child transport. No model/database imports."""
from dataclasses import dataclass,asdict
import fcntl
import json
import math
import os
from pathlib import Path
import queue
import re
import selectors
import signal
import stat
import struct
import subprocess
import sys
import threading
import time

PROTOCOL='commerce-adaptive-session/v1'
REQUEST_LIMIT=32768
RESULT_LIMIT=65536
STREAM_LIMIT=65536
INPUT_TOTAL=589896
DIAGNOSTIC_LIMIT=1024
FEATURE_KEYS={'report','observations','allowed_actions','attempted_tools','remaining_budgets','rejections'}

class SessionFailure(RuntimeError):pass
class KnownFailure(SessionFailure):pass

@dataclass(frozen=True)
class Config:
    family:str
    revision:str
    behavior:str='normal'
    slot_ms:int=30000
    preload_ms:int=120000
    version:str=PROTOCOL
    def __post_init__(self):
        if self.version!=PROTOCOL or self.family not in ('fake','laya','gliclass'):raise ValueError('Invalid session family/version')
        if (self.family=='fake' and self.revision!='fake-v1' or self.family!='fake' and not re.fullmatch('[0-9a-f]{40}',self.revision)):
            raise ValueError('Invalid recorded checkpoint revision')
        modes=('normal','malformed','truncated','wrong-session','wrong-request','frame-overflow','stderr-overflow','both-overflow','cumulative','preload-timeout','decision-timeout','descendants','preload-error','decision-error','slow-preload','exit-surplus','exit-stderr-overflow')
        if self.behavior not in modes or self.family!='fake' and self.behavior!='normal':raise ValueError('Invalid fake behavior')
        if type(self.slot_ms) is not int or not 1<=self.slot_ms<=30000 or type(self.preload_ms) is not int or not 1<=self.preload_ms<=120000:
            raise ValueError('Invalid phase caps')
    def record(self):return asdict(self)
    def admit(self):
        if self.family=='fake':return
        try:
            lines=Path(__file__).resolve().parents[2].joinpath('model-revisions.env').read_text().splitlines()
            pins=dict(line.split('=',1) for line in lines if '=' in line and not line.startswith('#'))
            if pins.get(self.family.upper()+'_REV')!=self.revision:raise SessionFailure('checkpoint_policy_changed: no dispatch')
        except OSError:raise SessionFailure('checkpoint_policy_unavailable: no dispatch') from None

def strict_json(data):
    def pairs(items):
        result={}
        for k,v in items:
            if k in result:raise ValueError('Duplicate JSON key')
            result[k]=v
        return result
    def bad(value):raise ValueError('Nonfinite JSON')
    return json.loads(data.decode('utf-8'),object_pairs_hook=pairs,parse_constant=bad)

def encode(message,limit=REQUEST_LIMIT):
    payload=json.dumps(message,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
    if not 0<len(payload)<=limit:raise SessionFailure('frame_size')
    return struct.pack('!I',len(payload))+payload

class Session:
    def __init__(self,config,session_id,deadline,*,cancel=None,slot_path=None,python=None,preload_deadline=None,lease_deadline=None,on_launch=None,on_started=None):
        if not isinstance(session_id,str) or len(session_id.encode())>128 or not math.isfinite(deadline) or deadline>time.monotonic()+240:raise ValueError('Invalid session identity/deadline')
        self.on_launch=on_launch;self.on_started=on_started;self.config=config;self.id=session_id;self.deadline=deadline;self.preload_deadline=preload_deadline or deadline;self.lease_deadline=lease_deadline or deadline;self.cancel=cancel or threading.Event()
        self.slot_path=Path(slot_path or f'/tmp/decisionops-commerce-adaptive-{os.getuid()}.lock')
        self.python=python or sys.executable;self.process=None;self.fd=None;self.reader=None
        self.closed=threading.Event();self.failed=None;self.messages=queue.Queue(maxsize=2);self.expected=None
        self.completed_response=False;self.lock=threading.Lock();self.sequence=0;self.input_bytes=0;self.input_bytes_written=0;self.input_frames=0
        self.consumed={'stdout':0,'stderr':0};self.retained={'stdout':bytearray(),'stderr':bytearray()}
        self.wait_ms=0;self.load_ms=0;self.inference_ms=0;self.ready=None;self.started=time.monotonic()
    def _fail(self,kind):
        with self.lock:
            if self.failed is None:self.failed=SessionFailure(kind)
        self._kill()
    def _kill(self):
        if self.process is not None:
            try:os.killpg(self.process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
    def _check(self,end):
        if not math.isfinite(end):raise SessionFailure('invalid_deadline')
        if self.failed:raise self.failed
        if self.cancel.is_set():self._fail('cancelled');raise self.failed
        if time.monotonic()>=min(end,self.deadline,self.lease_deadline):self._fail('deadline');raise self.failed
    def _slot(self):
        end=min(self.deadline,self.preload_deadline,time.monotonic()+self.config.slot_ms/1000)
        self.fd=os.open(self.slot_path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        info=os.fstat(self.fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise SessionFailure('unsafe_host_slot')
        begun=time.monotonic()
        try:
            while True:
                self._check(end)
                try:fcntl.flock(self.fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:time.sleep(.01)
        finally:self.wait_ms=int((time.monotonic()-begun)*1000)
    def _drain(self):
        pending=bytearray()
        try:
            with selectors.DefaultSelector() as selector:
                for name in ('stdout','stderr'):
                    pipe=getattr(self.process,name);os.set_blocking(pipe.fileno(),False);selector.register(pipe,selectors.EVENT_READ,name)
                while not self.closed.is_set():
                    self._check(self.deadline)
                    exited=self.process.poll() is not None
                    available=selector.select(0 if exited else .02)
                    if exited and not available:
                        if pending:raise SessionFailure('truncated_surplus_output')
                        if self.completed_response:return
                        raise SessionFailure('child_exit')
                    for key,_ in available:
                        name=key.data;remaining=STREAM_LIMIT-self.consumed[name]
                        try:data=os.read(key.fileobj.fileno(),min(4096,remaining+1))
                        except BlockingIOError:continue
                        if not data:
                            selector.unregister(key.fileobj)
                            if name=='stdout' and (pending or not self.completed_response):raise SessionFailure('truncated_or_closed_stdout')
                            continue
                        self.consumed[name]+=len(data)
                        self.retained[name].extend(data[:max(0,DIAGNOSTIC_LIMIT-len(self.retained[name]))])
                        if self.consumed[name]>STREAM_LIMIT:raise SessionFailure(name+'_cumulative_overflow')
                        if name=='stderr':continue
                        pending.extend(data)
                        while len(pending)>=4:
                            length=struct.unpack('!I',pending[:4])[0]
                            if not 0<length<=RESULT_LIMIT:raise SessionFailure('result_frame_size')
                            if len(pending)<length+4:break
                            frame=strict_json(bytes(pending[4:length+4]));del pending[:length+4]
                            with self.lock:
                                expected=self.expected
                                if (not isinstance(frame,dict) or set(frame)!={'protocol','type','session_id','sequence','request_id','payload'}
                                    or frame['protocol']!=PROTOCOL or frame['session_id']!=self.id or expected is None
                                    or type(frame['sequence']) is not int or not isinstance(frame['payload'],dict)
                                    or (frame['type'] not in (expected[0],'error')) or frame['sequence']!=expected[1]
                                    or frame['request_id']!=expected[2]):raise SessionFailure('correlation_or_unsolicited_frame')
                                self.expected=None;self.completed_response=True
                            try:self.messages.put_nowait(frame)
                            except queue.Full:raise SessionFailure('response_queue_overflow')
                    # Once the direct child exits, drain immediately buffered
                    # bytes before accepting its final frame. Never await EOF
                    # from descendants retaining these pipes.
        except (SessionFailure,ValueError,UnicodeError,OSError) as error:
            if not self.closed.is_set():self._fail(str(error))
    def _exchange(self,kind,payload,request_id,end,response):
        self._check(end)
        if self.process.poll() is not None:raise KnownFailure('child_exited_before_request')
        frame={'protocol':PROTOCOL,'type':kind,'session_id':self.id,'sequence':self.sequence,'request_id':request_id,'payload':payload}
        data=encode(frame)
        if self.input_frames>=18 or self.input_bytes+len(data)>INPUT_TOTAL:raise SessionFailure('stdin_cumulative_overflow')
        with self.lock:
            if self.expected is not None:raise SessionFailure('concurrent_request')
            self.expected=(response,self.sequence,request_id);self.completed_response=False
        self.input_frames+=1;self.input_bytes+=len(data)
        os.set_blocking(self.process.stdin.fileno(),False)
        with selectors.DefaultSelector() as selector:
            selector.register(self.process.stdin,selectors.EVENT_WRITE)
            view=memoryview(data)
            while view:
                self._check(end)
                if not selector.select(.02):continue
                try:n=os.write(self.process.stdin.fileno(),view[:4096]);self.input_bytes_written+=n;view=view[n:]
                except BlockingIOError:continue
                except BrokenPipeError:raise SessionFailure('stdin_closed')
        while True:
            self._check(end)
            try:frame=self.messages.get(timeout=.02);break
            except queue.Empty:continue
        if frame['type']=='error':
            if set(frame['payload'])!={'kind'} or not isinstance(frame['payload']['kind'],str) or len(frame['payload']['kind'])>128:raise SessionFailure('invalid_error_frame')
            raise KnownFailure('child_error:'+frame['payload']['kind'])
        return frame['payload']
    def start(self):
        if self.ready is not None:return self.ready
        self.config.admit();self._slot();begun=time.monotonic()
        if self.on_launch:self.on_launch()
        end=min(self.deadline,self.preload_deadline,begun+self.config.preload_ms/1000)
        env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',
                 CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='4',MKL_NUM_THREADS='4',TOKENIZERS_PARALLELISM='false',LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false')
        self._check(end)
        worker=Path(__file__).with_name('session_worker.py')
        self.process=subprocess.Popen([self.python,'-B',str(worker),'--deadline',str(self.deadline),'--parent-pid',str(os.getpid())],stdin=subprocess.PIPE,
             stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env=env,pass_fds=(self.fd,))
        self.reader=threading.Thread(target=self._drain,daemon=True);self.reader.start()
        if self.on_started:self.on_started()
        try:
            ready=self._exchange('preload',{'config':self.config.record()},None,end,'ready')
            if (not isinstance(ready,dict) or set(ready)!={'family','revision','load_ms','peak_rss_kib','simulated','load_count'}
                or ready['family']!=self.config.family or ready['revision']!=self.config.revision or ready['load_count']!=1
                or type(ready['load_count']) is not int or ready['simulated']!=(self.config.family=='fake') or type(ready['simulated']) is not bool
                or type(ready['load_ms']) is not int or not 0<=ready['load_ms']<=self.config.preload_ms or type(ready['peak_rss_kib']) is not int or ready['peak_rss_kib']<0):raise SessionFailure('invalid_readiness')
            self.ready=ready;return ready
        except Exception:
            self._kill();raise
        finally:self.load_ms=int((time.monotonic()-begun)*1000)
    def choose(self,request_id,features,end):
        if set(features)!=FEATURE_KEYS or not features['allowed_actions']:raise SessionFailure('invalid_features')
        if len(features['allowed_actions'])==1:
            return dict(action_index=0,inference_ms=0,forced=True,scores={},score_meaning='forced deterministic choice',peak_rss_kib=0,simulated=self.config.family=='fake',load_count=0)
        self.start();self.sequence+=1
        if self.sequence>16:raise SessionFailure('decision_cap')
        begun=time.monotonic()
        try:
            raw=self._exchange('request',{'features':features},request_id,min(end,begun+20), 'result')
            if (not isinstance(raw,dict) or set(raw)!={'action_index','inference_ms','forced','scores','score_meaning','peak_rss_kib','simulated','load_count'}
                or type(raw['action_index']) is not int or not 0<=raw['action_index']<len(features['allowed_actions'])
                or type(raw['inference_ms']) is not int or not 0<=raw['inference_ms']<=20000 or raw['forced'] is not False
                or type(raw['load_count']) is not int or raw['load_count']!=1 or type(raw['simulated']) is not bool or raw['simulated']!=(self.config.family=='fake')
                or not isinstance(raw['scores'],dict) or set(raw['scores'])!={str(i) for i in range(len(features['allowed_actions']))}
                or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in raw['scores'].values())
                or not isinstance(raw['score_meaning'],str) or len(raw['score_meaning'].encode())>4096
                or type(raw['peak_rss_kib']) is not int or raw['peak_rss_kib']<0):raise SessionFailure('invalid_result')
            return raw
        except Exception:self._kill();raise
        finally:self.inference_ms+=int((time.monotonic()-begun)*1000)
    def diagnostics(self):
        return dict(consumed=dict(self.consumed),retained={n:len(b) for n,b in self.retained.items()},
            diagnostics={n:bytes(b).decode('utf-8',errors='replace').replace(chr(0),chr(92)+'0') for n,b in self.retained.items()},
            readiness=self.ready,process_pid=self.process.pid if self.process is not None else None,
            input_bytes=self.input_bytes,input_bytes_written=self.input_bytes_written,input_frames=self.input_frames,process_reaped=self.process is None or self.process.returncode is not None,
            waiting_ms=self.wait_ms,load_ms=self.load_ms,inference_ms=self.inference_ms,total_ms=int((time.monotonic()-self.started)*1000),
            outcome=str(self.failed) if self.failed else 'closed' if self.closed.is_set() else 'active')
    def close(self):
        if self.closed.is_set():return
        self.closed.set();self._kill()
        if self.process is not None:
            for pipe in (self.process.stdin,self.process.stdout,self.process.stderr):
                try:pipe.close()
                except OSError:pass
            try:self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:self.failed=SessionFailure('cleanup_timeout')
        if self.reader is not None:self.reader.join(timeout=.2)
        if self.fd is not None:os.close(self.fd);self.fd=None
