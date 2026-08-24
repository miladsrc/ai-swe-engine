"""
Implements the exact questions §3.7 says the organization must be able
to answer: what requirement produced this code, which spec/blueprint/
prompt/RAG-context an agent used, who decided what and when, and whether
a given piece of code can be traced end-to-end back to a PRD.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.database import get_db
from api import models
from api.security import require_any_actor

router = APIRouter(prefix="/traceability", tags=["traceability"])


@router.get("/chain/{mrp_id}")
def full_chain_for_mrp(mrp_id: str, db: Session = Depends(get_db)):
    """
    Walks MRP -> Spec(s) -> User Story(ies) -> PRD, plus the Agent Run,
    any CRPs, and any VCRs — the full answer to "based on which
    requirement was this generated, who decided what, and is it auditable?"
    """
    mrp = db.get(models.MRP, mrp_id)
    if not mrp:
        raise HTTPException(404, "MRP not found")

    prd = db.get(models.PRD, mrp.prd_id) if mrp.prd_id else None
    specs = db.query(models.Spec).filter(models.Spec.id.in_(mrp.spec_ids or [])).all()
    agent_run = db.get(models.AgentRun, mrp.created_by_agent_run) if mrp.created_by_agent_run else None
    crps = db.query(models.CRP).filter(models.CRP.spec_id.in_(mrp.spec_ids or [])).all()
    crp_ids = [c.id for c in crps]
    vcrs = db.query(models.VCR).filter(models.VCR.related_artifact_id.in_(crp_ids + [mrp_id])).all()

    return {
        "mrp": mrp,
        "prd": prd,
        "specs": specs,
        "agent_run": agent_run,
        "crps": crps,
        "vcrs": vcrs,
        "fully_traceable": bool(prd and specs and agent_run),
    }


@router.get("/audit/{artifact_type}/{artifact_id}")
def audit_for_artifact(
    artifact_type: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    _actor: str = Depends(require_any_actor),
):
    """
    Every recorded action touching one artifact, in order. Guarded: the
    audit trail is governance evidence and must not be readable
    anonymously — any well-formed actor (human:/agent:/ci:/system:) may
    read it, but the request must identify itself.
    """
    return (
        db.query(models.AuditLog)
        .filter(models.AuditLog.artifact_type == artifact_type, models.AuditLog.artifact_id == artifact_id)
        .order_by(models.AuditLog.timestamp.asc())
        .all()
    )
