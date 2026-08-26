# ai-swe-engine Architecture

> **Objective:** Document the current and target architecture of the ai-swe-engine.
> **Current status:** Current state documented; target state defined in MASTER_PLAN.md. Architecture UNCHANGED by the Human Identity milestone — authentication was added inside the existing security seam, not as a new layer.
> **Owner:** Sara (external advisory)
> **Created date:** 2026-08-25
> **Last update:** 2026-08-26
> **Phase:** Phase 0 + Phase 1 complete; interstitial Human Identity complete; Phase 2 next
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
| FastAPI engine (api/) | Running | hard gates, audit, auth (/auth/login, /auth/me) |
| PostgreSQL | Running | localhost:5433, auto-migrations (003 adds users/api_tokens) |
| Product Agent | Functional | drafts PRD/US/AC via LLM |
| Spec Agent | Functional | drafts YAML spec via LLM |
| Coder Agent | Functional | writes code, runs tests, commits |
| Spring Boot Coder Agent | Functional | Maven variant (coder_springboot.py) |
| Designer Agent | Functional | DESIGN.md + frontend generation (uncommitted at doc time) |
| Orchestrator | Functional | sequential pipeline, --online/--offline/--code |
| Human Identity (users/api_tokens) | Running | Bearer tokens authoritative at human gates; strict flag OFF |
| Ollama | Running | qwen2.5-coder:7b q4, CPU-only |
| Reviewer Agent | Defined | role in config.py, no implementation |
| Reflection Agent | Defined | role in config.py, no implementation |
| Test Runner | Functional | LLM-free, records evidence |
| Blueprints router | Functional | blueprint CRUD, audited |
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

### Authentication Boundary: Human vs Agent identity (added by Human Identity milestone)
- **Human decisions** (spec validate, MRP human-decision, VCR writes): identity
  resolves inside `require_human_actor` — a valid `Authorization: Bearer`
  token is AUTHORITATIVE (`human:<username>` from the users table); any
  X-Acting-As header value is ignored. Legacy prefix check remains only while
  `SASE_REQUIRE_HUMAN_TOKEN` is unset (fail-closed once set).
- **Agent identities** (`agent:*`) and **machine actors** (`ci:`/`system:`) do
  NOT authenticate via users/tokens: agents act under allowlisted role
  identities on non-human endpoints; CI evidence additionally requires the
  shared `SASE_CI_TOKEN` (fail-closed when unconfigured).
- **Audit ownership:** `audit_log` (append-only, DB triggers) is the single
  owner of identity evidence; logins, gate decisions, and reaper/revert
  system actions are all recorded there with the resolved actor id.

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