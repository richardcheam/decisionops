"""Evaluation artifacts must expose failures and never overwrite prior evidence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class EvaluationTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable,'-B','-m','decisionops.commerce.evaluation',*args],cwd=ROOT,text=True,capture_output=True,timeout=10)

    def test_report_and_zero_provider_cost(self):
        result = self.run_cli()
        self.assertEqual(result.returncode,0,result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['passed'],12)
        self.assertEqual(report['provider_calls'],0)
        self.assertEqual(report['cost_usd'],'0')
        self.assertEqual(report['evidence_level'],'hand_inspected_regression')

    def test_wrong_label_reports_nonzero_without_rewriting_truth(self):
        data = json.loads((ROOT/'data/commerce/regression-v1.json').read_text())
        data['cases'][0]['expected']['status']='ineligible'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'wrong-label.json'
            path.write_text(json.dumps(data))
            result = self.run_cli('--dataset',str(path))
        self.assertEqual(result.returncode,1,result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['failed'],1)
        self.assertEqual(report['results'][0]['actual']['status'],'eligible_to_propose')

    def test_existing_artifact_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'report.json'
            path.write_text('previous evidence')
            result=self.run_cli('--output',str(path))
            self.assertEqual(result.returncode,2)
            self.assertEqual(path.read_text(),'previous evidence')
