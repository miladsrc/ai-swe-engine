"""
DB-free regression tests for api/gates.py and api/security.py.

These run without Postgres or a running API (pytest tests/test_gates_unit.py)
so they belong in any CI run. The end-to-end gate behavior is covered by
tests/test_traceability_chain.py against the live stack.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.gates import (
    agent_run_must_exist_for_generated_code,
    mrp_ready_for_merge,
    no_open_high_or_critical_crp_blocks_merge,
)
from api.security import require_human_actor


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
