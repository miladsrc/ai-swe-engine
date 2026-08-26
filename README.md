# SASE Engine — Offline AI Development Platform

An autonomous software engineering platform that runs entirely offline using local
language models (Ollama/Qwen). Built against the SASE (Structured Agentic
Software Engineering) framework, it implements a governed development chain where
every code change is traceable, auditable, and requires human approval at
critical gates.

## What it does

A local LLM (Qwen 2.5 Coder 7B on CPU) drafts requirements, writes real code,
runs its own tests, and opens merge requests — but **cannot ship a single line
without human approval**. Every action is recorded, every gate is enforced in
code, and the full chain from idea to merged code is reconstructable.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        HUMAN DECISIONS                          │
│  (validate specs, resolve CRPs via VCR, approve merges)         │
└─────────────┬───────────────────────────────────────────────────┘
              │ X-Acting-As: human:<name>
              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   SASE TRACEABILITY ENGINE                      │
│  FastAPI + PostgreSQL · api/                                     │
│  Hard gates in api/gates.py (§3.5, §3.6.3, §5.6.5)            │
│  Append-only audit log · Identity-guarded endpoints              │
└─────────────┬───────────────────────────────────────────────────┘
              │ API calls (enforced allowlists per role)
              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     AGENT LAYER (agents/)                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ Product  │ │   Spec   │ │  Coder   │ │Reviewer/ │          │
│  │  Agent   │ │  Agent   │ │  Agent   │ │Reflection│          │
│  │ draft    │ │ YAML     │ │ write    │ │ (planned)│          │
│  │ PRD/US/AC│ │ spec     │ │ code+tests│ │          │          │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────────┘          │
│       │            │            │                                │
│       │            │     ┌──────┴──────┐                        │
│       │            │     │  REAL EVIDENCE │                      │
│       │            │     │ pytest exit code │                    │
│       │            │     │ security scan    │                    │
│       │            │     │ compile lint     │                    │
│       │            │     └────────────────┘                      │
└───────┼────────────┼────────────┼────────────────────────────────┘
        │            │            │
        ▼            ▼            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LOCAL GIT WORKSPACE                           │
│  IdeaProjects/<project>/                                         │
│  Real .py files · Real pytest · Real git commits                │
│  Committed with run_id + spec_id provenance                     │
└─────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    LOCAL LLM (OFFLINE)                           │
│  Ollama · qwen2.5-coder:7b q4 · CPU-only                       │
│  localhost:11434 · No internet required                         │
└─────────────────────────────────────────────────────────────────┘
```

## What's built

### Traceability Engine (`api/`)
- **Postgres schema** (`migrations/001_init.sql`) for every artifact: Project, PRD, User Story, Acceptance Criteria, Spec, Blueprint, Agent Run, CRP, MRP, VCR, audit log
- **Hard gates in code** (`api/gates.py`), not just documentation:
  - Specs cannot enter code-gen until human-validated (§3.5)
  - MRPs cannot merge while High/Critical CRPs are open (§3.6.3)
  - `POST /mrps/{id}/check-ready` implements §5.6.5 gate table exactly
- **Identity-guarded endpoints** (`api/security.py`):
  - `/specs/{id}/validate`, `/mrps/{id}/human-decision`, VCR endpoints require `X-Acting-As: human:<name>`
  - Evidence endpoints require `X-Acting-As: ci:<pipeline>` + optional `X-CI-Token`
- **Append-only audit log** with REVOKE protection (triggers in `002_audit_lockdown.sql`)
- **Optional perimeter auth** (`SASE_API_TOKEN` middleware)

### Agent Layer (`agents/`)
- **6 role-defined agents** with separate identities and strict allowlists:
  - `agent:product` — drafts PRD, user stories, acceptance criteria
  - `agent:spec` — converts story+ACs into YAML technical spec
  - `agent:coder` — writes real code, runs tests, opens MRs, raises CRPs
  - `agent:reviewer` / `agent:reflection` — defined but not yet active
  - `ci:test-runner` — LLM-free, records real pytest evidence
- **Prompt contracts** (`agents/prompts.py`, `agents/coder_prompts.py`):
  - Explicit output formats (PRD sections, story form, YAML schema)
  - WORKED EXAMPLES for small models
  - ENGINEERING RULES (deterministic tests, subprocess invocation, env-overridable storage)
- **Reflection loop**: bounded (configurable `max_repairs`), evidence-driven (pytest output fed back), self-check checklists in repair prompts
- **Tolerant parsing**: handles backticked YAML from LLMs, code-fence stripping, fabricated AC ref enforcement

### Local LLM Integration (`agents/llm.py`)
- **Ollama backend**: `OllamaLLM` calls local `localhost:11434`
- **Template fallback**: `TemplateLLM` for deterministic offline testing
- **Auto-selection**: `pick_backend()` prefers Ollama, falls back to templates
- **No governance actions**: LLM only produces content; IDs, gates, audit are server-side

### Coder Agent (`agents/coder_agent.py`)
The full autonomous development loop:

```
validated spec → LLM generates code files → write to local git repo →
REAL pytest subprocess → if fails: reflection loop (up to N repairs) →
security scan (pattern-based, no LLM opinion) → compileall lint →
git commit with provenance → Agent Run Record → MRP → CI evidence →
if spec has open_questions: raise HIGH CRP (blocks merge) →
HUMAN GATES: VCR resolve + merge decision
```

Key properties:
- **Real evidence**: pytest exit codes, not LLM judgment
- **Provenance**: every commit carries run_id + spec_id
- **Immutability**: terminal agent runs cannot be patched (§3.7.8)
- **Workspace sandbox**: refuses to write outside the project directory

## Quick start

### Prerequisites
- Docker Desktop (for Postgres + API)
- Ollama installed locally (for LLM inference)
- Python 3.12+ with pytest

### 1. Start the stack
```bash
docker compose up -d
# Postgres on localhost:5433, API on localhost:8000
# Migrations auto-apply on first boot
```

### 2. Install and pull the model
```bash
# Install Ollama (Windows)
winget install Ollama.Ollama

# Pull the coding model (4.36GB, runs on CPU)
ollama pull qwen2.5-coder:7b
```

### 3. Run the full pipeline
```bash
# Full chain: PRD → story → AC → spec (offline templates)
python -m agents.orchestrator --offline

# Full chain via Qwen (requires Ollama running)
python -m agents.orchestrator --online

# Code phase only (requires validated spec)
python -m agents.orchestrator --online --code --spec SPEC-TODO-CORE-R4

# Regenerate only the spec (requires prior full run)
python -m agents.orchestrator --online --spec-only --name core-v2
```

### 4. Human gates (you must run these)

**Preferred — token flow (required once `SASE_REQUIRE_HUMAN_TOKEN=1`):**
```bash
# Login once; the token is shown exactly once
curl -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"<you>","password":"..."}'

# Validate a spec (Gate 1) — token identity is authoritative
curl -X POST localhost:8000/specs/<spec-id>/validate \
  -H 'Authorization: Bearer <token>' -d '{}'

# Resolve a CRP via VCR
curl -X POST localhost:8000/vcrs \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  -d '{"related_artifact_type":"CRP","related_artifact_id":"<crp-id>",...}'

# Approve a merge
curl -X POST localhost:8000/mrps/<mrp-id>/human-decision \
  -H 'Authorization: Bearer <token>' \
  -d '{"decision":"approved"}'
```

**Legacy header flow** (still works while `SASE_REQUIRE_HUMAN_TOKEN` is unset):
```bash
curl -X POST localhost:8000/specs/<spec-id>/validate \
  -H 'X-Acting-As: human:<your-name>' -d '{}'
```

## Proving the chain works — a manual walkthrough

```bash
# 1. Create a project
curl -X POST localhost:8000/projects \
  -H 'Content-Type: application/json' \
  -d '{"id":"demo-app","name":"Demo App","stack":"python-cli"}'

# 2. Create a PRD
curl -X POST localhost:8000/prds \
  -H 'Content-Type: application/json' \
  -d '{"project_id":"demo-app","domain":"TODO","title":"Todo CLI",
       "body_ref":"A minimal command-line todo app","created_by":"human:m.barani"}'

# 3. Create a User Story
curl -X POST localhost:8000/user-stories \
  -H 'Content-Type: application/json' \
  -d '{"prd_id":"PRD-TODO-001","domain":"TODO","body_ref":"As a user, I want to add and list tasks."}'

# 4. Create an Acceptance Criterion
curl -X POST localhost:8000/acceptance-criteria \
  -H 'Content-Type: application/json' \
  -d '{"user_story_id":"US-TODO-001","body_ref":"- todo add \"text\" persists and prints id"}'

# 5. Create a Spec
curl -X POST localhost:8000/specs \
  -H 'Content-Type: application/json' \
  -d '{"project_id":"demo-app","user_story_id":"US-TODO-001","domain":"TODO",
       "name":"core","body_ref":"artifact: todo-cli\nbehavior:\n  add: ..."}'

# 6. Try starting code-gen BEFORE validation — expect 409 (gate working)
curl -X POST localhost:8000/agent-runs \
  -H 'Content-Type: application/json' \
  -d '{"project_id":"demo-app","agent_role":"coder_agent","task_type":"code_generation",
       "model_name":"qwen2.5-coder:7b","model_short":"QW","spec_id":"SPEC-TODO-CORE"}'
# -> HTTP 409, gate blocks premature code-gen

# 7. Validate the spec (human-only; token flow shown — see §4 above)
curl -X POST localhost:8000/specs/SPEC-TODO-CORE/validate \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token-from-/auth/login>' -d '{}'

# 8. Now code-gen succeeds
curl -X POST localhost:8000/agent-runs \
  -H 'Content-Type: application/json' \
  -d '{"project_id":"demo-app","agent_role":"coder_agent","task_type":"code_generation",
       "model_name":"qwen2.5-coder:7b","model_short":"QW","spec_id":"SPEC-TODO-CORE"}'
# -> note run id, e.g. RUN-QW-2026-00001

# 9. Create MRP + check readiness
curl -X POST localhost:8000/mrps \
  -H 'Content-Type: application/json' \
  -d '{"project_id":"demo-app","pull_request_number":1,"branch_name":"agent/todo-core",
       "created_by_agent_run":"RUN-QW-2026-00001","prd_id":"PRD-TODO-001",
       "spec_ids":["SPEC-TODO-CORE"],"blueprint_id":"BP-PYTHON-CLI-001",
       "blueprint_version":"v1.0"}'

curl -X POST localhost:8000/mrps/MRP-PR-1/check-ready
# -> expect ready: false (missing evidence)

# 10. Record CI evidence (token-authenticated)
curl -X PATCH localhost:8000/mrps/MRP-PR-1/evidence \
  -H 'Content-Type: application/json' \
  -H 'X-Acting-As: ci:test-runner' \
  -H 'X-CI-Token: dev-ci-token-change-me' \
  -d '{"unit_tests_status":"passed","security_scan_status":"passed"}'

# 11. Approve merge (human-only)
curl -X POST localhost:8000/mrps/MRP-PR-1/human-decision \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <token-from-/auth/login>' \
  -d '{"decision":"approved"}'

# 12. Verify full traceability
curl localhost:8000/traceability/chain/MRP-PR-1
# -> fully_traceable: true
```

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `postgresql+psycopg2://sase:sase@postgres:5432/sase` | Postgres connection (docker-compose sets this) |
| `SASE_API_TOKEN` | _(unset)_ | Optional perimeter auth. When set, every request needs `X-API-Token` header |
| `SASE_CI_TOKEN` | **_(required for evidence)_** | Shared secret for CI evidence identity. Evidence endpoints FAIL CLOSED (HTTP 503) when unset — docker-compose provides the dev value `dev-ci-token-change-me` |
| `SASE_OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint used by the agent layer (P1) |
| `SASE_OLLAMA_MODEL` | `qwen2.5-coder:7b` | Default local model when a role doesn't specify one (P1) |
| `SASE_MODEL_VERSION` | _(unset)_ | Optional version tag recorded in AgentRun provenance (P2) |
| `SASE_ORPHAN_RUN_HOURS` | `24` | Runs still 'running' after this many hours are reaped to 'failed' at API startup (P4) |
| `SASE_REQUIRE_HUMAN_TOKEN` | _(unset)_ | Phase 2: when set, human gates reject `X-Acting-As` and REQUIRE a bearer token from `POST /auth/login`. Unset = legacy header path still open |
| `SASE_TOKEN_TTL_HOURS` | `72` | Lifetime of issued login tokens (`0` = no expiry) |
| `TODO_STORE` | `todos.json` | Data file path for todo-cli (agent test override: `TODO_STORE=/tmp/test.json`) |
| `CODER_MAX_REPAIRS` | `5` | Max reflection loop iterations before marking run as failed |

## Human authentication (Phase 2)

```bash
# 1. Apply the migration (existing volumes only; fresh volumes get it via initdb.d):
docker exec -i ai-swe-engine-postgres-1 psql -U sase -d sase < migrations/003_users.sql

# 2. Create a user (prompts for password; or set SASE_USER_PASSWORD for scripted runs):
.venv/bin/python scripts/create_user.py m.barani "Milad Barani"    # (Windows: python scripts\create_user.py ...)

# 3. Log in — the token is shown ONCE:
curl -X POST localhost:8000/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"m.barani","password":"..."}'

# 4. Use it on any human gate instead of / alongside X-Acting-As:
curl -X POST localhost:8000/specs/<id>/validate \
  -H 'Authorization: Bearer <token>' -H 'Content-Type: application/json' -d '{}'
```

- Token identity is **authoritative**: when a valid bearer is presented, any
  `X-Acting-As` header value is ignored — a logged-in human cannot be
  impersonated via headers.
- Only `sha256(token)` is stored; passwords use PBKDF2-HMAC-SHA256 (200k iters).
- Every login attempt is audited (`login_success` / `login_failed`).
- Until `SASE_REQUIRE_HUMAN_TOKEN` is set, the legacy `X-Acting-As` path keeps
  working for local dev and existing agent tooling.

## Governance Dashboard (UI)

> **Roadmap note:** the fuller Human Operating Layer (roles, assignment routing,
> per-user My Tasks, notifications, team management) is **deferred to Phase 9 —
> Platform UI / Human Operations Layer** (owner decision 2026-08-26). Concepts
> preserved in `docs/HUMAN_OPERATING_LAYER_PROPOSAL.md`.

Open **http://localhost:8000/ui/** after `docker compose up`. Log in with your
engine account (`scripts/create_user.py` creates users; tokens from
`/auth/login`). Black & gold = authority/decisions; blue & white = evidence.

Screens: personal dashboard · Approval Center (spec validations, CRPs, MRPs)
· decision detail with "acting as <you>" confirmation · Agent Runs · Evidence
chain viewer (Requirement→Spec→Run→MRP→CRP→VCR) · filterable Audit Logs ·
Projects · Agent Console (instructions recorded to the audit trail; execution
remains CLI-driven) · Settings.

The UI is a pure client layer: it owns no state and grants no rights — every
decision goes through the same gated backend endpoints, under YOUR token
identity. It never sends X-Acting-As. Read-only data endpoints require an
authenticated actor (`require_authenticated_actor`: bearer preferred, legacy
header until strict mode).

## Project structure

```
ai-swe-engine/
├── api/                        # Traceability engine (FastAPI)
│   ├── main.py                 # App entry, routers, perimeter middleware
│   ├── models.py               # SQLAlchemy models
│   ├── schemas.py              # Pydantic request/response schemas
│   ├── gates.py                # Hard gates (§3.5, §3.6.3, §5.6.5)
│   ├── security.py             # Identity-guarded endpoints
│   ├── ids.py                  # Deterministic ID generation
│   ├── audit.py                # Append-only audit log
│   ├── database.py             # Engine/session setup
│   └── routers/                # Endpoint implementations
│       ├── projects.py
│       ├── requirements.py     # PRDs, stories, ACs, specs
│       ├── agent_runs.py       # Agent run records + PATCH
│       ├── crp.py              # Conflict Resolution Packages
│       ├── mrp.py              # Merge Request Packages
│       ├── vcr.py              # Version Control Resolutions
│       └── traceability.py     # Chain reconstruction
├── agents/                     # LLM-powered agent layer
│   ├── config.py               # 6 role definitions + allowlists
│   ├── engine_client.py        # Identity-aware HTTP client
│   ├── llm.py                  # Ollama + template backends
│   ├── prompts.py              # Product/Spec agent prompts
│   ├── coder_prompts.py        # Coder agent prompts + repair
│   ├── product_agent.py        # PRD/story/AC generation
│   ├── spec_agent.py           # YAML spec generation + AC enforcement
│   ├── coder_agent.py          # Full coding loop + reflection
│   └── orchestrator.py         # Pipeline entry point (--online/--offline/--code)
├── migrations/
│   ├── 001_init.sql            # Full schema
│   └── 002_audit_lockdown.sql  # REVOKE protection on audit_log
├── blueprints/                 # Seed blueprints (org-wide + stack-specific)
├── tests/
│   ├── test_gates_unit.py      # Gate logic (DB-free)
│   ├── test_agents_unit.py     # Agent role separation
│   ├── test_coder_unit.py      # Coder parsing + security scan
│   └── test_traceability_chain.py  # Full E2E (requires running stack)
├── docker-compose.yml          # Postgres + API containers
└── README.md                   # This file
```

## What's NOT here yet

- **Reviewer / Reflection agents**: roles defined in `config.py` with allowlists, but no implementation. The coder's built-in reflection loop handles the immediate need; a separate reviewer agent is the next step.
- **RAG pipeline**: no vector store, chunking, or reranking. Blueprints are read as plain YAML.
- **OIDC/mTLS**: `X-Acting-As` is a seam, not real authn. Production identity comes later.
- **Alembic migrations**: schema changes are manual SQL in `migrations/`.
- **Agent-run terminal-state guard in CRP router**: `POST /crps` sets `run.status = "blocked"` by direct assignment, bypassing `assert_run_patchable`. Known engine bug, documented in code.

## Testing

```bash
# Unit tests (no stack required)
python -m pytest tests/ -q --ignore=tests/test_traceability_chain.py

# Full E2E (requires docker compose up)
python -m pytest tests/test_traceability_chain.py -v
```

## License

Internal use — Sahba platform / SIDG.
