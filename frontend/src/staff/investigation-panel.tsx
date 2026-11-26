import type { FormEvent } from "react";
import { formatCaseTime, type Case } from "./case-data";

type Investigation = NonNullable<Case["shipment_investigation"]>;

const toolLabels: Record<string, string> = {
  order_manifest: "Order items",
  replacement_policy: "Store replacement policy",
  payment: "Payment",
  fulfilment: "Shipment",
  carrier_loss: "Carrier loss confirmation",
  compensation_history: "Refund and replacement history",
  inventory: "Available stock",
};

function investigationStatus(
  investigation: Investigation, needsRefresh: boolean, replacementVerified: boolean,
) {
  if (replacementVerified) {
    return "Historical investigation. The replacement is verified by its execution record.";
  }
  if (investigation.historical) {
    return "Historical investigation from an earlier case generation. Current order checks and the proposal below govern this case.";
  }
  if (investigation.state === "active") {
    return "Investigation in progress. You can refresh or return later.";
  }
  if (investigation.state === "proposed") {
    return needsRefresh
      ? "Investigation complete. Refresh the evidence before reviewing the replacement."
      : "Investigation complete. Replacement proposal ready for your review.";
  }
  return investigation.blockers.length
    ? "Investigation finished. A required condition was not met."
    : "Investigation finished. More information or staff review is needed.";
}

function SpecialistTracks({ investigation }: { investigation: Investigation }) {
  const { specialists, steps, evidence } = investigation;
  if (!specialists?.length) return null;

  const decisionsAndReads = steps.filter(step => step.kind === "specialist_decision" ||
    (step.kind === "specialist_read_result" && step.data.specialist));
  return (
    <section aria-label="Specialist branches" className="specialists">
      <h3>Specialist branches</h3>
      <div className="tracks">
        {specialists.map(branch => {
          const running = investigation.state === "active" && branch.state === "pending" && !investigation.historical;
          const observations = new Set(branch.observations);
          const completedTools = new Set(evidence
            .filter(row => row.source && observations.has(row.source.observation_id))
            .map(row => row.tool));
          const tools = [...new Set(branch.tools)];
          const label = branch.name.replaceAll("_", " ");
          const state = branch.state.replaceAll("_", " ");
          return (
            <div key={branch.name} className={"track track-" + branch.name} data-live={running}>
              <div className="track-head">
                <h4>{label} specialist</h4>
                <span className={"tag" + (running ? " tag-live" : "")}>{running ? "working" : state}</span>
              </div>
              <ol className="steps" aria-label={label + " specialist reads"}>
                {tools.map(tool => {
                  const completed = completedTools.has(tool);
                  return (
                    <li key={tool} className={"step " + (completed ? "step-done" : "step-wait")}>
                      <span className="step-mark" aria-hidden="true" />
                      <span>{toolLabels[tool] || tool}<code>{tool}</code></span>
                      <em>{completed ? "read" : "not read"}</em>
                    </li>
                  );
                })}
                {running && (
                  <li className="step step-live">
                    <span className="step-mark" aria-hidden="true" />
                    <span>Gathering evidence</span><em>in progress</em>
                  </li>
                )}
              </ol>
              <p>Branch status: {state}</p>
              {tools.length > 0 && <p>Assigned reads: {tools.map(tool => toolLabels[tool] || tool).join(", ")}</p>}
              {branch.reason && <p>Branch outcome: {branch.reason.replaceAll("_", " ")}</p>}
              <p>{branch.observations.length} saved observations</p>
            </div>
          );
        })}
      </div>
      <details>
        <summary>Specialist decisions and read results</summary>
        <ol className="timeline">
          {decisionsAndReads.map(step => {
            const { specialist, chosen_action, tool, status, reason } = step.data;
            const toolId = tool || chosen_action?.tool;
            return (
              <li key={step.sequence}>
                <strong>{(specialist || "Specialist").replaceAll("_", " ")}</strong>
                {step.kind === "specialist_decision" ? ": Decision choice" : ": Read result"}
                {chosen_action?.kind && <span> · {chosen_action.kind.replaceAll("_", " ")}</span>}
                {toolId && <span> · {toolLabels[toolId] || toolId}</span>}
                {status && <span> · {status.replaceAll("_", " ")}</span>}
                {reason && <p>{reason.replaceAll("_", " ")}</p>}
                <time>{formatCaseTime(step.created_at)}</time>
              </li>
            );
          })}
        </ol>
      </details>
    </section>
  );
}

function EvidenceList({ evidence, needsRefresh }: { evidence: Investigation["evidence"]; needsRefresh: boolean }) {
  return (
    <ol className="timeline evidence-list">
      {evidence.map((row, index) => {
        const current = row.applicability === "current";
        let finding = "Needs information";
        if (needsRefresh) finding = "Not current: refresh required";
        else if (!current) finding = "Not current: " + row.applicability.replaceAll("_", " ");
        else if (row.value === true) finding = "Confirmed";
        else if (row.value === false) finding = "Not met";

        const { source } = row;
        return (
          <li key={source?.observation_id || index} data-value={needsRefresh || !current ? "unknown" : String(row.value)}>
            <strong>{toolLabels[row.tool] || row.tool}</strong>: {finding}
            <time>Checked {formatCaseTime(row.observed_at)}{row.expires_at ? " · Valid until " + formatCaseTime(row.expires_at) : ""}</time>
            {source && (
              <details>
                <summary>Evidence source</summary>
                <p>Declared record scope: {source.tables.join(", ")}. Order {source.order_id}; shipment {source.shipment_id}.</p>
                <p>This investigation consulted database records, not browser pages.</p>
                <p>Observation: {source.observation_id}<br />Version: {source.version}</p>
                {row.reason && <p>Evidence limitation: {row.reason.replaceAll("_", " ")}</p>}
                {row.customer_page && <a href={row.customer_page}>View corresponding customer page ↗</a>}
              </details>
            )}
          </li>
        );
      })}
    </ol>
  );
}

type Props = {
  caseStatus: string;
  hasDelivery: boolean;
  investigation: Case["shipment_investigation"];
  locked: boolean;
  report: string;
  onReportChange: (value: string) => void;
  onSubmitReport: (event: FormEvent) => Promise<void>;
  evidenceNeedsRefresh: boolean;
  replacementVerified: boolean;
};

export function InvestigationPanel({
  caseStatus, hasDelivery, investigation, locked, report, onReportChange, onSubmitReport,
  evidenceNeedsRefresh, replacementVerified,
}: Props) {
  const reportTooLong = new TextEncoder().encode(report).length > 2000;
  const continuation = investigation?.steps.filter(step => step.kind === "deterministic_continuation") ?? [];
  const hasInvalidEvidence = !investigation?.historical && investigation?.evidence.some(row =>
    ["expired", "dependency_changed", "future_timestamp", "conflicting_active_contents"].includes(row.applicability));

  return (
    <section className="card" aria-label="Shipment investigation">
      <h2>Investigation</h2>
      {caseStatus !== "executed" && (
        <details open={!hasDelivery} className="manual-report">
          <summary>Add a shipment report</summary>
          <form onSubmit={event => void onSubmitReport(event)}>
            <label htmlFor="shipment-report">Shipment report</label>
            <textarea
              id="shipment-report"
              rows={3}
              maxLength={1000}
              value={report}
              onChange={event => onReportChange(event.target.value)}
              placeholder="For example: the customer says their parcel has not arrived."
              disabled={locked}
              required
            />
            {reportTooLong && <p>Please shorten the report before submitting.</p>}
            <button type="submit" className="primary" disabled={locked || !report.trim() || reportTooLong}>
              Investigate shipment
            </button>
          </form>
        </details>
      )}
      {investigation && (
        <div aria-live="polite">
          {evidenceNeedsRefresh && !replacementVerified && (
            <p role="status" className="error">Saved evidence expired or source records changed. Start an explicit investigation refresh before relying on these findings.</p>
          )}
          <p role="status" className="investigation-status"
            data-state={replacementVerified || investigation.historical ? "historical" : investigation.state}>
            {investigationStatus(investigation, evidenceNeedsRefresh, replacementVerified)}
          </p>
          <SpecialistTracks investigation={investigation} />
          {hasInvalidEvidence && (
            <p role="status" className="error">Saved findings include expired, changed or conflicting evidence. Refresh the investigation before treating these findings as current.</p>
          )}
          {!!investigation.planned_checks?.length && (
            <p className="investigation-meta">Investigation outline: {investigation.planned_checks.join(" → ")}</p>
          )}
          <p className="investigation-meta">Saved report: {investigation.report}</p>
          <p className="investigation-meta">{investigation.unknowns.length} checks still unknown</p>
          <EvidenceList evidence={investigation.evidence} needsRefresh={evidenceNeedsRefresh} />
          {continuation.length > 0 && (
            <details>
              <summary>Why evidence gathering continued</summary>
              {continuation.map(step => (
                <p key={step.sequence}>Evidence continuation: the application selected {toolLabels[step.data.chosen_action?.tool || ""] || "the next read"} after a missing-information review choice. This was not a model choice.</p>
              ))}
            </details>
          )}
          {investigation.steps.filter(step => step.kind === "continuation_unavailable").map(step => (
            <p key={step.sequence}>Could not continue gathering evidence: {step.data.reason?.replaceAll("_", " ")}.</p>
          ))}
          {investigation.reason && <p>Review outcome: {investigation.reason.replaceAll("_", " ")}</p>}
        </div>
      )}
    </section>
  );
}
