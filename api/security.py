"""
Human-action authentication for the §3.5 / §3.6.3 gates.

The gates are only meaningful if a "human decision" actually came from a
human. Before this module existed, any caller (including an agent) could
post {"validated_by": "human:anyone"} or
{"human_reviewer": "human:anyone"} and forge its way past every gate,
because identity was taken from an unauthenticated request body.

Rule: on endpoints that record a *human* decision, identity comes from
the X-Acting-As header, and it must start with 'human:' — mirroring the
created_by convention ('human:<name>' vs 'agent:<role>') used throughout
the schema. Agents are structurally unable to pass this check without
impersonating a human at the transport layer, which is exactly what the
audit log is there to catch.

In production this should be backed by real authn (SSO/OIDC or mTLS);
this header contract is the seam where that plugs in.
"""

from fastapi import Header, HTTPException

HUMAN_PREFIX = "human:"


def require_human_actor(
    x_acting_as: str | None = Header(default=None),
) -> str:
    """
    FastAPI dependency. Returns the verified human actor id
    (e.g. 'human:m.barani') or raises.
    """
    if not x_acting_as:
        raise HTTPException(
            401,
            "Missing X-Acting-As header. Human decisions must be made under "
            "an explicit human identity: X-Acting-As: human:<name>.",
        )
    if not x_acting_as.strip().startswith(HUMAN_PREFIX):
        raise HTTPException(
            403,
            f"X-Acting-As '{x_acting_as}' is not a human actor. This endpoint "
            f"records a human decision (§3.5/§3.6.3) and requires an id "
            f"starting with '{HUMAN_PREFIX}'.",
        )
    return x_acting_as.strip()
