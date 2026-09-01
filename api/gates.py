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
import os
from api.models import Spec, CRP, AgentRun, MRP, AuditLog

ALLOWED_RUN_STATUSES = {"running", "completed", "failed", "blocked"}
TERMINAL_RUN_STATUSES = {"completed", "failed", "blocked"}

# Phase 2 I3 (G8): the independent Reviewer's (advisory) identity. G8 only
# accepts a review record whose audit actor_id is EXACTLY this — a coder or
# orchestrator cannot self-certify an AI review.
REVIEWER_ACTOR = "agent:reviewer"
REVIEW_ACTION = "update_mrp_review"


def _sod_strict() -> bool:
    """Phase 2 SoD enforcement switch (docs/PHASES/PHASE-2.md §5).
    Gate G7 only engages when the operator has flipped SASE_SOD_MODE=strict;
    default 'legacy' preserves existing behavior for MRPs created outside
    the SoD flow. Read at call time so tests can toggle it."""
    return os.environ.get("SASE_SOD_MODE", "legacy") == "strict"


def _verifier_evidence_tree_hash(db: Session, mrp: MRP) -> str | None:
    """
    Search the append-only audit trail for evidence this MRP's Independent
    Verifier actually produced (action=update_mrp_evidence with
    execution_context.runner == 'ci:verifier'), and return the tree hash
    that evidence was bound to. Returns None when no such record exists.

    Phase 2 SoD (Step 2): the trusted verifier authority is the separate
    ci:verifier subprocess (agents/verifier.py) — NOT the orchestrator,
    which no longer writes evidence or claims a runner identity.
    """
    rows = db.execute(
        select(AuditLog).where(
            AuditLog.artifact_type == "MRP",
            AuditLog.artifact_id == mrp.id,
            AuditLog.action == "update_mrp_evidence",
        )
    ).scalars().all()
    for row in rows:
        ctx = row.context or {}
        exec_ctx = (ctx.get("execution_context") or {})
        if exec_ctx.get("runner") == "ci:verifier":
            return exec_ctx.get("tree_hash")
    return None


def _reviewer_completed_review(db: Session, mrp: MRP) -> bool:
    """
    Phase 2 I3 (G8): True only when the append-only audit trail holds a
    REVIEW record for this MRP that (a) was WRITTEN by the independent
    Reviewer (actor_id == 'agent:reviewer', action == 'update_mrp_review')
    and (b) set ai_review_status == 'completed'. A coder, critic, or
    orchestrator writing to ai_review_* does not count — G8 requires the
    reviewer-owned, reviewer-completed review. Advisory reviews with
    'needs_revision' are not 'completed'.
    """
    rows = db.execute(
        select(AuditLog).where(
            AuditLog.artifact_type == "MRP",
            AuditLog.artifact_id == mrp.id,
            AuditLog.action == REVIEW_ACTION,
        )
    ).scalars().all()
    for row in rows:
        # Defensive getattr: not every audit row carries actor_id/context
        # (e.g. other evidence rows in the same query view). Only a row
        # written BY the reviewer that set ai_review_status=completed counts.
        if getattr(row, "actor_id", None) != REVIEWER_ACTOR:
            continue
        ctx = getattr(row, "context", None) or {}
        written = ctx.get("review_fields") or {}
        if written.get("ai_review_status") == "completed":
            return True
    return False


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

    # ---- Phase 2 SoD gate G7 (docs/PHASES/PHASE-2.md §4) ----
    # In strict mode an MRP is only merge-ready when its pass/fail was
    # decided by the independent VERIFIER, not by the coder that wrote the
    # code, and NOT by the orchestrator that coordinates the workflow. We
    # require evidence whose runner == "ci:verifier" AND whose bound tree
    # hash exactly matches the bytes this MRP claims to merge. Without it:
    # no code path allows the CoderAgent or Orchestrator process to
    # determine pass/fail at merge time.
    if _sod_strict():
        bound = getattr(mrp, "verified_tree_hash", None)
        if not bound:
            reasons.append(
                "verification not independently owned "
                "(MRP has no verifier-bound verified_tree_hash)")
        else:
            evidenced = _verifier_evidence_tree_hash(db, mrp)
            if not evidenced:
                reasons.append(
                    "verification not independently owned "
                    "(no verifier-owned evidence: runner != 'ci:verifier')")
            elif evidenced != bound:
                reasons.append(
                    "verification not independently owned "
                    "(evidence tree_hash does not match MRP verified_tree_hash)")

        # ---- Phase 2 I3 SoD gate G8 (docs/ADR/ADR-002, Reviewer/I3) ----
        # An MRP may only be merge-ready in strict mode when an INDEPENDENT
        # Reviewer (agent:reviewer) has COMPLETED its advisory review. This
        # has two parts, both required:
        #   (a) the MRP's ai_review_status == 'completed' (the reviewer's
        #       own verdict field), AND
        #   (b) the audit trail proves that field was written BY the reviewer
        #       (actor_id == 'agent:reviewer'), so neither the coder nor the
        #       orchestrator can set it on the MRP's behalf.
        if getattr(mrp, "ai_review_status", None) != "completed":
            reasons.append(
                "AI review not completed "
                "(ai_review_status != 'completed' in strict mode)")
        elif not _reviewer_completed_review(db, mrp):
            reasons.append(
                "AI review not independently owned "
                "(no reviewer-owned completed review record "
                "(actor_id != 'agent:reviewer' or not completed))")

    return (len(reasons) == 0), reasons
