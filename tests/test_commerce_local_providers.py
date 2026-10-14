"""Local contracts exercised without importing or downloading any model."""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from itertools import product
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_commerce_providers import request
from decisionops.commerce.providers import ProviderConfig,Pricing,ProviderResult,validate_result

class LocalContractTests(unittest.TestCase):
    def local_request(self,**kw):
        return request(config=ProviderConfig(mode='gliclass'),pricing=Pricing.local(),
                       deadline=datetime.now(timezone.utc)+timedelta(seconds=10),**kw)

    def test_zero_charge_unknown_usage_and_no_simulation(self):
        req=self.local_request()
        result=ProviderResult('present_replacement',req.config.provider_id,req.run_id,'LOCAL-1',
            input_tokens=None,output_tokens=None,simulated=False,metadata={
                'model_revision':req.config.model_revision,'forced_choice':False,
                'scores':{'present_replacement':0.8,'staff_review':0.2},
                'score_meaning':'single-label probabilities; uncalibrated',
                'load_seconds':1.0,'inference_seconds':0.2,'peak_rss_kib':2000})
        self.assertEqual(validate_result(req,result).selected_choice,'present_replacement')
        self.assertFalse(req.pricing.as_record()['simulated'])
        self.assertEqual(req.pricing.cost(1000,1000),0)
        for changes in ({'simulated':True},{'input_tokens':1},{'metadata':dict(result.metadata,scores={'execute':1})},
                        {'metadata':dict(result.metadata,model_revision='wrong')}):
            with self.assertRaises(ValueError):validate_result(req,replace(result,**changes))

    def test_features_exclude_identifiers_and_bindings(self):
        from decisionops.commerce.local_provider import model_features
        req=self.local_request();original=model_features(req)
        other=replace(req,case_id='OTHER',run_id='ANOTHER',binding=dict(req.binding,content_hash='c'*64))
        self.assertEqual(original,model_features(other))
        self.assertEqual(set(original),{'task','facts','allowed_choices'})

    def test_only_one_scored_boolean_input_exists(self):
        from decisionops.commerce.providers import permitted_choices
        from decisionops.commerce.eligibility import REQUIREMENTS
        scored=0
        for values in product((True,False,None),repeat=7):
            f=dict(zip(REQUIREMENTS,values));status='awaiting_review' if all(v is True for v in values) else 'needs_review'
            scored+=len(permitted_choices(f,status))>1
        self.assertEqual(scored,1)

    def test_sparse_snapshot_keeps_symlink_parent(self):
        from decisionops.backends import offline_model_path
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);(p/'snap').mkdir();(p/'blobs').mkdir();(p/'blobs'/'weight').write_text('fake')
            (p/'snap'/'model.safetensors').symlink_to(p/'blobs'/'weight')
            def cached(**args):
                self.assertTrue(args['local_files_only']);return str(p/'snap'/'model.safetensors')
            self.assertEqual(offline_model_path(cached,'repo','pin'),p/'snap')

    def test_forced_choice_does_not_start_process(self):
        from decisionops.commerce.local_provider import LocalProvider
        req=self.local_request();f=dict(req.facts,paid=None)
        req=replace(req,facts=f,allowed_choices=('staff_review',),binding=dict(req.binding,status='needs_review'))
        with patch('subprocess.Popen',side_effect=AssertionError('must not launch')):
            r=LocalProvider().choose(req)
        self.assertEqual(r.selected_choice,'staff_review');self.assertTrue(r.metadata['forced_choice'])
        self.assertIsNone(r.input_tokens)
        self.assertEqual(r.metadata['validation_outcome'],'accepted_deterministic')

    def test_bounded_worker_failure_and_timeout(self):
        from decisionops.commerce.local_provider import LocalProvider
        import sys
        req=self.local_request()
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'worker.py';p.write_text('import sys; sys.exit(7)')
            adapter=LocalProvider(python=sys.executable,worker=p)
            r=adapter.choose(req);self.assertEqual(r.status,'unavailable');self.assertFalse(r.simulated)
            p.write_text('import time; time.sleep(30)')
            req=replace(req,deadline=datetime.now(timezone.utc)+timedelta(seconds=.15))
            r=adapter.choose(req);self.assertEqual(r.status,'timeout');self.assertTrue(r.metadata['process_reaped'])

    def test_worker_malformed_or_override_fails_closed(self):
        from decisionops.commerce.local_provider import LocalProvider
        import sys
        req=self.local_request()
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'worker.py';p.write_text('print("not json")')
            r=LocalProvider(python=sys.executable,worker=p).choose(req)
            self.assertEqual(r.status,'invalid');self.assertIsNone(r.selected_choice)
            self.assertEqual(r.metadata['validation_outcome'],'rejected')

    def test_optional_modules_are_not_imported_by_contract(self):
        import subprocess,sys
        result=subprocess.run([sys.executable,'-B','-S','-c',
            "import sys;import decisionops.commerce.local_provider;assert not any(x in sys.modules for x in ('torch','transformers','laya','gliclass','huggingface_hub'))"],capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_timeout_reaps_exited_parent_with_living_descendant(self):
        from decisionops.commerce.local_provider import LocalProvider
        import sys
        req=self.local_request()
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'worker.py'
            p.write_text('import subprocess,sys\nsubprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])\n')
            req=replace(req,deadline=datetime.now(timezone.utc)+timedelta(seconds=.1))
            r=LocalProvider(python=sys.executable,worker=p).choose(req)
            self.assertEqual(r.status,'timeout');self.assertTrue(r.metadata['process_reaped'])

    def test_inference_failure_preserves_completed_load_timing(self):
        from decisionops.commerce import local_model_worker as worker
        from decisionops.commerce.local_provider import model_features
        from types import SimpleNamespace
        from contextlib import nullcontext
        class FailedRanker:
            def __init__(self,pins,model_revision=None):pass
            def load(self):pass
            def rank(self,*args):raise RuntimeError('inference failed')
        req=self.local_request()
        torch=SimpleNamespace(set_num_threads=lambda n:None,set_num_interop_threads=lambda n:None,inference_mode=nullcontext)
        with patch.dict('sys.modules',{'torch':torch}),patch.object(worker,'GLiClassActionRanker',FailedRanker),patch.object(worker.time,'perf_counter',side_effect=[0,1,2,3]):
            r=worker.run({'family':'gliclass','revision':req.config.model_revision,'features':model_features(req)})
        self.assertEqual(r['status'],'unavailable')
        self.assertEqual(r['metadata']['load_seconds'],1)
        self.assertEqual(r['metadata']['inference_seconds'],1)

    def test_rules_recommendation_uses_same_typed_validation_without_usage(self):
        from decisionops.commerce.providers import RulesProvider
        req=request(config=ProviderConfig(mode='rules'),pricing=Pricing.local())
        r=validate_result(req,RulesProvider().choose(req))
        self.assertEqual(r.selected_choice,'present_replacement');self.assertFalse(r.simulated)
        self.assertIsNone(r.input_tokens);self.assertIsNone(r.confidence)

    def test_recorded_revision_survives_pin_change_without_reading_current_pins(self):
        from decisionops.commerce import providers
        from decisionops.commerce.providers import ProviderRequest
        with tempfile.TemporaryDirectory() as root:
            pins=Path(root)/'pins.env';pins.write_text('GLICLASS_REV='+'a'*40+'\nLAYA_REV='+'c'*40+'\n')
            with patch.object(providers,'REVISION_FILE',pins):
                old=request(config=ProviderConfig(mode='gliclass'),pricing=Pricing.local())
                saved=old.as_record();pins.write_text('GLICLASS_REV='+'b'*40+'\nLAYA_REV='+'d'*40+'\n')
                with patch.object(providers,'configured_revision',side_effect=AssertionError('historical hydration must not read pins')):
                    hydrated=ProviderRequest.from_record(saved)
                self.assertEqual(hydrated.config.model_revision,'a'*40)
                self.assertEqual(hydrated.as_record(),saved)
                self.assertEqual(ProviderConfig(mode='gliclass').model_revision,'b'*40)
                with self.assertRaises(ValueError):ProviderConfig(mode='gliclass',model_revision='a'*40)
                with self.assertRaises(ValueError):request(config=hydrated.config,pricing=Pricing.local())
                saved['config']['model_revision']='main'
                with self.assertRaises(ValueError):ProviderRequest.from_record(saved)

    def test_stdout_overflow_is_detected_while_child_is_still_running(self):
        self.assert_overflow('stdout')

    def test_stderr_overflow_is_detected_while_child_is_still_running(self):
        self.assert_overflow('stderr')

    def assert_overflow(self,stream):
        from decisionops.commerce.local_provider import LocalProvider
        import sys,time
        with tempfile.TemporaryDirectory() as root:
            worker=Path(root)/'noisy.py'
            # Multibyte bytes overflow even though character count is below 64KiB.
            worker.write_text('import os,time\nos.write('+('1' if stream=='stdout' else '2')+', b"\\xc3\\xa9"*40000)\ntime.sleep(30)\n')
            begin=time.monotonic();r=LocalProvider(python=sys.executable,worker=worker).choose(self.local_request())
        self.assertEqual(r.error_kind,'worker_output_overflow')
        self.assertEqual(r.status,'invalid');self.assertIsNone(r.selected_choice)
        self.assertLess(time.monotonic()-begin,2)
        self.assertTrue(r.metadata['process_reaped'])
        self.assertEqual(r.metadata['overflow_stream'],stream)
        cap=r.metadata['stream_limits_bytes'][stream]
        self.assertEqual(r.metadata['stream_bytes_consumed'][stream],cap+1)
        self.assertLessEqual(r.metadata['stream_bytes_retained'][stream],cap)
        self.assertLessEqual(len(r.metadata['stream_diagnostics'][stream]),1024)

    def test_simultaneous_stream_overflow_drains_both_without_deadlock(self):
        from decisionops.commerce.local_provider import LocalProvider
        import sys
        with tempfile.TemporaryDirectory() as root:
            worker=Path(root)/'both.py'
            worker.write_text('import os,time,threading\ndef noisy(fd):\n for i in range(200):\n  os.write(fd,b"x"*4096);time.sleep(.001)\n time.sleep(30)\nthreading.Thread(target=noisy,args=(2,)).start()\nnoisy(1)\n')
            r=LocalProvider(python=sys.executable,worker=worker).choose(self.local_request())
        self.assertEqual(r.error_kind,'worker_output_overflow');self.assertTrue(r.metadata['process_reaped'])
        for stream in ('stdout','stderr'):
            self.assertGreater(r.metadata['stream_bytes_consumed'][stream],0)
            self.assertLessEqual(r.metadata['stream_bytes_retained'][stream],r.metadata['stream_limits_bytes'][stream])

    def test_closed_streams_do_not_hide_a_live_child_from_deadline(self):
        from decisionops.commerce.local_provider import LocalProvider
        import sys
        with tempfile.TemporaryDirectory() as root:
            worker=Path(root)/'closed.py';worker.write_text('import os,time\nos.close(1);os.close(2);time.sleep(30)\n')
            req=replace(self.local_request(),deadline=datetime.now(timezone.utc)+timedelta(seconds=.1))
            r=LocalProvider(python=sys.executable,worker=worker).choose(req)
        self.assertEqual(r.status,'timeout');self.assertTrue(r.metadata['process_reaped'])

    def test_both_streams_below_caps_are_drained_before_exit(self):
        from decisionops.commerce.local_provider import LocalProvider
        import sys
        with tempfile.TemporaryDirectory() as root:
            worker=Path(root)/'finite.py'
            worker.write_text('import os,threading\ndef output(fd):\n for i in range(12):os.write(fd,b"x"*4096)\nt=threading.Thread(target=output,args=(2,));t.start();output(1);t.join()\n')
            r=LocalProvider(python=sys.executable,worker=worker).choose(self.local_request())
        self.assertEqual(r.error_kind,'malformed_worker_result');self.assertTrue(r.metadata['process_reaped'])
        self.assertEqual(r.metadata['stream_bytes_consumed'],{'stdout':49152,'stderr':49152})

    def test_overflow_cleans_up_descendant_after_parent_exits(self):
        from decisionops.commerce.local_provider import LocalProvider
        import sys,time
        with tempfile.TemporaryDirectory() as root:
            worker=Path(root)/'descendant.py'
            worker.write_text('import subprocess,sys\nsubprocess.Popen([sys.executable,"-c","import os,time;os.write(2,b\\\"x\\\"*80000);time.sleep(30)"])\n')
            before=time.monotonic();r=LocalProvider(python=sys.executable,worker=worker).choose(self.local_request())
        self.assertEqual(r.error_kind,'worker_output_overflow');self.assertTrue(r.metadata['process_reaped'])
        self.assertLess(time.monotonic()-before,2)

    def test_cached_loaders_use_explicit_recorded_revision_not_rotated_file(self):
        from decisionops import backends
        from types import SimpleNamespace
        called=[]
        class Model:
            @classmethod
            def from_pretrained(cls,*a,**kw):return cls()
            def eval(self):pass
        fake_torch=SimpleNamespace(set_num_threads=lambda n:None)
        fake_hub=SimpleNamespace(hf_hub_download=lambda **kw:called.append(kw['revision']) or '/cached/snapshot/model.safetensors')
        fake_gli=SimpleNamespace(GLiClassModel=Model,ZeroShotClassificationPipeline=lambda *a,**kw:None)
        fake_transformers=SimpleNamespace(AutoTokenizer=Model)
        fake_laya=SimpleNamespace(load=lambda *a,**kw:None)
        with patch.dict('sys.modules',{'torch':fake_torch,'huggingface_hub':fake_hub,'gliclass':fake_gli,'transformers':fake_transformers,'laya':fake_laya}),patch.object(backends,'parse_revision_pins',side_effect=AssertionError('loader must not reread mutable pins')):
            backends.GLiClassActionRanker(Path('/configured/pins'),model_revision='a'*40).load()
            backends.LayaActionAgent(Path('/configured/pins'),model_revision='c'*40).load()
        self.assertEqual(called,['a'*40,'c'*40])

    def test_worker_forwards_admitted_revision_to_loader(self):
        from decisionops.commerce import local_model_worker as worker
        from decisionops.commerce.local_provider import model_features
        from types import SimpleNamespace
        from contextlib import nullcontext
        seen=[]
        class Ranker:
            def __init__(self,pins,model_revision=None):seen.append(model_revision)
            def load(self):pass
            def rank(self,*a):return {'present_replacement':.8,'staff_review':.2}
        torch=SimpleNamespace(set_num_threads=lambda n:None,set_num_interop_threads=lambda n:None,inference_mode=nullcontext)
        with patch.dict('sys.modules',{'torch':torch}),patch.object(worker,'GLiClassActionRanker',Ranker),patch.object(worker,'parse_revision_pins',return_value={'GLICLASS_REV':'a'*40,'LAYA_REV':'c'*40}),patch('importlib.metadata.version',return_value='model-free double'):
            r=worker.run({'family':'gliclass','revision':'a'*40,'features':model_features(self.local_request())})
        self.assertEqual(r['status'],'success');self.assertEqual(seen,['a'*40])
        self.assertEqual(r['metadata']['model_revision'],'a'*40)
