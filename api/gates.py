"""
Hard gates from the SASE paper, implemented as functions that raise
HTTPException rather than as documentation someone might skip.

Each function corresponds to a specific rule:

  spec_must_be_human_validated_before_code_gen  -> §3.5
  no_open_high_or_critical_crp_blocks_merge      -> §3.6.3, §3.7.8
  mrp_required_before_pr_review                  -> §5.6
   mrp_must_pass_tests_and_security_before_ready  -> §5.6.5
   agent_run_must_exist_for_generated_code        -> §3.7.8
   assert_run_patchable                           -> §3.7.8 (terminal runs immutable)
"""

from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from api.models import Spec, CRP, AgentRun, MRP

ALLOWED_RUN_STATUSES = {"running", "completed", "failed", "blocked"}
TERMINAL_RUN_STATUSES = {"completed", "failed", "blocked"}


def assert_run_patchable(current_status: str | None, new_status: str) -> None:
    """
    Pure state-machine check for PATCH /agent-runs/{id}: the payload status
    must be a known value, and a run that has already reached a terminal
    state ('completed', 'failed', 'blocked') may not be patched at all —
    its provenance (§3.7.8: which agent, with which inputs, produced what)
    is history and must stay immutable.
    """
    if new_status not in ALLOWED_RUN_STATUSES:
        raise HTTPException(
            422,
            f"Unknown Agent Run status {new_status!r}. Allowed values: "
            f"{', '.join(sorted(ALLOWED_RUN_STATUSES))}.",
        )
    if current_status in TERMINAL_RUN_STATUSES:
        raise HTTPException(
            409,
            f"Agent Run is already in terminal state '{current_status}'. Per "
            f"§3.7.8 the provenance of finished runs is immutable — no field "
            f"may be patched after completed/failed/blocked.",
        )


def spec_must_be_human_validated_before_code_gen(db: Session, spec_id: str) -> None:
    spec = db.get(Spec, spec_id)
    if spec is None:
        raise HTTPException(404, f"Spec {spec_id} not found")
    if not spec.human_validated:
        raise HTTPException(
            409,
            f"Spec {spec_id} has not been human-validated. Per §3.5, no Spec may "
            f"enter code generation without explicit human sign-off. "
            f"POST /specs/{spec_id}/validate first.",
        )


def no_open_high_or_critical_crp_blocks_merge(db: Session, spec_ids: list[str]) -> None:
    if not spec_ids:
        return
    stmt = select(CRP).where(
        CRP.spec_id.in_(spec_ids),
        CRP.status.in_(["open", "blocking"]),
        CRP.severity.in_(["high", "critical"]),
    )
    open_crps = db.execute(stmt).scalars().all()
    if open_crps:
        ids = ", ".join(c.id for c in open_crps)
        raise HTTPException(
            409,
            f"Cannot proceed: open High/Critical CRP(s) [{ids}] must be resolved "
            f"with a VCR before merge (§3.6.3, §3.7.8).",
        )


def agent_run_must_exist_for_generated_code(db: Session, agent_run_id: str | None) -> None:
    if not agent_run_id:
        raise HTTPException(
            409,
            "No Agent Run Record referenced. Per §3.7.8, every AI-generated "
            "change must be traceable to an Agent Run Record — none is unauditable.",
        )
    run = db.get(AgentRun, agent_run_id)
    if run is None:
        raise HTTPException(404, f"Agent Run {agent_run_id} not found")


def mrp_ready_for_merge(db: Session, mrp: MRP) -> tuple[bool, list[str]]:
    """
    Returns (ready, blocking_reasons). This is the concrete check behind
    the CI/CD gating table in §5.6.5 / §3.7.8 — call it before allowing
    a merge, not just before displaying a status badge.

    Bug fix: Query live CRP data instead of relying on stale open_crp_ids snapshot.
    This ensures CRPs raised after MRP creation are caught.
    """
    reasons = []
    if mrp.unit_tests_status not in ("passed",):
        reasons.append("unit tests not passing")
    if mrp.integration_tests_status not in ("passed", "not_applicable", None):
        reasons.append("integration tests not passing")
    if mrp.security_scan_status not in ("passed",):
        reasons.append("security scan not passed")
    if not mrp.spec_ids:
        reasons.append("no Spec referenced")
    if not mrp.blueprint_version:
        reasons.append("no Blueprint version referenced (unauditable per §3.7.8)")
    # Query live CRP data instead of relying on stale snapshot
    if mrp.spec_ids:
        live_crps = db.execute(
            select(CRP.id).where(
                CRP.spec_id.in_(mrp.spec_ids),
                CRP.status.in_(["open", "blocking"]),
                CRP.severity.in_(["high", "critical"]),
            )
        ).scalars().all()
        if live_crps:
            # Handle both string IDs and ORM objects with .id attribute
            crp_ids = [c.id if hasattr(c, 'id') else c for c in live_crps]
            reasons.append(f"open High/Critical CRPs still unresolved: {', '.join(crp_ids)}")
    if mrp.status == "rejected":
        reasons.append("MRP was rejected in human review")
    return (len(reasons) == 0), reasons
