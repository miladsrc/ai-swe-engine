from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import case
from sqlalchemy.orm import Session
from api.database import get_db
from api import models, schemas, ids
from api.audit import record_audit

router = APIRouter(prefix="/crps", tags=["crp"])

VALID_SEVERITIES = {"low", "medium", "high", "critical"}


@router.post("")
def create_crp(payload: schemas.CRPCreate, db: Session = Depends(get_db)):
    """
    Per §3.6.1, a CRP should only be raised for one of the seven documented
    trigger conditions — this endpoint doesn't (and can't) enforce *which*
    trigger fired, since that's a judgment call made by the calling agent,
    but it does require the agent to state its severity and recommendation
    rather than silently blocking with no artifact at all.
    """
    if payload.severity not in VALID_SEVERITIES:
        raise HTTPException(422, f"severity must be one of {VALID_SEVERITIES}")
    if not db.get(models.Project, payload.project_id):
        raise HTTPException(404, f"Project {payload.project_id} not found")

    new_id = ids.crp_id(db, payload.domain)
    crp = models.CRP(
        id=new_id,
        project_id=payload.project_id,
        agent_run_id=payload.agent_run_id,
        prd_id=payload.prd_id,
        user_story_id=payload.user_story_id,
        spec_id=payload.spec_id,
        severity=payload.severity,
        blocking_issue_title=payload.blocking_issue_title,
        blocking_issue_body=payload.blocking_issue_body,
        context_summary=payload.context_summary,
        options_considered=payload.options_considered,
        agent_recommendation=payload.agent_recommendation,
        required_decision=payload.required_decision,
        required_role=payload.required_role,
        default_policy=payload.default_policy,
        status="open",
    )
    db.add(crp)

    # If this run exists and severity is high/critical, mark the run blocked —
    # this is what §3.6.3 means by "must not proceed without human decision."
    if payload.agent_run_id:
        run = db.get(models.AgentRun, payload.agent_run_id)
        if run and payload.severity in ("high", "critical"):
            run.status = "blocked"

    record_audit(
        db, actor_type="agent", actor_id=payload.agent_run_id or "unknown",
        action="create_crp", artifact_type="CRP", artifact_id=new_id,
        context={"severity": payload.severity, "required_role": payload.required_role},
    )
    db.commit()
    return {"id": new_id, "status": "open", "severity": payload.severity}


@router.get("/{crp_id}")
def get_crp(crp_id: str, db: Session = Depends(get_db)):
    crp = db.get(models.CRP, crp_id)
    if not crp:
        raise HTTPException(404, "CRP not found")
    return crp


@router.get("")
def list_open_crps(status: str | None = "open", db: Session = Depends(get_db)):
    q = db.query(models.CRP)
    if status:
        q = q.filter(models.CRP.status == status)
    # Severity is stored as text; order by actual priority, not alphabetically
    # (plain .desc() would rank 'medium' above 'critical').
    severity_order = case(
        (models.CRP.severity == "critical", 0),
        (models.CRP.severity == "high", 1),
        (models.CRP.severity == "medium", 2),
        else_=3,
    )
    return q.order_by(severity_order.asc(), models.CRP.created_at.asc()).all()
