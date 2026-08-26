"""
Blueprints router — CRUD for architectural blueprints.

Blueprints are the "how to build it" documents that agents reference
during code generation. They live in the blueprints table with
composite PK (id, version) so the same blueprint can evolve over time.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from api.database import get_db
from api import models, schemas, ids
from api.audit import record_audit

router = APIRouter(prefix="/blueprints", tags=["blueprints"])


def _actor_type(actor_id: str) -> str:
    """Mirror the created_by convention: 'human:<name>' vs 'agent:<role>'."""
    if actor_id.startswith("human:"):
        return "human"
    if actor_id.startswith(("ci:", "system:")):
        return "system"
    return "agent"


@router.post("", status_code=201)
def create_blueprint(payload: schemas.BlueprintCreate, db: Session = Depends(get_db)):
    """Create a new blueprint. The (id, version) pair is the composite PK."""
    existing = db.get(models.Blueprint, (payload.id, payload.version))
    if existing:
        raise HTTPException(
            409, f"Blueprint {payload.id} v{payload.version} already exists."
        )
    bp = models.Blueprint(
        id=payload.id,
        version=payload.version,
        scope=payload.scope,
        body_ref=payload.body_ref,
        approved_by=payload.approved_by,
        change_note=payload.change_note,
    )
    db.add(bp)
    # P8: blueprint mutations are now audited — blueprint_version is
    # merge-gating evidence (§3.7.8), so its history must be append-only.
    record_audit(
        db, actor_type=_actor_type(payload.approved_by),
        actor_id=payload.approved_by, action="create_blueprint",
        artifact_type="Blueprint", artifact_id=f"{payload.id}:{payload.version}",
        context={"scope": payload.scope, "change_note": payload.change_note},
    )
    db.commit()
    return schemas.BlueprintOut.model_validate(bp)


@router.get("")
def list_blueprints(
    scope: str | None = None,
    db: Session = Depends(get_db),
):
    """List all blueprints, optionally filtered by scope prefix."""
    stmt = select(models.Blueprint).order_by(
        models.Blueprint.id, models.Blueprint.version
    )
    if scope:
        stmt = stmt.where(models.Blueprint.scope.startswith(scope))
    bps = db.execute(stmt).scalars().all()
    return [schemas.BlueprintOut.model_validate(b) for b in bps]


@router.get("/{blueprint_id}")
def get_blueprint(blueprint_id: str, db: Session = Depends(get_db)):
    """Get all versions of a blueprint."""
    stmt = (
        select(models.Blueprint)
        .where(models.Blueprint.id == blueprint_id)
        .order_by(models.Blueprint.version)
    )
    bps = db.execute(stmt).scalars().all()
    if not bps:
        raise HTTPException(404, f"Blueprint {blueprint_id} not found.")
    return [schemas.BlueprintOut.model_validate(b) for b in bps]


@router.get("/{blueprint_id}/versions/{version}")
def get_blueprint_version(
    blueprint_id: str, version: str, db: Session = Depends(get_db)
):
    """Get a specific version of a blueprint."""
    bp = db.get(models.Blueprint, (blueprint_id, version))
    if not bp:
        raise HTTPException(
            404, f"Blueprint {blueprint_id} v{version} not found."
        )
    return schemas.BlueprintOut.model_validate(bp)


@router.patch("/{blueprint_id}/versions/{version}")
def update_blueprint(
    blueprint_id: str,
    version: str,
    payload: schemas.BlueprintCreate,
    db: Session = Depends(get_db),
):
    """Update a specific blueprint version (body_ref, change_note, etc.)."""
    bp = db.get(models.Blueprint, (blueprint_id, version))
    if not bp:
        raise HTTPException(
            404, f"Blueprint {blueprint_id} v{version} not found."
        )
    for field in ("scope", "body_ref", "approved_by", "change_note"):
        val = getattr(payload, field, None)
        if val is not None:
            setattr(bp, field, val)
    # P8: audit blueprint updates in the same transaction as the write.
    record_audit(
        db, actor_type=_actor_type(payload.approved_by),
        actor_id=payload.approved_by, action="update_blueprint",
        artifact_type="Blueprint", artifact_id=f"{blueprint_id}:{version}",
        context={"scope": payload.scope, "change_note": payload.change_note},
    )
    db.commit()
    return schemas.BlueprintOut.model_validate(bp)
