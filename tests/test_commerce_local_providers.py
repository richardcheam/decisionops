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
            def __init__(self,pins):pass
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
