# ai-swe-engine Gap Analysis

> **Objective:** Compare current implementation, current documentation, and Master Development Plan.
> **Date:** 2026-08-25
> **Status:** Analysis complete

---

## 1. ALREADY COMPLETED

### Phase 0: Foundational Agent Loop
- Agent prompt engineering (ProductAgent, SpecAgent) with system prompts and worked examples
- Orchestrator refactor removing the SpecAgent bypass
- Empty-context bug fix (US/AC endpoints now echo body_ref)
- AC-reference enforcement (_enforce_ac_refs) as a governance post-processing layer
- CoderAgent: reads specs, writes files, runs pytest, runs security scan, commits, participates in MRP/CRP
- coder_prompts.py with engineering rules (deterministic tests, subprocess invocation, environment-overridable storage)
- End-to-end offline loop proven: RUN-QW-2026-00009, commit c8790ed5
- Documentation: README.md rewrite; FULL_DOCUMENTATION.md expansion
- 58 passing tests; clean working tree

### Documentation (just created)
- MASTER_PLAN.md: Official Source of Truth
- ARCHITECTURE.md: Current and target architecture
- PHASES/PHASE-0.md: Phase 0 documentation
- PHASES/PHASE-1.md: Phase 1 documentation
- ADR/ADR-001-sara-is-external.md: Architecture Decision Record
- CHANGELOG/CHANGELOG.md: Change history
- PROGRESS/2026-08-25.md: Daily progress tracking

---

## 2. PARTIALLY IMPLEMENTED

### Governance State Machine
- MRP/CRP/VCR works in the happy path
- Two known integrity gaps (Phase 1)

### Infrastructure
- PostgreSQL + API active
- Redis, Qdrant, Ollama present only as commented-out scaffolding

---

## 3. MISSING

### Phase 1: Governance Integrity Hardening
- Bug 1: CRP endpoint bypasses assert_run_patchable (api/routers/crp.py:53)
- Bug 2: open_crp_ids snapshot misses CRPs raised after MRP creation
- No provenance tagging on evidence records
- No read-only evidence export endpoint

### Phase 2: Separation of Duties
- Coder Agent currently runs its own tests (conflict of interest)
- No independent test execution step
- No formalized Security Agent boundary
- No Reviewer Agent implementation

### Phase 3: Semantic Memory Integration
- Qdrant not deployed
- No indexing pipeline
- No retrieval integration into agents

### Phase 4: Bounded Self-Repair
- No retry/attempt-tracking logic
- No repair attempt record type

### Phase 5: Coordination Layer (Redis)
- Redis not deployed
- No trigger condition met yet

### Phase 6-8: Not started

---

## 4. INCONSISTENCIES

### Documentation vs Code
- FULL_DOCUMENTATION.md says version 0.1.0 but code is v0.2.0
- README.md says 58 tests but some documentation references 37
- docker-compose.yml still has Redis/Qdrant commented out with old labels

### Architecture vs Master Plan
- Current architecture has no separation of duties (Phase 2)
- Current architecture has no provenance tagging (Phase 1)
- Current architecture has no semantic memory (Phase 3)

---

## 5. TECHNICAL DEBT

### Known Bugs
1. CRP endpoint bypasses assert_run_patchable (Phase 1)
2. open_crp_ids snapshot misses post-MRP CRPs (Phase 1)

### Structural Issues
1. Coder Agent self-attests its own tests (Phase 2)
2. No mechanism to catch wrong-but-working LLM output
3. No codified autonomy-level policy

### Documentation Gaps
1. No evidence provenance documentation
2. No autonomy model documentation
3. No test strategy documentation

---

## 6. DOCUMENTATION MISSING

### From Master Plan
- Section 5: Autonomy Model (not in any doc except MASTER_PLAN.md)
- Section 6: Memory Architecture (not in any doc except MASTER_PLAN.md)
- Section 7: Agent Architecture (partially in FULL_DOCUMENTATION.md)
- Section 8: Governance Model (partially in FULL_DOCUMENTATION.md)
- Section 9: Documentation System (new, just created)
- Section 10: Daily Development Tracking (new, just created)
- Section 11: Test Strategy (not documented)
- Section 12: Release Roadmap (not documented)
- Section 13: Biggest Risks (partially in FULL_DOCUMENTATION.md)

### From Architecture
- Trust boundaries (documented in MASTER_PLAN.md and SARA_ASSESSMENT.md)
- Component responsibilities (documented in MASTER_PLAN.md)
- Security model (documented in MASTER_PLAN.md)

---

## 7. PRIORITY ACTIONS

### Immediate (Phase 1)
1. Fix Bug 1: CRP endpoint bypasses assert_run_patchable
2. Fix Bug 2: open_crp_ids snapshot misses post-MRP CRPs
3. Add provenance tagging to evidence records
4. Build read-only evidence export endpoint
5. Write regression tests

### Short-term (Phase 2)
1. Extract test/scan from CoderAgent to Orchestrator
2. Add Reviewer Agent implementation
3. Formalize Security Agent boundary

### Medium-term (Phase 3)
1. Deploy Qdrant
2. Build indexing pipeline
3. Integrate retrieval into agents

---

## 8. CONCLUSION

The project is at the end of Phase 0. Phase 1 (Governance Integrity Hardening) is the immediate next step. The Master Development Plan is now the Source of Truth, and the documentation structure is established.

Key gaps:
- Two known governance bugs (Phase 1)
- No provenance tagging (Phase 1)
- No separation of duties (Phase 2)
- No semantic memory (Phase 3)

The project is well-structured but needs Phase 1 completion before any further capability work.