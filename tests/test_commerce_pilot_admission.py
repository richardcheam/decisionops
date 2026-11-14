"""Model-free operator-pilot gate tests; no PostgreSQL or model load."""
import contextlib,importlib.util,json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

@unittest.skipUnless(importlib.util.find_spec('sqlalchemy'),'Requires existing commerce dependencies')
class PilotAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('pilot_script',os.environ.get('COMMERCE_PILOT_SCRIPT',str(root/'scripts/commerce_adaptive_evaluation.py')))
        cls.script=importlib.util.module_from_spec(spec);spec.loader.exec_module(cls.script);cls.script.ROOT=root
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        manifest=self.script.load_manifest()
        import hashlib
        data={'status':'complete','manifest_sha256':hashlib.sha256((self.script.ROOT/'data/commerce/adaptive-evaluation-v1/manifest.json').read_bytes()).hexdigest(),
              'results':[dict(mode=m,scenario=s['id'],admissible=True,unsafe_proposals=0) for m in ('fixed','cue','fake') for s in manifest['scenarios']]}
        self.baseline=self.root/'baseline.json';self.baseline.write_text(json.dumps(data))
        self.admin=MagicMock();self.admin.connect.return_value.__enter__.return_value.exec_driver_sql.return_value.one.return_value=('commerce_stage5_test','commerce_stage5',5432)
    def invoke(self,mode='pilot',family='laya',leaf=None,**mocks):
        args=['pilot-script','--mode',mode,'--family',family,'--baseline-summary',str(self.baseline),'--output',str(self.root/'experiment'/(leaf or family))]
        with patch.object(sys,'argv',args),patch.dict(os.environ,COMMERCE_TEST_DATABASE_URL='postgresql+psycopg://commerce_stage5:x@127.0.0.1:55441/commerce_stage5_test'),patch.object(self.script,'database_engine',return_value=self.admin),(patch.multiple(self.script,**mocks) if mocks else contextlib.nullcontext()):return self.script.main()
    def test_comparison_rejected_before_admission(self):
        with self.assertRaises(SystemExit) as e:self.invoke('comparison')
        self.assertEqual(e.exception.code,2);self.admin.connect.assert_not_called();self.assertFalse((self.root/'experiment').exists())
    def test_missing_or_wrong_manifest_baseline_cannot_admit(self):
        for data in ({'status':'complete','results':[]},{**json.loads(self.baseline.read_text()),'manifest_sha256':'wrong'}):
            self.baseline.write_text(json.dumps(data))
            with self.assertRaises(ValueError):self.invoke()
            self.assertFalse((self.root/'experiment/stage5-model-budget.json').exists())
    def test_unavailable_has_zero_dispatch_and_cannot_retry_family(self):
        execute=MagicMock(side_effect=AssertionError('Native dispatch'))
        self.assertEqual(self.invoke(memory=lambda:0,execute=execute),1);execute.assert_not_called()
        summary=json.loads((self.root/'experiment/laya/summary.json').read_text())
        self.assertEqual(summary['status'],'resource_unavailable_no_dispatch');self.assertEqual(summary['results'][0]['dispatch_count'],0)
        saved=(self.root/'experiment/stage5-model-budget.json').read_bytes()
        with self.assertRaises(ValueError):self.invoke(leaf='laya-retry',memory=lambda:99999,execute=execute)
        self.assertEqual((self.root/'experiment/stage5-model-budget.json').read_bytes(),saved)
    def test_only_one_fixture_explicitly_admitted_with_native_inference_required(self):
        row=dict(inferred_decisions=1,fallbacks=0,uncertain_calls=0,admissible=True,stop_reason=None,run_state='review')
        execute=MagicMock(return_value=(row,[]))
        self.assertEqual(self.invoke(memory=lambda:99999,execute=execute),0)
        self.assertEqual(execute.call_count,1);self.assertEqual(execute.call_args.args[2]['id'],'eligible');self.assertEqual(execute.call_args.kwargs,{'native_pilot':True})
        budget=json.loads((self.root/'experiment/stage5-model-budget.json').read_text());self.assertEqual(budget['pilots']['laya'],'passed')
    def test_fallback_only_failure_stops_experiment_without_new_family_dispatch(self):
        execute=MagicMock(return_value=(dict(inferred_decisions=0,fallbacks=1,uncertain_calls=0,admissible=True,stop_reason=None,run_state='review'),[]))
        self.assertEqual(self.invoke(memory=lambda:99999,execute=execute),1)
        saved=(self.root/'experiment/stage5-model-budget.json').read_bytes()
        with self.assertRaises(ValueError):self.invoke(family='gliclass',memory=lambda:99999,execute=execute)
        self.assertEqual(execute.call_count,1);self.assertEqual((self.root/'experiment/stage5-model-budget.json').read_bytes(),saved)
    def test_expired_persistent_ledger_rejected_unchanged(self):
        path=self.root/'experiment/stage5-model-budget.json';path.parent.mkdir()
        from decisionops.commerce.adaptive_evaluation import admit_experiment_budget
        admit_experiment_budget(path,Path('/proc/sys/kernel/random/boot_id').read_text().strip(),0.)
        before=path.read_bytes()
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(path.read_bytes(),before)
    def test_resource_sample_handles_exited_child_without_ignoring_live_unknown(self):
        for text,expected in [('State:\tS (sleeping)\nVmRSS:\t100 kB\nVmHWM:\t120 kB\n',120),('State:\tZ (zombie)\n',0)]:
            with patch.object(Path,'read_text',return_value=text):self.assertEqual(self.script.child_peak_rss(123),expected)
        with patch.object(Path,'read_text',return_value='State:\tS (sleeping)\n'):
            with self.assertRaises(ValueError):self.script.child_peak_rss(123)
    def test_sampler_failure_is_not_a_zero_memory_live_child(self):
        process=MagicMock();process.pid=123;process.poll.return_value=None
        with patch.object(self.script,'memory',side_effect=OSError('host sample failed')):
            with self.assertRaises(OSError):self.script.pilot_resource_sample(None)
        with patch.object(self.script,'memory',return_value=2048),patch.object(self.script,'child_peak_rss',side_effect=PermissionError('child sample failed')):
            with self.assertRaises(PermissionError):self.script.pilot_resource_sample(process)
            process.poll.return_value=0
            self.assertEqual(self.script.pilot_resource_sample(process),(2048,0))
