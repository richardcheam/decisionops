"""Offline subprocess boundary. Importing this module never imports model packages."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .providers import ProviderResult,validate_result,response_id,thaw

LABELS={'present_replacement':'Present replacement for staff approval',
        'staff_review':'Request staff review'}
INSTRUCTIONS='Route the investigated replacement case. Present a proposal only when every requirement is established true. Otherwise request staff review. Neither choice authorizes execution.'


def model_features(request):
    return {'task':request.task,'facts':thaw(request.facts),'allowed_choices':list(request.allowed_choices)}


def diagnostics(request,**values):
    return {'model_revision':request.config.model_revision,'forced_choice':False,'scores':{},
            'score_meaning':'not measured','load_seconds':None,'inference_seconds':None,
            'peak_rss_kib':None,**values}


def local_result(request,choice=None,status='success',metadata=None,error=None):
    return ProviderResult(choice,request.config.provider_id,request.run_id,response_id('LOCAL',request.run_id),
        status=status,input_tokens=None,output_tokens=None,simulated=False,metadata=metadata or diagnostics(request),
        error_kind=error,error_message='Local provider failed; staff review required' if error else None)


def forced_result(request):
    return local_result(request,request.allowed_choices[0],metadata=diagnostics(request,
        forced_choice=True,validation_outcome='accepted_deterministic',score_meaning='forced deterministic choice; no model score',
        load_seconds=0.0,inference_seconds=0.0,peak_rss_kib=0,inference_performed=False))


class LocalProvider:
    def __init__(self,python=None,worker=None):
        self.python=python or os.environ.get('COMMERCE_MODEL_PYTHON') or sys.executable
        self.worker=worker or Path(__file__).with_name('local_model_worker.py')

    def choose(self,request):
        if request.config.mode not in ('laya','gliclass'):raise ValueError('Local provider mode required')
        if len(request.allowed_choices)==1:return forced_result(request)
        started=time.monotonic();remaining=(request.deadline-datetime.now(timezone.utc)).total_seconds()
        if remaining<=0:return local_result(request,status='timeout',error='deadline_before_load')
        env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',
                 HF_HUB_DISABLE_TELEMETRY='1',CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='4',MKL_NUM_THREADS='4',
                 TOKENIZERS_PARALLELISM='false',LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false')
        payload={'family':request.config.mode,'revision':request.config.model_revision,'features':model_features(request)}
        process=None;metadata=diagnostics(request);status='unavailable';error='worker_start_failed';choice=None;confidence=None
        try:
            process=subprocess.Popen([self.python,'-B',str(self.worker)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,text=True,env=env,start_new_session=True)
            out,err=process.communicate(json.dumps(payload),timeout=remaining)
            if process.returncode:
                error='worker_exit';metadata['exit_code']=process.returncode
            else:
                try:
                    if len(out)>65536:raise ValueError('Oversized worker result')
                    raw=json.loads(out);metadata=raw['metadata'];status=raw['status'];choice=raw['choice']
                    error=raw.get('error_kind');confidence=raw.get('confidence')
                    checked=validate_result(request,local_result(request,choice,status,metadata,error))
                    choice=checked.selected_choice
                except (ValueError,KeyError,TypeError):
                    status='invalid';choice=None;error='malformed_worker_result';metadata=diagnostics(request)
        except subprocess.TimeoutExpired:
            status='timeout';error='deadline_including_load'
        except OSError:
            pass
        finally:
            if process is not None:
                # An exited parent may leave descendants holding its pipes. The
                # group is owned by this invocation, so always close it as well.
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.communicate(timeout=5)
                metadata['process_reaped']=process.poll() is not None
        elapsed=time.monotonic()-started
        metadata['validation_outcome']='accepted' if status=='success' else 'rejected' if status=='invalid' else 'failed'
        metadata['wall_seconds']=elapsed
        metadata['deadline_includes_loading']=True
        result=local_result(request,choice,status,metadata,error)
        from dataclasses import replace
        return replace(result,latency_ms=int(elapsed*1000),confidence=confidence)
