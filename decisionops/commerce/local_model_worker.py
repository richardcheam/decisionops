"""One offline CPU model family per process; JSON protocol contains no audit IDs."""
import os
# These must precede model-library imports, including transitive ones.
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',
    HF_HUB_DISABLE_TELEMETRY='1',CUDA_VISIBLE_DEVICES='',OMP_NUM_THREADS='4',MKL_NUM_THREADS='4',TOKENIZERS_PARALLELISM='false')
import contextlib
import json
from pathlib import Path
import resource
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from decisionops.commerce.local_provider import LABELS,INSTRUCTIONS
from decisionops.commerce.eligibility import REQUIREMENTS
from decisionops.backends import GLiClassActionRanker,LayaActionAgent,parse_revision_pins,REPOSITORIES,normalize_laya_result
from decisionops import CandidateSpec


def run(payload):
    family=payload['family'];revision=payload['revision'];features=payload['features']
    pins=Path(__file__).resolve().parents[2]/'model-revisions.env'
    if family not in REPOSITORIES or revision!=parse_revision_pins(pins)[REPOSITORIES[family][1]]:raise ValueError('Checkpoint pin mismatch')
    if set(features)!= {'task','facts','allowed_choices'} or features['task']!='route_investigated_case':raise ValueError('Invalid features')
    facts=features['facts'];choices=tuple(features['allowed_choices'])
    if set(facts)!=set(REQUIREMENTS) or any(v is not True for v in facts.values()) or choices!=tuple(LABELS):raise ValueError('Only all-true two-choice inputs require inference')
    text=INSTRUCTIONS+'\n'+'\n'.join(f'{key}: established true' for key in REQUIREMENTS)
    metadata={'model_revision':revision,'repository':REPOSITORIES[family][0],'forced_choice':False,
              'device':'cpu','threads':4,'batch_size':1,'inference_performed':True,
              'model_features':features,'load_seconds':None,'inference_seconds':None,'peak_rss_kib':None,'scores':{},'score_meaning':'not measured'}
    start=time.perf_counter()
    try:
        import torch
        torch.set_num_threads(4);torch.set_num_interop_threads(1)
        model=GLiClassActionRanker(pins) if family=='gliclass' else LayaActionAgent(pins)
        model.load();metadata['load_seconds']=time.perf_counter()-start
        begun=time.perf_counter()
        with torch.inference_mode():
            if family=='gliclass':
                scores=model.rank(text,[(key,LABELS[key]) for key in choices]);choice=max(scores,key=scores.get)
                confidence=None;metadata['score_meaning']='single-label softmax probabilities across allowed labels; uncalibrated'
            else:
                question={'commerce_route':{'type':'choice','instructions':INSTRUCTIONS,
                    'criteria':{LABELS[key]:('All requirements established; present the existing proposal for mandatory staff approval.' if key=='present_replacement' else 'Evidence is insufficient or contradictory; request staff review.') for key in choices}}}
                raw=model.predict(text,question)
                native=normalize_laya_result(raw,tuple(CandidateSpec(key,LABELS[key],'') for key in choices),answer_key='commerce_route')
                scores=native['scores'];choice=native['selected_class'];confidence=native['confidence']
                metadata['native_confidence']=native['confidence'];metadata['answer_confidence']=native['answer_confidence'];metadata['action_act_probability']=native['action_act_probability']
                metadata['score_meaning']='native Laya choice probabilities; confidence/action heads uncalibrated and not permission'
        metadata.update(scores=scores,inference_seconds=time.perf_counter()-begun)
        from importlib.metadata import version
        metadata['package_versions']={n:version(n) for n in ('torch','transformers','laya','gliclass','huggingface-hub')}
        return {'status':'success','choice':choice,'confidence':confidence,'metadata':metadata}
    except (ImportError,OSError,ValueError,RuntimeError) as error:
        if metadata['load_seconds'] is None:metadata['load_seconds']=time.perf_counter()-start
        elif metadata['inference_seconds'] is None:metadata['inference_seconds']=time.perf_counter()-begun
        return {'status':'unavailable','choice':None,'confidence':None,'error_kind':type(error).__name__,'metadata':metadata}
    finally:metadata['peak_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


if __name__=='__main__':
    try:
        payload=json.loads(sys.stdin.read(32768))
        with contextlib.redirect_stdout(sys.stderr):result=run(payload)
        print(json.dumps(result,allow_nan=False))
    except Exception as error:
        print(type(error).__name__,file=sys.stderr);raise SystemExit(2)
