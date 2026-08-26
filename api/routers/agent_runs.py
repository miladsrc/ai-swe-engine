from datetime import datetime, timedelta, timezone
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from api.database import get_db
from api import models, schemas, ids
from api.audit import record_audit
from api.gates import spec_must_be_human_validated_before_code_gen, assert_run_patchable

router = APIRouter(prefix="/agent-runs", tags=["agent-runs"])

# P4: runs older than this many hours and still 'running' are considered
# orphaned by the startup reaper (SASE_ORPHAN_RUN_HOURS overrides).
ORPHAN_RUN_MAX_AGE_HOURS = 24.0


def _orphan_cutoff(now: datetime,
                   max_age_hours: float | None = None) -> datetime:
    """Pure helper (unit-tested): start of the orphan window."""
    hours = (float(os.environ.get("SASE_ORPHAN_RUN_HOURS", ORPHAN_RUN_MAX_AGE_HOURS))
             if max_age_hours is None else max_age_hours)
    return now - timedelta(hours=hours)


def reap_orphan_runs(db: Session, *, now: datetime | None = None,
                     max_age_hours: float | None = None) -> list[str]:
    """
    Mark abandoned 'running' AgentRuns as 'failed'. Uses the SAME
    transition rules as PATCH /agent-runs/{id} (terminal status +
    finished_at stamp) and the same audit mechanism — no new lifecycle
    concept is introduced. Returns the reaped run ids.

    `now`/`max_age_hours` parameters exist for deterministic tests;
    production callers use the defaults (wall clock + env/config age).
    """
    current = now or datetime.now(timezone.utc)
    cutoff = _orphan_cutoff(current, max_age_hours)
    stmt = select(models.AgentRun).where(
        models.AgentRun.status == "running",
        models.AgentRun.started_at < cutoff,
    )
    runs = db.execute(stmt).scalars().all()
    reaped: list[str] = []
    for run in runs:
        run.status = "failed"
        run.finished_at = func.now()
        record_audit(
            db, actor_type="system", actor_id="orphan-reaper",
            action="reap_orphan_run", artifact_type="AgentRun",
            artifact_id=run.id, result="failed",
            context={
                "started_at": run.started_at.isoformat()
                if run.started_at else None,
                "cutoff": cutoff.isoformat(),
                "max_age_hours": max_age_hours
                if max_age_hours is not None
                else float(os.environ.get("SASE_ORPHAN_RUN_HOURS",
                                          ORPHAN_RUN_MAX_AGE_HOURS)),
                "reason": "orphaned: process died before terminal patch",
            },
        )
        reaped.append(run.id)
    if reaped:
        db.commit()
    return reaped


@router.post("")
def start_agent_run(payload: schemas.AgentRunCreate, db: Session = Depends(get_db)):
    """
    Starts (and records) an Agent Run. If task_type == 'code_generation' and
    a spec_id is given, the Spec must already be human_validated — this is
    the concrete enforcement of §3.5, checked at the one point that matters:
    right before a Coder Agent would actually start generating code.
    """
    if not db.get(models.Project, payload.project_id):
        raise HTTPException(404, f"Project {payload.project_id} not found")

    if payload.task_type == "code_generation" and payload.spec_id:
        spec_must_be_human_validated_before_code_gen(db, payload.spec_id)

    new_id = ids.agent_run_id(db, payload.model_short)
    run = models.AgentRun(
        id=new_id,
        project_id=payload.project_id,
        agent_role=payload.agent_role,
        task_type=payload.task_type,
        prd_id=payload.prd_id,
        user_story_id=payload.user_story_id,
        spec_id=payload.spec_id,
        blueprint_ids=payload.blueprint_ids,
        model_name=payload.model_name,
        model_version=payload.model_version,
        prompt_id=payload.prompt_id,
        prompt_version=payload.prompt_version,
        system_prompt_hash=payload.system_prompt_hash,
        rag_retrieval_enabled=payload.rag_retrieval_enabled,
        rag_retrieved_doc_ids=payload.rag_retrieved_doc_ids,
        status="running",
    )
    db.add(run)
    record_audit(
        db, actor_type="agent", actor_id=payload.agent_role, action="start_agent_run",
        artifact_type="AgentRun", artifact_id=new_id,
        context={"task_type": payload.task_type, "spec_id": payload.spec_id},
        model_version=payload.model_name,
    )
    db.commit()
    return {"id": new_id}


@router.patch("/{run_id}")
def update_agent_run(run_id: str, payload: schemas.AgentRunUpdate, db: Session = Depends(get_db)):
    run = db.get(models.AgentRun, run_id)
    if not run:
        raise HTTPException(404, "Agent Run not found")

    # Terminal-state machine (§3.7.8): unknown statuses rejected 422; runs
    # already completed/failed/blocked are immutable provenance — 409.
    assert_run_patchable(run.status, payload.status)

    run.status = payload.status
    if payload.reflection_iterations is not None:
        run.reflection_iterations = payload.reflection_iterations
    if payload.tools_used is not None:
        run.tools_used = payload.tools_used
    if payload.generated_files is not None:
        run.generated_files = payload.generated_files
    if payload.commit_hash is not None:
        run.commit_hash = payload.commit_hash
    if payload.mrp_id is not None:
        run.mrp_id = payload.mrp_id
    if payload.status in ("completed", "failed", "blocked"):
        from sqlalchemy import func
        run.finished_at = func.now()

    record_audit(
        db, actor_type="agent", actor_id=run.agent_role, action="update_agent_run",
        artifact_type="AgentRun", artifact_id=run_id, result=payload.status,
    )
    db.commit()
    return {"id": run_id, "status": run.status}


@router.get("/{run_id}")
def get_agent_run(run_id: str, db: Session = Depends(get_db)):
    run = db.get(models.AgentRun, run_id)
    if not run:
        raise HTTPException(404, "Agent Run not found")
    return run
