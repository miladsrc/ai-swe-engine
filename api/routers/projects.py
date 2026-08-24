from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from api.database import get_db
from api import models, schemas
from api.audit import record_audit

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=schemas.ProjectOut)
def create_project(payload: schemas.ProjectCreate, db: Session = Depends(get_db)):
    if db.get(models.Project, payload.id):
        raise HTTPException(409, f"Project {payload.id} already exists")
    project = models.Project(**payload.model_dump())
    db.add(project)
    record_audit(db, actor_type="human", actor_id="api", action="create_project",
                 artifact_type="Project", artifact_id=project.id)
    db.commit()
    db.refresh(project)
    return project


@router.get("/{project_id}", response_model=schemas.ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    project = db.get(models.Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.get("", response_model=list[schemas.ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(models.Project).all()
