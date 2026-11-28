import { useEffect, useRef, useState } from "react";

type CatalogCase = {
  id: string;
  sku: string;
  title: string;
  status: "open" | "current" | "review" | "proposed" | "approved" | "confirmed";
  reason: string;
  current_image_id: string;
  proposed_image_id: string | null;
  proposal_hash: string | null;
  evidence: Record<string, unknown>;
  receipt: { saved_image_id: string; listing_version: number } | null;
};

type Request = <T>(path: string, body?: unknown) => Promise<T>;
type Confirmation = {
  action: "approve" | "confirm";
  id: string;
  sku: string;
  current: string;
  proposed: string;
  hash: string;
};

const statusLabels: Record<CatalogCase["status"], string> = {
  open: "Investigation needed",
  current: "Current image verified",
  review: "Staff review needed",
  proposed: "Ready for approval",
  approved: "Approved, awaiting relink",
  confirmed: "Image relink verified",
};

function casePath(id: string) {
  return "/api/catalog/" + encodeURIComponent(id);
}

function ListingImage({ path, auth, label, imageId }: {
  path: string; auth: string; label: string; imageId: string;
}) {
  const [image, setImage] = useState("");
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    const reader = new FileReader();
    setImage("");
    setError(false);
    async function load() {
      try {
        const response = await fetch(path, {
          headers: { Authorization: auth },
          credentials: "omit",
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok || response.headers.get("Content-Type") !== "image/png") {
          throw new Error("Catalog image unavailable");
        }
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        reader.onload = () => {
          if (!controller.signal.aborted && typeof reader.result === "string") setImage(reader.result);
        };
        reader.onerror = () => { if (!controller.signal.aborted) setError(true); };
        reader.readAsDataURL(blob);
      } catch {
        if (!controller.signal.aborted) setError(true);
      }
    }
    void load();
    return () => {
      controller.abort();
      if (reader.readyState === FileReader.LOADING) reader.abort();
    };
  }, [path, auth]);

  return <figure>
    {image ? <img src={image} alt={label} /> : <p>{error ? "Image unavailable" : "Loading image…"}</p>}
    <figcaption>{label} · {imageId}</figcaption>
  </figure>;
}

function showEvidence(value: unknown): string {
  if (value == null) return "Unknown";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.length ? value.map(showEvidence).join(", ") : "None";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function CatalogWorkspace({ request, auth, mayApprove }: {
  request: Request; auth: string; mayApprove: boolean;
}) {
  const [rows, setRows] = useState<CatalogCase[]>([]);
  const [selected, setSelected] = useState<CatalogCase | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const inFlight = useRef(false);

  useEffect(() => {
    let active = true;
    request<CatalogCase[]>("/api/catalog").then(
      data => { if (active) { setRows(data); setBusy(false); } },
      () => { if (active) { setError("Catalog cases could not be loaded."); setBusy(false); } },
    );
    return () => { active = false; };
  }, [auth]);

  async function perform(action: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "This catalog case could not be updated.");
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  function update(row: CatalogCase) {
    setSelected(row);
    setRows(previous => previous.map(item => item.id === row.id ? row : item));
  }

  function refresh() {
    return perform(async () => {
      setRows(await request<CatalogCase[]>("/api/catalog"));
      if (selected) setSelected(await request<CatalogCase>(casePath(selected.id)));
    });
  }

  function chooseAction(action: Confirmation["action"]) {
    if (!selected?.proposal_hash || !selected.proposed_image_id) return;
    setConfirmation({
      action,
      id: selected.id,
      sku: selected.sku,
      current: selected.current_image_id,
      proposed: selected.proposed_image_id,
      hash: selected.proposal_hash,
    });
  }

  function confirmAction(binding: Confirmation) {
    return perform(async () => {
      setConfirmation(null);
      try {
        update(await request<CatalogCase>(casePath(binding.id) + "/" + binding.action, {
          proposal_hash: binding.hash,
        }));
      } catch (failure) {
        await request<CatalogCase>(casePath(binding.id)).then(update, () => {});
        throw failure;
      }
    });
  }

  return <>
    <div className="return-workspace">
      <section className="card inbox" aria-label="Catalog cases">
        <div className="sectionhead">
          <h2>Catalog cases</h2>
          <button type="button" className="quiet" disabled={busy || Boolean(confirmation)} onClick={() => void refresh()}>Refresh catalog</button>
        </div>
        {error && <p role="alert" className="error">{error}</p>}
        {rows.length === 0 ? <p className="muted">{busy ? "Loading cases…" : "No catalog cases."}</p> :
          <ul>{rows.map(row => <li key={row.id}>
            <button type="button" className={"case-row" + (selected?.id === row.id ? " selected" : "")}
              aria-pressed={selected?.id === row.id} disabled={busy || Boolean(confirmation)}
              onClick={() => void perform(async () => update(await request<CatalogCase>(casePath(row.id))))}>
              <strong>{row.title} · {row.sku}</strong>
              <span>{statusLabels[row.status]}</span>
            </button>
          </li>)}</ul>}
      </section>
      <section className="card" aria-label="Selected catalog case">
        {selected ? <>
          <h2>{selected.title}</h2>
          <p>{selected.sku}</p>
          <p role="status">{statusLabels[selected.status]}</p>
          {selected.reason && <p>{selected.reason}</p>}
          <div className="catalog-images">{[
            { id: selected.current_image_id, label: "Current listing image" },
            { id: selected.proposed_image_id, label: "Proposed listing image" },
          ].map(({ id, label }) => id ? <ListingImage key={selected.id + ":" + label + ":" + id} auth={auth} label={label} imageId={id}
            path={casePath(selected.id) + "/images/" + encodeURIComponent(id)} /> : null)}</div>
          {selected.evidence && Object.keys(selected.evidence).length > 0 && <>
            <h3>Evidence</h3>
            <dl className="return-evidence">{Object.entries(selected.evidence).map(([key, value]) => <div key={key} className="catalog-evidence-row">
              <dt>{key.replaceAll("_", " ")}</dt><dd>{showEvidence(value)}</dd>
            </div>)}</dl>
          </>}
          {selected.receipt && <p>Verified saved image {selected.receipt.saved_image_id} · Listing version {selected.receipt.listing_version}</p>}
          {["open", "review", "current"].includes(selected.status) &&
            <button type="button" className="primary" disabled={busy} onClick={() => void perform(async () => {
              update(await request<CatalogCase>(casePath(selected.id) + "/investigate", {}));
            })}>Investigate image</button>}
          {mayApprove && selected.status === "proposed" && selected.proposal_hash && selected.proposed_image_id &&
            <button type="button" className="primary" disabled={busy} onClick={() => chooseAction("approve")}>Approve image change</button>}
          {mayApprove && selected.status === "approved" && selected.proposal_hash && selected.proposed_image_id &&
            <button type="button" className="primary" disabled={busy} onClick={() => chooseAction("confirm")}>Relink image</button>}
        </> : <p className="muted">Choose a catalog case to see its images and evidence.</p>}
      </section>
    </div>
    {confirmation && <div className="modal-backdrop">
      <section className="modal card" role="dialog" aria-modal="true" aria-labelledby="catalog-confirm-title">
        <h2 id="catalog-confirm-title">{confirmation.action === "approve" ? "Approve this image change?" : "Relink this listing image?"}</h2>
        <p>SKU {confirmation.sku}</p>
        <p>{confirmation.current} → {confirmation.proposed}</p>
        <details className="approval-binding" open><summary>Approval binding</summary><p>Case {confirmation.id}<br />Content hash {confirmation.hash}</p></details>
        <div className="modal-actions">
          <button type="button" className="quiet" disabled={busy} onClick={() => setConfirmation(null)}>Cancel</button>
          <button type="button" className="primary" disabled={busy} onClick={() => void confirmAction(confirmation)}>
            {confirmation.action === "approve" ? "Confirm approval" : "Confirm relink"}
          </button>
        </div>
      </section>
    </div>}
  </>;
}
