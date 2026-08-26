"""
Human authentication endpoints (Phase 2).

POST /auth/login  — password check -> bearer token (raw shown once).
GET  /auth/me     — resolve the presented bearer token.

These endpoints add REAL authn at the seam api/security.py documented.
Nothing else changes behavior until SASE_REQUIRE_HUMAN_TOKEN is set.
Every login attempt (success or failure) is audited — failed logins are
exactly the events an append-only trail exists for.

Deliberately NOT here (documented, awaiting approval): rate limiting,
refresh tokens, OIDC/mTLS federation, password reset flows.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from api import models, schemas
from api.audit import record_audit
from api.authn import issue_token, resolve_bearer, verify_password
from api.database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=schemas.LoginResponse)
def login(payload: schemas.LoginRequest,
          request: Request,
          db: Session = Depends(get_db)):
    username = payload.username.strip().lower()
    user = db.get(models.User, username)

    # Verify against a placeholder even when the user doesn't exist so
    # response timing does not reveal account existence (user enumeration).
    stored = user.password_hash if user else (
        "pbkdf2_sha256$1$00$00")
    ok = verify_password(payload.password, stored) and (
        user is not None and user.is_active)

    if not ok:
        record_audit(
            db, actor_type="system", actor_id="auth",
            action="login_failed", artifact_type="User",
            artifact_id=username,
            context={"ip": _client_ip(request),
                     "reason": "bad credentials" if user else "unknown user"},
        )
        db.commit()
        raise HTTPException(401, "Invalid credentials.")

    raw, expires_at = issue_token(db, username)
    record_audit(
        db, actor_type="human", actor_id=f"human:{username}",
        action="login_success", artifact_type="User", artifact_id=username,
        context={"ip": _client_ip(request), "expires_at":
                 expires_at.isoformat() if expires_at else None},
    )
    db.commit()
    return schemas.LoginResponse(token=raw, expires_at=expires_at,
                                 username=username,
                                 token_type="bearer")


@router.get("/me", response_model=schemas.MeResponse)
def me(authorization: str | None = Header(default=None),
       db: Session = Depends(get_db)):
    """
    Bearer-token introspection for humans and tooling. Note: this route is
    read-only and reveals nothing beyond the caller's own identity.
    """
    username = resolve_bearer(db, authorization)
    if username is None:
        raise HTTPException(
            401,
            "Missing or invalid Authorization: Bearer <token> header.",
        )
    user = db.get(models.User, username)
    return schemas.MeResponse(
        username=username,
        display_name=user.display_name if user else None,
        actor_id=f"human:{username}",
    )
