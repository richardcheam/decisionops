export type ReturnEligibility = {
  order_id: string;
  items: { variant_id: string; quantity: number }[];
  status: "choose_item" | "eligible" | "review" | "ineligible";
  reason?: string | null;
};

export type ReturnCase = {
  id: string;
  order_id: string;
  variant_id: string;
  status: "requested" | "review" | "ineligible" | "proposed" | "approved" | "authorized";
  reason?: string | null;
  authorization_id?: string | null;
  conversation_id?: string;
};

export const returnStatusLabels: Record<ReturnCase["status"], string> = {
  requested: "Return requested",
  review: "Staff review needed",
  ineligible: "Return ineligible",
  proposed: "Ready for approval",
  approved: "Approved, awaiting authorization",
  authorized: "Return authorized",
};

export function returnCustomerUpdate(status: ReturnCase["status"]) {
  switch (status) {
    case "authorized": return "The shop authorized your return.";
    case "ineligible": return "This item does not qualify for a return under the shop policy.";
    case "review": return "The shop needs to check the records before it can authorize your return.";
    default: return "The shop is reviewing your return request.";
  }
}

const returnReasons: Record<string, string> = {
  choose_item: "Choose one item to check.",
  delivery_missing: "The shop could not find a delivery record for this item.",
  delivery_conflicting: "The carrier records disagree about delivery.",
  delivery_unavailable: "The carrier records are currently unavailable.",
  delivery_not_verified: "The shop has no verified delivery for this item.",
  outside_window: "The return window for this item has closed.",
  item_ineligible: "The shop policy excludes this item.",
  prior_return: "The shop has already authorized a return for this item.",
  prior_refund: "The shop has already refunded this item.",
  history_incomplete: "The shop needs to verify the return and refund history.",
  eligible: "This item is eligible for a return request.",
  evidence_changed: "The records changed after approval. Review the current evidence.",
};

export function returnReason(reason: string | null | undefined) {
  return reason ? returnReasons[reason] : undefined;
}
