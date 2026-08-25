# ai-swe-engine Architecture

> **Objective:** Document the current and target architecture of the ai-swe-engine.
> **Current status:** Current state documented; target state defined in MASTER_PLAN.md.
> **Owner:** Sara (external advisory)
> **Created date:** 2026-08-25
> **Last update:** 2026-08-25
> **Phase:** Phase 0 complete
> **Dependencies:** MASTER_PLAN.md
> **Tests:** N/A (documentation only)
> **Evidence:** Code inspection + Master Plan
> **Completion criteria:** Architecture matches implementation
> **Future improvements:** Update as phases progress

---

## 1. Current Architecture (v0.2.0)

`
                          HUMAN
                    approves / reviews
                     /              \\
              consults              operates
                  |                     |
                  v                     v
                SARA          ai-swe-engine
        (external, advisory,        |
         read-only access)     Orchestrator (sequential
                                control loop, --online/--offline)
                                |
                         +------+------+
                         v      v      v
                    Product  Spec  Coder
                     Agent  Agent  Agent
                      (LLM) (LLM)  (LLM)
                         |      |      |
                         +------+--+---+
                                  |
                         +--------+--------+
                         v                 v
                   Ollama (LLM)     Local Git Workspace
                   localhost:11434   IdeaProjects/<project>/
                         |
                         v
                   PostgreSQL (engine)
                   localhost:5433
`

### Current Component Status

| Component | Status | Notes |
|---|---|---|
| FastAPI engine (api/) | Running | 12 routes, hard gates, audit |
| PostgreSQL | Running | localhost:5433, auto-migrations |
| Product Agent | Functional | drafts PRD/US/AC via LLM |
| Spec Agent | Functional | drafts YAML spec via LLM |
| Coder Agent | Functional | writes code, runs tests, commits |
| Orchestrator | Functional | sequential pipeline, --online/--offline/--code |
| Ollama | Running | qwen2.5-coder:7b q4, CPU-only |
| Reviewer Agent | Defined | role in config.py, no implementation |
| Reflection Agent | Defined | role in config.py, no implementation |
| Test Runner | Functional | LLM-free, records evidence |
| Qdrant | NOT deployed | commented out in docker-compose |
| Redis | NOT deployed | commented out in docker-compose |

---

## 2. Target Architecture (from MASTER_PLAN.md)

`
                          HUMAN
                    approves / reviews
                     /              \\
              consults              operates
                  |                     |
                  v                     v
                SARA          AIR-GAPPED ai-swe-engine
        (external, advisory,        |
         read-only evidence)    Orchestrator (deterministic
         zero write rights)     control loop / state machine)
                                |
                    +-----------+-----------+-----------+-----------+
                    v           v           v           v           v
                Product      Spec       Coder       Test       Security
                 Agent      Agent      Agent       Agent       Agent
                  (LLM)     (LLM)      (LLM)    (det. exec,  (det. scan
                    |         |          |      LLM-authored  + LLM
                    |         |          |       tests)    narrative)
                    +---------+----+-----+-----------+----------+
                                 v
                          Reviewer Agent (LLM,
                          risk narrative only)
                                 |
                                 v
                          Ollama (local LLM backend)
                                 |
                    +------------+------------+
                    v            v             v
               PostgreSQL     Qdrant        Redis
              (system of    (semantic /   (conditional -
               record)      project mem)  coordination)
                    |
                    v
          Governance Engine (deterministic)
                    |
                    v
           Evidence Store (immutable, provenance-tagged)
                    |
                    v
        Merge Gate (deterministic) -> Safe Merge
`

---

## 3. Trust Boundaries

### Outer Boundary: Human <-> Sara
- Advisory only, no execution rights in either direction.
- Sara can read code, docs, test results.
- Sara cannot modify code, trigger runs, or approve merges.

### Air-Gap Boundary
- Everything inside must function with zero internet access.
- No cloud APIs, no external LLMs, no public registries.
- Local LLM (Ollama) only.

### Inner Boundary: LLM Output <-> Governance Engine
- No LLM output becomes approved without passing a deterministic gate.
- LLMs produce content; deterministic code governs actions.

---

## 4. Component Responsibilities

| Component | Type | Responsibility | Trust Level |
|---|---|---|---|
| Human | External | Final authority on all irreversible decisions | Authoritative |
| Sara | External | Architecture advice, documentation, review | Advisory |
| Orchestrator | Deterministic code | Sequences agents, invokes gates | Trusted |
| Product / Spec Agents | LLM | Turn requirement into structured spec | Untrusted until gated |
| Coder Agent | LLM | Writes code against approved spec | Untrusted until gated |
| Test execution | Deterministic process | Runs tests, reports pass/fail | Trusted (ground truth) |
| Security Agent | Det. scan + LLM narrative | Scan is fact; narrative is advisory | Scan trusted |
| Reviewer Agent | LLM | Risk narrative for human review | Untrusted, advisory |
| Ollama | Infrastructure | Local inference backend | N/A |
| PostgreSQL | Deterministic store | System of record | Trusted |
| Qdrant | Deterministic store | Semantic memory | Retrieval trusted |
| Redis | Deterministic store (conditional) | Ephemeral coordination | Non-authoritative |
| Governance Engine | Deterministic code | State machine, MRP/CRP/VCR | Trusted |
| Evidence Store | Deterministic, immutable | Provenance-tagged record | Trusted |
| Merge Gate | Deterministic code | Final authorization check | Trusted |