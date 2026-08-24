"""
Every endpoint that creates or mutates a traceable artifact calls
record_audit() in the same transaction as the write. This is what
makes "every output traceable to which agent, with which inputs,
produced it" (v2 §8) an actual guarantee rather than a hope.

In production, lock this table down at the role level:

    REVOKE UPDATE, DELETE ON audit_log FROM sase_app;
    GRANT INSERT, SELECT ON audit_log TO sase_app;

so even a compromised or buggy application process cannot rewrite history.
"""

from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from api.models import AuditLog


def record_audit(
    db: Session,
    *,
    actor_type: str,          # 'agent' | 'human' | 'system'
    actor_id: str,
    action: str,
    artifact_type: Optional[str] = None,
    artifact_id: Optional[str] = None,
    model_version: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    tools_used: Optional[List[str]] = None,
    result: Optional[str] = None,
    human_decision: Optional[str] = None,
) -> None:
    entry = AuditLog(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        artifact_type=artifact_type,
        artifact_id=artifact_id,
        model_version=model_version,
        context=context or {},
        tools_used=tools_used or [],
        result=result,
        human_decision=human_decision,
    )
    db.add(entry)
    # Deliberately not committing here: caller commits once, atomically,
    # with the artifact write itself. An audit entry that exists without
    # its artifact (or vice versa) is worse than useless — it's misleading.
