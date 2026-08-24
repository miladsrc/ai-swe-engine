"""
DB-free regression tests for api/gates.py and api/security.py.

These run without Postgres or a running API (pytest tests/test_gates_unit.py)
so they belong in any CI run. The end-to-end gate behavior is covered by
tests/test_traceability_chain.py against the live stack.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.gates import (
    agent_run_must_exist_for_generated_code,
    assert_run_patchable,
    mrp_ready_for_merge,
    no_open_high_or_critical_crp_blocks_merge,
)
from api.main import app
from api.security import require_any_actor, require_ci_actor, require_human_actor


def make_mrp(**overrides):
    """A minimal MRP-shaped object; mrp_ready_for_merge only reads attributes."""
    base = dict(
        unit_tests_status=None,
        integration_tests_status=None,
        security_scan_status=None,
        spec_ids=[],
        blueprint_version=None,
        open_crp_ids=[],
        status="draft",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ------------------------------------------------------- MRP ready gate ----

def test_mrp_not_ready_when_no_evidence():
    ready, reasons = mrp_ready_for_merge(make_mrp())
    assert not ready
    assert "unit tests not passing" in reasons
    assert "security scan not passed" in reasons
    assert "no Spec referenced" in reasons
    assert "no Blueprint version referenced (unauditable per §3.7.8)" in reasons


def test_mrp_ready_when_all_gates_satisfied():
    ready, reasons = mrp_ready_for_merge(make_mrp(
        unit_tests_status="passed",
        integration_tests_status="passed",
        security_scan_status="passed",
        spec_ids=["SPEC-AUTH-SESSION-REFRESH"],
        blueprint_version="v1.0",
    ))
    assert ready
    assert reasons == []


def test_mrp_integration_tests_may_be_na_or_missing():
    for status in ("not_applicable", None):
        ready, _ = mrp_ready_for_merge(make_mrp(
            unit_tests_status="passed",
            integration_tests_status=status,
            security_scan_status="passed",
            spec_ids=["S1"],
            blueprint_version="v1.0",
        ))
        assert ready, f"integration_tests_status={status!r} should not block"


def test_mrp_blocked_by_failed_unit_or_security():
    assert not mrp_ready_for_merge(make_mrp(unit_tests_status="failed"))[0]
    assert not mrp_ready_for_merge(make_mrp(security_scan_status="failed"))[0]


def test_mrp_blocked_by_open_crps():
    ready, reasons = mrp_ready_for_merge(make_mrp(
        unit_tests_status="passed", security_scan_status="passed",
        spec_ids=["S1"], blueprint_version="v1.0",
        open_crp_ids=["CRP-AUTH-2026-001"],
    ))
    assert not ready
    assert any("open CRPs" in r for r in reasons)


def test_mrp_blocked_by_rejection():
    ready, reasons = mrp_ready_for_merge(make_mrp(
        unit_tests_status="passed", security_scan_status="passed",
        spec_ids=["S1"], blueprint_version="v1.0", status="rejected",
    ))
    assert not ready
    assert any("rejected" in r for r in reasons)


# ------------------------------------ CRP merge-block gate (no real db) ----

class _FakeResult:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return SimpleNamespace(all=lambda: self._items)


class _FakeDb:
    """
    Stands in for Session.execute(select(CRP...)) on the gate's query path.
    The CRP list passed here represents what the SQL filter would return
    (status open/blocking AND severity high/critical) — we're testing the
    gate's decision logic, not Postgres.
    """

    def __init__(self, filtered_crps):
        self._crps = filtered_crps

    def execute(self, stmt):
        return _FakeResult(self._crps)


def _crp(id):
    return SimpleNamespace(id=id)


def test_crp_gate_blocks_on_open_high_or_critical():
    db = _FakeDb([_crp("CRP-1"), _crp("CRP-2")])
    with pytest.raises(HTTPException) as exc:
        no_open_high_or_critical_crp_blocks_merge(db, ["SPEC-1"])
    assert exc.value.status_code == 409
    assert "CRP-1" in exc.value.detail
    assert "CRP-2" in exc.value.detail


def test_crp_gate_passes_when_query_returns_nothing_blocking():
    # Simulates the SQL filter finding no open High/Critical CRPs
    # (e.g. the only high-severity CRP is already resolved).
    no_open_high_or_critical_crp_blocks_merge(_FakeDb([]), ["SPEC-1"])  # must not raise


def test_crp_gate_short_circuits_on_empty_spec_list():
    no_open_high_or_critical_crp_blocks_merge(None, [])  # must not raise


# ------------------------------------------- agent-run existence gate ----

def test_agent_run_id_is_required():
    # db is never touched when the id is missing — the gate raises first.
    with pytest.raises(HTTPException) as exc:
        agent_run_must_exist_for_generated_code(None, None)
    assert exc.value.status_code == 409


# ------------------------------------------------------------ security ----

def test_human_actor_header_required():
    for missing in (None, ""):
        with pytest.raises(HTTPException) as exc:
            require_human_actor(x_acting_as=missing)
        assert exc.value.status_code == 401, f"{missing!r} must be rejected"


def test_agent_identity_cannot_pass_human_gate():
    for forged in ("agent:coder_agent", "gateway-controller:", "system", "HUMAN:x", "human"):
        with pytest.raises(HTTPException) as exc:
            require_human_actor(x_acting_as=forged)
        assert exc.value.status_code == 403, f"{forged!r} must not pass"


@pytest.mark.parametrize("actor", ["human:m.barani", "human:b.soltani"])
def test_valid_human_actor_passes(actor):
    assert require_human_actor(x_acting_as=actor) == actor


# ------------------------------------------------- CI actor guard (B1) ----

def test_ci_actor_header_required():
    for missing in (None, ""):
        with pytest.raises(HTTPException) as exc:
            require_ci_actor(x_acting_as=missing, x_ci_token=None)
        assert exc.value.status_code == 401, f"{missing!r} must be rejected"


@pytest.mark.parametrize("forged", ["human:x", "agent:coder_agent", "ci", "system", "CI:pipeline"])
def test_non_machine_actor_cannot_pass_ci_gate(forged):
    with pytest.raises(HTTPException) as exc:
        require_ci_actor(x_acting_as=forged, x_ci_token=None)
    assert exc.value.status_code == 403, f"{forged!r} must not pass"


def test_ci_actor_passes_without_token_configured(monkeypatch):
    # Local dev: SASE_CI_TOKEN unset -> header identity alone is enough.
    monkeypatch.delenv("SASE_CI_TOKEN", raising=False)
    assert require_ci_actor(x_acting_as="ci:pipeline", x_ci_token=None) == "ci:pipeline"
    assert require_ci_actor(x_acting_as="system:scanner", x_ci_token="whatever") == "system:scanner"


def test_ci_actor_with_matching_token_passes(monkeypatch):
    monkeypatch.setenv("SASE_CI_TOKEN", "secret-123")
    assert require_ci_actor(
        x_acting_as="ci:pipeline", x_ci_token="secret-123"
    ) == "ci:pipeline"


def test_ci_actor_with_wrong_token_is_forbidden(monkeypatch):
    monkeypatch.setenv("SASE_CI_TOKEN", "secret-123")
    with pytest.raises(HTTPException) as exc:
        require_ci_actor(x_acting_as="ci:pipeline", x_ci_token="wrong")
    assert exc.value.status_code == 403


def test_ci_actor_with_missing_token_is_unauthenticated(monkeypatch):
    monkeypatch.setenv("SASE_CI_TOKEN", "secret-123")
    with pytest.raises(HTTPException) as exc:
        require_ci_actor(x_acting_as="ci:pipeline", x_ci_token=None)
    assert exc.value.status_code == 401


# --------------------------------------------- any-actor guard (B4) ----

def test_any_actor_header_required():
    for missing in (None, ""):
        with pytest.raises(HTTPException) as exc:
            require_any_actor(x_acting_as=missing)
        assert exc.value.status_code == 401


def test_unrecognized_actor_rejected_by_any_gate():
    with pytest.raises(HTTPException) as exc:
        require_any_actor(x_acting_as="random")
    assert exc.value.status_code == 403


@pytest.mark.parametrize("actor", [
    "human:m.barani",
    "agent:coder_agent",
    "ci:pipeline",
    "system:scanner",
])
def test_every_valid_prefix_passes_any_gate(actor):
    assert require_any_actor(x_acting_as=actor) == actor


# ------------------------------- Agent Run terminal-state machine (B3) ----

def test_run_patch_unknown_status_invalid():
    for bad in ("done", "", None, "COMPLETED"):
        with pytest.raises(HTTPException) as exc:
            assert_run_patchable("running", bad)
        assert exc.value.status_code == 422, f"{bad!r} must be rejected"
        assert "running" in exc.value.detail  # allowed values are listed


def test_run_patch_on_terminal_run_blocked():
    for terminal in ("completed", "failed", "blocked"):
        with pytest.raises(HTTPException) as exc:
            assert_run_patchable(terminal, "running")
        assert exc.value.status_code == 409, f"terminal {terminal!r} must be immutable"
        assert "§3.7.8" in exc.value.detail or "immutable" in exc.value.detail


def test_run_patch_on_running_run_allowed():
    # No exception -> patchable; also covers running->terminal transitions.
    for new_status in ("running", "completed", "failed", "blocked"):
        assert_run_patchable("running", new_status)


# ------------------------------------- perimeter token middleware (B2) ----

client = TestClient(app)


def test_perimeter_token_missing_or_wrong_rejected(monkeypatch):
    monkeypatch.setenv("SASE_API_TOKEN", "perimeter-secret")
    r = client.get("/health")
    assert r.status_code == 401
    r = client.get("/health", headers={"X-API-Token": "wrong"})
    assert r.status_code == 401
    assert r.json()["detail"]  # JSON body present


def test_perimeter_token_correct_accepted(monkeypatch):
    monkeypatch.setenv("SASE_API_TOKEN", "perimeter-secret")
    r = client.get("/health", headers={"X-API-Token": "perimeter-secret"})
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_no_perimeter_token_needed_when_unset(monkeypatch):
    monkeypatch.delenv("SASE_API_TOKEN", raising=False)
    r = client.get("/health")  # no header at all
    assert r.status_code == 200
