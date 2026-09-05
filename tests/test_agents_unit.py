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


def test_verifier_midpath_wildcard_complete():
    # POST /verification-requests/*/complete -> exactly one path segment.
    verifier = EngineClient(role=ROLES["verifier"])
    assert verifier._assert_allowed(
        "POST", "/verification-requests/VR-2026-00001/complete") is None
    # exact claim endpoint remains allowed (exact match)
    assert verifier._assert_allowed(
        "POST", "/verification-requests/claim-next") is None
    # no segment (missing id) must NOT match
    with pytest.raises(PolicyViolation):
        verifier._assert_allowed("POST", "/verification-requests//complete")
    # extra segment (id + trailing) must NOT match
    with pytest.raises(PolicyViolation):
        verifier._assert_allowed(
            "POST", "/verification-requests/VR-1/sub/complete")
    # wrong method must NOT match even with a valid path
    with pytest.raises(PolicyViolation):
        verifier._assert_allowed("GET", "/verification-requests/VR-1/complete")


def test_reviewer_midpath_wildcard_review_only():
    reviewer = EngineClient(role=ROLES["reviewer"])
    assert reviewer._assert_allowed(
        "PATCH", "/mrps/MRP-PR-1/review") is None
    # granting /mrps/*/review must NOT open the evidence path
    with pytest.raises(PolicyViolation):
        reviewer._assert_allowed(
            "PATCH", "/mrps/MRP-PR-1/evidence")


def test_critic_midpath_wildcard_review_only():
    critic = EngineClient(role=ROLES["critic"])
    assert critic._assert_allowed(
        "PATCH", "/mrps/MRP-PR-2/review") is None
    with pytest.raises(PolicyViolation):
        critic._assert_allowed(
            "PATCH", "/mrps/MRP-PR-2/evidence")


# --- SpecAgent._enforce_ac_refs: LLM output never gets to break
# --- traceability by fabricating AC ids -------------------------------

from agents.spec_agent import _enforce_ac_refs


def test_enforce_ac_refs_replaces_fabricated_ids():
    body = ("artifact: x\nstory: US-1\nbehavior:\n  add:\n"
            "    - does the thing\nacceptance_criteria_refs:\n"
            "  - AC-X-01\n  - AC-X-02\nopen_questions:\n  - q1\n")
    out = _enforce_ac_refs(body, ["AC-TODO-007-01"])
    assert "- AC-TODO-007-01" in out
    assert "AC-X-01" not in out and "AC-X-02" not in out


def test_enforce_ac_refs_appends_when_block_missing():
    body = "artifact: x\nstory: US-1\nbehavior:\n  add:\n    - works\n"
    out = _enforce_ac_refs(body, ["AC-Y-01"])
    assert out.count("acceptance_criteria_refs:") == 1
    assert "- AC-Y-01" in out


def test_enforce_ac_refs_keeps_multiple_real_ids_in_order():
    body = "acceptance_criteria_refs:\n  - AC-FAB-9\nbehavior: x\n"
    out = _enforce_ac_refs(body, ["AC-B-01", "AC-A-02"])
    lines = [l.strip() for l in out.splitlines() if l.strip().startswith("- ")]
    assert lines == ["- AC-B-01", "- AC-A-02"]
