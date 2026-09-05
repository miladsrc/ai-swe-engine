"""
Step 2B — remote verification request lifecycle (DEV/CONTAINMENT harness).

The Orchestrator enqueues an IMMUTABLE verification request and NEVER
receives the verifier credential. A separately-administered Verifier
(remote GitLab runner / VM) atomically claims it, verifies the exact pinned
commit, writes trusted evidence to the MRP as ci:verifier, and records
completion. The Orchestrator only polls non-secret status.

PREVIEW (NOT the genuine boundary — see docs/ADR/ADR-002):
  - the security RULES below are the real ones the remote runner honors;
  - a local GitLab/Docker harness here exercises this protocol + secret
    delivery and its tests, but because its runner/admin is the same local
    m.barani, it cannot stand in for the separate-authority boundary.
    tests/test_sod_remote_boundary.py includes a demonstration of exactly why
    a same-user/local-admin execution context fails the genuine threat model.

Endpoints & authority:
  POST /verification-requests                  any machine/agent actor  -> create (idempotent by run_id)
  GET  /verification-requests/{id}/status      any well-formed actor     -> non-secret status
  POST /verification-requests/claim-next       ci:verifier + token       -> atomic claim of one pending
  POST /verification-requests/{id}/complete    ci:verifier + token       -> passed/failed/error
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from api import ids, models, schemas
from api.audit import record_audit
from api.database import get_db
from api.security import require_verifier_actor, require_any_actor

router = APIRouter(prefix="/verification-requests", tags=["verification"])

VALID_COMPLETE = {"passed", "failed", "error"}


def _row_to_schema(row) -> schemas.VerificationRequestStatus:
    return schemas.VerificationRequestStatus(
        id=row.id, run_id=row.run_id, mrp_id=row.mrp_id, commit=row.commit,
        status=row.status, verified_tree_hash=row.verified_tree_hash,
        failure_reason=row.failure_reason, worktree_ref=row.worktree_ref,
        created_at=row.created_at,
        started_at=row.started_at, completed_at=row.completed_at,
        expires_at=row.expires_at)


@router.post("", status_code=201)
def create_request(
    payload: schemas.VerificationRequestCreate,
    actor: str = Depends(require_any_actor),
    db: Session = Depends(get_db),
):
    """
    Orchestrator enqueues work. Idempotent by run_id:
      - same run_id + same commit      -> return the existing request (200 OK)
      - same run_id + DIFFERENT commit -> 409 (one logical verification per run)
    Carries ONLY immutable references — never a credential.
    """
    existing = db.query(models.VerificationRequest).filter(
        models.VerificationRequest.run_id == payload.run_id).first()
    if existing is not None:
        if existing.commit != payload.commit:
            raise HTTPException(
                409,
                f"Request for run_id {payload.run_id} already exists but "
                f"binds a different commit; one logical verification per run.")
        # idempotent re-POST -> return the existing record
        record_audit(db, actor_type="agent", actor_id=actor,
                     action="recreate_verification_request",
                     artifact_type="VerificationRequest",
                     artifact_id=existing.id,
                     context={"run_id": payload.run_id, "commit": payload.commit})
        db.commit()
        return _row_to_schema(existing)

    now = datetime.now(timezone.utc)
    vr = models.VerificationRequest(
        id=ids.verification_request_id(db),
        run_id=payload.run_id,
        mrp_id=payload.mrp_id,
        commit=payload.commit,
        worktree_ref=payload.worktree_ref,
        status="pending",
        created_at=now,
        expires_at=now + timedelta(seconds=payload.ttl_seconds or 3600),
    )
    db.add(vr)
    record_audit(db, actor_type="agent", actor_id=actor,
                 action="create_verification_request",
                 artifact_type="VerificationRequest", artifact_id=vr.id,
                 context={"run_id": payload.run_id, "mrp_id": payload.mrp_id,
                          "commit": payload.commit})
    db.commit()
    return _row_to_schema(vr)


@router.get("/{request_id}/status")
def get_status(
    request_id: str,
    actor: str = Depends(require_any_actor),
    db: Session = Depends(get_db),
):
    """Non-secret status for the Orchestrator. Never returns a credential."""
    row = db.get(models.VerificationRequest, request_id)
    if row is None:
        raise HTTPException(404, "verification request not found")
    # Fail closed on a stale pending request only at report time.
    if row.status == "pending" and row.expires_at \
            and row.expires_at < datetime.now(timezone.utc):
        row.status = "expired"
        db.commit()
    return _row_to_schema(row)


@router.post("/claim-next")
def claim_next(
    actor: str = Depends(require_verifier_actor),
    db: Session = Depends(get_db),
):
    """
    ATOMIC claim of the oldest pending, non-expired request. Only the
    verifier (ci:verifier + token) may claim. Uses a single UPDATE ...
    RETURNING so exactly one worker ever wins, and SKIP LOCKED so concurrent
    workers never claim the same row.
    """
    now = datetime.now(timezone.utc)
    # 1) Expire stale pending requests (fail closed).
    db.execute(
        text("UPDATE verification_requests SET status='expired', "
             "completed_at=:now, failure_reason='request expired before claim' "
             "WHERE status='pending' AND expires_at IS NOT NULL AND expires_at < :now"),
        {"now": now})
    db.commit()

    # 2) Atomically claim one oldest pending request.
    result = db.execute(
        text(
            """
            UPDATE verification_requests
               SET status = 'running',
                   lease_holder = :holder,
                   started_at = :now,
                   lease_expires_at = :lease
             WHERE id = (
                    SELECT id FROM verification_requests
                     WHERE status = 'pending'
                     ORDER BY created_at ASC
                     LIMIT 1
                      FOR UPDATE SKIP LOCKED
             )
            RETURNING id, run_id, mrp_id, commit, worktree_ref,
                      status, verified_tree_hash, failure_reason,
                      created_at, started_at, completed_at, expires_at
            """
        ),
        {"holder": actor, "now": now, "lease": now + timedelta(minutes=30)},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(404, "no claimable verification request")
    record_audit(db, actor_type="ci" if actor.startswith("ci:") else "system",
                 actor_id=actor, action="claim_verification_request",
                 artifact_type="VerificationRequest", artifact_id=row.id,
                 context={"run_id": row.run_id, "commit": row.commit})
    db.commit()
    return _row_to_schema(row)


@router.post("/{request_id}/complete")
def complete_request(
    request_id: str,
    payload: schemas.VerificationRequestComplete,
    actor: str = Depends(require_verifier_actor),
    db: Session = Depends(get_db),
):
    """
    Verifier-only completion of a request it claimed. Only the verifier can
    move a request to passed/failed/error — the Orchestrator can never mark
    verification successful. Rejects requests this verifier did not claim
    and requests already terminal.
    """
    if payload.status not in VALID_COMPLETE:
        raise HTTPException(422, f"status must be one of {sorted(VALID_COMPLETE)}")
    row = db.get(models.VerificationRequest, request_id)
    if row is None:
        raise HTTPException(404, "verification request not found")
    if row.status in ("passed", "failed", "error", "expired"):
        raise HTTPException(409, f"verification request already terminal: {row.status}")
    # Only the holder may complete (a different verifier cannot finish it).
    if row.lease_holder and row.lease_holder != actor:
        raise HTTPException(403, "request is claimed by a different verifier")
    row.status = payload.status
    row.verified_tree_hash = payload.verified_tree_hash
    row.failure_reason = payload.failure_reason
    row.completed_at = datetime.now(timezone.utc)
    record_audit(db, actor_type="ci" if actor.startswith("ci:") else "system",
                 actor_id=actor, action="complete_verification_request",
                 artifact_type="VerificationRequest", artifact_id=row.id,
                 result=payload.status,
                 context={"tree_hash": payload.verified_tree_hash,
                          "failure_reason": payload.failure_reason})
    db.commit()
    return _row_to_schema(row)
