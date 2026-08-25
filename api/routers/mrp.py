from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.database import get_db
from api import models, schemas, ids
from api.audit import record_audit
from api.gates import mrp_ready_for_merge, no_open_high_or_critical_crp_blocks_merge
from api.security import require_human_actor, require_ci_actor

router = APIRouter(prefix="/mrps", tags=["mrp"])


@router.post("")
def create_mrp(payload: schemas.MRPCreate, db: Session = Depends(get_db)):
    new_id = ids.mrp_id(payload.pull_request_number)
    if db.get(models.MRP, new_id):
        raise HTTPException(409, f"MRP {new_id} already exists")

    # Attach any currently-open CRPs tied to these specs, per §3.6.5/§3.6.6 —
    # an MRP must be able to answer "were any CRPs raised on this work, and
    # are they closed?"
    open_crps = []
    if payload.spec_ids:
        open_crps = [
            c.id for c in db.query(models.CRP)
            .filter(models.CRP.spec_id.in_(payload.spec_ids), models.CRP.status != "resolved")
            .all()
        ]

    mrp = models.MRP(
        id=new_id,
        project_id=payload.project_id,
        pull_request_ref=str(payload.pull_request_number),
        branch_name=payload.branch_name,
        created_by_agent_run=payload.created_by_agent_run,
        prd_id=payload.prd_id,
        user_story_ids=payload.user_story_ids,
        acceptance_criteria_ids=payload.acceptance_criteria_ids,
        spec_ids=payload.spec_ids,
        blueprint_id=payload.blueprint_id,
        blueprint_version=payload.blueprint_version,
        change_summary=payload.change_summary,
        affected_modules=payload.affected_modules,
        open_crp_ids=open_crps,
        status="draft",
    )
    db.add(mrp)
    record_audit(db, actor_type="agent", actor_id="reviewer_agent", action="create_mrp",
                 artifact_type="MRP", artifact_id=new_id,
                 context={"open_crp_ids": open_crps})
    db.commit()
    return {"id": new_id, "open_crp_ids": open_crps}


@router.patch("/{mrp_id}/evidence")
def update_evidence(
    mrp_id: str,
    payload: schemas.MRPEvidenceUpdate,
    db: Session = Depends(get_db),
    ci_actor: str = Depends(require_ci_actor),
):
    """
    CI/machine actors (test runner, linter, security scanner) call this
    incrementally as each check completes. Identity comes from the
    X-Acting-As header (must start with 'ci:' or 'system:', optionally
    backed by the shared SASE_CI_TOKEN — see api/security.py), never from
    an unauthenticated request: otherwise anyone could forge gate-passing
    evidence. Once all evidence is in, call POST /mrps/{id}/check-ready
    to evaluate the §5.6.5 gate.

    Phase 1: Evidence records now include provenance tagging (source: human | tool | llm).
    """
    mrp = db.get(models.MRP, mrp_id)
    if not mrp:
        raise HTTPException(404, "MRP not found")
    
    # Phase 1: Validate provenance if provided
    evidence_data = payload.model_dump(exclude_unset=True)
    provenance = evidence_data.pop("provenance", None)
    if provenance is not None:
        VALID_PROVENANCES = {"human", "tool", "llm"}
        if provenance not in VALID_PROVENANCES:
            raise HTTPException(422, f"provenance must be one of {VALID_PROVENANCES}")
    
    for field, value in evidence_data.items():
        setattr(mrp, field, value)
    
    # Phase 1: Include provenance in audit context for traceability
    audit_context = evidence_data.copy()
    if provenance:
        audit_context["provenance"] = provenance
    
    record_audit(db,
                 actor_type="ci" if ci_actor.startswith("ci:") else "system",
                 actor_id=ci_actor, action="update_mrp_evidence",
                 artifact_type="MRP", artifact_id=mrp_id,
                 context=audit_context)
    db.commit()
    return {"id": mrp_id, "provenance": provenance}


@router.post("/{mrp_id}/check-ready")
def check_ready(mrp_id: str, db: Session = Depends(get_db)):
    """
    The §5.6.5 gate. Returns whether this MRP may advance to human review,
    and if not, exactly why — this is what the CI pipeline calls before
    flipping the PR status, and it's also what a human reviewer should
    check before spending time on a PR at all.
    """
    mrp = db.get(models.MRP, mrp_id)
    if not mrp:
        raise HTTPException(404, "MRP not found")

    ready, reasons = mrp_ready_for_merge(db, mrp)
    mrp.status = "ready_for_human_review" if ready else "needs_revision"
    record_audit(db, actor_type="system", actor_id="ci-pipeline", action="check_mrp_ready",
                 artifact_type="MRP", artifact_id=mrp_id, result=mrp.status,
                 context={"reasons": reasons})
    db.commit()
    return {"id": mrp_id, "ready": ready, "status": mrp.status, "blocking_reasons": reasons}


@router.post("/{mrp_id}/human-decision")
def human_decision(
    mrp_id: str,
    payload: schemas.MRPHumanDecision,
    db: Session = Depends(get_db),
    human_reviewer: str = Depends(require_human_actor),
):
    """
    Records the human reviewer's call. This does NOT itself perform the
    merge — merging is a git operation outside this service's scope — but
    it is the recorded authorization a merge automation should require
    before it's allowed to proceed (mirrors §3.6.6: no Request Pull with
    an open High/Critical CRP goes to Merge, and no merge happens without
    an explicit human decision recorded here).

    The reviewer's identity comes from the X-Acting-As header (verified
    human), never from the request body — see api/security.py.
    """
    mrp = db.get(models.MRP, mrp_id)
    if not mrp:
        raise HTTPException(404, "MRP not found")

    if payload.decision == "approved":
        no_open_high_or_critical_crp_blocks_merge(db, mrp.spec_ids or [])
        ready, reasons = mrp_ready_for_merge(db, mrp)
        if not ready:
            raise HTTPException(409, f"Cannot approve: {', '.join(reasons)}")

    mrp.status = payload.decision
    mrp.human_reviewer = human_reviewer
    from sqlalchemy import func
    mrp.reviewed_at = func.now()

    record_audit(db, actor_type="human", actor_id=human_reviewer, action="mrp_human_decision",
                 artifact_type="MRP", artifact_id=mrp_id, human_decision=payload.decision)
    db.commit()
    return {"id": mrp_id, "status": mrp.status}


@router.get("/{mrp_id}")
def get_mrp(mrp_id: str, db: Session = Depends(get_db)):
    mrp = db.get(models.MRP, mrp_id)
    if not mrp:
        raise HTTPException(404, "MRP not found")
    return mrp
