import React, { useEffect, useRef, useState } from "react";
import { returnReason, returnStatusLabels, type ReturnCase } from "../return-data";

type StaffReturn = ReturnCase & {
  proposal_hash?: string | null;
  evidence?: Record<string, unknown> | null;
};
type ReturnRequest = <T>(path: string, body?: object) => Promise<T>;
type Confirmation = { action: "approve" | "confirm"; id: string; order: string; item: string; hash: string };

const evidenceLabels: Record<string, string> = {
  delivered_at: "Verified delivery",
  deadline: "Return deadline",
  shipment_id: "Parcel",
  window_days: "Policy window in days",
  item_eligible: "Item eligible",
  history_complete: "Return and refund records complete",
  prior_return: "Previous return",
  prior_refund: "Previous refund",
};

function displayEvidence(value: unknown): string {
  if (value == null) return "Missing";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.map(displayEvidence).join(", ") : "None";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function ReturnWorkspace({ request, mayApprove }: { request: ReturnRequest; mayApprove: boolean }) {
  const [cases, setCases] = useState<StaffReturn[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<StaffReturn | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const flight = useRef(false);

  useEffect(() => {
    let disposed = false;
    request<StaffReturn[]>("/api/returns").then(
      rows => { if (!disposed) { setCases(rows); setLoading(false); } },
      () => { if (!disposed) { setError("Return cases could not be loaded. Try Refresh returns."); setLoading(false); } },
    );
    return () => { disposed = true; };
  }, []);

  function path(id: string) {
    return "/api/returns/" + encodeURIComponent(id);
  }

  async function perform(operation: () => Promise<void>) {
    if (flight.current) return;
    flight.current = true;
    setBusy(true);
    setError("");
    try {
      await operation();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "The return could not be updated.");
    } finally {
      flight.current = false;
      setBusy(false);
    }
  }

  function refresh() {
    return perform(async () => {
      setCases(await request<StaffReturn[]>("/api/returns"));
      if (selected) setSelected(await request<StaffReturn>(path(selected.id)));
    });
  }

  function update(row: StaffReturn) {
    setSelected(row);
    setCases(rows => rows.map(item => item.id === row.id ? row : item));
  }

  function startConfirmation(action: Confirmation["action"]) {
    if (!selected?.proposal_hash) return;
    setConfirmation({
      action,
      id: selected.id,
      order: selected.order_id,
      item: selected.variant_id,
      hash: selected.proposal_hash,
    });
  }

  function confirmAction(binding: Confirmation) {
    return perform(async () => {
      setConfirmation(null);
      try {
        update(await request<StaffReturn>(path(binding.id) + "/" + binding.action, { proposal_hash: binding.hash }));
      } catch (failure) {
        await request<StaffReturn>(path(binding.id)).then(update, () => {});
        throw failure;
      }
    });
  }

  return <>
    <div className="return-workspace">
      <section className="card inbox" aria-label="Return cases">
        <div className="sectionhead">
          <h2>Return cases</h2>
          <button type="button" className="quiet" disabled={loading || busy || Boolean(confirmation)} onClick={() => void refresh()}>Refresh returns</button>
        </div>
        {error && <p role="alert" className="error">{error}</p>}
        {loading ? <p role="status" className="muted">Loading return cases…</p> : cases.length === 0 ? <p className="muted">No return requests in this shop.</p> :
          <ul>{cases.map(row => <li key={row.id}>
            <button type="button" className={"case-row" + (selected?.id === row.id ? " selected" : "")}
              aria-pressed={selected?.id === row.id} disabled={busy || Boolean(confirmation)}
              onClick={() => void perform(async () => setSelected(await request<StaffReturn>(path(row.id))))}>
              <strong>{row.order_id} · {row.variant_id}</strong>
              <span>{returnStatusLabels[row.status]}</span>
            </button>
          </li>)}</ul>}
      </section>
      <section className="card" aria-label="Selected return">
        {selected ? <>
          <h2>{selected.order_id}</h2>
          <p className="muted">Return {selected.id} · One item · {selected.variant_id}</p>
          <p role="status">{returnStatusLabels[selected.status]}</p>
          {returnReason(selected.reason) && <p>{returnReason(selected.reason)}</p>}
          {selected.evidence && <dl className="return-evidence">
            {Object.entries(selected.evidence).map(([field, value]) =>
              <React.Fragment key={field}><dt>{evidenceLabels[field] ?? field.replaceAll("_", " ")}</dt><dd>{displayEvidence(value)}</dd></React.Fragment>
            )}
          </dl>}
          {selected.authorization_id && <p>Authorization {selected.authorization_id}</p>}
          {(selected.status === "requested" || selected.status === "review" || selected.status === "ineligible") &&
            <button type="button" className="primary" disabled={busy}
              onClick={() => void perform(async () => update(await request<StaffReturn>(path(selected.id) + "/investigate", {})))}>
              Investigate return
            </button>}
          {mayApprove && selected.status === "proposed" && selected.proposal_hash &&
            <button type="button" className="primary" disabled={busy} onClick={() => startConfirmation("approve")}>Approve return</button>}
          {mayApprove && selected.status === "approved" && selected.proposal_hash &&
            <button type="button" className="primary" disabled={busy} onClick={() => startConfirmation("confirm")}>Authorize return</button>}
        </> : <p className="muted">Choose a return case to see its item and evidence.</p>}
      </section>
    </div>
    {confirmation && <div className="modal-backdrop">
      <section className="modal card" role="dialog" aria-modal="true" aria-labelledby="return-confirm-title">
        <h2 id="return-confirm-title">{confirmation.action === "approve" ? "Approve this return proposal?" : "Authorize this return?"}</h2>
        <p>{confirmation.order} · One item · {confirmation.item}</p>
        <details className="approval-binding" open><summary>Approval binding</summary><p>Return {confirmation.id}<br />Content hash {confirmation.hash}</p></details>
        <p className="muted">{confirmation.action === "approve" ? "Approval allows a separate authorization step." : "Confirmation checks the latest evidence and creates the return authorization."}</p>
        <div className="modal-actions">
          <button type="button" className="quiet" disabled={busy} onClick={() => setConfirmation(null)}>Cancel</button>
          <button type="button" className="primary" disabled={busy} onClick={() => void confirmAction(confirmation)}>
            {confirmation.action === "approve" ? "Confirm return approval" : "Confirm return authorization"}
          </button>
        </div>
      </section>
    </div>}
  </>;
}
