"""Durable investigations; callers own transactions. Business records are read only."""
import json
import uuid

import sqlalchemy as sa

from . import schema as db
from .proposals import build_proposal, check_proposal, document_hash
from .read_tools import AssessmentRequest, canonical, read_assessment


def investigate(connection, request, now):
    assessment = json.loads(canonical(read_assessment(connection, request, now)))
    investigation_id = "INV-" + uuid.uuid4().hex
    connection.execute(sa.insert(db.investigations).values(
        id=investigation_id, order_id=request.order_id, created_at=now, assessment=assessment))
    document = build_proposal(assessment)
    proposal_id = None
    if document is not None:
        proposal_id = "PROP-" + uuid.uuid4().hex
        connection.execute(sa.insert(db.proposals).values(
            id=proposal_id, investigation_id=investigation_id, created_at=now,
            document=document, content_hash=document_hash(document)))
    return {"investigation_id": investigation_id, "proposal_id": proposal_id,
            "created_at": now.isoformat(), "decision": assessment["decision"],
            "scope_reasons": assessment["scope_reasons"], "execution_authorized": False}


def load_proposal(connection, proposal_id):
    row = connection.execute(sa.select(db.proposals).where(db.proposals.c.id == proposal_id)).mappings().one_or_none()
    if row is None:
        raise ValueError("Proposal not found")
    result = dict(row)
    if document_hash(result["document"]) != result["content_hash"]:
        raise ValueError("Stored proposal content hash mismatch; investigate audit integrity")
    return result


def inspect_investigation(connection, investigation_id):
    row = connection.execute(sa.select(db.investigations).where(
        db.investigations.c.id == investigation_id)).mappings().one_or_none()
    if row is None:
        raise ValueError("Investigation not found")
    result = dict(row)
    proposal_id = connection.execute(sa.select(db.proposals.c.id).where(
        db.proposals.c.investigation_id == investigation_id)).scalar_one_or_none()
    result["proposal"] = load_proposal(connection, proposal_id) if proposal_id else None
    return result


def recheck(connection, proposal_id, now):
    saved = load_proposal(connection, proposal_id)
    request = AssessmentRequest(**saved["document"]["request"])
    current = read_assessment(connection, request, now)
    result = check_proposal(saved["document"], current)
    result.update(proposal_id=proposal_id, investigation_id=saved["investigation_id"],
                  checked_at=now.isoformat(), current_assessment=current)
    return result
