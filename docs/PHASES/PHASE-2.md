# PHASE 2 — Separation of Duties (I1 implemented + E2E-validated on two tracks)

> **Objective:** Remove the conflict of interest where the Coder Agent both writes code AND certifies its own tests/security posture.
> **Current status:** VALIDATED END-TO-END 2026-08-26 (`SASE_SOD_MODE=legacy` default; strict path proven live on Spring Boot AND Angular tracks; final human approvals pending). Remaining increments: G7/G8 gate enforcement (I2), Reviewer Agent (I3).
> **Owner:** m.barani · **Dependencies:** Phase 1 provenance tagging (done); Human Identity milestone (done)
> **Evidence:** tests/test_sod_unit.py · audit trail MRPs 71577–71583 · docs/DEMO_VALIDATION_SOD.md · docs/demo/MAP_DEMO_BLUEPRINT.md
> **Completion criteria:** no code path exists where the CoderAgent process determines pass/fail; Reviewer Agent exists as a distinct traceable call

---

## 1. Self-certification risk register (as-built today)

| # | Risk | Location | Severity |
|---|---|---|---|
| R1 | **Test execution inside the coder process** — `run_tests()` (pytest subprocess) is invoked by `CoderAgent.implement_spec`; the same process wrote the code and the tests | coder_agent.py:108,129 | HIGH |
| R2 | **Security scan inside the coder process** — `security_scan()` runs on in-memory `files` dict in the same process; scanner lives in the coder's own module | coder_agent.py:131,344 | HIGH |
| R3 | **No content binding** — nothing proves the scanned/tested bytes are the committed bytes; files can change between test→scan→commit | order of ops in implement_spec | MEDIUM-HIGH |
| R4 | **Misleading provenance** — evidence PATCHed by `ci:test-runner` identity with CI token, but the DATA originates from the agent's own process; audit says "tool" when it is effectively "agent" | orchestrator._run_code_phase → record_ci_evidence | HIGH |
| R5 | **Self-authored tests** — coder writes the tests it then passes; accepted for now (proposed-tests model) but execution must still be independent | FILE blocks include test files | MEDIUM |
| R6 | **Reviewer absent** — reviewer role defined in config but never called; `ai_review_status` always null; human review has no risk narrative to lean on | config.py vs routers/mrp.py | MEDIUM |
| R7 | SpringBoot variant duplicates the whole flow with its own ordering (partially hardened but same structural conflict) | coder_springboot.implement_spec | MEDIUM |

Non-goals: merge-approval ownership stays exactly as-is (human gates + tokens); roles/routing remain Phase 9.

## 2. Target responsibility split

```
Orchestrator (owns ALL verification; deterministic)
 ├─ Step A  CoderAgent.generate(spec)      → proposed files (code+tests), run record
 │           NO test/scan/lint/git rights in this path anymore
 ├─ Step B  Snapshot: git commit → COMMIT_HASH + TREE_HASH bound to the run
 ├─ Step C  TestExecutionStep (fresh process, cwd = clean checkout at TREE_HASH)
 │            → exit code IS ground truth; output captured
 ├─ Step D  SecurityScanStep (deterministic scanner over the SAME tree hash)
 ├─ Step E  LintStep (compileall / mvn verify)
 ├─ Step F  ReviewerAgent (LLM, separate call): reads evidence export ONLY,
 │            emits ai_review_notes (advisory narrative, never pass/fail)
 ├─ Step G  Evidence PATCH via ci:test-runner token, now carrying:
 │            runner="orchestrator", tree_hash, per-step exit codes, provenance=tool
 └─ Step H  MRP create + terminal patch + CRP (unchanged order)
```

## 3. Evidence ownership rules

1. Every verification result records `runner: "orchestrator"` + `tree_hash`.
2. Provenance tag semantics tightened: `tool` may only be used when the producing step ran OUTSIDE any agent process (enforced by convention now, gate-checked later).
3. The CoderAgent loses API permission to PATCH anything except its own run lifecycle (allowlist already prevents evidence writes — keep).

## 4. Required gates

| Gate | Check | Failure |
|---|---|---|
| G7 (new) | `mrp_ready_for_merge` requires evidence whose `execution_context.runner == "orchestrator"` AND `execution_context.tree_hash == mrp.commit-bound tree hash` | blocking reason "verification not independently owned" |
| G8 (new) | AI review must exist (`ai_review_status == completed`) before ready_for_human_review — narrative advisory, presence mandatory | needs_revision |
| Existing | G1–G6 unchanged | unchanged |

## 5. Required backend changes

| Change | Files |
|---|---|
| Extract verification into `agents/verification.py` (test/scan/lint steps, tree-hash snapshot) | new module; coder_agent keeps generation only |
| Orchestrator drives steps A–H explicitly (`_run_code_phase` rewrite) | agents/orchestrator.py |
| `agents/reviewer_agent.py`: separate LLM call, input = evidence export JSON, output = risk narrative | new |
| MRP: optional `verified_tree_hash` column (migration 004) so G7 checks a real field, not just JSONB | migrations/004, models.py |
| `MRPEvidenceUpdate.execution_context` gains required-at-check-ready keys when SoD mode on | schemas.py, mrp.py |
| Rollout flag `SASE_SOD_MODE=strict\|legacy` (default legacy) — flip after E2E green | env, gates.py |
| SpringBoot variant delegates to the same verification module | coder_springboot.py |

## 6. Migration plan

1. **I1:** ✅ DONE — `agents/verification.py` (tree-hash binding, clean-checkout test/scan/lint steps); `CoderAgent.implement_spec(propose_only=)` proposal path; orchestrator strict branch; 9 unit tests. Legacy default untouched.
2. **I2 (next):** G7/G8 gate logic + migration 004 (`mrps.verified_tree_hash`) + regression tests proving coder cannot self-certify at the API layer.
3. **I3:** Reviewer Agent + ai_review wiring; E2E chain extension.
4. **Flip:** full suite + live E2E in strict mode → `SASE_SOD_MODE=strict` in compose → legacy path removed in a follow-up commit. SpringBoot variant delegates to verification module before flip.
5. Apply migration 004 manually to live volume (same procedure as 003).

## 7. What does NOT change

Human gates, token auth, CRP/VCR mechanics, MRP schema semantics beyond one additive column, Phase order, air-gap constraints, no new frameworks (steps are stdlib subprocess + existing scanner code relocated).
