"""
Live verification for the Governance Dashboard API layer (additive,
read-mostly). Requires the compose stack running; skips otherwise.

Proves:
- new /dashboard endpoints require an actor identity (401 anonymous)
- bearer-token login can read overview/approvals/audit/agent-runs
- console instructions are recorded into the audit trail under the
  AUTHORITATIVE identity (spoofed X-Acting-As loses)
- existing gated flows still work alongside the UI layer

Run: SASE_LIVE_USERNAME=... SASE_LIVE_PASSWORD=... pytest tests/test_dashboard_live.py
"""

import httpx
import os
import uuid

import pytest

BASE = "http://localhost:8000"
CI = {"X-Acting-As": "ci:pipeline", "X-CI-Token": "dev-ci-token-change-me"}


def _api_reachable() -> bool:
    try:
        with httpx.Client(base_url=BASE, timeout=2) as c:
            return c.get("/health").status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(
    not _api_reachable(),
    reason="API not running at localhost:8000",
)

CRED_USER = os.environ.get("SASE_LIVE_USERNAME")
CRED_PASS = os.environ.get("SASE_LIVE_PASSWORD")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


def _auth_header(client) -> dict:
    if not (CRED_USER and CRED_PASS):
        pytest.skip("set SASE_LIVE_USERNAME/SASE_LIVE_PASSWORD")
    r = client.post("/auth/login", json={"username": CRED_USER,
                                         "password": CRED_PASS})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_ui_is_served(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (200, 307), "dashboard root redirect missing"
    if r.status_code == 307:
        assert r.headers["location"].startswith("/ui")


def test_dashboard_endpoints_require_identity(client):
    for path in ("/dashboard/overview", "/dashboard/approvals",
                 "/dashboard/audit", "/dashboard/agent-runs"):
        r = client.get(path)
        assert r.status_code == 401, f"{path} must not be anonymous"


def test_dashboard_reads_with_bearer_token(client):
    auth = _auth_header(client)
    for path in ("/dashboard/overview", "/dashboard/approvals",
                 "/dashboard/audit?limit=5", "/dashboard/agent-runs?limit=5"):
        r = client.get(path, headers=auth)
        assert r.status_code == 200, f"{path} failed with valid token"


def test_console_instruction_records_authoritative_identity(client):
    auth = _auth_header(client)
    marker = f"ui-test-{uuid.uuid4().hex[:8]}"
    # spoofed header riding along must NOT win
    r = client.post("/dashboard/console/instructions",
                    headers={**auth, "X-Acting-As": "human:someone.else"},
                    json={"instruction": marker})
    assert r.status_code == 200
    assert r.json()["actor"] == f"human:{CRED_USER}"

    q = client.get(f"/dashboard/audit?action=agent_instruction&limit=10",
                   headers=auth).json()
    mine = [e for e in q if marker in str(e.get("context", {}))]
    assert mine, "instruction not found in audit trail"
    assert all(e["actor_id"] == f"human:{CRED_USER}" for e in mine)


def test_existing_gates_still_enforced_alongside_ui(client):
    """UI is additive: the old negative gate checks still hold."""
    suffix = uuid.uuid4().hex[:6].upper()
    r = client.post("/projects", json={
        "id": f"dash-{suffix}", "name": "Dash test", "stack": "python-cli"})
    assert r.status_code in (200, 409)
    r = client.post("/specs", json={
        "project_id": f"dash-{suffix}", "domain": "DSH",
        "name": f"spec-{suffix}", "body_ref": "n/a"})
    assert r.status_code == 200
    spec_id = r.json()["id"]
    # no human identity at all -> 401; agent identity -> 403
    assert client.post(f"/specs/{spec_id}/validate", json={}).status_code == 401
    assert client.post(f"/specs/{spec_id}/validate", json={},
                       headers={"X-Acting-As": "agent:coder_agent"}
                       ).status_code == 403
