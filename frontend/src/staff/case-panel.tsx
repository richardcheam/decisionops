import type { FormEvent } from "react";
import { caseStatusLabels, formatCaseItems, formatCaseTime, type Case } from "./case-data";
import { InvestigationPanel } from "./investigation-panel";

const requirements: Record<string, string> = {
  paid: "Payment confirmed",
  shipped: "Full order shipped",
  loss_confirmed: "Carrier confirms loss",
  quantities_valid: "Items and quantities match",
  no_previous_compensation: "Not already refunded or replaced",
  stock_available: "Replacement stock available",
  policy_permits: "Store policy permits replacement",
};
const events: Record<string, string> = {
  opened: "Case opened",
  customer_report_received: "Customer reported a missing parcel",
  adaptive_started: "Shipment investigation started",
  staff_investigation_requested: "Shipment report received",
  adaptive_proposed: "Evidence checked — proposal prepared",
  adaptive_finished: "Shipment investigation finished",
  investigated: "Order checked",
  reviewed: "Review decision saved",
  approval_invalidated: "Information changed — approval needed again",
  proposal_stale: "Information changed — check again",
  executed: "Replacement created and items set aside",
  escalated: "Marked for manager review",
};
const missingInformation: Record<string, string> = {
  paid: "We need confirmation that this order was paid.",
  shipped: "We need confirmation that all these items were shipped.",
  loss_confirmed: "We need an up-to-date confirmation from the carrier that the parcel is lost.",
  quantities_valid: "We need to confirm these items and quantities match the order.",
  no_previous_compensation: "We need the full refund and replacement history before continuing.",
  stock_available: "We need current stock information before promising a replacement.",
  policy_permits: "We need to confirm which store rule applies to this order.",
};
const failedChecks: Record<string, string> = {
  paid: "Payment is not confirmed for this order.",
  shipped: "These items have not all been shipped.",
  loss_confirmed: "The carrier reports a status other than lost. Ask your manager to review the delivery issue.",
  quantities_valid: "These items or quantities do not match the original order.",
  no_previous_compensation: "These items have already been refunded or replaced.",
  stock_available: "There are not enough items available for this replacement.",
  policy_permits: "The store's rule does not allow replacement for this order.",
};
function nextStep(value: Case) {
  if (value.operation && value.operation.status !== "verified")
    return "We could not confirm the replacement. Ask your manager to check this case before trying again.";
  if (value.assessment?.scope_reasons?.length)
    return "This order needs a manager's review. It may include split shipments, only some items, or a previous partial refund or replacement.";
  const guidance: Record<string, string> = {
    open: value.delivery ? "Investigate the parcel to see if it can be replaced." : "Check the order to see if it can be replaced.",
    awaiting_review: "The checks passed. Review the replacement and approve or decline it.",
    needs_review: "Some information is missing or has changed. Check again or ask your manager for help before promising a replacement.",
    blocked: "A replacement is not available for this request. See the reasons below or ask your manager for help.",
    approved: "Approved. Choose Create replacement to set these items aside. They will not be shipped yet.",
    rejected: "The replacement was declined. You can check again or ask for help.",
    escalated: "This case is marked for help. Share it with your manager; no replacement has been created.",
    executed: "This replacement has been created. It has not been shipped yet.",
  };
  return guidance[value.status] || "Ask your manager to review this case.";
}

type Props = {
  active: Case | null;
  hasSelection: boolean;
  busy: boolean;
  mayApprove: boolean;
  evidenceNeedsRefresh: boolean;
  report: string;
  reason: string;
  onStartInvestigation: () => void;
  onCheckOrder: (caseId: string) => void;
  onApprove: () => void;
  onDecline: () => void;
  onCreateReplacement: () => void;
  onReportChange: (value: string) => void;
  onSubmitReport: (event: FormEvent) => Promise<void>;
  onReasonChange: (value: string) => void;
  onEscalate: (caseId: string, reason: string) => void;
};

export function CasePanel({
  active, hasSelection, busy, mayApprove, evidenceNeedsRefresh, report, reason,
  onStartInvestigation, onCheckOrder, onApprove, onDecline, onCreateReplacement,
  onReportChange, onSubmitReport, onReasonChange, onEscalate,
}: Props) {
  const pending = active?.latest_job && ["queued", "running"].includes(active.latest_job.status);
  const locked = busy || Boolean(pending);
  const replacementVerified = active?.operation?.status === "verified";
  const canStartDeliveryInvestigation = Boolean(active?.delivery && active.status === "open");
  let nextStepMessage = active ? nextStep(active) : "";
  if (!replacementVerified && pending) {
    nextStepMessage = "We are checking the order. You can leave this page and return later.";
  } else if (!replacementVerified && evidenceNeedsRefresh) {
    nextStepMessage = "Saved evidence needs an explicit investigation refresh before approval or execution.";
  }

  return (
    <section className="casepanel" id="staff-case" tabIndex={-1} aria-label="Selected case">
      {!hasSelection ? (
        <div className="empty card">
          <h2>Select a case</h2>
          <p className="muted">Open an exception to see the parcel and its next step.</p>
        </div>
      ) : !active ? (
        <div className="card">Loading case…</div>
      ) : (
        <>
          <section className="card caseheader">
            <div>
              <h2>{active.request.order_id}</h2>
              <p>{active.delivery ? `${active.delivery.dispatch_origin} → ${active.delivery.city}` : active.request.shipment_id}</p>
              <p className="muted">{formatCaseItems(active.request.items)}</p>
            </div>
            <span className={"status " + active.status}>
              {active.operation && active.operation.status !== "verified"
                ? "Needs confirmation"
                : caseStatusLabels[active.status] || "Needs review"}
            </span>
          </section>
          <section className="card next-step" aria-label="Next step">
            <h2>Next step</h2>
            <p>{nextStepMessage}</p>
            <div className="actions">
              {canStartDeliveryInvestigation && (
                <button className="primary" disabled={locked}
                  onClick={onStartInvestigation}>
                  Investigate case
                </button>
              )}
              {!canStartDeliveryInvestigation && active.status !== "executed" && <button
                className={active.proposal && !evidenceNeedsRefresh ? "quiet" : "primary"}
                disabled={locked}
                onClick={() => onCheckOrder(active.id)}
              >
                {pending
                  ? "Checking…"
                  : active.generation
                    ? "Check again"
                    : "Check order"}
              </button>}
              {mayApprove && active.status === "awaiting_review" && (
                <>
                  <button
                    className="primary"
                    disabled={locked || evidenceNeedsRefresh}
                    onClick={onApprove}
                  >
                    Approve replacement
                  </button>
                  <button
                    className="quiet danger"
                    disabled={locked}
                    onClick={onDecline}
                  >
                    Decline replacement
                  </button>
                </>
              )}
              {mayApprove && active.status === "approved" && (
                <button
                  className="primary"
                  disabled={locked || evidenceNeedsRefresh}
                  onClick={onCreateReplacement}
                >
                  Create replacement
                </button>
              )}
              {pending && (
                <span className="muted" role="status">
                  {active.latest_job?.status === "queued"
                    ? "Your order check will start shortly"
                    : "Checking order information"}
                </span>
              )}
            </div>
            {!mayApprove && ["awaiting_review", "approved"].includes(active.status) && <p className="muted">An approver must review the exact proposal and separately confirm execution.</p>}
          </section>
          {active.latest_job?.status === "failed" && (
            <div role="alert" className="error">
              We could not finish checking this order. Try checking again.
              If it continues, ask your manager for help.
            </div>
          )}
          {active.operation && (
            <section
              className={
                "card outcome " +
                (active.operation.status === "verified" ? "success" : "")
              }
            >
              <p className="eyebrow">Result</p>
              <h2>
                {active.operation.status === "verified"
                  ? "Replacement confirmed"
                  : "Replacement needs confirmation"}
              </h2>
              <p>
                {active.operation.status === "verified"
                  ? "The replacement is created and the items are set aside. They have not been shipped yet."
                  : "We could not confirm the result. Ask your manager to check this case before creating another replacement."}
              </p>
            </section>
          )}
          {active.delivery && <details className="card" aria-label="Carrier timeline">
            <summary>Carrier updates</summary>
            <p>{active.delivery.dispatch_origin} → {active.delivery.city}. {active.delivery.promised_at ? "Promised " + formatCaseTime(active.delivery.promised_at) : "Delivery promise unknown"}.</p>
            {active.delivery.carrier_events.some(event => event.verified && event.status === "lost") && active.delivery.carrier_events.some(event => event.verified && event.status === "delivered") && <p className="error">Conflicting verified loss and delivery records require review.</p>}
            <ol className="timeline">{active.delivery.carrier_events.map(event => <li key={event.id}>
              <strong>{event.status.replaceAll("_", " ")} · {event.verified ? "Verified record" : "Unverified record"}</strong>
              <p>Event <time dateTime={event.event_at}>{formatCaseTime(event.event_at)}</time> · Received <time dateTime={event.received_at}>{formatCaseTime(event.received_at)}</time></p>
              <p>Source: {event.source} · Event ID: {event.external_id} · Record: {event.id}</p>
              <details><summary>Original simulated carrier event</summary><pre>{JSON.stringify(event.original, null, 2)}</pre></details>
            </li>)}</ol>
          </details>}
          <InvestigationPanel
            caseStatus={active.status}
            hasDelivery={Boolean(active.delivery)}
            investigation={active.shipment_investigation}
            locked={locked}
            report={report}
            onReportChange={onReportChange}
            onSubmitReport={onSubmitReport}
            evidenceNeedsRefresh={evidenceNeedsRefresh}
            replacementVerified={replacementVerified}
          />
          {active.assessment && !replacementVerified && (
            <section className="card">
              <div className="sectionhead">
                <h2>Order checks</h2>
                <span className="muted">
                  {evidenceNeedsRefresh ? Object.keys(requirements).length : active.assessment.decision.unknowns.length} not
                  confirmed
                </span>
              </div>
              {(() => {
                const values = Object.keys(requirements).map(key => evidenceNeedsRefresh ? null : active.assessment!.facts[key]);
                const met = values.filter(value => value === true).length;
                return <div className="meter" role="img" aria-label={`${met} of ${values.length} conditions confirmed`}>
                  {values.map((value, i) => <span key={i} className={value === true ? "met" : value === false ? "unmet" : "unknown"} />)}
                </div>;
              })()}
              <div className="requirements">
                {Object.entries(requirements).map(([key, label]) => {
                  const value = evidenceNeedsRefresh ? null : active.assessment!.facts[key];
                  const evidence = active.assessment!.read_tools.find(
                    (row) => row.requirement === key,
                  );
                  return (
                    <div className="requirement" key={key}>
                      <span
                        className={
                          "fact-icon " +
                          (value === true
                            ? "true"
                            : value === false
                              ? "false"
                              : "unknown")
                        }
                      >
                        {value === true
                          ? "✓"
                          : value === false
                            ? "×"
                            : "?"}
                      </span>
                      <div>
                        <strong>{label}</strong>
                        <span>
                          {value === true
                            ? "Confirmed"
                            : value === false
                              ? "Not met"
                              : "Needs information"}
                        </span>
                        {value !== true && <p>{value === false ? failedChecks[key] : missingInformation[key]}</p>}
                        {evidence && <small>Last checked {formatCaseTime(evidence.observed_at)}</small>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}
          {active.proposal && (
            <section className="card proposal">
              <p className="eyebrow">Suggested replacement</p>
              <h2>
                Replace{" "}
                {Object.values(active.request.items).reduce(
                  (sum, quantity) => sum + quantity,
                  0,
                )}{" "}
                item(s)
              </h2>
              <p>{formatCaseItems(active.proposal.document.request.items)}</p>
              <p className="muted compact">
                We will check the order and stock again before creating
                this replacement. If anything changes, you will need to
                review it again.
              </p>
              <p className="gate" aria-label="Approval steps">
                {active.status === "executed" ? <><s>1 Approve</s>→<s>2 Create</s></> : active.status === "approved" ? <><s>1 Approve</s>→<b>2 Create</b></> : <><b>1 Approve</b>→<span>2 Create</span></>}
              </p>
            </section>
          )}
          <section className="card">
            <h2>Case history</h2>
            <details className="case-reference"><summary>Case reference</summary><p>{active.id}<br />Parcel {active.request.shipment_id}</p></details>
            <ol className="timeline">
              {active.events?.map((event) => (
                <li key={event.id}>
                  <div>
                    <strong>{events[event.kind] || event.kind}</strong>
                    {event.kind === "customer_report_received" && typeof event.details.message === "string" && <p>{event.details.message}</p>}
                    <time>{formatCaseTime(event.created_at)}</time>
                  </div>
                </li>
              ))}
            </ol>
          </section>
          {active.status !== "executed" && (
            <section className="card">
              <h2>Ask a manager</h2>
              <p className="muted">Save a note, then share the case with your manager.</p>
              <label>
                What needs checking?
                <input
                  value={reason}
                  maxLength={500}
                  onChange={(event) => onReasonChange(event.target.value)}
                  placeholder="For example: the carrier has not confirmed the parcel is lost"
                />
              </label>
              <button
                className="quiet"
                disabled={locked || !reason.trim()}
                onClick={() => onEscalate(active.id, reason)}
              >
                Ask for help
              </button>
            </section>
          )}
          <details className="card">
            <summary>Technical details</summary>
            {active.shipment_investigation && <p>{active.shipment_investigation.mode === "llm" ? "Local LLM specialists" : active.shipment_investigation.mode === "mock_specialists" ? "Simulated specialists" : active.shipment_investigation.mode === "simulated_decisions" ? "Simulated Decisions responses" : "Rules investigation"}</p>}
            <pre>{JSON.stringify(active, null, 2)}</pre>
          </details>
        </>
      )}
    </section>
  );
}
