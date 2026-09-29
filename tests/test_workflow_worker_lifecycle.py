"""Model-free tests for workflow worker process supervision."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from decisionops import workflow_eval


LINUX = sys.platform.startswith("linux")


class WorkerLifecycleTests(unittest.TestCase):
    def supervise(self, code, timeout=2.0, ready_path=None, grace=0.15):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        command = [sys.executable, "-u", "-c", code]
        result = workflow_eval._supervise_worker_process(
            command,
            cwd=root,
            env=os.environ.copy(),
            timeout_seconds=timeout,
            cancellation=workflow_eval.CancellationRequest(),
            stdout_path=root / "stdout.log",
            stderr_path=root / "stderr.log",
            termination_grace_seconds=grace,
        )
        return result, root

    def test_success_and_nonzero_exit_capture_bounded_diagnostics(self):
        result, _root = self.supervise("print('ready'); print('error', file=__import__('sys').stderr)")
        self.assertEqual(result["status"], "completed")
        self.assertIn("ready", result["stdout"])
        self.assertIn("error", result["stderr"])
        failed, _root = self.supervise("print('bad'); raise SystemExit(7)")
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["returncode"], 7)
        self.assertEqual(failed["reason"], "worker_exit")
        noisy, _root = self.supervise("print('x' * 10000)")
        self.assertLessEqual(len(noisy["stdout"]), 4000)

    def test_deadline_terminates_worker_and_records_elapsed_time(self):
        result, _root = self.supervise("import time; print('ready', flush=True); time.sleep(20)", timeout=0.25)
        self.assertEqual(result["status"], "timed_out")
        self.assertEqual(result["reason"], "worker_timeout")
        self.assertLess(result["elapsed_seconds"], 2)
        self.assertIn("ready", result["stdout"])

    @unittest.skipUnless(LINUX, "process-group escalation is Linux-specific")
    def test_ignoring_worker_and_descendant_are_killed_as_a_group(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            child_pid = root / "descendant.pid"
            code = (
                "import os, signal, subprocess, sys, time; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"child=subprocess.Popen([sys.executable, '-c', \"import os,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); open('{child_pid}', 'w').write(str(os.getpid())); time.sleep(30)\"]); "
                "print('ready', flush=True); time.sleep(30)"
            )
            result = workflow_eval._supervise_worker_process(
                [sys.executable, "-u", "-c", code], cwd=root, env=os.environ.copy(),
                timeout_seconds=0.25, cancellation=workflow_eval.CancellationRequest(),
                stdout_path=root / "stdout.log", stderr_path=root / "stderr.log",
                termination_grace_seconds=0.15,
            )
            self.assertEqual(result["status"], "timed_out")
            self.assertTrue(child_pid.exists(), "descendant did not complete its readiness handshake")
            pid = int(child_pid.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    @unittest.skipUnless(LINUX and hasattr(signal, "SIGTERM"), "requires Linux process signals")
    def test_evaluator_signal_finalizes_run_and_does_not_launch_next_worker(self):
        for requested_signal, expected_code in ((signal.SIGINT, 130), (signal.SIGTERM, 143)):
            with self.subTest(signal=requested_signal), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                output = root / "report"
                ready = root / "worker-ready"
                later_worker = root / "laya-started"
                child_script = root / "worker.py"
                child_script.write_text(
                    "import os,pathlib,sys,time; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(30)\n",
                    encoding="utf-8",
                )
                harness = r'''import json, pathlib, sys
from decisionops import workflow_eval as e
root=pathlib.Path(sys.argv[1]); ready=root/'worker-ready'; output=root/'report'; worker=root/'worker.py'; later=root/'laya-started'
def command_factory(stage, family, split, scenarios, pins):
    if family == 'laya': return [sys.executable, '-c', f"pathlib.Path({str(later)!r}).touch()"]
    return [sys.executable, str(worker), str(ready)]
try:
    e.evaluate_suite(output_dir=output, split='development', worker_timeout_seconds=10,
                     _worker_command_factory=command_factory)
except e.WorkflowEvaluationError as exc:
    raise SystemExit(exc.exit_code)
'''
                proc = subprocess.Popen(
                    [sys.executable, "-c", harness, str(root)], cwd=workflow_eval.ROOT,
                    env={**os.environ, "PYTHONPATH": str(workflow_eval.ROOT)},
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                )
                try:
                    deadline = time.monotonic() + 5
                    while not ready.exists() and time.monotonic() < deadline and proc.poll() is None:
                        time.sleep(0.02)
                    self.assertTrue(ready.exists(), "worker did not report readiness")
                    os.kill(proc.pid, requested_signal)
                    _stdout, stderr = proc.communicate(timeout=5)
                    self.assertEqual(proc.returncode, expected_code, stderr)
                    status = json.loads((output / "run-status.json").read_text())
                    self.assertEqual(status["evaluation_execution_status"], "cancelled")
                    self.assertEqual(status["cancellation_reason"], "sigint" if requested_signal == signal.SIGINT else "sigterm")
                    self.assertEqual(status["workers"]["gliclass"]["status"], "cancelled")
                    self.assertEqual(status["workers"]["laya"]["status"], "not_run")
                    self.assertFalse(later_worker.exists())
                    self.assertFalse((output / "all-summary.json").exists())
                    self.assertFalse((output / "all-summary.md").exists())
                finally:
                    if proc.poll() is None:
                        proc.send_signal(requested_signal)
                        try:
                            proc.communicate(timeout=3)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait(timeout=2)
                    if ready.exists():
                        try:
                            os.killpg(int(ready.read_text()), signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_timeout_marks_remaining_worker_not_run_and_withholds_aggregate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "report"
            launches = []
            old_int = signal.getsignal(signal.SIGINT)
            old_term = signal.getsignal(signal.SIGTERM)

            def command_factory(stage, family, split, scenarios, pins):
                launches.append(family)
                return [sys.executable, "-c", "import time; time.sleep(30)"]

            with self.assertRaises(workflow_eval.WorkflowEvaluationError) as caught:
                workflow_eval.evaluate_suite(output_dir=output, split="development", worker_timeout_seconds=0.25,
                                             _worker_command_factory=command_factory)
            self.assertEqual(caught.exception.exit_code, 124)
            self.assertEqual(launches, ["gliclass"])
            status = json.loads((output / "run-status.json").read_text())
            self.assertEqual(status["evaluation_execution_status"], "failed")
            self.assertEqual(status["workers"]["gliclass"]["status"], "timed_out")
            self.assertEqual(status["workers"]["laya"]["status"], "not_run")
            self.assertEqual(status["workers"]["gliclass"]["worker_timeout_seconds"], 0.25)
            self.assertGreater(status["workers"]["gliclass"]["elapsed_seconds"], 0)
            self.assertFalse((output / "all-summary.json").exists())
            self.assertIs(signal.getsignal(signal.SIGINT), old_int)
            self.assertIs(signal.getsignal(signal.SIGTERM), old_term)

    def test_completed_worker_artifacts_remain_as_partial_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "report"
            worker_script = root / "successful_worker.py"
            worker_script.write_text(
                """import json, pathlib, sys
p=pathlib.Path(sys.argv[1]); names=('gliclass','gliclass_evidence_masked'); policies={}
for name in names:
    traces=p/'traces'/name; traces.mkdir(parents=True)
    episodes=[{'scenario_id': str(i)} for i in range(12)]
    for i in range(12): (traces/f'{i:03}.jsonl').write_text('{}\\n')
    summary={'policy':name,'episodes':episodes,'metrics_by_split':{'development':{'episode_count':12}}}
    (p/f'{name}-summary.json').write_text(json.dumps(summary)); policies[name]=summary
data={'worker_status':'completed','model_family':'gliclass','policy_names':list(names),
      'model_loading_seconds':0.01,'peak_process_rss_bytes':1,'policies':policies}
(p/'worker-summary.json').write_text(json.dumps(data))
""",
                encoding="utf-8",
            )

            def command_factory(stage, family, *_args):
                if family == "gliclass":
                    return [sys.executable, str(worker_script), str(stage)]
                return [sys.executable, "-c", "import time; time.sleep(30)"]

            with self.assertRaises(workflow_eval.WorkflowEvaluationError):
                workflow_eval.evaluate_suite(
                    output_dir=output, split="development", worker_timeout_seconds=0.25,
                    _worker_command_factory=command_factory,
                )
            status = json.loads((output / "run-status.json").read_text())
            self.assertEqual(status["workers"]["gliclass"]["status"], "completed")
            self.assertEqual(status["workers"]["laya"]["status"], "timed_out")
            self.assertTrue((output / "workers/gliclass-worker.json").is_file())
            self.assertTrue((output / "gliclass-summary.json").is_file())
            self.assertTrue((output / "traces/gliclass/000.jsonl").is_file())
            self.assertFalse((output / "all-summary.json").exists())

    def test_cli_rejects_invalid_deadline_before_creating_output(self):
        from decisionops.cli import main

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "report"
            for value in ("0", "-2", "nan", "inf"):
                with self.subTest(value=value):
                    with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as caught:
                        main(["workflow", "evaluate", "--worker-timeout-seconds", value, "--output-dir", str(output)])
                    self.assertEqual(caught.exception.code, 2)
                    self.assertFalse(output.exists())

    def test_invalid_timeout_is_rejected_before_run_directory_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            for value in (0, -1, float("nan"), float("inf")):
                target = Path(temp) / f"run-{str(value)}"
                with self.subTest(value=value), self.assertRaises(ValueError):
                    workflow_eval.evaluate_suite(output_dir=target, worker_timeout_seconds=value)
                self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
