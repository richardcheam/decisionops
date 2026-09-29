"""Sequential scenario evaluation, replayable traces, and provenance reports."""

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import resource
import signal
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .backends import GLiClassActionRanker, LayaActionAgent, REPOSITORIES, parse_revision_pins
from .workflow import ACTION_IDS, ACTION_NAMES, EpisodeResult, run_episode
from .workflow_policies import (
    FixedOrderPolicy, GLiClassPolicy, LayaPolicy, RulesPolicy,
    WORKFLOW_LAYA_ACTION_DESCRIPTIONS, WORKFLOW_LAYA_INSTRUCTIONS,
)
from .workflow_scenarios import SCENARIO_FILE, Scenario, load_scenarios

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "reports" / "workflow-model-comparison-20260927"
DEFAULT_PINS = ROOT / "model-revisions.env"
POLICY_NAMES = ("fixed_order", "rules", "gliclass", "gliclass_evidence_masked", "laya", "laya_evidence_masked")
DEFAULT_WORKER_TIMEOUT_SECONDS = 600.0
WORKER_TERMINATION_GRACE_SECONDS = 2.0
WORKFLOW_CODE_FILES = (
    ROOT / "decisionops" / "workflow.py", ROOT / "decisionops" / "workflow_eval.py",
    ROOT / "decisionops" / "workflow_policies.py", ROOT / "decisionops" / "workflow_scenarios.py",
    ROOT / "decisionops" / "backends.py", ROOT / "decisionops" / "cli.py",
    ROOT / "decisionops" / "workflow_worker.py",
    ROOT / "data" / "build_workflow_scenarios.py",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str | None:
    result = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _package_versions() -> dict[str, str | None]:
    names = ("torch", "transformers", "gliclass", "huggingface-hub")
    versions = {"decisionops": tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def _peak_rss_bytes() -> int | None:
    if sys.platform != "linux":
        return None
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low, high = int(position), int(position + 0.999999999)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (position - low)


def _assertion_matches(observations: tuple[dict[str, Any], ...], assertion: dict[str, Any]) -> str | None:
    for observation in observations:
        if observation["tool_name"] != assertion["tool_name"] or observation["status"] != "success" or observation["time_scope"] != assertion["time_scope"]:
            continue
        if assertion["fact"] in observation["facts"] and observation["facts"][assertion["fact"]] == assertion["equals"]:
            return observation["observation_id"]
    return None


def has_acceptable_gold_evidence(scenario: Scenario, result: EpisodeResult) -> bool:
    if not scenario.acceptable_evidence:
        return scenario.gold_terminal_action == "request_review"
    if not result.cited_evidence_ids:
        return False
    cited = set(result.cited_evidence_ids)
    return any(
        all((obs_id := _assertion_matches(result.observations, assertion)) is not None and obs_id in cited for assertion in alternative)
        for alternative in scenario.acceptable_evidence
    )


def summarize_results(scenarios: list[Scenario], results: list[EpisodeResult]) -> dict[str, Any]:
    if len(scenarios) != len(results):
        raise ValueError("scenario and episode result counts differ")
    diagnosable = [index for index, scenario in enumerate(scenarios) if scenario.gold_terminal_action != "request_review"]
    review_required = [index for index, scenario in enumerate(scenarios) if scenario.gold_terminal_action == "request_review"]
    supported_correct = sum(
        results[index].terminal_action == scenarios[index].gold_terminal_action
        and results[index].terminal_reason == "completed"
        and has_acceptable_gold_evidence(scenarios[index], results[index])
        for index in diagnosable
    )
    correct_review = sum(results[index].terminal_action == "request_review" and results[index].terminal_reason == "review" for index in review_required)
    incorrect = sum(
        result.terminal_action in {"diagnose_database_failure", "diagnose_authentication_failure", "diagnose_disk_full", "diagnose_healthy"}
        and result.terminal_action != scenario.gold_terminal_action
        for scenario, result in zip(scenarios, results, strict=True)
    )
    latencies = [result.end_to_end_seconds for result in results]
    calls = [result.tool_call_count for result in results]
    status_counts = Counter(result.terminal_status for result in results)
    reason_counts = Counter(result.terminal_reason for result in results)
    terminal_status_counts = {key: status_counts.get(key, 0) for key in ("completed", "review", "failed")}
    terminal_reason_counts = {key: reason_counts.get(key, 0) for key in ("completed", "review", "exhausted_budget", "invalid_proposal", "tool_failure")}
    for key, value in reason_counts.items():
        terminal_reason_counts.setdefault(key, value)
    failed_episodes = terminal_status_counts["failed"]
    return {
        "episode_count": len(results), "scenario_count": len(scenarios),
        "run_status": "failed" if failed_episodes else "passed",
        "terminal_status_counts": terminal_status_counts, "terminal_reason_counts": terminal_reason_counts,
        "failed_episodes": failed_episodes,
        "diagnosable_count": len(diagnosable), "review_required_count": len(review_required),
        "correct_supported_diagnoses": supported_correct,
        "correct_supported_diagnosis_rate": supported_correct / len(diagnosable) if diagnosable else None,
        "correct_review_decisions": correct_review,
        "correct_review_decision_rate": correct_review / len(review_required) if review_required else None,
        "incorrect_diagnoses": incorrect,
        "unnecessary_review_on_diagnosable_cases": sum(results[index].terminal_action == "request_review" for index in diagnosable),
        "unsupported_diagnosis_proposals": sum(result.unsupported_diagnosis_proposals for result in results),
        "invalid_proposals_rejected": sum(result.invalid_proposals_rejected for result in results),
        "policy_execution_errors": sum(
            event["acceptance"]["reason"] == "policy_execution_error"
            for result in results for event in result.trace
        ),
        "budget_exhaustion_episodes": sum(result.terminal_reason == "exhausted_budget" for result in results),
        "tool_related_failures": sum(result.terminal_reason == "tool_failure" for result in results),
        "simulator_failures": sum(result.simulator_failure for result in results),
        "tool_calls": {"total": sum(calls), "per_episode_mean": sum(calls) / len(calls) if calls else None},
        "end_to_end_latency_seconds": {"sample_count": len(latencies), "mean": sum(latencies) / len(latencies) if latencies else None,
                                       "p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
    }


def _json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _atomic_json_write(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_worker_timeout(value: float) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("worker timeout must be a finite positive number of seconds") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("worker timeout must be a finite positive number of seconds")
    return timeout


class WorkflowEvaluationError(RuntimeError):
    def __init__(self, message: str, exit_code: int = 1):
        super().__init__(message)
        self.exit_code = exit_code


class CancellationRequest:
    """Signal-safe, single-threaded cancellation state shared with the supervisor."""

    def __init__(self):
        self.signum: int | None = None

    def request(self, signum: int) -> None:
        if self.signum is None:
            self.signum = signum


def _install_cancellation_handlers(request: CancellationRequest) -> dict[int, Any]:
    previous = {}

    def handler(signum, _frame):
        request.request(signum)

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, handler)
    return previous


def _restore_cancellation_handlers(previous: dict[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def _tail_text(path: Path, limit: int = 4000) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - limit))
            return stream.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _process_group_exists(process: subprocess.Popen) -> bool:
    if os.name != "posix":
        return process.poll() is None
    try:
        os.killpg(process.pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _signal_worker_group(process: subprocess.Popen, signum: int) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signum)
        elif process.poll() is None:
            process.send_signal(signum)
    except ProcessLookupError:
        pass


def _terminate_worker_group(process: subprocess.Popen, grace_seconds: float) -> None:
    _signal_worker_group(process, signal.SIGTERM)
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline and _process_group_exists(process):
        process.poll()
        time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
    if _process_group_exists(process):
        _signal_worker_group(process, signal.SIGKILL)
    try:
        process.wait(timeout=max(0.1, grace_seconds))
    except subprocess.TimeoutExpired:
        _signal_worker_group(process, signal.SIGKILL)
        process.wait()


def _supervise_worker_process(
    command: list[str], *, cwd: Path, env: dict[str, str], timeout_seconds: float,
    cancellation: CancellationRequest, stdout_path: Path, stderr_path: Path,
    termination_grace_seconds: float = WORKER_TERMINATION_GRACE_SECONDS,
) -> dict[str, Any]:
    """Run one worker with a monotonic deadline and bounded in-memory diagnostics."""
    timeout_seconds = validate_worker_timeout(timeout_seconds)
    started = time.monotonic()
    process = None
    outcome = "failed"
    reason = "worker_start_error"
    error = None
    try:
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(
                command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                stdout=stdout_file, stderr=stderr_file, start_new_session=(os.name == "posix"),
            )
            while process.poll() is None:
                if cancellation.signum is not None:
                    outcome = "cancelled"
                    reason = "sigint" if cancellation.signum == signal.SIGINT else "sigterm"
                    _terminate_worker_group(process, termination_grace_seconds)
                    break
                remaining = timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    outcome = "timed_out"
                    reason = "worker_timeout"
                    _terminate_worker_group(process, termination_grace_seconds)
                    break
                try:
                    process.wait(timeout=min(0.05, remaining))
                except subprocess.TimeoutExpired:
                    continue
            if process.poll() is not None and outcome == "failed":
                if cancellation.signum is not None:
                    outcome = "cancelled"
                    reason = "sigint" if cancellation.signum == signal.SIGINT else "sigterm"
                    _terminate_worker_group(process, termination_grace_seconds)
                elif time.monotonic() - started >= timeout_seconds:
                    outcome = "timed_out"
                    reason = "worker_timeout"
                    _terminate_worker_group(process, termination_grace_seconds)
                elif process.returncode == 0:
                    outcome = "completed"
                    reason = "completed"
                else:
                    outcome = "failed"
                    reason = "worker_exit"
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        if process is not None:
            _terminate_worker_group(process, termination_grace_seconds)
        if isinstance(exc, KeyboardInterrupt):
            cancellation.request(signal.SIGINT)
            outcome = "cancelled"
            reason = "sigint"
            error = None
        elif isinstance(exc, SystemExit):
            raise
    elapsed = time.monotonic() - started
    return {
        "status": outcome, "reason": reason, "returncode": process.returncode if process is not None else None,
        "elapsed_seconds": elapsed, "stdout": _tail_text(stdout_path), "stderr": _tail_text(stderr_path),
        **({"error": error} if error else {}),
    }


def _trace_text(events: tuple[dict[str, Any], ...]) -> str:
    return "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events)


def _evaluate_policy(name: str, scenarios: list[Scenario], policy, output_dir: Path) -> tuple[dict[str, Any], list[EpisodeResult], list[dict[str, Any]]]:
    trace_dir = output_dir / "traces" / name
    trace_dir.mkdir(parents=True, exist_ok=True)
    for old in trace_dir.glob("*.jsonl"):
        old.unlink()
    results, episode_rows = [], []
    for index, scenario in enumerate(scenarios, 1):
        split_order = sum(1 for prior in scenarios[:index - 1] if prior.split == scenario.split) + 1
        episode_id = f"{scenario.split[:3]}-{split_order:03d}"
        result = run_episode(scenario, policy, episode_id=episode_id)
        trace_path = trace_dir / f"{episode_id}.jsonl"
        trace_path.write_text(_trace_text(result.trace), encoding="utf-8")
        results.append(result)
        supported = has_acceptable_gold_evidence(scenario, result) if result.terminal_action == scenario.gold_terminal_action else False
        episode_rows.append({
            "episode_id": episode_id, "scenario_id": scenario.scenario_id, "split": scenario.split,
            "gold_terminal_action": scenario.gold_terminal_action, "terminal_action": result.terminal_action,
            "terminal_reason": result.terminal_reason, "gold_evidence_supported": supported,
            "tool_call_count": result.tool_call_count, "decision_count": result.decision_count,
            "end_to_end_seconds": result.end_to_end_seconds, "trace": str(trace_path.relative_to(output_dir)),
        })
    grouped = {}
    observed_splits = tuple(split for split in ("development", "evaluation") if any(item.split == split for item in scenarios))
    for split in observed_splits:
        indexes = [index for index, scenario in enumerate(scenarios) if scenario.split == split]
        grouped[split] = summarize_results([scenarios[index] for index in indexes], [results[index] for index in indexes])
        grouped[split]["model_loading_seconds"] = float(getattr(policy, "load_seconds", 0.0))
        grouped[split]["peak_process_rss_bytes"] = _peak_rss_bytes()
    summary = {
        "policy": name, "model_loading_seconds": float(getattr(policy, "load_seconds", 0.0)),
        "peak_process_rss_bytes": _peak_rss_bytes(),
        "run_status": "failed" if any(metrics["failed_episodes"] for metrics in grouped.values()) else "passed",
        "metrics_by_split": grouped,
        "episodes": episode_rows,
    }
    _json_write(output_dir / f"{name}-summary.json", summary)
    return summary, results, episode_rows


def _provenance(scenario_path: Path, pin_path: Path, split: str) -> dict[str, Any]:
    revisions = parse_revision_pins(pin_path)
    implementation = {str(path.relative_to(ROOT)): _sha256(path) for path in WORKFLOW_CODE_FILES}
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=False)
    dirty_paths = status.stdout.rstrip("\n").splitlines() if status.returncode == 0 else []
    try:
        python_packages = {"python": platform.python_version(), "platform": platform.platform(), "pytorch_threads": 4, "batch_size": 1, "device": "cpu", "offline": os.environ.get("HF_HUB_OFFLINE")}
    except Exception:
        python_packages = {}
    return {
        "git_head": _git("rev-parse", "HEAD"), "git_dirty": bool(dirty_paths), "git_dirty_paths": [line[3:] for line in dirty_paths],
        "implementation_sha256": implementation, "scenario_file": str(scenario_path.resolve()), "scenario_sha256": _sha256(scenario_path),
        "package_versions": _package_versions(), "runtime": python_packages,
        "models": {
            name: {"repository": REPOSITORIES[name][0], "revision": revisions[REPOSITORIES[name][1]], "device": "cpu"}
            for name in ("gliclass", "laya")
        },
        "action_candidate_representation": [{"id": action_id, "model_name": ACTION_NAMES[action_id]} for action_id in ACTION_IDS],
        "policy_order": list(POLICY_NAMES), "max_tool_calls": 4, "max_decisions": 6,
        "evaluation_scope": split,
        "split_counts": {split_name: 12 for split_name in (("development", "evaluation") if split == "all" else ("development",))},
        "evidence_masking": "Both evidence-masked model policies remove diagnoses rejected by check_terminal_evidence on visible state only",
        "laya_action_question": {
            "question_id": "next_action", "type": "choice", "instructions": WORKFLOW_LAYA_INSTRUCTIONS,
            "choices": [
                {"id": action_id, "name": ACTION_NAMES[action_id],
                 "description": WORKFLOW_LAYA_ACTION_DESCRIPTIONS[action_id]}
                for action_id in ACTION_IDS
            ],
            "input_format_note": "Laya receives its native named-choice question; GLiClass receives an ordered candidate-name list. The model-family comparison does not isolate architecture from native input format.",
        },
        "worker_isolation": {"model_families_sequential": True, "one_family_per_process": True,
                             "each_family_reuses_one_model_for_its_two_variants": True},
    }


def evaluate_model_family(model_family: str, scenario_path: Path, output_dir: Path, pin_path: Path, split: str) -> dict[str, Any]:
    """Run both variants of one family in this process, then report worker RSS."""
    if model_family not in {"gliclass", "laya"}:
        raise ValueError(f"unknown model family {model_family!r}")
    if split not in {"development", "all"}:
        raise ValueError("workflow evaluation split must be 'development' or 'all'")
    os.environ["HF_HUB_OFFLINE"] = "1"
    scenarios = [scenario for scenario in load_scenarios(scenario_path) if split == "all" or scenario.split == "development"]
    if model_family == "gliclass":
        model = GLiClassActionRanker(pin_path)
        model.load()
        policy_class = GLiClassPolicy
    else:
        model = LayaActionAgent(pin_path)
        model.load()
        policy_class = LayaPolicy
    names = (model_family, f"{model_family}_evidence_masked")
    policies = {name: policy_class(model, evidence_masked=index == 1) for index, name in enumerate(names)}
    summaries = {}
    for name in names:
        summary, _results, _episodes = _evaluate_policy(name, scenarios, policies[name], output_dir)
        summaries[name] = summary
    worker_rss = _peak_rss_bytes()
    for summary in summaries.values():
        summary["model_loading_seconds"] = float(model.load_seconds)
        summary["peak_process_rss_bytes"] = worker_rss
        for metrics in summary["metrics_by_split"].values():
            metrics["model_loading_seconds"] = float(model.load_seconds)
            metrics["peak_process_rss_bytes"] = worker_rss
        _json_write(output_dir / f"{summary['policy']}-summary.json", summary)
    return {"worker_status": "completed", "model_family": model_family,
            "model_loading_seconds": float(model.load_seconds), "peak_process_rss_bytes": worker_rss,
            "policy_names": list(names), "policies": summaries}


def _run_model_worker(
    model_family: str,
    split: str,
    output_dir: Path,
    scenario_path: Path,
    pin_path: Path,
    timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS,
    cancellation: CancellationRequest | None = None,
    command_factory=None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Run a model family in a clean child process and publish outputs only when complete."""
    timeout_seconds = validate_worker_timeout(timeout_seconds)
    cancellation = cancellation or CancellationRequest()
    stage_dir = Path(tempfile.mkdtemp(prefix=f".worker-{model_family}-", dir=output_dir))
    command = [
        sys.executable, "-m", "decisionops.workflow_worker", "--model-family", model_family,
        "--split", split, "--output-dir", str(stage_dir), "--scenario-file", str(scenario_path.resolve()),
        "--revision-file", str(pin_path.resolve()),
    ]
    if command_factory is not None:
        command = command_factory(stage_dir, model_family, split, scenario_path, pin_path)
    env = os.environ.copy()
    env["HF_HUB_OFFLINE"] = "1"
    try:
        process_status = _supervise_worker_process(
            command, cwd=ROOT, env=env, timeout_seconds=timeout_seconds, cancellation=cancellation,
            stdout_path=stage_dir / "stdout.log", stderr_path=stage_dir / "stderr.log",
        )
    except BaseException:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise
    process_returncode = process_status["returncode"]
    failure = process_status.get("error")
    if process_status["status"] in {"timed_out", "cancelled"}:
        failure = process_status["reason"]
    worker_file = stage_dir / "worker-summary.json"
    expected_names = (model_family, f"{model_family}_evidence_masked")
    worker_data = None
    if process_status["status"] == "completed" and worker_file.is_file():
        try:
            worker_data = json.loads(worker_file.read_text(encoding="utf-8"))
            expected_scenarios = [item for item in load_scenarios(scenario_path) if split == "all" or item.split == "development"]
            expected_by_split = {
                split_name: sum(item.split == split_name for item in expected_scenarios)
                for split_name in ("development", "evaluation") if any(item.split == split_name for item in expected_scenarios)
            }
            complete = (
                worker_data.get("worker_status") == "completed"
                and worker_data.get("model_family") == model_family
                and tuple(worker_data.get("policy_names", ())) == expected_names
                and all((stage_dir / f"{name}-summary.json").is_file() for name in expected_names)
                and all((stage_dir / "traces" / name).is_dir() for name in expected_names)
                and worker_data.get("model_loading_seconds", 0) > 0
                and worker_data.get("peak_process_rss_bytes", 0) > 0
                and all(len(worker_data["policies"][name]["episodes"]) == len(expected_scenarios) for name in expected_names)
                and all(set(worker_data["policies"][name]["metrics_by_split"]) == set(expected_by_split) for name in expected_names)
                and all(worker_data["policies"][name]["metrics_by_split"][split_name]["episode_count"] == expected_count
                        for name in expected_names for split_name, expected_count in expected_by_split.items())
                and all(len(list((stage_dir / "traces" / name).glob("*.jsonl"))) == len(expected_scenarios) for name in expected_names)
            )
            if not complete:
                failure = "worker output was incomplete or did not match its model family"
                worker_data = None
        except (OSError, json.JSONDecodeError, AttributeError, TypeError, KeyError, ValueError):
            failure = "worker summary was missing or malformed"
            worker_data = None
    elif process_status["status"] == "completed":
        failure = "worker exited without a complete result"
    elif process_status["status"] == "failed" and not failure:
        failure = f"worker exited with status {process_returncode}"
    success = worker_data is not None and failure is None and process_status["status"] == "completed"
    status_name = "completed" if success else ("failed" if process_status["status"] == "completed" else process_status["status"])
    status: dict[str, Any] = {
        "model_family": model_family, "status": status_name,
        "returncode": process_returncode, "worker_timeout_seconds": timeout_seconds,
        "elapsed_seconds": process_status["elapsed_seconds"], "termination_reason": process_status["reason"],
        "model_loading_seconds": worker_data.get("model_loading_seconds") if success else None,
        "peak_process_rss_bytes": worker_data.get("peak_process_rss_bytes") if success else None,
        "stdout": process_status["stdout"], "stderr": process_status["stderr"],
    }
    if failure:
        status["error"] = failure
        shutil.rmtree(stage_dir, ignore_errors=True)
        worker_dir = output_dir / "workers"
        worker_dir.mkdir(exist_ok=True)
        _json_write(worker_dir / f"{model_family}-process.json", status)
        return status, None
    try:
        (output_dir / "traces").mkdir(exist_ok=True)
        for name in expected_names:
            shutil.move(str(stage_dir / "traces" / name), str(output_dir / "traces" / name))
            shutil.move(str(stage_dir / f"{name}-summary.json"), str(output_dir / f"{name}-summary.json"))
        worker_dir = output_dir / "workers"
        worker_dir.mkdir(exist_ok=True)
        shutil.move(str(worker_file), str(worker_dir / f"{model_family}-worker.json"))
        _json_write(worker_dir / f"{model_family}-process.json", status)
    except Exception as exc:
        shutil.rmtree(stage_dir, ignore_errors=True)
        for name in expected_names:
            shutil.rmtree(output_dir / "traces" / name, ignore_errors=True)
            (output_dir / f"{name}-summary.json").unlink(missing_ok=True)
        status.update({"status": "failed", "error": f"failed to publish worker artifacts: {type(exc).__name__}: {exc}"})
        return status, None
    shutil.rmtree(stage_dir, ignore_errors=True)
    return status, worker_data["policies"]


def evaluate_suite(
    scenario_path: Path = SCENARIO_FILE, output_dir: Path = DEFAULT_OUTPUT_DIR, pin_path: Path = DEFAULT_PINS,
    split: str = "all", worker_timeout_seconds: float = DEFAULT_WORKER_TIMEOUT_SECONDS, *,
    _worker_command_factory=None,
) -> dict[str, Any]:
    worker_timeout_seconds = validate_worker_timeout(worker_timeout_seconds)
    if split not in {"development", "all"}:
        raise ValueError("workflow evaluation split must be 'development' or 'all'")
    if output_dir.exists():
        raise FileExistsError(f"report directory already exists; choose a fresh output directory: {output_dir}")
    output_dir = output_dir.resolve()
    os.environ["HF_HUB_OFFLINE"] = "1"
    scenarios = [scenario for scenario in load_scenarios(scenario_path) if split == "all" or scenario.split == "development"]
    output_dir.mkdir(parents=True)
    run_status = {"evaluation_execution_status": "running", "evaluation_scope": split,
                  "worker_timeout_seconds": worker_timeout_seconds,
                  "workers": {"gliclass": {"status": "pending", "worker_timeout_seconds": worker_timeout_seconds},
                              "laya": {"status": "pending", "worker_timeout_seconds": worker_timeout_seconds}}}
    cancellation = CancellationRequest()
    previous_handlers = _install_cancellation_handlers(cancellation)
    status_path = output_dir / "run-status.json"
    all_summaries: dict[str, Any] = {}
    policies = {"fixed_order": FixedOrderPolicy(), "rules": RulesPolicy()}
    try:
        _atomic_json_write(status_path, run_status)
        for name in ("fixed_order", "rules"):
            if cancellation.signum is not None:
                raise WorkflowEvaluationError("workflow evaluation cancelled", 130 if cancellation.signum == signal.SIGINT else 143)
            all_summaries[name], _results, _episodes = _evaluate_policy(name, scenarios, policies[name], output_dir)
        for model_family in ("gliclass", "laya"):
            if cancellation.signum is not None:
                raise WorkflowEvaluationError("workflow evaluation cancelled", 130 if cancellation.signum == signal.SIGINT else 143)
            run_status["workers"][model_family] = {
                "status": "running", "worker_timeout_seconds": worker_timeout_seconds,
            }
            _atomic_json_write(status_path, run_status)
            print(f"Starting isolated {model_family} worker", flush=True)
            status, summaries = _run_model_worker(
                model_family, split, output_dir, scenario_path, pin_path,
                timeout_seconds=worker_timeout_seconds, cancellation=cancellation,
                command_factory=_worker_command_factory,
            )
            run_status["workers"][model_family] = {key: status[key] for key in (
                "status", "returncode", "model_loading_seconds", "peak_process_rss_bytes", "error",
                "worker_timeout_seconds", "elapsed_seconds", "termination_reason",
            ) if key in status}
            _atomic_json_write(status_path, run_status)
            if summaries is not None:
                all_summaries.update(summaries)
            if status["status"] in {"timed_out", "cancelled"}:
                for remaining in ("gliclass", "laya"):
                    if run_status["workers"][remaining]["status"] == "pending":
                        run_status["workers"][remaining] = {
                            "status": "not_run", "worker_timeout_seconds": worker_timeout_seconds,
                            "termination_reason": status["termination_reason"],
                        }
                if status["status"] == "cancelled":
                    run_status["evaluation_execution_status"] = "cancelled"
                    run_status["cancellation_reason"] = status["termination_reason"]
                    run_status["termination_reason"] = status["termination_reason"]
                    exit_code = 130 if status["termination_reason"] == "sigint" else 143
                    message = f"workflow evaluation cancelled by {status['termination_reason']}"
                else:
                    run_status["evaluation_execution_status"] = "failed"
                    run_status["failure_reason"] = "worker_timeout"
                    run_status["termination_reason"] = "worker_timeout"
                    exit_code = 124
                    message = f"{model_family} worker exceeded {worker_timeout_seconds:g} second deadline"
                _atomic_json_write(status_path, run_status)
                _json_write(output_dir / "provenance.json", _provenance(scenario_path, pin_path, split))
                raise WorkflowEvaluationError(f"{message}; see {status_path}", exit_code)
        failed_workers = [name for name, status in run_status["workers"].items() if status["status"] != "completed"]
        provenance = _provenance(scenario_path, pin_path, split)
        _json_write(output_dir / "provenance.json", provenance)
        if failed_workers:
            run_status["evaluation_execution_status"] = "failed"
            run_status["failed_workers"] = failed_workers
            run_status["failure_reason"] = "worker_failure"
            _atomic_json_write(status_path, run_status)
            raise WorkflowEvaluationError(f"model evaluation worker(s) failed: {', '.join(failed_workers)}; see {status_path}")
        if cancellation.signum is not None:
            raise WorkflowEvaluationError("workflow evaluation cancelled", 130 if cancellation.signum == signal.SIGINT else 143)
        comparison = []
        for name in POLICY_NAMES:
            summary = all_summaries[name]
            for split_name, metrics in summary["metrics_by_split"].items():
                comparison.append({"policy": name, "split": split_name, **{key: metrics[key] for key in (
                    "episode_count", "run_status", "terminal_status_counts", "terminal_reason_counts", "failed_episodes",
                    "correct_supported_diagnoses", "diagnosable_count", "correct_review_decisions", "review_required_count",
                    "incorrect_diagnoses", "unnecessary_review_on_diagnosable_cases", "unsupported_diagnosis_proposals",
                    "invalid_proposals_rejected", "policy_execution_errors", "budget_exhaustion_episodes", "tool_related_failures",
                    "tool_calls", "end_to_end_latency_seconds",
                )}, "model_loading_seconds": summary["model_loading_seconds"], "peak_process_rss_bytes": summary["peak_process_rss_bytes"]})
        result = {"created_utc": datetime.now(timezone.utc).isoformat(), "scenario_sha256": _sha256(scenario_path),
                  "evaluation_scope": split, "evaluation_execution_status": "completed", "worker_status": run_status["workers"],
                  "provenance": provenance, "policies": all_summaries, "comparison": comparison}
        _json_write(output_dir / "all-summary.json", result)
        _write_comparison_markdown(output_dir / "all-summary.md", result)
        _write_example_trace(output_dir, all_summaries)
        if cancellation.signum is not None:
            raise WorkflowEvaluationError("workflow evaluation cancelled", 130 if cancellation.signum == signal.SIGINT else 143)
        run_status["evaluation_execution_status"] = "completed"
        _atomic_json_write(status_path, run_status)
        return result
    except BaseException as exc:
        if run_status["evaluation_execution_status"] == "running":
            if cancellation.signum is not None:
                signum = cancellation.signum
                run_status["evaluation_execution_status"] = "cancelled"
                run_status["cancellation_reason"] = "sigint" if signum == signal.SIGINT else "sigterm"
                run_status["termination_reason"] = run_status["cancellation_reason"]
                for name, worker in run_status["workers"].items():
                    if worker["status"] in {"pending", "running"}:
                        run_status["workers"][name] = {
                            "status": "cancelled" if worker["status"] == "running" else "not_run",
                            "worker_timeout_seconds": worker_timeout_seconds,
                            "termination_reason": run_status["cancellation_reason"],
                        }
                code = 130 if signum == signal.SIGINT else 143
                if not isinstance(exc, WorkflowEvaluationError):
                    exc = WorkflowEvaluationError("workflow evaluation cancelled", code)
            else:
                run_status["evaluation_execution_status"] = "failed"
                run_status["failure_reason"] = "evaluation_error"
                if isinstance(exc, KeyboardInterrupt):
                    run_status["evaluation_execution_status"] = "cancelled"
                    run_status["cancellation_reason"] = "sigint"
                    exc = WorkflowEvaluationError("workflow evaluation cancelled by Ctrl-C", 130)
            _atomic_json_write(status_path, run_status)
        if run_status["evaluation_execution_status"] != "completed":
            (output_dir / "all-summary.json").unlink(missing_ok=True)
            (output_dir / "all-summary.md").unlink(missing_ok=True)
        if exc is not None and not isinstance(exc, WorkflowEvaluationError):
            raise
        if isinstance(exc, WorkflowEvaluationError):
            raise exc
        raise
    finally:
        _restore_cancellation_handlers(previous_handlers)


def _write_example_trace(output_dir: Path, summaries: dict[str, Any]) -> None:
    trace_dir = output_dir / "examples"
    trace_dir.mkdir(parents=True, exist_ok=True)
    fixed = summaries["fixed_order"]["episodes"]
    episode = next(row for row in fixed if row["scenario_id"] == "dev-database-clear")
    source = output_dir / episode["trace"]
    (trace_dir / "fixed-order-database-example.jsonl").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def _write_comparison_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Recorded diagnostic workflow evaluation", "",
        "> Offline synthetic simulation. Fixture tools return recorded observations; no shell command, live service, or host action is executed.", "",
        "| Policy | Split | Episodes | Run | Terminal statuses (completed/review/failed) | Terminal reasons | Failed | Supported diagnoses | Correct reviews | Incorrect diagnoses | Unnecessary review | Unsupported proposals | Invalid proposals | Policy errors | Budget exhausted | Tool failures | Tool calls mean | Latency p50 / p95 | Model load | Peak RSS |",
        "|---|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["comparison"]:
        latency = row["end_to_end_latency_seconds"]
        statuses = row["terminal_status_counts"]
        reasons = ", ".join(f"{key}={value}" for key, value in row["terminal_reason_counts"].items())
        lines.append(
            f"| {row['policy']} | {row['split']} | {row['episode_count']} | {row['run_status']} | "
            f"{statuses['completed']}/{statuses['review']}/{statuses['failed']} | {reasons} | {row['failed_episodes']} | "
            f"{row['correct_supported_diagnoses']}/{row['diagnosable_count']} | "
            f"{row['correct_review_decisions']}/{row['review_required_count']} | {row['incorrect_diagnoses']} | "
            f"{row['unnecessary_review_on_diagnosable_cases']} | {row['unsupported_diagnosis_proposals']} | "
            f"{row['invalid_proposals_rejected']} | {row['policy_execution_errors']} | {row['budget_exhaustion_episodes']} | {row['tool_related_failures']} | "
            f"{row['tool_calls']['per_episode_mean']:.2f} | {latency['p50'] * 1000:.1f} / {latency['p95'] * 1000:.1f} ms | "
            f"{row['model_loading_seconds']:.2f} s | {row['peak_process_rss_bytes']} bytes |"
        )
    lines += ["", "`correct_supported_diagnoses` requires the terminal action to match the gold diagnosis, the harness to accept it, and cited visible evidence to match a gold evidence alternative. `correct_review_decisions` counts review outcomes for review-required scenarios. `incorrect_diagnoses` counts any terminal diagnosis different from the gold terminal action; `unnecessary_review_on_diagnosable_cases` counts review choices on diagnosable scenarios. Terminal-status counts and terminal-reason counts each sum to episode count. `failed_episodes` counts terminal status `failed`; `unsupported_diagnosis_proposals` counts evidence-check rejections, while `invalid_proposals_rejected` counts malformed, out-of-candidate, or otherwise harness-invalid outputs. `run_status` is failed whenever any episode fails. Policy execution errors and simulator failures are reported separately. Review-everything therefore has zero supported diagnoses and its unnecessary reviews remain visible. Tool fixture timeouts/errors are observations, not simulator failures.", "", "Policies receive the same scenario reports and harness action eligibility. The evidence-masked variant removes diagnoses unsupported by observations collected so far; this does not prove that unrequested tools contain no additional faults. Fixture execution latency is not live tool latency.", "", "See `provenance.json` for code/scenario hashes, package versions, model pin, runtime, candidate order, and budgets. Each policy summary has episode outcomes; `traces/` contains one JSONL replay trace per episode. `examples/fixed-order-database-example.jsonl` is a compact example.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def run_one_episode(scenario_id: str, policy_name: str, scenario_path: Path = SCENARIO_FILE, pin_path: Path = DEFAULT_PINS,
                    max_tool_calls: int = 4, max_decisions: int = 6) -> tuple[Scenario, EpisodeResult]:
    scenarios = load_scenarios(scenario_path)
    scenario = next((item for item in scenarios if item.scenario_id == scenario_id), None)
    if scenario is None:
        raise ValueError(f"unknown scenario ID {scenario_id!r}")
    if policy_name == "fixed_order":
        policy = FixedOrderPolicy()
    elif policy_name == "rules":
        policy = RulesPolicy()
    elif policy_name in {"gliclass", "gliclass_evidence_masked"}:
        ranker = GLiClassActionRanker(pin_path)
        ranker.load()
        policy = GLiClassPolicy(ranker, evidence_masked=policy_name == "gliclass_evidence_masked")
    elif policy_name in {"laya", "laya_evidence_masked"}:
        agent = LayaActionAgent(pin_path)
        agent.load()
        policy = LayaPolicy(agent, evidence_masked=policy_name == "laya_evidence_masked")
    else:
        raise ValueError(f"unknown policy {policy_name!r}")
    result = run_episode(scenario, policy, episode_id=f"{scenario.split[:3]}-one", max_tool_calls=max_tool_calls, max_decisions=max_decisions)
    return scenario, result
