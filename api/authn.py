"""
Human authentication primitives (Phase 2) — standard library only.

Design constraints (architectural preservation rule):
- Additive: nothing existing changes behavior unless
  SASE_REQUIRE_HUMAN_TOKEN is set.
- No new frameworks: PBKDF2-HMAC-SHA256 via hashlib, tokens via secrets,
  comparison via hmac.compare_digest (same hygiene as P3).
- Agents cannot touch this path: tokens are issued ONLY after a password
  check against the users table; no agent role has credentials.

Token model:
- Raw token: 64 hex chars (secrets.token_hex(32)); shown ONCE at login.
- Stored: sha256(raw) as PK — a DB leak does not leak usable tokens.
"""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from api import models

PBKDF2_ITERATIONS = int(os.environ.get("SASE_PBKDF2_ITERATIONS", "200000"))
TOKEN_TTL_HOURS = float(os.environ.get("SASE_TOKEN_TTL_HOURS", "72"))


# ------------------------------------------------------------- passwords ----

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt,
                                 PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification. Returns False on any malformed input."""
    try:
        algo, iterations, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex),
            int(iterations))
        return hmac.compare_digest(digest.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------- tokens ----

def _token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_token(db: Session, username: str,
                ttl_hours: float | None = None) -> tuple[str, datetime | None]:
    """
    Create a token for a verified user. Returns (raw_token, expires_at);
    the raw value is returned exactly once and only its sha256 is stored.
    Caller commits.
    """
    raw = secrets.token_hex(32)
    expires = None
    ttl = TOKEN_TTL_HOURS if ttl_hours is None else ttl_hours
    if ttl > 0:
        expires = datetime.now(timezone.utc) + timedelta(hours=ttl)
    db.add(models.ApiToken(token_hash=_token_hash(raw),
                           username=username, expires_at=expires))
    return raw, expires


def resolve_bearer(db: Session, authorization: str | None) -> str | None:
    """
    Resolve an 'Authorization: Bearer <token>' header to the canonical
    human username ('human:<name>' prefix added by callers). Returns None
    for anything invalid: missing header, non-Bearer scheme, unknown/
    revoked/expired/inactive user. Updates last_used_at when valid.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    raw = authorization[7:].strip()
    if not raw:
        return None
    tok = db.get(models.ApiToken, _token_hash(raw))
    if tok is None or tok.revoked:
        return None
    if tok.expires_at is not None:
        exp = tok.expires_at
        now = datetime.now(timezone.utc)
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < now:
            return None
    user = db.get(models.User, tok.username)
    if user is None or not user.is_active:
        return None
    tok.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return tok.username
