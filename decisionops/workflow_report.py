"""Load recorded workflow reports and export a self-contained offline viewer."""

import json
from pathlib import Path
from typing import Any

from .workflow import replay_trace

POLICY_NAMES = (
    "fixed_order", "rules", "gliclass", "gliclass_evidence_masked",
    "laya", "laya_evidence_masked",
)
_COMPARISON_FIELDS = (
    "episode_count", "run_status", "terminal_status_counts", "terminal_reason_counts", "failed_episodes",
    "correct_supported_diagnoses", "diagnosable_count", "correct_review_decisions", "review_required_count",
    "incorrect_diagnoses", "unnecessary_review_on_diagnosable_cases", "unsupported_diagnosis_proposals",
    "invalid_proposals_rejected", "policy_execution_errors", "budget_exhaustion_episodes", "tool_related_failures",
    "tool_calls", "end_to_end_latency_seconds", "model_loading_seconds", "peak_process_rss_bytes",
)
_GUIDED_EXAMPLES = (
    {
        "id": "blocked",
        "title": "A diagnosis the harness blocks",
        "description": "On dev-database-clear, unmasked Laya selects Database failure before any observation. The harness rejects it as unsupported, returns visible feedback, and rejects the retry. The episode ends failed with no diagnosis.",
        "split": "development", "scenario": "dev-database-clear", "policy": "laya",
        "compare_fixed_order": False,
    },
    {
        "id": "masked",
        "title": "Masking leaves a useful tool-first choice",
        "description": "On that same report, evidence-masked Laya scores Check database after unsupported diagnoses are removed. The recorded database check then supports the selected database diagnosis. Compare against the unmasked trace above.",
        "split": "development", "scenario": "dev-database-clear", "policy": "laya_evidence_masked",
        "compare_fixed_order": False,
    },
    {
        "id": "premature",
        "title": "Supported by one observation, premature for two faults",
        "description": "On eval-multiple-current-faults, masked Laya records database and authentication failures, then chooses Database failure. The visible database fact passes the harness check, while the evaluator labels this multiple-fault case for review. Fixed order requests review on the same scenario.",
        "split": "evaluation", "scenario": "eval-multiple-current-faults", "policy": "laya_evidence_masked",
        "compare_fixed_order": True,
    },
)


class ReportLoadError(ValueError):
    """A report is incomplete, inconsistent, malformed, or unsafe to export."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportLoadError(f"missing report file: {path.name}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportLoadError(f"cannot read valid JSON from {path.name}: {exc}") from exc


def _read_report_json(root: Path, name: str) -> Any:
    return _read_json(_report_file(root, name))


def _report_file(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ReportLoadError("trace path must be a relative path inside the report directory")
    try:
        path = (root / relative).resolve(strict=True)
        path.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ReportLoadError(f"trace path is missing or outside the report directory: {relative}") from exc
    if not path.is_file():
        raise ReportLoadError(f"trace path is not a file: {relative}")
    return path


def _trace_events(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        result = replay_trace(events)
    except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise ReportLoadError(f"invalid replay trace {path.name}: {exc}") from exc
    return events, result


def load_report(report_dir: Path | str) -> dict[str, Any]:
    """Load a completed six-policy report and validate every referenced replay trace."""
    try:
        root = Path(report_dir).resolve(strict=True)
    except OSError as exc:
        raise ReportLoadError(f"report directory does not exist: {report_dir}") from exc
    if not root.is_dir():
        raise ReportLoadError(f"not a report directory: {report_dir}")

    all_summary = _read_report_json(root, "all-summary.json")
    run_status = _read_report_json(root, "run-status.json")
    provenance = _read_report_json(root, "provenance.json")
    if not isinstance(all_summary, dict) or not isinstance(run_status, dict) or not isinstance(provenance, dict):
        raise ReportLoadError("report summaries and provenance must contain JSON objects")
    if all_summary.get("evaluation_execution_status") != "completed" or run_status.get("evaluation_execution_status") != "completed":
        raise ReportLoadError("evaluation execution did not complete successfully")
    worker_status = run_status.get("workers")
    if not isinstance(worker_status, dict) or any(
        not isinstance(worker_status.get(model), dict) or worker_status[model].get("status") != "completed"
        for model in ("gliclass", "laya")
    ):
        raise ReportLoadError("one or more model workers did not complete")

    rows = all_summary.get("comparison")
    if not isinstance(rows, list):
        raise ReportLoadError("all-summary.json has no comparison rows")
    if all_summary.get("evaluation_scope") not in {"all", "development"}:
        raise ReportLoadError("all-summary.json has an unsupported evaluation scope")
    row_index: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ReportLoadError("comparison rows must be objects")
        key = (row.get("policy"), row.get("split"))
        if not isinstance(key[0], str) or not isinstance(key[1], str):
            raise ReportLoadError("comparison policy and split names must be strings")
        if key in row_index:
            raise ReportLoadError(f"duplicate comparison row: {key}")
        row_index[key] = row
    expected_splits = ("development", "evaluation") if all_summary.get("evaluation_scope") == "all" else ("development",)
    if set(key[1] for key in row_index) != set(expected_splits):
        raise ReportLoadError("comparison splits do not match the report scope")
    if set(key[0] for key in row_index) != set(POLICY_NAMES) or len(row_index) != len(POLICY_NAMES) * len(expected_splits):
        raise ReportLoadError("comparison must contain one row per policy and split")

    policies: dict[str, Any] = {}
    evaluator: dict[str, dict[str, Any]] = {split: {} for split in expected_splits}
    reference_scenarios: dict[str, set[str]] | None = None
    for name in POLICY_NAMES:
        summary = _read_report_json(root, f"{name}-summary.json")
        if not isinstance(summary, dict) or summary.get("policy") != name:
            raise ReportLoadError(f"{name}-summary.json names a different policy")
        metrics_by_split = summary.get("metrics_by_split")
        episodes = summary.get("episodes")
        if not isinstance(metrics_by_split, dict) or set(metrics_by_split) != set(expected_splits) or not isinstance(episodes, list):
            raise ReportLoadError(f"{name}-summary.json has incomplete split metrics or episodes")
        for split in expected_splits:
            metrics = metrics_by_split[split]
            if not isinstance(metrics, dict):
                raise ReportLoadError(f"{name}-summary.json has malformed metrics for {split}")
            row = row_index[(name, split)]
            for field in _COMPARISON_FIELDS:
                source_value = metrics.get(field, summary.get(field) if field in {"model_loading_seconds", "peak_process_rss_bytes"} else None)
                if row.get(field) != source_value:
                    raise ReportLoadError(f"{name} {split} comparison field {field!r} disagrees with its policy summary")
        viewer_episodes: dict[str, dict[str, dict[str, Any]]] = {split: {} for split in expected_splits}
        counts = {split: 0 for split in expected_splits}
        for episode in episodes:
            if not isinstance(episode, dict):
                raise ReportLoadError(f"{name}-summary.json contains a malformed episode row")
            split, scenario_id = episode.get("split"), episode.get("scenario_id")
            if not isinstance(split, str) or split not in viewer_episodes or not isinstance(scenario_id, str) or not scenario_id:
                raise ReportLoadError(f"{name}-summary.json contains an unknown split or scenario")
            if scenario_id in viewer_episodes[split]:
                raise ReportLoadError(f"{name}-summary.json repeats scenario {scenario_id!r} in {split}")
            trace_path = _report_file(root, episode.get("trace"))
            events, replayed = _trace_events(trace_path)
            if replayed.get("terminal_action") != episode.get("terminal_action") or replayed.get("terminal_reason") != episode.get("terminal_reason"):
                raise ReportLoadError(f"{trace_path.name} terminal result disagrees with {name}-summary.json")
            viewer_episodes[split][scenario_id] = {
                "episode_id": episode.get("episode_id"),
                "events": events,
            }
            counts[split] += 1
            gold = {"gold_terminal_action": episode.get("gold_terminal_action")}
            entry = evaluator[split].setdefault(scenario_id, {"gold": gold, "policy_outcomes": {}})
            if entry["gold"] != gold:
                raise ReportLoadError(f"gold annotation differs between policies for scenario {scenario_id!r}")
            entry["policy_outcomes"][name] = {
                "terminal_action": episode.get("terminal_action"),
                "terminal_reason": episode.get("terminal_reason"),
                "gold_evidence_supported": episode.get("gold_evidence_supported"),
            }
        for split in expected_splits:
            metrics = metrics_by_split[split]
            if counts[split] != metrics.get("episode_count"):
                raise ReportLoadError(f"{name} {split} episode count disagrees with its summary")
        coverage = {split: set(viewer_episodes[split]) for split in expected_splits}
        if reference_scenarios is not None and coverage != reference_scenarios:
            raise ReportLoadError(f"{name}-summary.json does not cover the same scenarios as other policies")
        reference_scenarios = coverage
        policies[name] = {
            "metrics_by_split": metrics_by_split,
            "episodes": viewer_episodes,
            "model_loading_seconds": summary.get("model_loading_seconds", 0.0),
            "peak_process_rss_bytes": summary.get("peak_process_rss_bytes"),
        }
    return {
        "evaluation_execution_status": run_status["evaluation_execution_status"],
        "worker_status": worker_status,
        "evaluation_scope": all_summary.get("evaluation_scope"),
        "created_utc": all_summary.get("created_utc"),
        "comparison": rows,
        "policies": policies,
        "provenance": provenance,
        "evaluator": evaluator,
        "guided_examples": list(_GUIDED_EXAMPLES),
    }


def _safe_json(value: Any) -> str:
    """Keep data inside a script data block and safe from HTML parser termination."""
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("&", r"\u0026")
        .replace("<", r"\u003c")
        .replace(">", r"\u003e")
        .replace("\u2028", r"\u2028")
        .replace("\u2029", r"\u2029")
    )


def render_html(report: dict[str, Any]) -> str:
    """Render an offline viewer; dynamic report text is always inserted as text."""
    viewer_data = {
        key: report[key] for key in (
            "evaluation_execution_status", "worker_status", "evaluation_scope", "created_utc", "comparison", "policies",
            "provenance", "guided_examples",
        )
    }
    evaluator_data = report["evaluator"]
    template = _HTML_TEMPLATE
    return template.replace("__VIEWER_DATA__", _safe_json(viewer_data)).replace("__EVALUATOR_DATA__", _safe_json(evaluator_data))


def export_report(report_dir: Path | str, output: Path | str) -> Path:
    """Export a validated report without writing into or changing its source directory."""
    root = Path(report_dir).resolve(strict=True)
    destination = Path(output).resolve()
    try:
        destination.relative_to(root)
    except ValueError:
        pass
    else:
        raise ReportLoadError("HTML output must be outside the source report directory")
    report = load_report(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_html(report), encoding="utf-8")
    return destination


_HTML_TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DecisionOps · Recorded workflow investigation</title>
<style>
:root{color-scheme:light;--ink:#17212b;--muted:#526271;--paper:#f4f6f8;--panel:#fff;--line:#cbd4dc;--navy:#173c5a;--blue:#175d8c;--red:#8b2424;--green:#17603a;--amber:#704a00}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
header,main{width:min(1200px,calc(100% - 32px));margin-inline:auto}header{padding:24px 0 12px}h1{font-size:clamp(1.6rem,3vw,2.2rem);line-height:1.15;margin:.1rem 0 .7rem;color:#102d45}h2{font-size:1.25rem;margin:0 0 .6rem}h3{font-size:1.05rem;margin:0 0 .45rem}p{margin:.35rem 0}.banner{padding:14px 16px;background:#e8f0f6;border-left:5px solid var(--navy);border-radius:5px}.banner strong{display:block}.warning{background:#fff3d5;border-color:#805400}
main{padding-bottom:42px}.section{margin:18px 0;padding:18px;background:var(--panel);border:1px solid var(--line);border-radius:8px;box-shadow:0 1px 2px #1423330d}.section-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}.muted{color:var(--muted)}.eyebrow{text-transform:uppercase;letter-spacing:.07em;font-size:.76rem;font-weight:750;color:var(--muted)}
.tabs,.guided{display:flex;gap:8px;flex-wrap:wrap}.tabs button,.guided button{font:inherit;font-weight:650;border:1px solid #8798a7;background:#fff;color:#183750;border-radius:6px;padding:8px 12px;cursor:pointer}.tabs button[aria-pressed=true]{background:var(--navy);border-color:var(--navy);color:white}button:hover{border-color:var(--blue)}button:focus-visible,select:focus-visible,input:focus-visible,summary:focus-visible{outline:3px solid #e39d17;outline-offset:2px}
.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:14px}.metric-card{border:1px solid var(--line);border-radius:7px;padding:13px;background:#fff}.metric-card h3{overflow-wrap:anywhere}.status{font-size:.82rem;font-weight:750;border-radius:99px;padding:2px 8px;background:#e8edf1;color:#243544}.status.passed{background:#e2f3e8;color:#14552f}.status.failed{background:#fae7e5;color:#7a1d1d}.metric-list{display:grid;grid-template-columns:1fr auto;gap:2px 10px;margin:.5rem 0 0}.metric-list dt{color:var(--muted)}.metric-list dd{margin:0;text-align:right;font-variant-numeric:tabular-nums}.controls{display:grid;grid-template-columns:minmax(180px,1fr) minmax(200px,1.2fr) auto;align-items:end;gap:14px;margin:16px 0}.field label{display:block;font-weight:700;margin-bottom:4px}.field select{width:100%;font:inherit;padding:8px;border:1px solid #8999a7;border-radius:5px;background:white;color:var(--ink)}.check{display:flex;gap:8px;align-items:center;padding:8px 0}.check input{width:18px;height:18px}
.guided{margin:12px 0}.guided button{text-align:left;flex:1 1 230px}.guided button span{display:block;font-size:.84rem;font-weight:450;color:var(--muted)}.timeline{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr));gap:14px}.track{min-width:0;border:1px solid var(--line);border-radius:8px;padding:14px;background:#f9fbfc}.step{margin:10px 0;padding:13px;background:#fff;border:1px solid var(--line);border-radius:7px}.step h4{font-size:1rem;margin:0 0 8px}.step-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.step-block{min-width:0;border-top:1px solid #e2e7eb;padding-top:7px}.step-block strong{display:block;font-size:.84rem;color:#334958}.step-block p{overflow-wrap:anywhere}.observation{margin:5px 0;padding:7px 9px;background:#f1f5f7;border-radius:4px}.observation code,.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.88em;overflow-wrap:anywhere}.fact{white-space:pre-wrap;overflow-wrap:anywhere;font: .83rem/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;margin:4px 0}.accept{font-weight:750}.accept.reject{color:var(--red)}.accept.yes{color:var(--green)}.raw{margin-top:9px}.raw summary{cursor:pointer;color:#154e74;font-weight:650}.raw pre{max-height:380px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;background:#eef2f5;padding:10px;border-radius:5px;font:12px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}
.evaluator{border:2px solid #7b4e00;background:#fff9e9}.evaluator h2{color:#593b00}.gold{padding:12px;background:#fff;border:1px solid #cda958;border-radius:6px}.small{font-size:.9rem}.status-line{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.divider{border:0;border-top:1px solid var(--line);margin:18px 0}.footer{font-size:.9rem;color:var(--muted)}
@media(max-width:760px){.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.controls{grid-template-columns:1fr}.section{padding:14px}}@media(max-width:480px){header,main{width:min(100% - 20px,1200px)}.cards{grid-template-columns:1fr}.step-grid{grid-template-columns:1fr}.section{padding:12px}}
@media print{body{background:white}.section{box-shadow:none;break-inside:avoid}.controls,.guided,.tabs{display:none}.timeline{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<header>
<p class="eyebrow">DecisionOps · offline evaluation artifact</p>
<h1>Recorded workflow investigation</h1>
<div class="banner warning"><strong>Offline synthetic simulation</strong>This viewer uses inspected synthetic scenarios and recorded fixture observations. It does not contact live systems. Fixture timing is not live tool latency. Model scores and confidence values are uncalibrated.</div>
</header>
<main>
<section class="section" aria-labelledby="execution-title">
<div class="section-head"><h2 id="execution-title">Evaluation execution</h2><span id="execution-status" class="status"></span></div>
<p id="execution-detail" class="muted"></p>
</section>
<section class="section" aria-labelledby="comparison-title">
<div class="section-head"><h2 id="comparison-title">Six-policy comparison</h2><span class="eyebrow">Termination and correctness are separate</span></div>
<div id="split-tabs" class="tabs" role="group" aria-label="Comparison split"></div>
<div id="comparison-cards" class="cards"></div>
</section>
<section class="section" aria-labelledby="investigation-title">
<h2 id="investigation-title">Trace investigation</h2>
<p class="muted">Each timeline step shows the policy-visible state and the harness response. Gold labels and evaluator annotations are kept in the separate evaluator-only section below.</p>
<div id="guided-examples" class="guided" aria-label="Guided examples"></div>
<div class="controls">
<div class="field"><label for="scenario-select">Scenario</label><select id="scenario-select"></select></div>
<div class="field"><label for="policy-select">Policy</label><select id="policy-select"></select></div>
<label class="check"><input id="compare-fixed" type="checkbox"><span>Compare with fixed order</span></label>
</div>
<div id="trace-heading" class="status-line"></div>
<div id="timeline" class="timeline"></div>
</section>
<section class="section evaluator" aria-labelledby="evaluator-title">
<p class="eyebrow">Evaluator only · not available to a policy</p>
<h2 id="evaluator-title">Gold outcome and scored result</h2>
<p class="small">The gold terminal action and evidence annotations below were used only after the episode. Scenario IDs are report navigation labels. Unrequested fixture observations are not shown to the policy in any timeline.</p>
<div id="evaluator-outcome" class="gold"></div>
</section>
<section class="section" aria-labelledby="method-title"><h2 id="method-title">What is deterministic here?</h2>
<p>Candidate eligibility, evidence masking, budgets, fixture responses, evidence checks, proposal acceptance, and terminal accounting are harness behavior. Learned policies choose from their scored candidates. Fixed order follows its documented tool sequence and is deterministic.</p>
<p>“Completed” describes episode termination only. It does not mean the outcome matched the evaluator. Supported diagnoses and correct reviews have explicit denominators in the comparison cards. Candidate scores, native probabilities, confidence, and action probability are recorded metadata, not calibrated confidence or permission to act.</p>
<p>GLiClass and Laya receive different native input formats, so this comparison does not isolate model architecture. These inspected synthetic regression scenarios are not a production accuracy estimate.</p>
<p id="provenance" class="footer"></p><div id="provenance-details"></div></section>
</main>
<script id="viewer-data" type="application/json">__VIEWER_DATA__</script>
<script id="evaluator-data" type="application/json">__EVALUATOR_DATA__</script>
<script>
"use strict";
const DATA=JSON.parse(document.getElementById("viewer-data").textContent);
const EVALUATOR=JSON.parse(document.getElementById("evaluator-data").textContent);
const LABELS={fixed_order:"Fixed order",rules:"Rules",gliclass:"GLiClass",gliclass_evidence_masked:"GLiClass · evidence masked",laya:"Laya",laya_evidence_masked:"Laya · evidence masked"};
const ACTIONS={check_database:"Check database",check_authentication:"Check authentication",check_storage:"Check storage",check_service_health:"Check service health",diagnose_database_failure:"Database failure",diagnose_authentication_failure:"Authentication failure",diagnose_disk_full:"Disk full",diagnose_healthy:"Healthy",request_review:"Request review"};
let selectedSplit="development";
let selectedScenario="dev-database-clear",selectedPolicy="laya";
const byId=id=>document.getElementById(id);
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined&&text!==null)e.textContent=String(text);if(cls)e.className=cls;return e}
function add(parent,tag,text,cls){const e=node(tag,text,cls);parent.append(e);return e}
function metricLine(parent,label,value){add(parent,"dt",label);add(parent,"dd",value)}
function renderExecution(){const s=byId("execution-status");s.textContent=DATA.evaluation_execution_status;s.className="status "+DATA.evaluation_execution_status;const workers=Object.entries(DATA.worker_status||{}).map(([name,value])=>name+": "+value.status).join(" · ");byId("execution-detail").textContent="Model worker status: "+workers+". Individual policy run status and episode outcomes are separate."}
function renderComparison(){const tabs=byId("split-tabs");tabs.replaceChildren();for(const split of ["development","evaluation"]){if(!DATA.comparison.some(x=>x.split===split))continue;const b=node("button",split==="development"?"Development":"Evaluation");b.type="button";b.setAttribute("aria-pressed",String(selectedSplit===split));b.addEventListener("click",()=>{selectedSplit=split;renderComparison();renderScenarioOptions();renderInvestigation()});tabs.append(b)}
 const cards=byId("comparison-cards");cards.replaceChildren();for(const policy of Object.keys(LABELS)){const m=DATA.policies[policy].metrics_by_split[selectedSplit];if(!m)continue;const card=add(cards,"article",undefined,"metric-card");const head=add(card,"div",undefined,"section-head");add(head,"h3",LABELS[policy]);add(head,"span","Policy run status: "+m.run_status,"status "+m.run_status);
 const dl=add(card,"dl",undefined,"metric-list"),st=m.terminal_status_counts,lat=m.end_to_end_latency_seconds;
 metricLine(dl,"Episodes",m.episode_count);metricLine(dl,"Termination: completed / review / failed",st.completed+" / "+st.review+" / "+st.failed);
 metricLine(dl,"Supported diagnoses",m.correct_supported_diagnoses+" / "+m.diagnosable_count);metricLine(dl,"Correct reviews",m.correct_review_decisions+" / "+m.review_required_count);
 metricLine(dl,"Incorrect diagnoses",m.incorrect_diagnoses);metricLine(dl,"Unnecessary reviews",m.unnecessary_review_on_diagnosable_cases);
 metricLine(dl,"Unsupported proposals",m.unsupported_diagnosis_proposals);metricLine(dl,"Tool calls (mean)",Number(m.tool_calls.per_episode_mean).toFixed(2));
 metricLine(dl,"Episode latency (mean)",Number(lat.mean).toFixed(3)+" s");metricLine(dl,"Model load",Number(DATA.policies[policy].model_loading_seconds||0).toFixed(2)+" s");
 const rss=DATA.policies[policy].peak_process_rss_bytes;metricLine(dl,"Worker peak RSS",rss?Math.round(rss/1048576)+" MiB":"not recorded");details(card,"Terminal reasons",m.terminal_reason_counts);
 details(card,"Latency p50 / p95",lat);
 }}
function renderScenarioOptions(){const select=byId("scenario-select"),scenarios=EVALUATOR[selectedSplit]||{};select.replaceChildren();for(const id of Object.keys(scenarios).sort()){const o=node("option",id);o.value=id;select.append(o)}if(!scenarios[selectedScenario])selectedScenario=Object.keys(scenarios).sort()[0]||"";select.value=selectedScenario}
function details(parent,label,value){const d=add(parent,"details",undefined,"raw"),s=add(d,"summary",label),pre=add(d,"pre");pre.textContent=JSON.stringify(value,null,2);return d}
function renderObservation(parent,obs){const box=add(parent,"div",undefined,"observation");add(box,"strong",(obs.observation_id||"Observation")+" · "+(obs.tool_name||"tool"));add(box,"p",(obs.status||"")+" · "+(obs.time_scope||"")+" · "+(obs.observed_at||""));if(obs.message)add(box,"p",obs.message);add(box,"pre",JSON.stringify(obs.facts||{},null,2),"fact")}
function renderTrack(container,policy){const ep=DATA.policies[policy]?.episodes?.[selectedSplit]?.[selectedScenario];const track=add(container,"section",undefined,"track");add(track,"h3",LABELS[policy]||policy);if(!ep){add(track,"p","No trace was recorded for this policy and scenario.","muted");return}
 for(const event of ep.events){if(event.event_type!=="decision"){const box=add(track,"article",undefined,"step");add(box,"h4","Harness termination");add(box,"p",event.acceptance?.detail||event.acceptance?.reason||"No detail");const terminal=event.terminal_decision||{};add(box,"p","Episode termination: "+(terminal.status||"unknown")+" · "+(terminal.reason||event.acceptance?.reason||"unknown"));add(box,"p","Terminal action: "+(ACTIONS[terminal.action_id]||terminal.action_id||"none"));details(box,"Raw event",event);continue}
 const before=event.visible_state_before||{},proposal=event.proposal||{},acceptance=event.acceptance||{},after=event.visible_state_after||{};
 const step=add(track,"article",undefined,"step");add(step,"h4","Step "+event.step_id);
 const grid=add(step,"div",undefined,"step-grid");
 let block=add(grid,"div",undefined,"step-block");add(block,"strong","Initial report");add(block,"p",before.initial_report||"");
 block=add(grid,"div",undefined,"step-block");add(block,"strong","Budgets before action");add(block,"p","Tool calls: "+before.remaining_tool_calls+" / "+before.max_tool_calls+" · Decisions: "+before.remaining_decisions+" / "+before.max_decisions);
 block=add(grid,"div",undefined,"step-block");add(block,"strong","Observations available to policy");const observations=before.observations||[];if(!observations.length)add(block,"p","None recorded yet.","muted");for(const obs of observations)renderObservation(block,obs);
 block=add(grid,"div",undefined,"step-block");add(block,"strong","Proposed action");const action=proposal.action_id;add(block,"p",(ACTIONS[action]||action||"No action recorded")+" · "+(action||"malformed or missing proposal"));
 block=add(grid,"div",undefined,"step-block");add(block,"strong","Scored candidates");const candidates=event.scored_candidate_ids||[];add(block,"p",candidates.length?candidates.map(x=>ACTIONS[x]||x).join(", "):"No scored candidates recorded for this step.");if(proposal.scores)add(block,"pre",JSON.stringify(proposal.scores,null,2),"fact");if(proposal.scores)add(block,"p","Scores and native probabilities are uncalibrated.","muted");
 block=add(grid,"div",undefined,"step-block");add(block,"strong","Masked or otherwise excluded candidates and reasons");const excluded=event.excluded_candidates||{};if(Object.keys(excluded).length)add(block,"pre",JSON.stringify(excluded,null,2),"fact");else add(block,"p","None recorded.","muted");
 block=add(grid,"div",undefined,"step-block");add(block,"strong","Harness acceptance");add(block,"p",(acceptance.accepted?"Accepted":"Rejected")+" · "+(acceptance.reason||"unknown"),"accept "+(acceptance.accepted?"yes":"reject"));if(acceptance.detail)add(block,"p",acceptance.detail);if(after.rejection_feedback?.length)add(block,"p","Visible rejection feedback: "+after.rejection_feedback.join("; "));
 block=add(grid,"div",undefined,"step-block");add(block,"strong","Returned fixture observation");if(event.tool_observation)renderObservation(block,event.tool_observation);else add(block,"p","No observation returned for this action.","muted");
 block=add(grid,"div",undefined,"step-block");add(block,"strong","Remaining budgets after action");const rb=event.remaining_budgets||{};add(block,"p","Tool calls: "+(rb.tool_calls??after.remaining_tool_calls)+" · Decisions: "+(rb.decisions??after.remaining_decisions));
 if(after.terminal_status&&after.terminal_status!=="in_progress"){block=add(grid,"div",undefined,"step-block");add(block,"strong","Terminal result");add(block,"p","Episode termination: "+after.terminal_status+" · "+after.terminal_reason);add(block,"p","Action: "+(ACTIONS[after.terminal_action]||after.terminal_action||"none"))}
 if(proposal.native_metadata)add(step,"p","Native metadata recorded; details are in raw data.","muted");
 details(step,"Expand raw event, scores, policy input, and native metadata",event);
 }
}
function renderInvestigation(){const heading=byId("trace-heading");heading.replaceChildren();const badge=add(heading,"span",selectedSplit,"status");add(heading,"span",selectedScenario,"mono");const timeline=byId("timeline");timeline.replaceChildren();renderTrack(timeline,selectedPolicy);const compare=byId("compare-fixed").checked&&selectedPolicy!=="fixed_order";if(compare)renderTrack(timeline,"fixed_order");
 const item=EVALUATOR[selectedSplit]?.[selectedScenario];const out=byId("evaluator-outcome");out.replaceChildren();if(!item){add(out,"p","No evaluator annotation is available.");return}add(out,"p","Gold terminal action: "+(ACTIONS[item.gold.gold_terminal_action]||item.gold.gold_terminal_action));for(const policy of (compare?[selectedPolicy,"fixed_order"]:[selectedPolicy])){const v=item.policy_outcomes[policy];if(v){add(out,"p",(LABELS[policy]||policy)+": terminal action "+(ACTIONS[v.terminal_action]||v.terminal_action||"none")+" · termination "+v.terminal_reason);add(out,"p",(LABELS[policy]||policy)+" · gold evidence supported for recorded result: "+String(v.gold_evidence_supported))}}
}
function setExample(id){const ex=DATA.guided_examples.find(x=>x.id===id);if(!ex)return;selectedSplit=ex.split;selectedScenario=ex.scenario;selectedPolicy=ex.policy;byId("compare-fixed").checked=ex.compare_fixed_order;byId("policy-select").value=selectedPolicy;renderComparison();renderScenarioOptions();renderInvestigation()}
function init(){renderExecution();for(const [split,label] of [["development","Development"],["evaluation","Evaluation"]])if(DATA.comparison.some(x=>x.split===split)){/* tabs filled by renderer */}
 renderComparison();const policy=byId("policy-select");for(const p of Object.keys(LABELS)){const o=node("option",LABELS[p]);o.value=p;policy.append(o)}policy.value=selectedPolicy;
 const guides=byId("guided-examples");for(const ex of DATA.guided_examples){const b=node("button");b.type="button";b.append(node("strong",ex.title),node("span",ex.description));b.addEventListener("click",()=>setExample(ex.id));guides.append(b)}
 byId("scenario-select").addEventListener("change",e=>{selectedScenario=e.target.value;renderInvestigation()});policy.addEventListener("change",e=>{selectedPolicy=e.target.value;renderInvestigation()});byId("compare-fixed").addEventListener("change",renderInvestigation);
 renderScenarioOptions();renderInvestigation();
 const prov=DATA.provenance||{};byId("provenance").textContent="Report created "+(DATA.created_utc||"unknown")+" · source commit "+(prov.git_head||"not recorded")+".";
 details(byId("provenance-details"),"Expand recorded provenance and runtime metadata",prov);
}
init();
</script>
</body>
</html>
'''
