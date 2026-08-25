# ai-swe-engine Changelog

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