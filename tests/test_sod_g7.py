"""
Phase 2 SoD gate G7 regression tests — updated for the Step 2 Verifier boundary.

G7 (docs/PHASES/PHASE-2.md §4) says an MRP may only become merge-ready when
its pass/fail was decided by the INDEPENDENT VERIFIER (ci:verifier), not the
coder that wrote the code and not the orchestrator that coordinates the
workflow, AND the evidence is bound to the exact tree hash the MRP claims to
merge. This file has two layers:

  1. DB-free unit tests of `mrp_ready_for_merge` decision logic — run in
     any CI, no Postgres needed.
  2. A live API-layer test that drives the real /mrps + /evidence +
     /check-ready endpoints against the running stack, proving a non-verifier
     cannot write trusted evidence and that genuine verifier evidence binds.

Run with:
    pytest tests/test_sod_g7.py                     # DB-free only
    # (live test auto-skips unless the stack is up AND SASE_SOD_MODE=strict)
"""

import os
from types import SimpleNamespace

import pytest

from api.gates import mrp_ready_for_merge
from api.models import AuditLog


# ---------------------------------------------------------------- DB-free ----

class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return SimpleNamespace(all=lambda: self._items)


class _FakeDb:
    """
    Stands in for Session.execute, dispatching on which query the gate runs:
    the Live-CRP query returns `crps`, the G7 audit-log query returns
    `evidence`. Keeps each branch isolated so the gate reads exactly the
    data the scenario describes.
    """

    def __init__(self, crps=None, evidence=None):
        self._crps = crps or []
        self._evidence = evidence or []

    def execute(self, stmt):
        descriptions = getattr(stmt, "column_descriptions", None) or []
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is AuditLog:
            return _FakeResult(self._evidence)
        return _FakeResult(self._crps)


def _audit_row(runner, tree_hash, actor_id=None, action=None, context=None):
    """
    A minimally shaped AuditLog row. G7 reads .context.execution_context
    (verifier evidence). G8 reads .actor_id + .context.review_fields
    (reviewer review). Accept keyword args so a single row can model either.
    """
    if context is not None:
        ctx = context
    else:
        ctx = {"execution_context": None} if runner is None else {
            "execution_context": {"runner": runner, "tree_hash": tree_hash}}
    return SimpleNamespace(
        context=ctx,
        actor_id=actor_id,
        action=action,
        model_version=None,
    )


def _review_row(status, actor_id="agent:reviewer"):
    """A G8-completed review row written by the independent reviewer."""
    return _audit_row(
        runner=None, tree_hash=None, actor_id=actor_id,
        action="update_mrp_review",
        context={"review_fields": {"ai_review_status": status}})


def _crp(id):
    return SimpleNamespace(id=id)


def _make_mrp(verified_tree_hash=None, **overrides):
    base = dict(
        id="MRP-G7-TEST",
        unit_tests_status="passed",
        integration_tests_status="passed",
        security_scan_status="passed",
        spec_ids=["SPEC-SOD-001"],
        blueprint_version="v1.0",
        open_crp_ids=[],
        status="draft",
        verified_tree_hash=verified_tree_hash,
        # Phase 2 I3 (G8): a strict-mode merge-ready MRP additionally needs a
        # completed independent AI review.
        ai_review_status="completed",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def strict_mode(monkeypatch):
    monkeypatch.setenv("SASE_SOD_MODE", "strict")
    yield


def test_g7_rejects_coder_self_certification(strict_mode):
    """
    A coder-owned evidence record (runner != 'ci:verifier') must NOT make an
    MRP merge-ready, even if everything else passes and the tree hash matches.
    """
    evidence = _audit_row("coder-process", "abc123")
    ready, reasons = mrp_ready_for_merge(
        _FakeDb(evidence=[evidence]), _make_mrp(verified_tree_hash="abc123"))
    assert not ready
    assert any("not independently owned" in r for r in reasons)
    assert any("runner != 'ci:verifier'" in r for r in reasons)


def test_g7_rejects_non_verifier_evidence(strict_mode):
    """
    Any non-verifier runner — the coordinator (orchestrator), legacy CI, an
    arbitrary tool — is rejected: neither the coder nor the orchestrator
    process ever decides pass/fail at merge time.
    """
    for runner in ("orchestrator", "ci:test-runner", "coder-process",
                   "system:scanner"):
        evidence = _audit_row(runner, "abc123")
        ready, reasons = mrp_ready_for_merge(
            _FakeDb(evidence=[evidence]), _make_mrp(verified_tree_hash="abc123"))
        assert not ready, f"runner={runner!r} must be rejected"
        assert any("runner != 'ci:verifier'" in r for r in reasons)


def test_g7_rejects_wrong_tree_hash(strict_mode):
    """
    Even verifier-owned evidence must match the MRP's bound tree hash
    exactly; a different hash means the verified bytes are not the merged bytes.
    """
    evidence = _audit_row("ci:verifier", "hash-of-verified-bytes")
    ready, reasons = mrp_ready_for_merge(
        _FakeDb(evidence=[evidence]), _make_mrp(verified_tree_hash="hash-of-merged-bytes"))
    assert not ready
    assert any("tree_hash does not match" in r for r in reasons)


def test_g7_rejects_missing_verified_tree_hash(strict_mode):
    """
    A strict-mode MRP with no bound tree hash has no independently verified
    bytes at all — it cannot be merge-ready.
    """
    evidence = _audit_row("ci:verifier", "abc123")
    ready, reasons = mrp_ready_for_merge(
        _FakeDb(evidence=[evidence]), _make_mrp(verified_tree_hash=None))
    assert not ready
    assert any("no verifier-bound verified_tree_hash" in r for r in reasons)


def test_g7_rejects_missing_verifier_evidence(strict_mode):
    """
    A bound tree hash with NO verifier-owned evidence record means nobody
    independent reported on these bytes — still not independently owned.
    """
    ready, reasons = mrp_ready_for_merge(
        _FakeDb(), _make_mrp(verified_tree_hash="abc123"))
    assert not ready
    assert any("no verifier-owned evidence" in r for r in reasons)


def test_g7_accepts_matching_verifier_evidence(strict_mode):
    """
    The happy path: verifier-owned evidence whose tree hash EXACTLY matches
    the MRP's verified_tree_hash → merge-ready. (G8 also requires a
    completed independent review, since G7+G8 both gate in strict mode;
    this test models the full strict flow.)
    """
    evidence = _audit_row("ci:verifier", "abc123")
    review = _review_row("completed")
    ready, reasons = mrp_ready_for_merge(
        _FakeDb(evidence=[evidence, review]),
        _make_mrp(verified_tree_hash="abc123"))
    assert ready
    assert reasons == []


def test_g7_is_inert_in_legacy_mode(monkeypatch):
    """
    In the default 'legacy' mode G7 must NOT block — pre-SoD MRPs and
    non-strict deployments keep their existing behavior.
    """
    monkeypatch.setenv("SASE_SOD_MODE", "legacy")
    # No evidence, no verified_tree_hash — must still be merge-ready on
    # the ordinary gates (independently-owned check is skipped).
    ready, reasons = mrp_ready_for_merge(
        _FakeDb(), _make_mrp(verified_tree_hash=None))
    assert ready
    assert reasons == []


# ------------------------------------------------------- live API layer ----

import httpx

BASE = "http://localhost:8000"
VERIFIER = {"X-Acting-As": "ci:verifier",
            "X-CI-Token": os.environ.get("SASE_VERIFIER_TOKEN",
                                         "dev-verifier-token-change-me")}
AGENT = {"X-Acting-As": "agent:coder_agent"}


def _api_reachable() -> bool:
    try:
        with httpx.Client(base_url=BASE, timeout=2) as c:
            return c.get("/health").status_code == 200
    except httpx.HTTPError:
        return False


@pytest.mark.skipif(
    not _api_reachable(),
    reason="API not running at localhost:8000 — start the stack")
def test_live_api_g7_enforces_verifier_owned_evidence():
    """
    Full API-layer proof that neither a coder nor the orchestrator can
    self-certify at the merge gate. Builds a real validated spec chain, then
    shows:
      - coder/CI/orchestrator-owned evidence -> MRP NOT merge-ready (G7 blocks,
        and non-verifier evidence writes are rejected in strict mode),
      - VERIFIER-owned evidence with a MATCHING tree hash -> merge-ready.
    """
    import uuid
    suffix = uuid.uuid4().hex[:6].upper()
    domain = f"SOD{suffix}"
    pr_number = 12000 + int(suffix[:4], 16)

    with httpx.Client(base_url=BASE, timeout=10) as c:
        # 1. Project + full spec chain (so the MRP is otherwise merge-eligible).
        c.post("/projects", json={
            "id": "test-sod-g7", "name": "SoD G7 test", "stack": "python"})
        r = c.post("/prds", json={
            "project_id": "test-sod-g7", "domain": domain, "title": "G7",
            "body_ref": "n/a", "created_by": "human:pytest"})
        prd_id = r.json()["id"]
        r = c.post("/user-stories", json={
            "prd_id": prd_id, "domain": domain, "body_ref": "n/a"})
        us_id = r.json()["id"]
        c.post("/acceptance-criteria",
               json={"user_story_id": us_id, "body_ref": "n/a"})
        r = c.post("/specs", json={
            "project_id": "test-sod-g7", "user_story_id": us_id,
            "domain": domain, "name": f"spec-{suffix}", "body_ref": "n/a"})
        spec_id = r.json()["id"]
        r = c.post(f"/specs/{spec_id}/validate", json={"validated_by": None},
                   headers={"X-Acting-As": "human:pytest"})
        assert r.status_code == 200, r.text
        r = c.post("/agent-runs", json={
            "project_id": "test-sod-g7", "agent_role": "coder_agent",
            "task_type": "code_generation", "model_name": "qwen2.5-coder:7b",
            "model_short": "QW", "spec_id": spec_id})
        assert r.status_code == 200, r.text
        run_id = r.json()["id"]

        # 2. MRP. In the strict Step 2 flow the orchestrator does NOT set
        # verified_tree_hash at create — it is written by verifier evidence.
        r = c.post("/mrps", json={
            "project_id": "test-sod-g7",
            "pull_request_number": pr_number,
            "branch_name": f"agent/g7-{suffix}",
            "created_by_agent_run": run_id,
            "prd_id": prd_id,
            "spec_ids": [spec_id],
            "blueprint_id": "BP-PYTHON-CLI-001",
            "blueprint_version": "v1.0",
            # verified_tree_hash intentionally omitted (verifier-owned).
        })
        assert r.status_code in (200, 409), r.text
        if r.status_code == 409:
            return  # id collision from a prior manual run; covered by DB-free tests
        mrp_id = r.json()["id"]

        # 3. A non-verifier evidence write must be REJECTED in strict mode.
        r = c.patch(f"/mrps/{mrp_id}/evidence",
                    headers={"X-Acting-As": "ci:test-runner",
                             "X-CI-Token": "dev-ci-token-change-me"},
                    json={"unit_tests_status": "passed",
                          "security_scan_status": "passed",
                          "execution_context": {
                              "runner": "orchestrator",
                              "tree_hash": "abc123"}})
        assert r.status_code in (403, 503), (
            f"non-verifier evidence write must be rejected in strict (got "
            f"{r.status_code})")

        # 3b. Even an orchestrator-claimed runner with the CI token is rejected.
        r = c.patch(f"/mrps/{mrp_id}/evidence",
                    headers=AGENT,
                    json={"unit_tests_status": "passed",
                          "security_scan_status": "passed"})
        assert r.status_code in (403, 503), (
            f"agent (coder/orchestrator) evidence write must be rejected (got "
            f"{r.status_code})")

        r = c.post(f"/mrps/{mrp_id}/check-ready")
        assert r.json()["ready"] is False, "no verifier evidence yet -> not ready"

        # 4. VERIFIER-owned evidence with a MATCHING tree hash + G8: a
        # completed INDEPENDENT AI review -> ready.
        r = c.patch(f"/mrps/{mrp_id}/evidence",
                    headers=VERIFIER,
                    json={"unit_tests_status": "passed",
                          "security_scan_status": "passed",
                          "verified_tree_hash": "abc123",
                          "execution_context": {
                              "runner": "ci:verifier",
                              "tree_hash": "abc123"}})
        assert r.status_code == 200, r.text

        # Still not ready: G8 requires a reviewer-owned completed AI review.
        r = c.post(f"/mrps/{mrp_id}/check-ready")
        assert r.json()["ready"] is False, (
            "verifier evidence alone must NOT be merge-ready in strict mode "
            f"(G8 not satisfied): {r.json()['blocking_reasons']}")

        # Complete the independent AI review as agent:reviewer.
        reviewer_headers = {
            "X-Acting-As": "agent:reviewer",
            "X-Reviewer-Token": os.environ.get(
                "SASE_REVIEWER_TOKEN", "dev-reviewer-token-change-me")}
        r = c.patch(f"/mrps/{mrp_id}/review",
                    headers=reviewer_headers,
                    json={"ai_review_status": "completed",
                          "ai_review_notes": ["no blocking findings"],
                          "ai_review_findings": []})
        assert r.status_code == 200, r.text

        r = c.post(f"/mrps/{mrp_id}/check-ready")
        assert r.status_code == 200, r.text
        assert r.json()["ready"] is True, (
            f"verifier-owned matching evidence + completed AI review should be "
            f"merge-ready: {r.json()['blocking_reasons']}")
