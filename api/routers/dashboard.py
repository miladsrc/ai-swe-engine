"""
Dashboard read-only API (additive UI support).

The UI is a CLIENT LAYER over the existing governance engine â€” it owns no
state and grants no rights. Every endpoint here:
  - is READ-ONLY except the console-instruction recorder, which writes
    ONLY to the existing append-only audit log via record_audit();
  - requires an explicit actor identity (require_authenticated_actor) so anonymous
    scraping is impossible;
  - performs NO authorization decisions â€” approval/rejection still goes
    exclusively through the pre-existing gated endpoints
    (POST /specs/{id}/validate, POST /mrps/{id}/human-decision,
     POST /vcrs), where require_human_actor enforces token identity.

Nothing in this file changes any existing flow.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api import models
from api.audit import record_audit
from api.database import get_db
from api.security import require_authenticated_actor, require_human_actor

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/overview")
def overview(db: Session = Depends(get_db),
             actor: str = Depends(require_authenticated_actor)):
    """Counts for the personal dashboard header."""
    def count(model, *conditions):
        from sqlalchemy import func
        stmt = select(func.count()).select_from(model)
        for c in conditions:
            stmt = stmt.where(c)
        return db.execute(stmt).scalar() or 0

    return {
        "agent_runs": {
            "running": count(models.AgentRun, models.AgentRun.status == "running"),
            "completed": count(models.AgentRun, models.AgentRun.status == "completed"),
            "failed": count(models.AgentRun, models.AgentRun.status == "failed"),
            "blocked": count(models.AgentRun, models.AgentRun.status == "blocked"),
        },
        "pending": {
            "open_crps": count(models.CRP, models.CRP.status.in_(["open", "blocking"])),
            "mrps_awaiting_human": count(
                models.MRP, models.MRP.status.in_(
                    ["ready_for_human_review", "needs_revision"])),
            "unvalidated_specs": count(models.Spec, models.Spec.human_validated == False),  # noqa: E712
        },
    }


@router.get("/agent-runs")
def list_agent_runs(status: str | None = None,
                    project_id: str | None = None,
                    limit: int = Query(50, le=200),
                    db: Session = Depends(get_db),
                    actor: str = Depends(require_authenticated_actor)):
    stmt = select(models.AgentRun).order_by(
        models.AgentRun.started_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(models.AgentRun.status == status)
    if project_id:
        stmt = stmt.where(models.AgentRun.project_id == project_id)
    runs = db.execute(stmt).scalars().all()
    return [
        {
            "id": r.id, "project_id": r.project_id, "agent_role": r.agent_role,
            "task_type": r.task_type, "status": r.status,
            "model_name": r.model_name, "spec_id": r.spec_id,
            "mrp_id": r.mrp_id, "reflection_iterations": r.reflection_iterations,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        } for r in runs
    ]


@router.get("/approvals")
def pending_approvals(db: Session = Depends(get_db),
                      actor: str = Depends(require_authenticated_actor)):
    """
    The Approval Center inbox. Read-only aggregation of everything a human
    may need to decide on. Decisions themselves happen ONLY at the
    pre-existing gated endpoints.
    """
    specs = db.execute(select(models.Spec).where(
        models.Spec.human_validated == False)  # noqa: E712
        .order_by(models.Spec.created_at.desc()).limit(50)).scalars().all()
    crps = db.execute(select(models.CRP).where(
        models.CRP.status.in_(["open", "blocking"]))
        .order_by(models.CRP.created_at.desc()).limit(50)).scalars().all()
    mrps = db.execute(select(models.MRP).where(
        models.MRP.status.in_(["ready_for_human_review", "needs_revision", "blocked_by_consultation"]))
        .order_by(models.MRP.created_at.desc()).limit(50)).scalars().all()

    return {
        "spec_validations": [
            {"kind": "SPEC_VALIDATION", "id": s.id, "project_id": s.project_id,
             "created_at": s.created_at.isoformat() if s.created_at else None}
            for s in specs],
        "crps": [
            {"kind": "CRP", "id": c.id, "severity": c.severity,
             "status": c.status, "title": c.blocking_issue_title,
             "required_role": c.required_role, "spec_id": c.spec_id,
             "agent_run_id": c.agent_run_id,
             "created_at": c.created_at.isoformat() if c.created_at else None}
            for c in crps],
        "mrps": [
            {"kind": "MRP", "id": m.id, "status": m.status,
             "project_id": m.project_id, "change_summary": m.change_summary,
             "branch_name": m.branch_name, "spec_ids": m.spec_ids,
             "unit_tests_status": m.unit_tests_status,
             "security_scan_status": m.security_scan_status,
             "created_by_agent_run": m.created_by_agent_run,
             "created_at": m.created_at.isoformat() if m.created_at else None}
            for m in mrps],
    }


@router.get("/audit")
def query_audit(action: str | None = None,
                artifact_type: str | None = None,
                artifact_id: str | None = None,
                actor_id: str | None = None,
                limit: int = Query(100, le=500),
                db: Session = Depends(get_db),
                actor: str = Depends(require_authenticated_actor)):
    """Filterable audit query â€” same append-only table as everywhere else."""
    stmt = select(models.AuditLog).order_by(
        models.AuditLog.timestamp.desc()).limit(limit)
    if action:
        stmt = stmt.where(models.AuditLog.action == action)
    if artifact_type:
        stmt = stmt.where(models.AuditLog.artifact_type == artifact_type)
    if artifact_id:
        stmt = stmt.where(models.AuditLog.artifact_id.contains(artifact_id))
    if actor_id:
        stmt = stmt.where(models.AuditLog.actor_id.contains(actor_id))
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": e.id, "actor_type": e.actor_type, "actor_id": e.actor_id,
            "action": e.action, "artifact_type": e.artifact_type,
            "artifact_id": e.artifact_id, "result": e.result,
            "human_decision": e.human_decision,
            "context": e.context,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        } for e in rows
    ]


@router.get("/projects/{project_id}/summary")
def project_summary(project_id: str,
                    db: Session = Depends(get_db),
                    actor: str = Depends(require_authenticated_actor)):
    """One-page state of a project."""
    project = db.get(models.Project, project_id)
    if not project:
        from fastapi import HTTPException
        raise HTTPException(404, f"Project {project_id} not found")
    specs = db.execute(select(models.Spec).where(
        models.Spec.project_id == project_id)
        .order_by(models.Spec.created_at.desc()).limit(50)).scalars().all()
    runs = db.execute(select(models.AgentRun).where(
        models.AgentRun.project_id == project_id)
        .order_by(models.AgentRun.started_at.desc()).limit(50)).scalars().all()
    mrps = db.execute(select(models.MRP).where(
        models.MRP.project_id == project_id)
        .order_by(models.MRP.created_at.desc()).limit(50)).scalars().all()
    return {
        "project": {"id": project.id, "name": project.name,
                    "stack": project.stack},
        "specs": [{"id": s.id, "human_validated": s.human_validated,
                   "created_at": s.created_at.isoformat()
                   if s.created_at else None} for s in specs],
        "runs": [{"id": r.id, "status": r.status, "agent_role": r.agent_role,
                  "started_at": r.started_at.isoformat()
                  if r.started_at else None} for r in runs],
        "mrps": [{"id": m.id, "status": m.status,
                  "created_at": m.created_at.isoformat()
                  if m.created_at else None} for m in mrps],
    }


@router.post("/console/instructions")
def record_console_instruction(payload: dict,
                               db: Session = Depends(get_db),
                               human: str = Depends(require_human_actor)):
    """
    Agent Console: records a human instruction into the append-only audit
    trail so agent operators have one governed place to issue directions.
    NOTE (honest boundary): pipeline EXECUTION remains CLI-driven
    (`python -m agents.orchestrator ...`) â€” this endpoint does not spawn
    agents; it makes instructions traceable. See FULL_DOCUMENTATION Â§UI.
    """
    text = str(payload.get("instruction", "")).strip()
    if not text:
        from fastapi import HTTPException
        raise HTTPException(422, "instruction must be a non-empty string")
    if len(text) > 4000:
        raise HTTPException(422, "instruction too long (max 4000 chars)")
    record_audit(db, actor_type="human", actor_id=human,
                 action="agent_instruction",
                 artifact_type="Console",
                 artifact_id=payload.get("run_id") or "unassigned",
                 context={"instruction": text})
    db.commit()
    return {"recorded": True, "actor": human}
