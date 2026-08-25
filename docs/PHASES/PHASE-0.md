# PHASE 0 - Foundational Agent Loop

> **Objective:** Prove an offline, LLM-backed engineering loop can run end-to-end with basic governance.
> **Current status:** COMPLETE
> **Owner:** m.barani + Sara (advisory)
> **Created date:** 2026-08-24
> **Last update:** 2026-08-25
> **Phase:** 0
> **Dependencies:** Ollama, PostgreSQL, existing MRP/CRP/VCR scaffolding
> **Tests:** 58 passing (unit + E2E)
> **Evidence:** RUN-QW-2026-00009, commit c8790ed5
> **Completion criteria:** End-to-end offline loop with governance
> **Future improvements:** Expand worked examples as new failure modes are discovered

---

## 1. Why This Phase Exists

Without a working baseline loop, no governance or autonomy work has anything to attach to.

## 2. What Was Solved

- Upstream agent prompts were poor (Qwen behaved like a chatbot)
- No real coding agent existed
- No end-to-end offline proof existed

## 3. Architecture Changes

- Introduced agents/prompts.py, agents/coder_agent.py, agents/coder_prompts.py
- Refactored orchestrator to stop bypassing SpecAgent

## 4. New Components

- ProductAgent + SpecAgent prompts with worked examples
- CoderAgent with reflection loop
- _enforce_ac_refs governance post-processor

## 5. Changed Components

- Orchestrator (no more inline one-liner bypass)
- US/AC endpoints (fixed empty-context body_ref bug)

## 6. Security Impact

Established the pattern of a governance post-processing layer (AC-reference enforcement) - first instance of deterministic code checks LLM output.

## 7. Human Approval Points

- Merge approval (exercised once, successfully)

## 8. Tests Required

- Unit tests for agents and endpoints
- Full run test (offline loop end-to-end)

## 9. Success Criteria

A real requirement produces real files, passing tests, passing security scan, and a merged commit.

**Achieved:** RUN-QW-2026-00009, commit c8790ed5

## 10. Definition of Done

- 58 tests passing
- Clean working tree
- One full successful run on record
- Docs updated

## 11. Status

**COMPLETE**

## 12. Possible Future Improvements

- Expand worked examples as new failure modes are discovered
- This phases governance pattern (_enforce_ac_refs) should be the template for every future agent-output check