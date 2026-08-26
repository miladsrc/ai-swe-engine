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

The same forgery argument applies to machine actors: PATCH
/mrps/{id}/evidence records test/security evidence under a hardcoded
'ci-pipeline' identity, so any anonymous caller could forge gate-passing
evidence. require_ci_actor closes that hole, optionally backed by a
shared CI secret (SASE_CI_TOKEN). require_any_actor guards reads that
must not be anonymous (the audit trail) while still accepting any
well-formed actor kind.
"""

import hmac
import os

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from api import authn
from api.database import get_db

HUMAN_PREFIX = "human:"
CI_PREFIXES = ("ci:", "system:")
ANY_PREFIXES = ("human:", "agent:", "ci:", "system:")


def require_human_actor(
    x_acting_as: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> str:
    """
    FastAPI dependency. Returns the verified human actor id
    (e.g. 'human:m.barani') or raises.

    Phase 2 — real authn at the documented seam, additive:

    1. Authorization: Bearer <token> present -> resolved against the
       api_tokens/users tables; a valid token yields the AUTHORITATIVE
       identity 'human:<username>' (any X-Acting-As header is ignored —
       a logged-in human cannot be impersonated by header values).
       Invalid/expired/revoked tokens are rejected 401.
    2. No bearer token -> legacy X-Acting-As prefix check as before.
    3. SASE_REQUIRE_HUMAN_TOKEN set (non-empty) -> path 2 is closed:
       humans MUST authenticate with a token (fail-closed, P3 style).

    Agents are structurally unaffected: no agent can obtain a token.
    """
    # isinstance guards: when called directly (unit tests) rather than via
    # FastAPI DI, Header()/Depends() sentinels arrive as defaults.
    has_bearer = isinstance(authorization, str) and authorization
    if has_bearer:
        username = authn.resolve_bearer(db, authorization)
        if username is None:
            raise HTTPException(
                401,
                "Invalid or expired bearer token. Log in again via "
                "POST /auth/login.",
            )
        return f"{HUMAN_PREFIX}{username}"

    if os.environ.get("SASE_REQUIRE_HUMAN_TOKEN", ""):
        raise HTTPException(
            401,
            "This deployment requires human authentication "
            "(SASE_REQUIRE_HUMAN_TOKEN). Send 'Authorization: Bearer <token>' "
            "obtained from POST /auth/login.",
        )

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


def require_ci_actor(
    x_acting_as: str | None = Header(default=None),
    x_ci_token: str | None = Header(default=None),
) -> str:
    """
    FastAPI dependency for machine-written evidence (e.g. PATCH
    /mrps/{id}/evidence). Requires X-Acting-As starting with 'ci:' or
    'system:' and a matching X-CI-Token header backed by SASE_CI_TOKEN.
    Returns the verified actor id.

    P3 fail-closed rule: if SASE_CI_TOKEN is NOT configured, evidence
    writes are refused (503) — never silently allowed. There is no
    hardcoded fallback token. docker-compose sets a documented dev
    placeholder; production should inject it from a secret manager, or
    replace it entirely with mTLS between CI and this service.
    """
    if not x_acting_as:
        raise HTTPException(
            401,
            "Missing X-Acting-As header. Evidence endpoints require an explicit "
            "machine identity: X-Acting-As: ci:<pipeline> (or system:<...>).",
        )
    actor = x_acting_as.strip()
    if not actor.startswith(CI_PREFIXES):
        raise HTTPException(
            403,
            f"X-Acting-As '{x_acting_as}' is not a machine actor. This endpoint "
            f"records CI evidence and requires an id starting with "
            f"'{CI_PREFIXES[0]}' or '{CI_PREFIXES[1]}'.",
        )

    expected_token = os.environ.get("SASE_CI_TOKEN", "")
    if not expected_token:
        # Fail closed (P3): an unconfigured deployment must not accept
        # machine evidence silently — that would let anyone forge
        # gate-passing test/security results.
        raise HTTPException(
            503,
            "Evidence endpoints are locked: SASE_CI_TOKEN is not configured "
            "on this deployment. Set it (e.g. from a secret manager) to "
            "allow CI evidence recording.",
        )
    if not x_ci_token:
        raise HTTPException(
            401,
            "Missing X-CI-Token header. This deployment requires the shared "
            "CI token to record evidence.",
        )
    if not hmac.compare_digest(x_ci_token.strip(), expected_token):
        raise HTTPException(403, "X-CI-Token does not match the configured CI token.")
    return actor


def require_any_actor(
    x_acting_as: str | None = Header(default=None),
) -> str:
    """
    FastAPI dependency for reads that must not be anonymous but may come from
    any well-formed actor kind (human:/agent:/ci:/system:) — e.g. the audit
    trail endpoints. Returns the verified actor id.
    """
    if not x_acting_as:
        raise HTTPException(
            401,
            "Missing X-Acting-As header. This endpoint requires an explicit "
            "actor identity (human:, agent:, ci:, or system:).",
        )
    actor = x_acting_as.strip()
    if not actor.startswith(ANY_PREFIXES):
        raise HTTPException(
            403,
            f"X-Acting-As '{x_acting_as}' is not a recognized actor id. It must "
            f"start with one of: {', '.join(ANY_PREFIXES)}.",
        )
    return actor
