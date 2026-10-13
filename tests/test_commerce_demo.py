import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "data/commerce/eligible.json"


class DemoTests(unittest.TestCase):
    def run_demo(self, *args):
        return subprocess.run(
            [sys.executable, "-B", "-S", "-m", "decisionops.commerce.demo",
             *map(str, args), "--as-of", "2026-10-12T12:00:00Z"],
            cwd=ROOT, text=True, capture_output=True, timeout=10,
        )

    def test_success_writes_inspectable_artifact_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "assessment.json"
            result = self.run_demo(FIXTURE, "--output", output)
            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = json.loads(output.read_text())
            self.assertEqual(artifact["decision"]["status"], "eligible_to_propose")
            self.assertEqual(json.loads(result.stdout), artifact)
            before = output.read_bytes()
            retry = self.run_demo(FIXTURE, "--output", output)
            self.assertEqual(retry.returncode, 2)
            self.assertEqual(json.loads(retry.stderr)["event"], "input_error")
            self.assertEqual(output.read_bytes(), before)

    def test_stale_carrier_is_review_with_diagnostic_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stale.json"
            fixture = json.loads(FIXTURE.read_text())
            for item in fixture["observations"]:
                if item["requirement"] == "loss_confirmed":
                    item["observed_at"] = "2026-10-09T11:00:00Z"
            path.write_text(json.dumps(fixture))
            result = self.run_demo(path)
            self.assertEqual(result.returncode, 0, result.stderr)
            artifact = json.loads(result.stdout)
            self.assertEqual(artifact["decision"]["status"], "needs_review")
            self.assertEqual(artifact["issues"]["loss_confirmed"], ["stale"])
            self.assertFalse(artifact["evidence"]["loss_confirmed"][0]["accepted"])

    def test_invalid_boolean_reports_error_without_writing_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            output = Path(directory) / "assessment.json"
            fixture = json.loads(FIXTURE.read_text())
            fixture["observations"][0]["value"] = "true"
            path.write_text(json.dumps(fixture))
            result = self.run_demo(path, "--output", output)
            self.assertEqual(result.returncode, 2)
            self.assertIn("paid", json.loads(result.stderr)["error"])
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
