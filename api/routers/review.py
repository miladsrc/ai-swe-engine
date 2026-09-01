"""
Phase 2 I3 (G8) — independent Reviewer boundary.

The Reviewer (identity `agent:reviewer`) is a genuinely separate,
ADVISORY-ONLY authority. This router exposes exactly ONE write path for
it — PATCH /mrps/{id}/review — which can only ever set the MRP's own
review fields (ai_review_status, ai_review_notes, ai_review_findings).

Why a dedicated endpoint rather than reusing PATCH /mrps/{id}/evidence:
the evidence path carries verification evidence (unit/security/lint
status) and, in strict mode, is Verifier-only. Review fields are NOT
verification evidence and are NOT owned by the verifier. G8 demands that
the reviewer be advisory-only: it must not be able to write verification
evidence, touch code, mutate agent runs, or approve a merge. By giving it
a narrow endpoint whose payload model fixes the writable field set, a
reviewer (even one that misbehaves) is structurally unable to forge
gate-passing evidence.

Every successful review write is recorded in the append-only audit trail
with actor_id == 'agent:reviewer'. G8 (see api/gates.py) requires that a
merge-ready MRP in strict mode carries a reviewer-owned 'completed'
review record — nothing the coder or orchestrator writes can satisfy it.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api import models, schemas
from api.audit import record_audit
from api.database import get_db
from api.security import require_reviewer_actor, require_any_actor, REVIEWER_ACTOR

router = APIRouter(prefix="/mrps", tags=["review"])

# The ONLY fields this endpoint may ever write, and their valid values.
REVIEW_STATUS_VALUES = {"in_progress", "needs_revision", "completed"}
_WRITABLE_FIELDS = ("ai_review_status", "ai_review_notes", "ai_review_findings")


@router.patch("/{mrp_id}/review")
def update_review(
    mrp_id: str,
    payload: schemas.MRPReviewUpdate,
    db: Session = Depends(get_db),
    reviewer_actor: str = Depends(require_reviewer_actor),
):
    """
    G8: the independent Reviewer writes its OWN advisory review. Only
    fields in MRPReviewUpdate are honored; anything else is rejected with
    explicit detail. The reviewer can never write verification evidence,
    touch code/agent runs, or make a merge decision — that is enforced by
    (a) the narrow payload model here, (b) require_reviewer_actor's token
    gate, and (c) the reviewer role's client-side allowlist in
    agents/config.py.
    """
    mrp = db.get(models.MRP, mrp_id)
    if not mrp:
        raise HTTPException(404, "MRP not found")

    data = payload.model_dump(exclude_unset=True)

    if not data:
        raise HTTPException(422, "Review update payload is empty — "
                                 "nothing to write.")

    # Reject any attempt to smuggle a non-review field through the model.
    for field in data:
        if field not in _WRITABLE_FIELDS:
            raise HTTPException(
                403,
                f"Reviewer may not write field '{field}'. The reviewer is "
                f"advisory-only and may write only: {_WRITABLE_FIELDS}.",
            )

    if "ai_review_status" in data:
        status = data["ai_review_status"]
        if status not in REVIEW_STATUS_VALUES:
            raise HTTPException(
                422,
                f"Invalid ai_review_status '{status}'. Allowed: "
                f"{sorted(REVIEW_STATUS_VALUES)}. (Advisory only — a reviewer "
                f"never approves a merge.)",
            )

    written = {}
    for field in _WRITABLE_FIELDS:
        if field in data:
            setattr(mrp, field, data[field])
            written[field] = data[field]

    record_audit(
        db,
        actor_type="agent",
        actor_id=reviewer_actor,       # == "agent:reviewer", never forgable
        action="update_mrp_review",
        artifact_type="MRP",
        artifact_id=mrp_id,
        context={
            "review_fields": written,
            "sod_mode": "strict:g8",
            "advisory": True,
        },
    )
    db.commit()
    return {
        "id": mrp_id,
        "reviewer_actor": reviewer_actor,
        "written": written,
    }


@router.get("/{mrp_id}/review")
def get_review(mrp_id: str, db: Session = Depends(get_db),
               _actor: str = Depends(require_any_actor)):
    """
    Read-only view of the advisory review. Any authenticated actor
    (human:/agent:/ci:/system:) may read it — it is advisory evidence, not
    a secret and not a merge authorization.
    """
    mrp = db.get(models.MRP, mrp_id)
    if not mrp:
        raise HTTPException(404, "MRP not found")
    return {
        "mrp_id": mrp.id,
        "ai_review_status": mrp.ai_review_status,
        "ai_review_notes": mrp.ai_review_notes or [],
        "ai_review_findings": mrp.ai_review_findings or [],
        "reviewer_actor": REVIEWER_ACTOR,
    }
