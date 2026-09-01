"""
Phase 2 I3 — Reviewer boundary + G8 gate tests (ADR-002 Separation of Duties).

The Reviewer (agent:reviewer) is a genuinely separate, ADVISORY-ONLY
authority. G8 says an MRP may not reach merge-ready in strict mode unless
its AI review is completed AND that review is independently owned (audit
actor_id == 'agent:reviewer'). These tests assert the cut-lines:

  A. Source / credential separation (no runtime):
       - only agents/reviewer.py executes SASE_REVIEWER_TOKEN; the coder and
         orchestrator never reference it. If they could, they could
         self-certify a review — collapsing the advisory boundary.
       - the reviewer role allowlist forbids writing verification evidence,
         code, or agent runs; it only ever writes PATCH /mrps/*/review.

  B. DB-free API security + gate logic:
       - require_reviewer_actor enforces the exact agent:reviewer identity +
         its own SASE_REVIEWER_TOKEN; coders/orchestrator/verifier/generic CI
         are rejected; unset credential is fail-closed (503).
       - G8 gate blocks when there is no completed review, and when the
         completed status was written by a non-reviewer; it passes only with
         a reviewer-owned completed review.

  C. Live API integration (auto-skips without the stack):
       - a live MRP: verifier evidence alone is NOT merge-ready (G8 blocks);
         a reviewer-owned completed review makes it merge-ready; the audit
         trail shows actor_id == 'agent:reviewer'.
       - the review endpoint rejects evidence/code/agent-run fields and
         non-reviewer identities.

Run:
    pytest tests/test_sod_g8.py -m "not live"   # A + B (no stack)
    pytest tests/test_sod_g8.py                 # A + B + C (stack up)
"""

import ast
import io
import os
import textwrap
import tokenize
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.security import require_reviewer_actor, REVIEWER_ACTOR
from api.gates import mrp_ready_for_merge
from api.models import AuditLog
from agents.config import ROLES

REPO_ROOT = Path(__file__).resolve().parent.parent
CODER_SRC = (REPO_ROOT / "agents" / "coder_agent.py").read_text(encoding="utf-8")
ORCHESTRATOR_SRC = (REPO_ROOT / "agents" / "orchestrator.py").read_text(
    encoding="utf-8")
REVIEWER_SRC = (REPO_ROOT / "agents" / "reviewer.py").read_text(encoding="utf-8")

TOKEN_ENV = "SASE_REVIEWER_TOKEN"
REVIEWER_TOKEN = "dev-reviewer-token-change-me"


def _code_tokens(src: str) -> set[str]:
    names: set[str] = set()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(src).readline)
        for tok in tokens:
            if tok.type == tokenize.NAME and tok.string == TOKEN_ENV:
                names.add(tok.string)
    except tokenize.TokenError:
        pass
    return names


def _func_ast(src: str, func_name: str):
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == func_name:
            return node
    return None


def _reads_reviewer_token(fn) -> bool:
    found = False

    def visit(node):
        nonlocal found
        if found:
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Module, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                rest = body[1:]
            else:
                rest = body
            for child in rest:
                visit(child)
            return
        if isinstance(node, ast.Subscript):
            try:
                value = node.value
                if isinstance(value, ast.Attribute) and value.attr == "environ":
                    idx = node.slice
                    if isinstance(idx, ast.Constant) and idx.value == TOKEN_ENV:
                        found = True
                        return
            except Exception:
                pass
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "get":
                args = node.args
                if args and isinstance(args[0], ast.Constant) \
                        and args[0].value == TOKEN_ENV:
                    found = True
                    return
        for child in ast.iter_child_nodes(node):
            visit(child)
    visit(fn)
    return found


# ------------------------------------------------------------ A. source ----

def test_only_reviewer_module_consumes_reviewer_credential():
    """
    SoD: only agents/reviewer.py may read SASE_REVIEWER_TOKEN in executable
    code. If the coder or the orchestrator could, they could self-certify a
    review — collapsing the advisory boundary.
    """
    assert TOKEN_ENV in REVIEWER_SRC          # reviewer consumes its own token
    assert TOKEN_ENV not in _code_tokens(CODER_SRC), (
        f"coder_agent.py executes a reference to {TOKEN_ENV}")
    assert TOKEN_ENV not in _code_tokens(ORCHESTRATOR_SRC), (
        f"orchestrator.py executes a reference to {TOKEN_ENV}")


def test_orchestrator_coordinator_never_reads_reviewer_token():
    fn = _func_ast(ORCHESTRATOR_SRC, "_sod_verify_and_package")
    assert fn is not None
    assert not _reads_reviewer_token(fn), (
        f"the strict orchestration function must never hold {TOKEN_ENV}")


def test_reviewer_allowlist_cannot_write_evidence_code_or_runs():
    """
    Role allowlist (agents/config.py): the reviewer may READ specs/agent
    runs/MRPs/verification-requests/evidence/traceability, and WRITE only
    PATCH /mrps/*/review. It must NOT be able to write verification evidence
    (the broad PATCH /mrps* is gone), mutate agent runs, or raise CRPs.
    """
    reviewer = ROLES["reviewer"]
    allowed = {f"{m} {p}" for m, p in reviewer.allow}
    for required in ("GET /specs*", "GET /agent-runs*", "GET /mrps*",
                     "GET /verification-requests*", "GET /evidence*",
                     "GET /traceability*"):
        assert required in allowed, f"reviewer lost required read {required}"
    writes = {f"{m} {p}" for m, p in reviewer.allow if m == "PATCH"}
    assert writes == {"PATCH /mrps/*/review"}, (
        f"reviewer must only ever write the review endpoint, got {writes}")
    assert "PATCH /mrps/*" not in allowed
    assert not any(m == "PATCH" and p == "PATCH /agent-runs*"
                   for m, p in reviewer.allow)


def test_reviewer_model_differs_from_coder():
    """G8 requirement 5: generation and review use DIFFERENT model families."""
    assert ROLES["reviewer"].model != ROLES["coder"].model
    assert ROLES["reviewer"].model == "deepseek-r1:8b"
    # Coder uses the qwen2.5-coder model family (a different family from the
    # deepseek reviewer). 14b proved unreliable (empty/hang) on this CPU-only
    # Ollama for multi-file generation, so the coder runs the proven 7b.
    assert ROLES["coder"].model in ("qwen2.5-coder:7b", "qwen2.5-coder:14b")
    assert ROLES["coder"].model.startswith("qwen2.5-coder:")


def test_critics_writes_are_advisory_review_fields_only():
    """The Critic (reflection) role also stays advisory: review-endpoint write only."""
    critic = ROLES["critic"]
    assert critic.identity == "agent:critic"
    writes = {f"{m} {p}" for m, p in critic.allow if m == "PATCH"}
    assert writes == {"PATCH /mrps/*/review"}
    assert not any(m == "POST" or p == "PATCH /agent-runs*" for m, p in critic.allow)


# ------------------------------------------------------------- B. security ---

def test_reviewer_requires_header():
    for missing in (None, ""):
        with pytest.raises(HTTPException) as exc:
            require_reviewer_actor(x_acting_as=missing)
        assert exc.value.status_code == 401, f"{missing!r} must be rejected"


def test_reviewer_rejects_other_identities():
    """A coder, critic, the orchestrator, the verifier, or generic CI may not act as reviewer."""
    for forged in ("agent:coder_agent", "agent:critic", "ci:verifier",
                   "ci:test-runner", "orchestrator"):
        with pytest.raises(HTTPException) as exc:
            require_reviewer_actor(x_acting_as=forged, x_reviewer_token=REVIEWER_TOKEN)
        assert exc.value.status_code == 403, f"{forged!r} must not pass"


def test_reviewer_fails_closed_when_unconfigured(monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    with pytest.raises(HTTPException) as exc:
        require_reviewer_actor(x_acting_as=REVIEWER_ACTOR,
                               x_reviewer_token=REVIEWER_TOKEN)
    assert exc.value.status_code == 503


def test_reviewer_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, REVIEWER_TOKEN)
    with pytest.raises(HTTPException) as exc:
        require_reviewer_actor(x_acting_as=REVIEWER_ACTOR,
                               x_reviewer_token="wrong-token")
    assert exc.value.status_code == 403


def test_reviewer_accepts_identity_and_token(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, REVIEWER_TOKEN)
    actor = require_reviewer_actor(x_acting_as=REVIEWER_ACTOR,
                                   x_reviewer_token=REVIEWER_TOKEN)
    assert actor == REVIEWER_ACTOR


def test_ci_and_verifier_tokens_do_not_unlock_reviewer(monkeypatch):
    """Separation of credentials: generic CI or verifier tokens are not the reviewer's."""
    monkeypatch.setenv(TOKEN_ENV, REVIEWER_TOKEN)
    monkeypatch.setenv("SASE_CI_TOKEN", "dev-ci-token-change-me")
    monkeypatch.setenv("SASE_VERIFIER_TOKEN", "dev-verifier-token-change-me")
    for other in ("dev-ci-token-change-me", "dev-verifier-token-change-me"):
        with pytest.raises(HTTPException) as exc:
            require_reviewer_actor(x_acting_as=REVIEWER_ACTOR,
                                   x_reviewer_token=other)
        assert exc.value.status_code == 403


# ---- G8 gate (DB-free decision logic) ----

class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return SimpleNamespace(all=lambda: self._items)


class _FakeDb:
    def __init__(self, rows=None):
        self._rows = rows or []

    def execute(self, stmt):
        descriptions = getattr(stmt, "column_descriptions", None) or []
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is AuditLog:
            return _FakeResult(self._rows)
        return _FakeResult([])


def _verifier_evidence_row():
    return type("R", (), {"context": {"execution_context": {
        "runner": "ci:verifier", "tree_hash": "hash"}}})()


def _review_row(actor_id, status):
    return type("R", (), {
        "context": {"review_fields": {"ai_review_status": status}},
        "actor_id": actor_id, "action": "update_mrp_review",
    })()


def _mrp(ai_review_status=None):
    return type("M", (), {
        "id": "MRP-G8-TEST",
        "unit_tests_status": "passed",
        "integration_tests_status": "passed",
        "security_scan_status": "passed",
        "spec_ids": ["S1"], "blueprint_version": "v1.0",
        "status": "draft",
        "verified_tree_hash": "hash",
        "ai_review_status": ai_review_status,
    })()


def test_g8_blocks_merge_without_review(monkeypatch):
    """Verifier evidence alone (G7 satisfied) but NO AI review -> G8 blocks."""
    monkeypatch.setenv("SASE_SOD_MODE", "strict")
    ready, reasons = mrp_ready_for_merge(
        _FakeDb(rows=[_verifier_evidence_row()]), _mrp(ai_review_status=None))
    assert not ready
    assert any("AI review not completed" in r for r in reasons)


def test_g8_blocks_when_completed_set_but_not_reviewer_owned(monkeypatch):
    """
    A completed ai_review_status is NOT enough: G8 requires the audit trail
    to prove the completed status was written BY the reviewer. A
    coder/orchestrator writing to it does not count.
    """
    monkeypatch.setenv("SASE_SOD_MODE", "strict")
    forged = _review_row("agent:coder_agent", "completed")
    ready, reasons = mrp_ready_for_merge(
        _FakeDb(rows=[_verifier_evidence_row(), forged]),
        _mrp(ai_review_status="completed"))
    assert not ready
    assert any("not independently owned" in r for r in reasons)
    assert any("actor_id != 'agent:reviewer'" in r for r in reasons)


def test_g8_passes_only_with_reviewer_owned_completed_review(monkeypatch):
    """G7 owned + G8 reviewer-owned completed review -> merge-ready."""
    monkeypatch.setenv("SASE_SOD_MODE", "strict")
    review = _review_row(REVIEWER_ACTOR, "completed")
    ready, reasons = mrp_ready_for_merge(
        _FakeDb(rows=[_verifier_evidence_row(), review]),
        _mrp(ai_review_status="completed"))
    assert ready, reasons
    assert reasons == []


def test_g8_rejects_needs_revision_even_if_reviewer_owned(monkeypatch):
    monkeypatch.setenv("SASE_SOD_MODE", "strict")
    review = _review_row(REVIEWER_ACTOR, "needs_revision")
    ready, reasons = mrp_ready_for_merge(
        _FakeDb(rows=[_verifier_evidence_row(), review]),
        _mrp(ai_review_status="needs_revision"))
    assert not ready
    assert any("AI review not completed" in r for r in reasons)


def test_g8_inert_in_legacy_mode(monkeypatch):
    """Outside strict mode G8 does not block (matches G7 behavior)."""
    monkeypatch.setenv("SASE_SOD_MODE", "legacy")
    ready, reasons = mrp_ready_for_merge(_FakeDb(), _mrp(ai_review_status=None))
    assert ready
    assert reasons == []


# -------------------------------------------------------- C. integration ----

BASE = "http://localhost:8000"
VERIFIER = {"X-Acting-As": "ci:verifier",
            "X-CI-Token": os.environ.get("SASE_VERIFIER_TOKEN",
                                         "dev-verifier-token-change-me")}
REVIEWER = {"X-Acting-As": REVIEWER_ACTOR,
            "X-Reviewer-Token": os.environ.get(
                "SASE_REVIEWER_TOKEN", "dev-reviewer-token-change-me")}
CODER = {"X-Acting-As": "agent:coder_agent",
         "X-Reviewer-Token": "dev-reviewer-token-change-me"}


def _api_reachable() -> bool:
    try:
        import httpx
        with httpx.Client(base_url=BASE, timeout=2) as c:
            return c.get("/health").status_code == 200
    except Exception:
        return False


@pytest.mark.live
@pytest.mark.skipif(not _api_reachable(),
                    reason="API not running at localhost:8000 — start the stack")
def test_live_g8_reviewer_boundary_and_gate():
    """
    Full API-layer proof of the advisory reviewer boundary + G8 gate:
      1. a coder identity cannot write review fields (rejected 403);
      2. the reviewer cannot write verification evidence (rejected on
         /mrps/{id}/evidence);
      3. verifier evidence alone is NOT merge-ready in strict mode (G8 blocks);
      4. a reviewer-owned completed review makes the MRP merge-ready;
      5. the audit trail records the review under actor_id == 'agent:reviewer'.
    """
    import uuid
    import httpx
    suffix = uuid.uuid4().hex[:6].upper()
    domain = f"G8{suffix}"
    pr_number = 41000 + int(suffix[:4], 16)

    with httpx.Client(base_url=BASE, timeout=10) as c:
        c.post("/projects", json={
            "id": "test-sod-g8", "name": "G8", "stack": "python"})
        r = c.post("/prds", json={
            "project_id": "test-sod-g8", "domain": domain, "title": "g8",
            "body_ref": "n/a", "created_by": "human:pytest"})
        prd_id = r.json()["id"]
        r = c.post("/user-stories", json={
            "prd_id": prd_id, "domain": domain, "body_ref": "n/a"})
        us_id = r.json()["id"]
        c.post("/acceptance-criteria", json={"user_story_id": us_id, "body_ref": "n/a"})
        r = c.post("/specs", json={
            "project_id": "test-sod-g8", "user_story_id": us_id,
            "domain": domain, "name": f"spec-{suffix}", "body_ref": "n/a"})
        assert r.status_code in (200, 409), r.text
        if r.status_code == 409:
            pytest.skip("spec id collision from a prior run")
        spec_id = r.json()["id"]
        c.post(f"/specs/{spec_id}/validate", json={"validated_by": None},
               headers={"X-Acting-As": "human:pytest"})
        r = c.post("/agent-runs", json={
            "project_id": "test-sod-g8", "agent_role": "coder_agent",
            "task_type": "code_generation", "model_name": "qwen2.5-coder:14b",
            "model_short": "G8", "spec_id": spec_id})
        assert r.status_code == 200, r.text
        run_id = r.json()["id"]
        r = c.post("/mrps", json={
            "project_id": "test-sod-g8", "pull_request_number": pr_number,
            "branch_name": f"agent/g8-{suffix}",
            "created_by_agent_run": run_id, "prd_id": prd_id,
            "spec_ids": [spec_id], "blueprint_id": "BP-PYTHON-CLI-001",
            "blueprint_version": "v1.0"})
        assert r.status_code in (200, 409), r.text
        if r.status_code == 409:
            pytest.skip("MRP id collision from a prior run")
        mrp_id = r.json()["id"]

        # 1. A coder identity must NOT be able to write review fields.
        r = c.patch(f"/mrps/{mrp_id}/review", headers=CODER,
                    json={"ai_review_status": "completed"})
        assert r.status_code in (403, 401), (
            f"coder must not write review fields (got {r.status_code})")

        # 2. The reviewer must NOT be able to write verification evidence.
        r = c.patch(f"/mrps/{mrp_id}/evidence",
                    headers={"X-Acting-As": REVIEWER_ACTOR,
                             "X-Reviewer-Token": "dev-reviewer-token-change-me",
                             "X-CI-Token": "dev-ci-token-change-me"},
                    json={"unit_tests_status": "passed"})
        assert r.status_code in (403, 401, 503), (
            f"reviewer must not write verification evidence (got {r.status_code})")

        # 2b. The review endpoint must reject non-review fields.
        r = c.patch(f"/mrps/{mrp_id}/review", headers=REVIEWER,
                    json={"unit_tests_status": "passed"})
        assert r.status_code == 422, (
            f"review endpoint must reject verification-evidence fields (got "
            f"{r.status_code})")

        # 3. Verifier-owned evidence -> still NOT merge-ready (G8 blocks).
        r = c.patch(f"/mrps/{mrp_id}/evidence", headers=VERIFIER,
                    json={"unit_tests_status": "passed",
                          "security_scan_status": "passed",
                          "verified_tree_hash": "abc123",
                          "execution_context": {
                              "runner": "ci:verifier", "tree_hash": "abc123"}})
        assert r.status_code == 200, r.text
        r = c.post(f"/mrps/{mrp_id}/check-ready")
        body = r.json()
        assert body["ready"] is False, (
            "verifier evidence alone must NOT be merge-ready in strict mode: "
            f"{body['blocking_reasons']}")
        assert any("AI review not completed" in b for b in body["blocking_reasons"])

        # 4. Reviewer-owned completed review -> merge-ready.
        r = c.patch(f"/mrps/{mrp_id}/review", headers=REVIEWER,
                    json={"ai_review_status": "completed",
                          "ai_review_notes": ["no blocking findings"],
                          "ai_review_findings": [
                              {"severity": "low", "file": "todo.py",
                               "line": 1, "message": "nits only"}]})
        assert r.status_code == 200, r.text
        r = c.post(f"/mrps/{mrp_id}/check-ready")
        body = r.json()
        assert body["ready"] is True, body["blocking_reasons"]

        # 5. Audit trail: the review was written BY agent:reviewer.
        r = c.get(f"/traceability/audit/MRP/{mrp_id}",
                  headers={"X-Acting-As": "human:pytest"})
        assert r.status_code == 200, r.text
        review_entries = [e for e in r.json()
                          if e["action"] == "update_mrp_review"]
        assert review_entries, "no review audit entries found"
        assert all(e["actor_id"] == REVIEWER_ACTOR for e in review_entries), (
            f"review audit actor_id must be {REVIEWER_ACTOR}: "
            f"{[e['actor_id'] for e in review_entries]}")
