"""
Evidence export endpoint — read-only API for Sara's advisory role.

Phase 1: Provides a read-only view of all evidence for a given agent run,
including provenance tags. This allows external advisors (like Sara) to
review the evidence trail without modifying any data.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.database import get_db
from api import models
from api.audit import record_audit

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("/run/{run_id}")
def export_run_evidence(run_id: str, db: Session = Depends(get_db)):
    """
    Read-only export of all evidence for a given agent run.
    
    Returns:
    - Agent run details (status, model, timestamps, files)
    - MRP evidence (if MRP exists)
    - Audit trail for this run
    
    This endpoint is read-only and designed for external advisory review.
    """
    run = db.get(models.AgentRun, run_id)
    if not run:
        raise HTTPException(404, f"Agent Run {run_id} not found")
    
    # Get MRP if it exists
    mrp = None
    if run.mrp_id:
        mrp = db.get(models.MRP, run.mrp_id)
    
    # Get audit trail for this run
    from sqlalchemy import select
    audit_stmt = select(models.AuditLog).where(
        models.AuditLog.artifact_id == run_id
    ).order_by(models.AuditLog.timestamp.asc())
    audit_entries = db.execute(audit_stmt).scalars().all()
    
    # Record this export in audit (read-only access is still auditable)
    record_audit(
        db, actor_type="system", actor_id="evidence-export",
        action="export_run_evidence", artifact_type="AgentRun", artifact_id=run_id,
        context={"exported_by": "external-advisor"}
    )
    db.commit()
    
    return {
        "run": {
            "id": run.id,
            "project_id": run.project_id,
            "agent_role": run.agent_role,
            "task_type": run.task_type,
            "spec_id": run.spec_id,
            "model_name": run.model_name,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "reflection_iterations": run.reflection_iterations,
            "tools_used": run.tools_used,
            "generated_files": run.generated_files,
            "commit_hash": run.commit_hash,
        },
        "mrp_evidence": {
            "id": mrp.id if mrp else None,
            "unit_tests_status": mrp.unit_tests_status if mrp else None,
            "integration_tests_status": mrp.integration_tests_status if mrp else None,
            "security_scan_status": mrp.security_scan_status if mrp else None,
            "lint_status": mrp.lint_status if mrp else None,
            "ai_review_status": mrp.ai_review_status if mrp else None,
            "status": mrp.status if mrp else None,
        } if mrp else None,
        "audit_trail": [
            {
                "id": entry.id,
                "actor_type": entry.actor_type,
                "actor_id": entry.actor_id,
                "action": entry.action,
                "artifact_type": entry.artifact_type,
                "context": entry.context,
                "result": entry.result,
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            }
            for entry in audit_entries
        ],
    }
