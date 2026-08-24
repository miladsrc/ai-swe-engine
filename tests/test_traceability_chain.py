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
import pytest

BASE = "http://localhost:8000"
HUMAN = {"X-Acting-As": "human:pytest"}


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
    # 1. project
    r = client.post("/projects", json={
        "id": "test-project", "name": "Test Project", "stack": "springboot"
    })
    assert r.status_code in (200, 409)  # 409 if re-run against existing db

    # 2. PRD
    r = client.post("/prds", json={
        "project_id": "test-project", "domain": "TST", "title": "Test PRD",
        "body_ref": "n/a", "created_by": "human:pytest"
    })
    assert r.status_code == 200
    prd_id = r.json()["id"]

    # 3. User Story + AC
    r = client.post("/user-stories", json={
        "prd_id": prd_id, "domain": "TST", "body_ref": "n/a"
    })
    assert r.status_code == 200
    us_id = r.json()["id"]

    client.post("/acceptance-criteria", json={"user_story_id": us_id, "body_ref": "n/a"})

    # 4. Spec, unvalidated
    r = client.post("/specs", json={
        "project_id": "test-project", "user_story_id": us_id, "domain": "TST",
        "name": "test-spec", "body_ref": "n/a"
    })
    assert r.status_code == 200
    spec_id = r.json()["id"]

    # 5. GATE CHECK: code-gen agent run must be REJECTED before Spec is validated
    r = client.post("/agent-runs", json={
        "project_id": "test-project", "agent_role": "coder_agent", "task_type": "code_generation",
        "model_name": "DeepSeek-671B", "model_short": "DS", "spec_id": spec_id
    })
    assert r.status_code == 409, "Spec-must-be-validated gate did not block an unvalidated Spec (§3.5)"

    # 6. validate, then retry — must succeed
    r = client.post(f"/specs/{spec_id}/validate", json={"validated_by": None}, headers=HUMAN)
    assert r.status_code == 200

    # 6b. GATE CHECK: the same call without a human X-Acting-As header is rejected
    r = client.post("/specs", json={
        "project_id": "test-project", "user_story_id": us_id, "domain": "TST",
        "name": "test-spec-2", "body_ref": "n/a"
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
        "project_id": "test-project", "pull_request_number": 9999,
        "branch_name": "test-branch", "created_by_agent_run": run_id,
        "prd_id": prd_id, "spec_ids": [spec_id]
    })
    assert r.status_code == 200
    mrp_id = r.json()["id"]
    assert crp_id in r.json()["open_crp_ids"], "MRP did not surface the open CRP tied to its Spec"

    # 9. GATE CHECK: cannot approve MRP while High CRP is open
    r = client.patch(f"/mrps/{mrp_id}/evidence", json={
        "unit_tests_status": "passed", "security_scan_status": "passed"
    })
    assert r.status_code == 200
    r = client.post(f"/mrps/{mrp_id}/human-decision", json={
        "decision": "approved"
    }, headers=HUMAN)
    assert r.status_code == 409, "Merge gate did not block on an open High-severity CRP (§3.6.3)"

    # 10. resolve the CRP via VCR, then approval must succeed
    r = client.post("/vcrs", json={
        "related_artifact_type": "CRP", "related_artifact_id": crp_id,
        "decision_status": "approved_with_changes", "rationale": "test resolution",
    }, headers=HUMAN)
    assert r.status_code == 200

    r = client.post(f"/mrps/{mrp_id}/human-decision", json={
        "decision": "approved"
    }, headers=HUMAN)
    assert r.status_code == 200, "Merge should succeed once the blocking CRP is resolved"

    # 11. full chain must be reconstructable
    r = client.get(f"/traceability/chain/{mrp_id}")
    assert r.status_code == 200
    assert r.json()["fully_traceable"] is True
