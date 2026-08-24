"""
The requirement chain: PRD -> User Story -> Acceptance Criteria -> Spec.
Spec cannot proceed to code generation until human_validated=True (§3.5) —
that gate lives in api/gates.py and is enforced in routers/agent_runs.py
at the point code generation is requested, not here at creation time.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.database import get_db
from api import models, schemas, ids
from api.audit import record_audit
from api.security import require_human_actor

router = APIRouter(tags=["requirements"])


@router.post("/prds", response_model=schemas.PRDOut)
def create_prd(payload: schemas.PRDCreate, db: Session = Depends(get_db)):
    if not db.get(models.Project, payload.project_id):
        raise HTTPException(404, f"Project {payload.project_id} not found")
    new_id = ids.prd_id(db, payload.domain)
    prd = models.PRD(
        id=new_id,
        project_id=payload.project_id,
        title=payload.title,
        body_ref=payload.body_ref,
        confidence=payload.confidence,
        created_by=payload.created_by,
    )
    db.add(prd)
    record_audit(db, actor_type="human" if payload.created_by.startswith("human:") else "agent",
                 actor_id=payload.created_by, action="create_prd",
                 artifact_type="PRD", artifact_id=new_id)
    db.commit()
    db.refresh(prd)
    return prd


@router.get("/prds/{prd_id}", response_model=schemas.PRDOut)
def get_prd(prd_id: str, db: Session = Depends(get_db)):
    prd = db.get(models.PRD, prd_id)
    if not prd:
        raise HTTPException(404, "PRD not found")
    return prd


@router.post("/user-stories")
def create_user_story(payload: schemas.UserStoryCreate, db: Session = Depends(get_db)):
    if not db.get(models.PRD, payload.prd_id):
        raise HTTPException(404, f"PRD {payload.prd_id} not found")
    new_id = ids.user_story_id(db, payload.domain)
    us = models.UserStory(
        id=new_id, prd_id=payload.prd_id, body_ref=payload.body_ref,
        confidence=payload.confidence,
    )
    db.add(us)
    record_audit(db, actor_type="agent", actor_id="product_agent", action="create_user_story",
                 artifact_type="UserStory", artifact_id=new_id, context={"prd_id": payload.prd_id})
    db.commit()
    return {"id": new_id}


@router.post("/acceptance-criteria")
def create_acceptance_criteria(payload: schemas.AcceptanceCriteriaCreate, db: Session = Depends(get_db)):
    if not db.get(models.UserStory, payload.user_story_id):
        raise HTTPException(404, f"User Story {payload.user_story_id} not found")
    new_id = ids.acceptance_criteria_id(db, payload.user_story_id)
    ac = models.AcceptanceCriteria(id=new_id, user_story_id=payload.user_story_id, body_ref=payload.body_ref)
    db.add(ac)
    record_audit(db, actor_type="agent", actor_id="product_agent", action="create_acceptance_criteria",
                 artifact_type="AcceptanceCriteria", artifact_id=new_id)
    db.commit()
    return {"id": new_id}


@router.post("/specs")
def create_spec(payload: schemas.SpecCreate, db: Session = Depends(get_db)):
    if not db.get(models.Project, payload.project_id):
        raise HTTPException(404, f"Project {payload.project_id} not found")
    new_id = ids.spec_id(payload.domain, payload.name)
    if db.get(models.Spec, new_id):
        raise HTTPException(409, f"Spec {new_id} already exists")
    spec = models.Spec(
        id=new_id, project_id=payload.project_id, user_story_id=payload.user_story_id,
        format=payload.format, body_ref=payload.body_ref, confidence=payload.confidence,
    )
    db.add(spec)
    record_audit(db, actor_type="agent", actor_id="spec_agent", action="create_spec",
                 artifact_type="Spec", artifact_id=new_id, context={"confidence": payload.confidence})
    db.commit()
    return {"id": new_id}


@router.post("/specs/{spec_id}/validate")
def validate_spec(
    spec_id: str,
    payload: schemas.SpecValidate,
    db: Session = Depends(get_db),
    validated_by: str = Depends(require_human_actor),
):
    """
    §3.5: 'No Spec may enter code generation without final human validation
    and review.' This endpoint is the ONLY way human_validated becomes True —
    there is no code path that sets it automatically.

    The validator's identity is taken from the X-Acting-As header (verified
    human), never from the request body — see api/security.py.
    """
    spec = db.get(models.Spec, spec_id)
    if not spec:
        raise HTTPException(404, "Spec not found")
    spec.human_validated = True
    spec.human_validated_by = validated_by
    from sqlalchemy import func
    spec.human_validated_at = func.now()
    record_audit(db, actor_type="human", actor_id=validated_by, action="validate_spec",
                 artifact_type="Spec", artifact_id=spec_id, human_decision="approved")
    db.commit()
    return {"id": spec_id, "human_validated": True}


@router.get("/specs/{spec_id}")
def get_spec(spec_id: str, db: Session = Depends(get_db)):
    spec = db.get(models.Spec, spec_id)
    if not spec:
        raise HTTPException(404, "Spec not found")
    return spec
