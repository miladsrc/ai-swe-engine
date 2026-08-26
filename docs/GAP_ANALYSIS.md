# ai-swe-engine Gap Analysis

> **Objective:** Compare current implementation, current documentation, and Master Development Plan.
> **Date:** 2026-08-25 (**status refresh 2026-08-26**)
> **Status:** Analysis complete; refreshed after Phase 1 + hardening + Human Identity completion

---

## 1. ALREADY COMPLETED

### Phase 0: Foundational Agent Loop
- (Unchanged from 2026-08-25 analysis: prompts, orchestrator refactor, AC enforcement, CoderAgent, offline loop RUN-QW-2026-00009.)

### Phase 1: Governance Integrity Hardening â€” COMPLETE
- Bug 1 (CRP terminal-state bypass) FIXED with regression test
- Bug 2 (open_crp_ids staleness) FIXED â€” merge gate queries live CRP data
- Provenance tagging on evidence records DONE
- Read-only evidence export endpoint (`GET /evidence/run/{id}`) DONE

### Hardening batch P1-P8 (2026-08-26) â€” COMPLETE
- Env-configurable Ollama + transient-failure retry; AgentRun provenance fields populated; fail-closed CI token + constant-time compares; orphan-run reaper; surgical git staging; language-aware security scan; execution evidence persisted to audit context; blueprint mutations audited.

### Interstitial Human Identity milestone â€” COMPLETE
- users/api_tokens tables; PBKDF2 passwords; bearer tokens authoritative at human gates; /auth/login + /auth/me; full token-flow migration of tests/docs/tooling; strict flag ready (OFF). See docs/PHASES/HUMAN-IDENTITY.md.

---

## 2. PARTIALLY IMPLEMENTED

### Infrastructure
- PostgreSQL + API active; Redis, Qdrant present only as commented-out scaffolding

### Agent roster
- Reviewer / Reflection roles defined in config but not implemented as separate processes

---

## 3. MISSING (unchanged roadmap gaps)

### Phase 2: Separation of Duties â€” NEXT UP
- Coder Agent still runs its own tests (conflict of interest)
- No independent test execution step owned by the Orchestrator
- No formalized Security Agent boundary
- No Reviewer Agent implementation

### Phase 3: Semantic Memory Integration
- Qdrant not deployed; no indexing pipeline; no retrieval integration

### Phase 4: Bounded Self-Repair â€” not started
### Phase 5: Coordination Layer (Redis) â€” deferred pending trigger condition
### Phase 6-8: Not started

---

## 4. INCONSISTENCIES (resolved 2026-08-26 audit)
- ~~FULL_DOCUMENTATION version mismatch~~ resolved (v0.2.0 everywhere)
- ~~Test-count drift across docs~~ resolved (101 unit + live E2E is the reference)
- Known open documentation debt is tracked in docs/PROGRESS/2026-08-26.md (audit section)

---

## 5. TECHNICAL DEBT (current)

1. Coder Agent self-attests its own tests (Phase 2 target)
2. Prompts table has no writers â€” provenance hashes reference code history
3. Evidence-export endpoint anonymous (P9, awaiting approval)
4. Spring Boot / designer agents carry placeholder upstream ids
5. No rate limiting on /auth/login
6. No mechanism to catch wrong-but-working LLM output beyond human review

---

## 6. CONCLUSION *(updated)*

Phase 0 and Phase 1 are complete, followed by an approved hardening batch and the interstitial Human Identity milestone (strict mode ready, flag OFF). Master-Plan Phase 2 (Separation of Duties) is the next planned work. The Master Development Plan remains the Source of Truth.

---

