"""
Automated version of the README walkthrough. Requires the stack running
(docker compose up) and DATABASE_URL pointing at it, OR run against a
local Postgres with the schema applied. This test is the regression
guard for the gates in api/gates.py — if someone "fixes" a gate into
uselessness, this should fail.

Run with:  pytest tests/test_traceability_chain.py
(requires the API + Postgres reachable at localhost, per docker-compose.yml)
"""

import httpx
import os
import pytest
import uuid

BASE = "http://localhost:8000"
# LEGACY identity header — kept ONLY as a fallback for environments without
# live credentials. Dies automatically once SASE_REQUIRE_HUMAN_TOKEN=1.
HUMAN = {"X-Acting-As": "human:pytest"}
# Phase 2 SoD Step 2: in strict mode TRUSTED verification evidence may only
# be written by the independent verifier (ci:verifier) using its OWN
# credential (SASE_VERIFIER_TOKEN), separate from the shared CI token.
# The legacy `CI` (ci:pipeline + SASE_CI_TOKEN) is retained for the
# non-strict (legacy) evidence identity and for negative checks.
CI = {"X-Acting-As": "ci:pipeline", "X-CI-Token": "dev-ci-token-change-me"}
VERIFIER = {"X-Acting-As": "ci:verifier",
            "X-CI-Token": os.environ.get("SASE_VERIFIER_TOKEN",
                                         "dev-verifier-token-change-me")}
# Phase 2 I3 (ADR-002): the independent reviewer (agent:reviewer) uses its
# own credential (SASE_REVIEWER_TOKEN). G8 requires a reviewer-owned
# completed AI review before an MRP can be merge-ready in strict mode.
REVIEWER = {"X-Acting-As": "agent:reviewer",
            "X-Reviewer-Token": os.environ.get(
                "SASE_REVIEWER_TOKEN", "dev-reviewer-token-change-me")}


def _human_auth(client) -> tuple[dict, str, bool]:
    """
    Token-first human authentication for gate calls (Phase 2 migration).

    Returns (headers, actor_id, used_token). When SASE_LIVE_USERNAME /
    SASE_LIVE_PASSWORD are set, logs in and returns an AUTHORITATIVE
    bearer token. Otherwise falls back to the legacy X-Acting-As header
    so the suite still runs credential-less until the flag flips.
    """
    username = os.environ.get("SASE_LIVE_USERNAME")
    password = os.environ.get("SASE_LIVE_PASSWORD")
    if username and password:
        r = client.post("/auth/login", json={"username": username,
                                             "password": password})
        assert r.status_code == 200, (
            f"login failed ({r.status_code}) — check SASE_LIVE_* credentials")
        return ({"Authorization": f"Bearer {r.json()['token']}"},
                f"human:{username}", True)
    return dict(HUMAN), "human:pytest", False


def _api_reachable() -> bool:
    try:
        with httpx.Client(base_url=BASE, timeout=2) as c:
            return c.get("/health").status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not _api_reachable(),
    reason="API not running at localhost:8000 — start the stack with 'docker compose up'",
)


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


def test_full_chain_and_gates(client):
    # Unique suffix per run: fixed IDs (SPEC-..., MRP-PR-...) would collide
    # on any re-run against a persistent database (409s mid-test).
    suffix = uuid.uuid4().hex[:6].upper()
    domain = f"TST{suffix}"
    spec_name = f"test-spec-{suffix}"
    pr_number = 10000 + int(suffix[:4], 16)

    # 1. project
    r = client.post("/projects", json={
        "id": "test-project", "name": "Test Project", "stack": "springboot"
    })
    assert r.status_code in (200, 409)  # 409 if re-run against existing db

    # 2. PRD
    r = client.post("/prds", json={
        "project_id": "test-project", "domain": domain, "title": "Test PRD",
        "body_ref": "n/a", "created_by": "human:pytest"
    })
    assert r.status_code == 200
    prd_id = r.json()["id"]

    # 3. User Story + AC
    r = client.post("/user-stories", json={
        "prd_id": prd_id, "domain": domain, "body_ref": "n/a"
    })
    assert r.status_code == 200
    us_id = r.json()["id"]

    client.post("/acceptance-criteria", json={"user_story_id": us_id, "body_ref": "n/a"})

    # 4. Spec, unvalidated
    r = client.post("/specs", json={
        "project_id": "test-project", "user_story_id": us_id, "domain": "TST",
        "name": spec_name, "body_ref": "n/a"
    })
    assert r.status_code == 200
    spec_id = r.json()["id"]

    # 5. GATE CHECK: code-gen agent run must be REJECTED before Spec is validated
    r = client.post("/agent-runs", json={
        "project_id": "test-project", "agent_role": "coder_agent", "task_type": "code_generation",
        "model_name": "DeepSeek-671B", "model_short": "DS", "spec_id": spec_id
    })
    assert r.status_code == 409, "Spec-must-be-validated gate did not block an unvalidated Spec (§3.5)"

    # 6. validate, then retry — must succeed (token-first, legacy fallback)
    human_headers, human_actor, used_token = _human_auth(client)
    print(f"[chain] human auth mode: "
          f"{'bearer token' if used_token else 'legacy header'}")
    r = client.post(f"/specs/{spec_id}/validate", json={"validated_by": None},
                    headers=human_headers)
    assert r.status_code == 200

    # 6b. GATE CHECK: the same call without a human X-Acting-As header is rejected
    r = client.post("/specs", json={
        "project_id": "test-project", "user_story_id": us_id, "domain": "TST",
        "name": spec_name + "-2", "body_ref": "n/a"
    })
    assert r.status_code == 200
    spec2_id = r.json()["id"]
    r = client.post(f"/specs/{spec2_id}/validate", json={"validated_by": None},
                    headers={"X-Acting-As": "agent:coder_agent"})
    assert r.status_code == 403, "Agent identity must not be able to forge human validation"
    r = client.post(f"/specs/{spec2_id}/validate", json={"validated_by": None})
    assert r.status_code == 401, "Missing identity must not be able to validate a Spec"

    r = client.post("/agent-runs", json={
        "project_id": "test-project", "agent_role": "coder_agent", "task_type": "code_generation",
        "model_name": "DeepSeek-671B", "model_short": "DS", "spec_id": spec_id
    })
    assert r.status_code == 200
    run_id = r.json()["id"]

    # 7. raise a high-severity CRP
    r = client.post("/crps", json={
        "project_id": "test-project", "domain": "TST", "agent_run_id": run_id,
        "spec_id": spec_id, "severity": "high",
        "blocking_issue_title": "test ambiguity", "blocking_issue_body": "n/a",
        "required_decision": "pick one", "required_role": "Tech Lead"
    })
    assert r.status_code == 200
    crp_id = r.json()["id"]

    # 8. MRP for this spec must show the open CRP
    r = client.post("/mrps", json={
        "project_id": "test-project", "pull_request_number": pr_number,
        "branch_name": f"test-branch-{suffix}", "created_by_agent_run": run_id,
        "prd_id": prd_id, "spec_ids": [spec_id],
        "blueprint_id": "BP-SPRINGBOOT-001", "blueprint_version": "v1.0"
    })
    assert r.status_code == 200
    mrp_id = r.json()["id"]
    assert crp_id in r.json()["open_crp_ids"], "MRP did not surface the open CRP tied to its Spec"

    # 9. GATE CHECK: cannot approve MRP while High CRP is open
    # Evidence must come from the INDEPENDENT VERIFIER (ci:verifier) using
    # its own credential (SASE_VERIFIER_TOKEN) — see api/security.py
    # require_verifier_actor. In strict mode a generic CI/coder/orchestrator
    # identity writing trusted verification evidence is rejected (asserted
    # below), and G7 requires a verifier-bound tree hash to merge.
    r = client.patch(f"/mrps/{mrp_id}/evidence", json={
        "unit_tests_status": "passed",
        "security_scan_status": "passed",
        "verified_tree_hash": "deadbeef",
        "execution_context": {"runner": "ci:verifier",
                              "tree_hash": "deadbeef"},
    }, headers=VERIFIER)
    assert r.status_code == 200, (
        f"verifier-owned evidence write must succeed in strict mode (got "
        f"{r.status_code}): {r.text}")
    # Negative: the legacy CI / coder / orchestrator identity cannot write
    # trusted verification evidence in strict mode.
    for spoof in (CI, {"X-Acting-As": "ci:test-runner",
                       "X-CI-Token": "dev-ci-token-change-me"}):
        r2 = client.patch(f"/mrps/{mrp_id}/evidence", json={
            "unit_tests_status": "passed",
            "security_scan_status": "passed",
            "verified_tree_hash": "deadbeef",
        }, headers=spoof)
        assert r2.status_code in (403, 503), (
            f"non-verifier evidence write must be rejected (got {r2.status_code})")
    r = client.post(f"/mrps/{mrp_id}/human-decision", json={
        "decision": "approved"
    }, headers=human_headers)
    assert r.status_code == 409, "Merge gate did not block on an open High-severity CRP (§3.6.3)"

    # 10. resolve the CRP via VCR, then approval must succeed
    r = client.post("/vcrs", json={
        "related_artifact_type": "CRP", "related_artifact_id": crp_id,
        "decision_status": "approved_with_changes", "rationale": "test resolution",
    }, headers=human_headers)
    assert r.status_code == 200

    # 10a. G8: a completed AI review owned by the INDEPENDENT reviewer
    # (agent:reviewer, SASE_REVIEWER_TOKEN) is required for merge-ready in
    # strict mode — a coder/orchestrator/CI identity cannot file one.
    r = client.patch(f"/mrps/{mrp_id}/review", json={
        "ai_review_status": "completed",
        "ai_review_notes": ["advisory: no blocking findings"],
        "ai_review_findings": [],
    }, headers=REVIEWER)
    assert r.status_code == 200, (
        f"reviewer-owned review must be writable (got {r.status_code}): {r.text}")
    # Negative: the verifier/coder/CI identity must NOT be able to file a review.
    for spoof in (VERIFIER, CI):
        r2 = client.patch(f"/mrps/{mrp_id}/review", json={
            "ai_review_status": "completed",
        }, headers=spoof)
        assert r2.status_code in (403, 503), (
            f"non-reviewer review write must be rejected (got {r2.status_code})")

    r = client.post(f"/mrps/{mrp_id}/human-decision", json={
        "decision": "approved"
    }, headers=human_headers)
    assert r.status_code == 200, "Merge should succeed once the blocking CRP is resolved"

    # 10b. In token mode, prove the recorded identity is the AUTHORITATIVE
    # token identity (never a spoofable header value).
    if used_token:
        r = client.get(f"/traceability/audit/MRP/{mrp_id}",
                       headers={"X-Acting-As": "human:pytest"})
        assert r.status_code == 200
        decisions = [e for e in r.json()
                     if e["action"] == "mrp_human_decision"]
        assert decisions, "no human decision found in audit trail"
        assert all(e["actor_id"] == human_actor for e in decisions), (
            f"expected only {human_actor}, got "
            f"{[e['actor_id'] for e in decisions]}")

    # 11. full chain must be reconstructable
    r = client.get(f"/traceability/chain/{mrp_id}")
    assert r.status_code == 200
    assert r.json()["fully_traceable"] is True


# ---------------------------------------------------------------------------
# Phase 2: token-flow verification (M6). Env-gated because it needs real
# credentials on the live stack. Run e.g.:
#   SASE_LIVE_USERNAME=m.barani SASE_LIVE_PASSWORD=... pytest \
#       tests/test_traceability_chain.py::test_human_gates_accept_bearer_token
# ---------------------------------------------------------------------------

def test_human_gates_accept_bearer_token(client):
    """Proves the THREE conditions required before strict mode:
    (1) a valid token authenticates every human gate,
    (2) an invalid/expired token is rejected 401,
    (3) a spoofed X-Acting-As can NEVER override token identity
        (audit trail records the authoritative identity)."""
    username = os.environ.get("SASE_LIVE_USERNAME")
    password = os.environ.get("SASE_LIVE_PASSWORD")
    if not (username and password):
        pytest.skip("set SASE_LIVE_USERNAME/SASE_LIVE_PASSWORD to run the "
                    "token-flow gate check against the live stack")

    # --- login ---
    r = client.post("/auth/login", json={"username": username,
                                         "password": password})
    assert r.status_code == 200, "login failed — check credentials"
    token = r.json()["token"]
    auth = {"Authorization": f"Bearer {token}"}

    # --- /auth/me resolves the token to the authoritative identity ---
    r = client.get("/auth/me", headers=auth)
    assert r.status_code == 200
    assert r.json()["actor_id"] == f"human:{username}"

    # --- build a minimal spec chain ---
    suffix = uuid.uuid4().hex[:6].upper()
    r = client.post("/prds", json={
        "project_id": "test-project", "domain": f"TOK{suffix}",
        "title": "Token flow", "body_ref": "n/a",
        "created_by": f"human:{username}"})
    assert r.status_code == 200
    prd_id = r.json()["id"]
    r = client.post("/user-stories", json={
        "prd_id": prd_id, "domain": f"TOK{suffix}", "body_ref": "n/a"})
    us_id = r.json()["id"]
    client.post("/acceptance-criteria",
                json={"user_story_id": us_id, "body_ref": "n/a"})
    r = client.post("/specs", json={
        "project_id": "test-project", "user_story_id": us_id,
        "domain": "TOK", "name": f"token-flow-{suffix}", "body_ref": "n/a"})
    spec_id = r.json()["id"]

    # (1) VALID TOKEN + spoofed header riding along: gate passes AND the
    # spoof loses — audit records the token identity.
    r = client.post(f"/specs/{spec_id}/validate", json={},
                    headers={**auth, "X-Acting-As": "human:someone.else"})
    assert r.status_code == 200, "human gate rejected a valid bearer token"

    r = client.get(f"/traceability/audit/Spec/{spec_id}",
                   headers={"X-Acting-As": "human:pytest"})
    entries = [e for e in r.json() if e["action"] == "validate_spec"]
    assert entries and entries[-1]["actor_id"] == f"human:{username}", (
        "spoofed X-Acting-As must not override token identity in audit")
    assert all(e["actor_id"] != "human:someone.else" for e in entries)

    # (2) INVALID token on another fresh spec: rejected 401.
    r = client.post("/specs", json={
        "project_id": "test-project", "user_story_id": us_id,
        "domain": "TOK", "name": f"token-flow-bad-{suffix}", "body_ref": "n/a"})
    bad_spec_id = r.json()["id"]
    r = client.post(f"/specs/{bad_spec_id}/validate", json={},
                    headers={"Authorization": f"Bearer {'f' * 64}",
                             "X-Acting-As": "human:someone.else"})
    assert r.status_code == 401, "invalid bearer token must not pass gates"

    # (2b) malformed/garbage Authorization header: also 401.
    r = client.post(f"/specs/{bad_spec_id}/validate", json={},
                    headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert r.status_code == 401
