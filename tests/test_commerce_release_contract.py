"""Release verifier guard/failure tests; no Docker, HTTP, DB or credentials accessed."""
import contextlib,io,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,call
from scripts import commerce_portfolio_verify as v
class ReleaseVerifierTests(unittest.TestCase):
    def test_explicit_release_flag_required_before_any_operations(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(v,'OUT',Path(temp)),patch.object(v,'ENV',{'COMMERCE_PORTFOLIO_PASSWORD':'fictional-release-test-only'}),patch('sys.argv',['verify']),patch.object(v,'docker',side_effect=AssertionError('Must not touch existing projects')) as docker,contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):v.main()
            docker.assert_not_called()
    def test_restart_health_failure_still_restores_owned_worker(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(v,'OUT',Path(temp)),patch.object(v,'docker',side_effect=['stopped','started']) as docker,patch.object(v,'snapshot',return_value={}),patch.object(v.urllib.request,'urlopen',side_effect=OSError('Injected health failure')):
            with self.assertRaisesRegex(OSError,'Injected health failure'):v.restart_staff_worker()
            self.assertEqual(docker.call_args_list,[call(v.COMPOSE+['stop','staff-investigator']),call(v.COMPOSE+['start','staff-investigator'])])
            self.assertEqual((Path(temp)/'worker-restart.log').read_text(),'started')
