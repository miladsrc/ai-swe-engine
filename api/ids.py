"""
ID generation matching the traceability scheme from the SASE paper (§3.7.1):

    PRD-AUTH-001
    US-AUTH-003
    AC-AUTH-003-01
    SPEC-AUTH-SESSION-REFRESH
    BP-BACKEND-001
    RUN-DS-2026-00045
    CRP-AUTH-2026-004
    MRP-PR-145
    VCR-CRP-AUTH-2026-004

These IDs are stable, human-readable, and greppable across the whole
.ai-engineering/ tree and the database — that's a deliberate property,
not just a naming convention: an engineer should be able to find every
artifact touching a domain by searching for its prefix.
"""

from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session


def _next_seq(db: Session, counter_key: str) -> int:
    """
    Atomic counter: a single UPSERT that increments and returns the new
    value in one statement. The ON CONFLICT UPDATE takes a row lock on the
    counter row for the duration of the statement, so two concurrent
    requests can never observe the same sequence value (the previous
    INSERT-then-SELECT version could hand out duplicates under load,
    causing PK collisions on the artifact tables).
    """
    row = db.execute(
        text(
            """
            INSERT INTO id_counters (key, value) VALUES (:key, 1)
            ON CONFLICT (key) DO UPDATE SET value = id_counters.value + 1
            RETURNING value
            """
        ),
        {"key": counter_key},
    ).fetchone()
    return row[0]


def prd_id(db: Session, domain: str) -> str:
    seq = _next_seq(db, f"prd:{domain}")
    return f"PRD-{domain.upper()}-{seq:03d}"


def user_story_id(db: Session, domain: str) -> str:
    seq = _next_seq(db, f"us:{domain}")
    return f"US-{domain.upper()}-{seq:03d}"


def acceptance_criteria_id(db: Session, user_story_id_value: str) -> str:
    seq = _next_seq(db, f"ac:{user_story_id_value}")
    return f"AC-{user_story_id_value.replace('US-', '')}-{seq:02d}"


def spec_id(domain: str, name: str) -> str:
    slug = name.upper().replace(" ", "-")
    return f"SPEC-{domain.upper()}-{slug}"


def agent_run_id(db: Session, model_short: str) -> str:
    year = datetime.now(timezone.utc).year
    seq = _next_seq(db, f"run:{model_short}:{year}")
    return f"RUN-{model_short.upper()}-{year}-{seq:05d}"


def crp_id(db: Session, domain: str) -> str:
    year = datetime.now(timezone.utc).year
    seq = _next_seq(db, f"crp:{domain}:{year}")
    return f"CRP-{domain.upper()}-{year}-{seq:03d}"


def mrp_id(pull_request_number: int) -> str:
    return f"MRP-PR-{pull_request_number}"


def vcr_id(related_artifact_id: str) -> str:
    return f"VCR-{related_artifact_id}"
