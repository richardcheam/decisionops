"""Pure proposal contents and review checks; neither approval nor execution."""
from copy import deepcopy
import hashlib
import json

from .eligibility import REQUIREMENTS


def document_hash(document):
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def binding(assessment):
    versions = {tool["requirement"]: tool["source_version"] for tool in assessment["read_tools"]}
    if set(versions) != set(REQUIREMENTS):
        raise ValueError("Assessment must contain all seven evidence versions")
    return {
        "schema_version": 1,
        "action": "propose_replacement",
        "request": deepcopy(assessment["request"]),
        "policy_id": assessment["policy_id"],
        "source_versions": versions,
    }


def build_proposal(assessment):
    if assessment["decision"]["status"] != "eligible_to_propose" or assessment["scope_reasons"]:
        return None
    return binding(assessment)


def check_proposal(document, current):
    latest = binding(current)
    changed = [name for name in REQUIREMENTS
               if document["source_versions"][name] != latest["source_versions"][name]]
    matches = document == latest
    eligible = current["decision"]["status"] == "eligible_to_propose" and not current["scope_reasons"]
    return {
        "status": "valid_for_review" if matches and eligible else "requires_reinvestigation",
        "binding_matches": matches,
        "changed_requirements": changed,
        "current_decision": deepcopy(current["decision"]),
        "scope_reasons": list(current["scope_reasons"]),
        "execution_authorized": False,
    }
