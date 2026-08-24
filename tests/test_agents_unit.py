"""
Unit tests for the agent layer's role-separation guarantees.
All tests are DB-free and network-free (EngineClient._assert_allowed is
checked before any request is built; urllib is never reached).
"""

import pytest

from agents.config import ROLES
from agents.engine_client import EngineClient, PolicyViolation


def test_every_role_has_unique_identity():
    identities = [r.identity for r in ROLES.values()]
    assert len(identities) == len(set(identities))
    for ident in identities:
        kind, _, _ = ident.partition(":")
        assert kind in ("agent", "ci", "system"), ident
        assert not ident.startswith("human:"), \
            "no agent may hold a human identity"


def test_spec_agent_cannot_validate():
    client = EngineClient(role=ROLES["spec"])
    with pytest.raises(PolicyViolation):
        client.post("/specs/SPEC-X/validate", {})


def test_product_agent_cannot_start_agent_runs():
    client = EngineClient(role=ROLES["product"])
    with pytest.raises(PolicyViolation):
        client.post("/agent-runs", {"project_id": "x"})


def test_coder_cannot_touch_mrps():
    client = EngineClient(role=ROLES["coder"])
    with pytest.raises(PolicyViolation):
        client.patch("/mrps/MRP-PR-1/evidence",
                     {"unit_tests_status": "passed"})


def test_reviewer_can_read_mrps_but_not_create_crps():
    reviewer = EngineClient(role=ROLES["reviewer"])
    assert reviewer._assert_allowed("GET", "/mrps/MRP-PR-1") is None
    with pytest.raises(PolicyViolation):
        reviewer.post("/crps", {"project_id": "x"})


def test_test_runner_is_llm_free():
    assert ROLES["test_runner"].model is None


def test_unbound_client_has_no_client_side_limit():
    # scripts/tests may be unbound; server-side gates remain the authority
    client = EngineClient()
    assert client._assert_allowed("POST", "/anything") is None


def test_allowlist_matching_is_method_exact():
    client = EngineClient(role=ROLES["product"])
    # GET /projects allowed; DELETE same path not:
    with pytest.raises(PolicyViolation):
        client.request("DELETE", "/projects/x")
