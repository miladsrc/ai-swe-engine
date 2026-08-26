# PHASE 1 - Governance Integrity Hardening

> **Objective:** Close known integrity gaps before adding any further capability.
> **Current status:** COMPLETE (2026-08-25)
> **Owner:** m.barani
> **Created date:** 2026-08-25
> **Last update:** 2026-08-26 (status sync)
> **Phase:** 1
> **Dependencies:** None beyond existing PostgreSQL
> **Tests:** Regression tests for both bugs + provenance assertion tests
> **Evidence:** Failing-then-passing regression tests; provenance tags on all evidence
> **Completion criteria:** Both bugs closed with regression tests; all evidence has provenance; export endpoint works
> **Future improvements:** Move evidence to genuinely append-only construct

---

## 1. Why This Phase Exists

Two governance-critical bugs are already known. Building memory, autonomy, or new agents on top of an unverified governance layer means every future phase inherits unverified trust.

## 2. Known Bugs

### Bug 1: CRP endpoint bypasses terminal-state guard

- Location: api/routers/crp.py, line 53
- Problem: run.status = blocked is a direct assignment that bypasses assert_run_patchable
- Impact: A terminal run (completed/failed/blocked) can be flipped back to blocked
- Fix: Wrap the status change in assert_run_patchable check

### Bug 2: open_crp_ids snapshot misses CRPs raised after MRP creation

- Location: api/routers/mrp.py
- Problem: When an MRP is created, it snapshots currently-open CRPs. Any CRP raised AFTER MRP creation is not in the snapshot.
- Impact: Merge gate shows stale open_crp_ids (though the live query in the gate itself catches this, display is misleading)
- Fix: Make the merge gate query live CRP data, not the snapshot; or update snapshot on CRP creation

## 3. Architecture Changes

- Add provenance field (source: human | tool | llm) to every evidence record
- Make evidence append-only
- Add a read-only evidence/report export endpoint

## 4. New Components

- Evidence provenance schema (column on evidence-related tables)
- Read-only export API (for Saras advisory role)

## 5. Changed Components

- CRP endpoint (enforce assert_run_patchable unconditionally)
- CRP snapshot logic (include CRPs raised after MRP creation)
- Evidence writes (add provenance tag)

## 6. Security Impact

HIGH - this phase closes the only known ways the governance layer can currently be bypassed or show a misleading state.

## 7. Human Approval Points

- Sign-off that both known bugs are verifiably closed
- Regression test proves the bypass path now fails correctly

## 8. Implementation Tasks

1. Fix Bug 1: Add assert_run_patchable check to CRP endpoint
2. Fix Bug 2: Update open_crp_ids logic to include post-MRP CRPs
3. Add provenance column to evidence-related tables
4. Update all evidence-writing code paths to include provenance tag
5. Build read-only export endpoint
6. Write regression tests for both bugs
7. Write provenance assertion tests

## 9. Tests Required

- Regression test: attempt CRP bypass -> assert 409
- Regression test: CRP raised post-MRP -> assert appears in live query
- Provenance tests: every evidence-writing path has non-null provenance
- Export endpoint test: returns full evidence trail read-only

## 10. Success Criteria

- Both bugs have failing-then-passing regression tests
- Every evidence record has a non-null provenance tag
- Export endpoint returns a runs full evidence trail read-only

## 11. Definition of Done

- All above tests merged and passing
- No evidence-writing path lacks a provenance tag (verified by lint/check rule)

## 12. Status

**COMPLETE (2026-08-25).** Evidence:
- Bug 1 fixed: `api/routers/crp.py` calls `assert_run_patchable` before blocking; regression test asserts 409.
- Bug 2 fixed: `mrp_ready_for_merge` queries live CRP data (gates.py); snapshot kept for display only; regression tests cover post-MRP CRPs.
- Provenance tagging: `MRPEvidenceUpdate.provenance` (human|tool|llm), stored in audit context.
- Read-only export: `GET /evidence/run/{run_id}`.
- Commits: `13f61a5`, merged via `367a5d7`.
- Follow-on hardening batch (2026-08-26, P1-P8) extended this phase's integrity work — see CHANGELOG and docs/PROGRESS/2026-08-26.md.

## 13. Risks

- ~~Schema change may require data migration for existing evidence records~~ — none required (provenance stored in audit JSONB).
- Export endpoint design: implemented as read-only aggregate; known gap — endpoint is currently anonymous (documented, fix awaiting approval).

## 14. Possible Future Improvements

- Move evidence storage to genuinely append-only construct (write-once table constraints or hash-chained log)