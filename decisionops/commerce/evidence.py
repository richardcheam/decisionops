"""Assess trusted demo read-tool attestations, not raw messages or model output."""

from datetime import datetime
import math

from .eligibility import REQUIREMENTS, evaluate_eligibility


def utc_timestamp(value):
    """Parse an explicit UTC timestamp; reject ambiguous local timestamps."""
    if not isinstance(value, str):
        raise ValueError("observed_at must be a UTC timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("observed_at must have an explicit UTC offset")
    return parsed


def assess_evidence(records, *, order_id, supported_case, now,
                    trusted_sources, max_age_seconds):
    """Return normalized facts, provenance and deterministic rejection reasons.

    Facts are attestations from trusted read adapters. Carrier adapters must
    attest True only for explicit authoritative loss confirmation; this function
    does not infer loss from tracking text. Scope is established by the caller.
    """
    if type(supported_case) is not bool:
        raise ValueError("supported_case must be a boolean")
    if now.utcoffset() is None or now.utcoffset().total_seconds() != 0:
        raise ValueError("now must be UTC")
    if (type(max_age_seconds) not in (int, float)
            or not math.isfinite(max_age_seconds) or max_age_seconds <= 0):
        raise ValueError("max_age_seconds must be finite and positive")
    if set(trusted_sources) != set(REQUIREMENTS):
        raise ValueError("trusted_sources must configure every requirement")
    if any(not isinstance(source, str) or not source for source in trusted_sources.values()):
        raise ValueError("trusted source IDs must be nonempty strings")
    if not isinstance(order_id, str) or not order_id:
        raise ValueError("order_id must be a nonempty string")
    if not isinstance(records, list):
        raise ValueError("observations must be a list")

    evidence = {name: [] for name in REQUIREMENTS}
    issues = {name: [] for name in REQUIREMENTS}
    values = {name: set() for name in REQUIREMENTS}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("observations must contain objects")
        requirement = record.get("requirement")
        if requirement not in REQUIREMENTS:
            raise ValueError("unknown evidence requirement")
        for field in ("source_id", "source_version", "order_id"):
            if not isinstance(record.get(field), str) or not record[field]:
                raise ValueError(f"{requirement}: {field} must be nonempty")
        status = record.get("status")
        if status not in ("success", "missing", "unavailable"):
            raise ValueError(f"{requirement}: invalid status")
        value = record.get("value")
        if value is not True and value is not False and value is not None:
            raise ValueError(f"{requirement}: value must be True, False, or None")
        observed = utc_timestamp(record.get("observed_at"))
        reasons = []
        if record["order_id"] != order_id:
            reasons.append("wrong_order")
        if record["source_id"] != trusted_sources[requirement]:
            reasons.append("untrusted_source")
        age = (now - observed).total_seconds()
        if age < 0:
            reasons.append("future_timestamp")
        elif age > max_age_seconds:
            reasons.append("stale")
        if status != "success":
            reasons.append(status)
        elif value is None:
            reasons.append("unknown_fact")
        evidence[requirement].append({
            **record, "accepted": not reasons, "reasons": reasons,
        })
        issues[requirement].extend(reasons)
        if not reasons:
            values[requirement].add(value)

    facts = {}
    for requirement in REQUIREMENTS:
        if not evidence[requirement]:
            issues[requirement].append("missing")
        if len(values[requirement]) > 1:
            issues[requirement].append("contradictory")
        # Conservative snapshot: any unresolved record prevents establishing a fact.
        facts[requirement] = (next(iter(values[requirement]))
                              if len(values[requirement]) == 1 and not issues[requirement]
                              else None)
        issues[requirement] = list(dict.fromkeys(issues[requirement]))

    decision = evaluate_eligibility(facts)
    if not supported_case:
        decision["status"] = "needs_review"
    return {
        "facts": facts, "decision": decision, "evidence": evidence,
        "issues": issues,
        "scope_issue": None if supported_case else "unsupported_case",
    }
