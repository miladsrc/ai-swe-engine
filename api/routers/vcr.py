from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.database import get_db
from api import models, schemas, ids
from api.audit import record_audit
from api.security import require_human_actor

router = APIRouter(prefix="/vcrs", tags=["vcr"])


@router.post("")
def create_vcr(
    payload: schemas.VCRCreate,
    db: Session = Depends(get_db),
    decided_by: str = Depends(require_human_actor),
):
    """
    Records a human decision as a durable, versioned artifact (§3.7.6).
    If the related artifact is a CRP, this closes it. This is the ONLY
    way a CRP transitions to 'resolved' — there is no automatic path.

    The decider's identity comes from the X-Acting-As header (verified
    human), never from the request body — see api/security.py.
    """
    if payload.related_artifact_type == "CRP":
        crp = db.get(models.CRP, payload.related_artifact_id)
        if not crp:
            raise HTTPException(404, f"CRP {payload.related_artifact_id} not found")
        crp.status = "resolved"
        # Clear the resolved CRP from every MRP that had it attached at
        # creation time. Without this, mrp_ready_for_merge keeps reading a
        # stale open_crp_ids snapshot and blocks the merge forever after —
        # the CRP is resolved but the MRP never finds out.
        affected_mrps = (
            db.query(models.MRP)
            .filter(models.MRP.open_crp_ids.any(payload.related_artifact_id))
            .all()
        )
        for m in affected_mrps:
            m.open_crp_ids = [
                c for c in (m.open_crp_ids or []) if c != payload.related_artifact_id
            ]
    elif payload.related_artifact_type == "MRP":
        if not db.get(models.MRP, payload.related_artifact_id):
            raise HTTPException(404, f"MRP {payload.related_artifact_id} not found")
    else:
        raise HTTPException(422, "related_artifact_type must be 'CRP' or 'MRP'")

    new_id = ids.vcr_id(payload.related_artifact_id)
    if db.get(models.VCR, new_id):
        raise HTTPException(409, f"VCR {new_id} already exists — a resolution was already recorded")

    vcr = models.VCR(
        id=new_id,
        related_artifact_type=payload.related_artifact_type,
        related_artifact_id=payload.related_artifact_id,
        decision_status=payload.decision_status,
        selected_option=payload.selected_option,
        rationale=payload.rationale,
        decided_by=decided_by,
        decided_role=payload.decided_role,
        update_prd=payload.update_prd,
        update_user_story=payload.update_user_story,
        update_spec=payload.update_spec,
        update_blueprint=payload.update_blueprint,
        update_tests=payload.update_tests,
        required_updates=payload.required_updates,
    )
    db.add(vcr)
    record_audit(
        db, actor_type="human", actor_id=decided_by, action="create_vcr",
        artifact_type="VCR", artifact_id=new_id,
        human_decision=payload.decision_status,
        context={"related_artifact_id": payload.related_artifact_id},
    )
    db.commit()
    return {"id": new_id}


@router.post("/{vcr_id}/promote")
def promote_to_org_memory(
    vcr_id: str,
    db: Session = Depends(get_db),
    promoted_by: str = Depends(require_human_actor),
):
    """
    v3 §4 curation gate: a VCR only enters Org RAG/Blueprint when a human
    explicitly marks it as generalizing beyond this project. This is a
    deliberate, separate action from recording the decision itself —
    most VCRs are project-local and should stay that way.

    Identity from the X-Acting-As header — see api/security.py.
    """
    vcr = db.get(models.VCR, vcr_id)
    if not vcr:
        raise HTTPException(404, "VCR not found")
    vcr.promoted_to_org_memory = True
    record_audit(
        db, actor_type="human", actor_id=promoted_by, action="promote_vcr_to_org_memory",
        artifact_type="VCR", artifact_id=vcr_id,
    )
    db.commit()
    return {"id": vcr_id, "promoted_to_org_memory": True}


@router.get("/{vcr_id}")
def get_vcr(vcr_id: str, db: Session = Depends(get_db)):
    vcr = db.get(models.VCR, vcr_id)
    if not vcr:
        raise HTTPException(404, "VCR not found")
    return vcr
