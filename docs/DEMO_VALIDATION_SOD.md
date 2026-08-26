# SoD Validation Demo — "Internal Task Manager" (run 2026-08-26)

Purpose: prove the Phase 2 Separation-of-Duties architecture end to end —
human requirement → spec → human validation → proposal-only coder →
independent orchestrator verification → evidence bound to a tree hash →
MRP → human approval through the dashboard.

## How to re-run

1. `docker compose up -d --build api`
2. Login: `POST /auth/login` (m.barani) → token
3. `SASE_HUMAN_TOKEN=<tok> SASE_CI_TOKEN=dev-ci-token-change-me python scripts/run_demo_validation.py`
4. Open `/ui/` → **SoD Validation** view → approve the MRP in Approval Center.

The script is idempotent (re-uses deterministic ids on 409). The proposal is
a deterministic FILE-block template (`scripts/demo_proposal.txt`) — the demo
validates trust boundaries, not LLM prose quality.

## Recorded run (2026-08-26)

| Stage | Artifact / result | Identity |
|---|---|---|
| Requirement + chain | PRD-DTM-001, US-DTM-001, AC-DTM-001-01, SPEC-DTM-TASK-MANAGER-CORE | human:m.barani |
| GATE 1 spec validation | validated | human:m.barani (Bearer) |
| Proposal-only coder run | RUN-QW-2026-00015, commit 3212d2dc, 2 files | agent:coder (wrote nothing else) |
| Orchestrator verification | clean worktree checkout; tree beb7554f…; tests **6/6 PASS**, scan PASS, lint PASS | runner=orchestrator, provenance=tool |
| Evidence PATCH | audit #449 carries execution_context{runner, provenance, tree_hash} | ci:test-runner |
| MRP | MRP-PR-71834, fully_traceable=True | agent:coder created |
| Merge approval | status=approved, audited | human:m.barani (Bearer) |

## What this validated in Phase 2

- Coder is proposal-only: no test/scan/lint execution, no MRP/CRP creation,
  no terminal status from the coder process.
- Verification runs in an isolated clean checkout and FAILS CLOSED on
  tree-hash drift.
- Evidence records `runner: orchestrator`, `provenance: tool`, `tree_hash` —
  the exact fields gate G7 will require in Increment 2.
- Human gates unchanged: validation and merge approval both required real
  Bearer identity; audit shows the authoritative actor.

## Bugs found & fixed during validation (real-code fixes)

1. `agent_runs(prompt_id, prompt_version)` FK → seeded prompt registry via
   migrations/004_prompt_registry.sql (generated verbatim from code;
   HUMAN APPROVAL PENDING rows).
2. `AgentRunUpdate.status` was mandatory — now optional so proposal patches
   are non-terminal metadata (terminal machine unchanged).
3. `_commit` used `git status --porcelain` (sees unrelated untracked noise)
   → now checks staged changes only.

## Remaining before SASE_SOD_MODE=strict default / G7-G8 enforcement
- I2: gates G7/G8 + migration 004b (mrps.verified_tree_hash) + API-layer
  regression tests.
- I3: Reviewer Agent advisory narrative.
- SpringBoot coder delegates to verification module.
