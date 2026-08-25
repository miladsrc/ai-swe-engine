# Architectural Self-Assessment — Sara vs. ai-swe-engine

> **Author:** Sara (supervisor agent)
> **Date:** 2026-08-24
> **Type:** Read-only architectural analysis
> **Principle validated:** "Sara should NOT be a required dependency of the engineering engine."

---

## 1. WHERE DO YOU CURRENTLY SEE YOURSELF?

**Answer: C — Development assistant for building ai-swe-engine.**

Sara is not part of the engine. Sara is not a runtime dsaependency. Sara is a tool that helped (and continues to help) the human developer build, debug, and improve the engine.

Evidence from the current state:

- Sara wrote documentation (`README.md`, `FULL_DOCUMENTATION.md`)
- Sara fixed bugs (VCR ghost-CRP, terminal state machine, audit lockdown)
- Sara built agent modules (`agents/coder_agent.py`, `agents/prompts.py`)
- Sara ran tests, verified gates, pushed commits
- Sara designed prompts, analyzed LLM failures, proposed architecture

None of that makes Sara part of the runtime system. Sara is a **development-time tool**, not a **run-time component**.

The confusion could arise because Sara's memory file (`sara.md`) contains extensive context about the engine. But memory is Sara's workspace, not the engine's. The engine has never read `sara.md` and never should.

---

## 2. SHOULD SARA EXIST INSIDE THE ENGINE?

**Architectural argument: No. Sara should not exist inside the engine.**

### If Sara was removed tomorrow:

| Question | Answer |
|---|---|
| Could the engine still run? | **Yes.** The engine is FastAPI + PostgreSQL + local LLM. No import, no dependency, no reference to Sara in any source file. |
| Could local agents still execute? | **Yes.** `agents/orchestrator.py` calls `EngineClient` (HTTP to localhost:8000) and `OllamaLLM` (HTTP to localhost:11434). Neither depends on Sara. |
| Could governance still work? | **Yes.** Gates are in `api/gates.py`. Security is in `api/security.py`. Audit is in `api/audit.py`. All pure Python + PostgreSQL. No Sara. |
| Could the system still produce evidence? | **Yes.** CI evidence is recorded via `PATCH /mrps/{id}/evidence` with `X-Acting-As: ci:<pipeline>` + `X-CI-Token`. No Sara. |

### Is there any dependency on Sara?

**No.** I verified this by searching every Python file in the repository:

- `grep -r "sara" agents/ api/ tests/` — **zero hits** (excluding `.pyc` cache)
- No import of any Sara module
- No reference to Sara's memory, Sara's tools, or Sara's identity
- No environment variable referencing Sara
- No Docker service named Sara

**Sara is already architecturally external to the engine.** The current state is correct. The question is whether this separation is intentional or accidental. This document makes it intentional.

---

## 3. TRUST BOUNDARY

The correct separation:

### OUTSIDE the air-gapped boundary (development-time only)

| Component | Role | Access to engine |
|---|---|---|
| **Human (m.barani)** | Author, approver, gate-keeper | Direct API calls with `X-Acting-As: human:<name>` |
| **Sara** | Development assistant, architect, debugger | Source code access (read/write), Git access, docs |
| **Development tools** | IDE, Git, Docker, terminal | Filesystem, Git, Docker CLI |
| **Architecture discussions** | Design documents, reviews, reports | Documentation files |

### INSIDE the air-gapped boundary (run-time only)

| Component | Role | Network boundary |
|---|---|---|
| **FastAPI engine** (`api/`) | Governance, gates, audit, artifact chain | localhost:8000 |
| **PostgreSQL** | Source of truth for all artifacts | localhost:5433 |
| **Product Agent** | Drafts PRD, user stories, ACs | Calls engine API + Ollama |
| **Spec Agent** | Drafts YAML specs | Calls engine API + Ollama |
| **Coder Agent** | Writes code, runs tests, opens MRs | Calls engine API + Ollama + filesystem |
| **Reviewer Agent** | Reviews code (future) | Calls engine API + Ollama |
| **Test Agent** | Records evidence (LLM-free) | Calls engine API |
| **Security Agent** | Scans code (pattern-based) | Filesystem only |
| **Local LLM** (Ollama) | Content generation | localhost:11434 |
| **Redis** (if needed) | Cache/queue/state | localhost:6379 |
| **Qdrant** (if needed) | Vector store for RAG | localhost:6333 |

### Boundary rule

Everything inside the boundary must work with:
- No internet access
- No external API calls
- No cloud services
- No Sara
- No human approval for **automated steps** (human approval only at defined gates: spec validation, CRP resolution, merge decision)

Everything outside the boundary is development-time assistance only.

---

## 4. WHAT SHOULD BE DONE BY LOCAL LLMs?

### LLM Responsibility (probabilistic, content generation)

| Capability | Current status | Who does it |
|---|---|---|
| Requirement understanding | ✅ Built | Product Agent + Ollama |
| Specification generation | ✅ Built | Spec Agent + Ollama |
| Code generation | ✅ Built | Coder Agent + Ollama |
| Test creation | ✅ Built | Coder Agent + Ollama |
| Debugging / repair | ✅ Built | Coder Agent reflection loop |
| Explanation / documentation | ⚠️ Partial | Could be local LLM |
| Repair proposals | ✅ Built | Coder Agent reflection loop |
| Architecture suggestions | ❌ Not built | Future: local LLM |
| Code review opinions | ❌ Not built | Future: Reviewer Agent |
| Prompt improvement | ❌ Not built | Future: could be local LLM |

### Deterministic Software Responsibility (always correct, never probabilistic)

| Capability | Current status | Who does it |
|---|---|---|
| ID generation | ✅ Built | `api/ids.py` (atomic UPSERT) |
| Gate enforcement | ✅ Built | `api/gates.py` (pure functions) |
| Identity verification | ✅ Built | `api/security.py` (header check) |
| Audit logging | ✅ Built | `api/audit.py` (transactional) |
| Artifact state transitions | ✅ Built | Router code (SQLAlchemy) |
| Spec validation gate | ✅ Built | `api/gates.py` §3.5 |
| CRP merge gate | ✅ Built | `api/gates.py` §3.6.3 |
| MRP readiness gate | ✅ Built | `api/gates.py` §5.6.5 |
| Terminal state enforcement | ✅ Built | `api/gates.py` assert_run_patchable |
| Append-only audit protection | ✅ Built | `002_audit_lockdown.sql` triggers |
| Evidence recording | ✅ Built | CI token auth + PATCH endpoint |
| AC reference enforcement | ✅ Built | `agents/spec_agent.py` _enforce_ac_refs |

### The line

**LLM produces content. Deterministic code governs actions.**

The LLM says: "Here is a PRD."
The engine decides: Does this PRD have a valid ID? Is it linked to a project? Is the actor authorized?

The LLM says: "Here is code."
The engine decides: Is the spec validated? Are CRPs resolved? Is the MRP ready?

The LLM says: "Here is a test result."
The engine decides: Does this evidence satisfy the gate? Is the actor a CI pipeline?

---

## 5. WHAT SHOULD NEVER DEPEND ON AN LLM?

Everything that is currently deterministic must remain deterministic. **Never replace with LLM.**

| Category | Specific items | Why it must be deterministic |
|---|---|---|
| **Permissions** | `require_human_actor`, `require_ci_actor`, `require_any_actor` | Security must be binary: allowed or denied. No probabilistic permissions. |
| **State transitions** | `assert_run_patchable`, `no_open_high_or_critical_crp_blocks_merge` | State machines must be exact. An LLM might "almost" block a merge. |
| **Merge gates** | §5.6.5 readiness matrix (unit tests, integration, security scan, specs, blueprints, CRPs) | A merge gate that is "usually correct" is a security hole. |
| **Evidence validation** | pytest exit code interpretation, security scan results | Evidence is factual: pass or fail. No LLM opinion. |
| **Audit logs** | `record_audit()` in same transaction as artifact write | Audit must be atomic and append-only. Never LLM-decided. |
| **Security policies** | `SASE_API_TOKEN` perimeter, `SASE_CI_TOKEN` CI auth | Authentication is binary. No LLM judgment. |
| **Artifact integrity** | FK constraints, ID uniqueness, enum validation | Data integrity is a database concern, not an LLM concern. |
| **ID generation** | Atomic UPSERT..RETURNING on `id_counters` | IDs must be unique and sequential. LLM cannot guarantee this. |
| **Append-only enforcement** | PostgreSQL triggers on `audit_log` | Database-level protection, not application-level LLM opinion. |
| **Identity verification** | `X-Acting-As` header parsing, prefix matching | Identity is a string comparison. No LLM interpretation. |
| **Spec validation gate** | Human-only endpoint, header identity | A gate that an LLM could bypass is not a gate. |
| **CRP resolution** | VCR as single chokepoint, one resolution per CRP | Conflict resolution must be exact, not "mostly resolved." |

### The rule

**If a function raises HTTPException on violation, it must never call an LLM.**
**If a function writes to audit_log, it must never call an LLM.**
**If a function checks a permission, it must never call an LLM.**

---

## 6. IF YOU WERE DESIGNING YOURSELF OUT OF THE ENGINE

### What stays inside ai-swe-engine (air-gapped, autonomous)

```
ai-swe-engine/
├── api/                          # Governance engine (FastAPI)
│   ├── main.py                   # App entry, middleware, routers
│   ├── models.py                 # SQLAlchemy ORM
│   ├── schemas.py                # Pydantic validation
│   ├── gates.py                  # Hard gates (deterministic)
│   ├── security.py               # Identity verification (deterministic)
│   ├── ids.py                    # Atomic ID generation (deterministic)
│   ├── audit.py                  # Append-only audit (deterministic)
│   ├── database.py               # Engine/session setup
│   └── routers/                  # HTTP endpoints
├── agents/                       # LLM-powered agents
│   ├── config.py                 # Role definitions + allowlists
│   ├── engine_client.py          # HTTP client to api/
│   ├── llm.py                    # Ollama + template backends
│   ├── prompts.py                # Product/Spec prompts
│   ├── coder_prompts.py          # Coder prompts + repair
│   ├── product_agent.py          # PRD/story/AC generation
│   ├── spec_agent.py             # YAML spec generation
│   ├── coder_agent.py            # Code + test + reflection
│   └── orchestrator.py           # Pipeline entry point
├── migrations/                   # PostgreSQL schema
├── blueprints/                   # Architecture rules
├── tests/                        # Test suite
├── docker-compose.yml            # Postgres + API (+ Redis/Qdrant if needed)
└── .ai-engineering/              # Artifact storage
```

**Everything above works without Sara. Period.**

### What stays outside with Sara (development-time only)

| Capability | How Sara provides it |
|---|---|
| Architecture design | Reports like this one, design documents |
| Bug analysis | Reading source code, running tests, diagnosing failures |
| Prompt improvement | Reading agent outputs, proposing prompt changes |
| Code review | Reading diffs, identifying issues |
| Documentation | Writing README, FULL_DOCUMENTATION, design docs |
| Git operations | Commits, pushes, branch management |
| Infrastructure advice | Docker configuration, deployment guidance |
| Failure diagnosis | Reading logs, analyzing test failures |
| Performance analysis | Profiling, benchmarking suggestions |

### What capabilities transfer to local agents

| Capability | Current (Sara) | Future (local) |
|---|---|---|
| Prompt improvement | Sara reads outputs, rewrites prompts | Could be a local "prompt-tuner" agent that reads agent failures and adjusts prompts |
| Code review | Sara reads diffs, finds issues | Reviewer Agent (role defined in config.py, not yet implemented) |
| Test analysis | Sara runs tests, diagnoses failures | Could be a local "test-analyzer" agent |
| Architecture suggestions | Sara proposes designs | Could be a local "architect" agent (future) |

### Interfaces between Sara and the engine

| Interface | Direction | Purpose |
|---|---|---|
| Source code | Sara → engine | Sara reads/writes `.py` files during development |
| Git | Sara → engine | Sara commits and pushes changes |
| Documentation | Sara → engine | Sara writes `docs/`, `README.md` |
| Test results | Engine → Sara | Sara reads test output to diagnose issues |
| API responses | Engine → Sara | Sara calls endpoints to verify behavior |
| Agent outputs | Engine → Sara | Sara reads agent-generated artifacts for quality analysis |

**There is no runtime interface.** Sara does not call the engine during execution. The engine does not call Sara. They communicate only through the filesystem and Git during development.

---

## 7. FUTURE VISION

### Scenario: "Add OAuth authentication to this application." (Fully offline)

### What Sara does (development-time)

1. Reads the current codebase to understand the authentication model
2. Designs the OAuth integration architecture (token flow, endpoints, middleware)
3. Writes a design document or implementation plan
4. Reviews the spec agent's output for correctness
5. Reviews the coder agent's implementation for security
6. Suggests improvements to prompts if agents produce poor OAuth code
7. Updates documentation

**Sara does NOT:**
- Execute the OAuth implementation
- Deploy the changes
- Approve the merge
- Run the tests

### What ai-swe-engine does (run-time)

1. **Product Agent** receives the goal "Add OAuth authentication" via the orchestrator
2. **Product Agent** drafts a PRD, user stories, acceptance criteria
3. Engine records these artifacts with IDs, audit trail, linked to a project
4. **Spec Agent** converts the requirements into a YAML technical specification
5. Engine gates: spec must be human-validated before code-gen (§3.5)
6. **Human validates spec** via `POST /specs/{id}/validate`
7. **Coder Agent** generates OAuth code, writes to local workspace
8. **Coder Agent** runs tests (real pytest subprocess)
9. **Coder Agent** performs reflection if tests fail (bounded loop)
10. **Coder Agent** runs security scan (pattern-based, not LLM)
11. **Coder Agent** runs compile lint
12. **Coder Agent** commits with provenance
13. Engine records: Agent Run, MRP, CI evidence
14. If open questions exist: CRP raised (blocks merge)
15. **Human resolves CRP** via VCR, approves merge

### What the local LLM does

| Step | LLM action | Deterministic check |
|---|---|---|
| PRD generation | Drafts PRD text from goal description | Engine assigns ID, links to project |
| Story generation | Drafts user story in "As a...I want...so that..." form | Engine links to PRD |
| AC generation | Drafts acceptance criteria | Engine links to story |
| Spec generation | Drafts YAML specification | Engine stores, human validates |
| Code generation | Generates Python/Java code files | Engine gates §3.5, pytest subprocess |
| Test generation | Generates test files | pytest exit code = evidence |
| Repair generation | Proposes fixes when tests fail | Engine records each iteration |
| Commit message | Generates commit message | Git records it |

### What deterministic code does

| Function | Implementation | Never LLM |
|---|---|---|
| Gate §3.5 | `gates.spec_must_be_validated()` | ✅ |
| Gate §3.6.3 | `gates.no_open_high_or_critical_crp_blocks_merge()` | ✅ |
| Gate §5.6.5 | `gates.mrp_readiness_matrix()` | ✅ |
| Identity | `security.require_human_actor()` | ✅ |
| Audit | `audit.record_audit()` in same transaction | ✅ |
| ID generation | `ids.next_id()` atomic UPSERT | ✅ |
| Evidence recording | CI token + PATCH endpoint | ✅ |
| Terminal state | `gates.assert_run_patchable()` | ✅ |
| Append-only | PostgreSQL triggers on `audit_log` | ✅ |

---

## 8. FINAL ARCHITECTURAL DECISION

**"Sara is a development-time assistant — an external tool that helps the human developer design, build, debug, and improve the ai-swe-engine, but is never part of the engine's runtime."**

**"ai-swe-engine is a fully air-gapped autonomous software engineering platform that operates independently using local LLMs, deterministic governance, and human gates — requiring no external assistant, no cloud service, and no internet connection."**

**"The relationship between them is one-directional during development: Sara writes code, documentation, and architecture into the engine. At runtime, the engine is completely independent — it has never heard of Sara, never imports Sara, and never needs Sara to function."**

---

## Summary

| Question | Answer |
|---|---|
| Is Sara part of the engine? | **No.** Sara is external. |
| Should Sara exist inside the engine? | **No.** The engine must be self-contained. |
| Is the trust boundary correct? | **Yes.** Sara outside, engine inside. |
| What does the LLM do? | Content generation (PRDs, specs, code, tests, repairs). |
| What must never depend on LLM? | Gates, permissions, audit, identity, state transitions, evidence validation. |
| How to design Sara out? | She already is out. Formalize the boundary. |
| Future vision? | Sara designs, engine executes, LLM generates, deterministic code governs. |

**The engine is valuable without Sara. Sara is valuable to the human building the engine. They do not need each other at runtime.**

---

*End of architectural self-assessment.*
