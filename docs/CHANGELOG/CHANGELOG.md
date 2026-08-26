# ai-swe-engine Changelog

---

## 2026-08-26

### Added (hardening batch P1–P8 — evolutionary, no architecture change)
- P1: `agents/llm.py` — Ollama host/model from env (`SASE_OLLAMA_HOST`, `SASE_OLLAMA_MODEL`); bounded retry with linear backoff for transient failures (URLError/5xx only; 4xx fails fast)
- P2: AgentRun provenance fields populated (`model_version`, `prompt_id`, `prompt_version`, `system_prompt_hash`) — existing columns, previously dead
- P3: secret hygiene — CI token fail-closed when `SASE_CI_TOKEN` unset (503), no hardcoded fallback, constant-time comparisons (evidence gate + perimeter middleware)
- P4: orphan-run reaper at API startup — stale 'running' runs marked failed by system actor `orphan-reaper`, audited (`SASE_ORPHAN_RUN_HOURS`, default 24h)
- P5: coder agents stage only files they wrote (no more `git add -A`); security scan is language-aware (JVM patterns for .java/.kt/.scala)
- P7: raw execution evidence (full test output, scan findings, lint output) persisted into audit context via `MRPEvidenceUpdate.execution_context`
- P8: blueprint create/update audited via existing append-only mechanism
- docs/P6_A_PLAN_BEFORE_WRITE_DESIGN.md: plan-before-write design (Phase A passive / Phase B enforcing — Phase B NOT approved yet)

### Fixed
- coder_springboot lifecycle ordering: terminal patch moved AFTER MRP/CRP (was 409-prone); guarded failure patch

### Tests
- tests/test_hardening_batch.py: 17 new DB-free unit tests (79 unit total, plus live E2E green)

---

## 2026-08-25

### Added
- MASTER_PLAN.md: Official Source of Truth for the project
- ARCHITECTURE.md: Current and target architecture documentation
- PHASES/PHASE-0.md: Phase 0 (Foundational Agent Loop) documentation
- PHASES/PHASE-1.md: Phase 1 (Governance Integrity Hardening) documentation
- ADR/ADR-001-sara-is-external.md: Architecture Decision Record
- PROGRESS/ directory for daily tracking

### Changed
- README.md: Complete rewrite for v0.2.0 (agent layer, local LLM)
- FULL_DOCUMENTATION.md: Added Agent Layer, Local LLM Integration sections
- docker-compose.yml: Updated Ollama comments

### Known Issues
- Bug 1: CRP endpoint bypasses assert_run_patchable (Phase 1)
- Bug 2: open_crp_ids snapshot misses post-MRP CRPs (Phase 1)
- No provenance tagging on evidence records (Phase 1)

---

## 2026-08-24

### Added
- Agent layer (agents/): config.py, engine_client.py, llm.py, product_agent.py, spec_agent.py, coder_agent.py, coder_prompts.py, prompts.py, orchestrator.py
- Coder Agent with reflection loop
- Prompt contracts for Product/Spec agents
- Local LLM integration (Ollama + Template fallback)
- 58+ tests passing
- Full end-to-end offline loop proven (RUN-QW-2026-00009)

### Fixed
- ids.py race condition (atomic UPSERT)
- security.py human-decision forgery (X-Acting-As header)
- crp.py severity ordering (CASE priority)
- VCR ghost-CRP bug (clear from MRPs on resolve)
- Terminal state machine (assert_run_patchable)
- Audit lockdown (REVOKE triggers)