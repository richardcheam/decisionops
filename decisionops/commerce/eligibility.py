"""Evaluate normalized eligibility facts for supported whole-shipment cases.

Callers establish facts from authoritative evidence and route unsupported
partial cases to review. This module neither retrieves evidence nor approves
or executes replacements.
"""

REQUIREMENTS = (
    "paid",
    "shipped",
    "loss_confirmed",
    "quantities_valid",
    "no_previous_compensation",
    "stock_available",
    "policy_permits",
)


def evaluate_eligibility(facts):
    """Evaluate True/False/None facts; reject malformed requirement values.

    Absent keys mean unknown. Extra keys do not supply required evidence.
    """
    blockers = []
    unknowns = []

    for requirement in REQUIREMENTS:
        value = facts.get(requirement)

        if value is not True and value is not False and value is not None:
            raise ValueError(f"{requirement} must be True, False, or None")

        if value is False:
            blockers.append(requirement)
        elif value is None:
            unknowns.append(requirement)

    if blockers:
        status = "ineligible"
    elif unknowns:
        status = "needs_review"
    else:
        status = "eligible_to_propose"

    return {
        "status": status,
        "blockers": blockers,
        "unknowns": unknowns,
    }
