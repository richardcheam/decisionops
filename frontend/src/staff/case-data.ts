type Evidence = {
  requirement: string;
  value: boolean | null;
  source_id: string;
  source_version: string;
  observed_at: string;
  details: Record<string, unknown>;
};
type Assessment = {
  facts: Record<string, boolean | null>;
  decision: { status: string; blockers: string[]; unknowns: string[] };
  read_tools: Evidence[];
  scope_reasons?: string[];
};
export type Case = {
  id: string;
  status: string;
  generation: number;
  request: {
    order_id: string;
    shipment_id: string;
    items: Record<string, number>;
  };
  updated_at: string;
  delivery?: {
    city: string; promised_at: string | null; dispatch_origin: string;
    carrier_events: {id: string; source: string; external_id: string; event_at: string; received_at: string; status: string; verified: boolean; original: Record<string, unknown>}[];
  } | null;
  assessment?: Assessment;
  proposal?: {
    id: string;
    content_hash: string;
    document: { policy_id: string; request: { items: Record<string, number> } };
  } | null;
  approval?: { operation_id: string; actor: string } | null;
  events?: {
    id: string;
    kind: string;
    created_at: string;
    details: Record<string, unknown>;
  }[];
  latest_job?: {
    id: string;
    status: string;
    action: string;
    error_kind: string | null;
  } | null;
  shipment_investigation?: {
    id: string; generation?: number; historical?: boolean; state: string; report: string; mode: string; reason: string | null;
    unknowns: string[]; blockers: string[]; evidence_current?: boolean; planned_checks?: string[];
    evidence: {tool: string; value: boolean | null; applicability: string; status: string; reason: string | null; observed_at: string; expires_at?: string; source?: {kind:string;observation_id:string;version:string;order_id:string;shipment_id:string;tables:string[]}}[];
    steps: {sequence: number; kind: string; data: {specialist?: string; tool?: string; status?: string; chosen_action?: {tool?: string; kind?: string}; reason?: string}; created_at: string}[];
    specialists?: {name: string; state: string; tools: string[]; reason?: string | null; observations: string[]}[];
  } | null;
  operation?: {
    status: string;
    replacement_id: string;
    operation_id: string;
    meaning: string;
  } | null;
};
export const caseStatusLabels: Record<string, string> = {
  open: "Ready to check",
  awaiting_review: "Ready for your review",
  needs_review: "Needs more information",
  blocked: "Replacement unavailable",
  approved: "Replacement approved",
  rejected: "Replacement declined",
  escalated: "Needs manager review",
  executed: "Replacement created",
};
// Display labels for the two fictional variants; requests still use exact IDs.
const productNames: Record<string, string> = {
  "shirt-blue-M": "Blue shirt · Size M",
  "shirt-red-M": "Red shirt · Size M",
};
export function formatCaseTime(value: string) {
  return new Date(value).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Europe/Paris",
  });
}
export function formatCaseItems(value: Record<string, number>) {
  return Object.entries(value)
    .map(([variant, qty]) => `${productNames[variant] || variant} × ${qty}`)
    .join(", ");
}
