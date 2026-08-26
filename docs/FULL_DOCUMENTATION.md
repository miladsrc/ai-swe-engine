# SASE Engine — Full Project Documentation

> **Project:** ai-swe-engine · **Version:** 0.1.0 · **Status:** Phase 1 (traceability backbone)
> **Generated:** 2026-08-24 by Sara (supervisor agent), from a full code read + independent review-agent analysis.
> **Framework:** SASE — Structured Agentic Software Engineering.

---

## Table of Contents

1. [Mission & Scope](#1-mission--scope)
2. [Architecture](#2-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Data Model](#4-data-model)
5. [ID Scheme](#5-id-scheme)
6. [API Reference](#6-api-reference)
7. [Hard Gates & Security](#7-hard-gates--security)
8. [Audit & Traceability](#8-audit--traceability)
9. [Blueprints](#9-blueprints)
10. [Configuration & Deployment](#10-configuration--deployment)
11. [Testing](#11-testing)
12. [Change Log (2026-08-24 session)](#12-change-log-2026-08-24-session)
13. [Risk Register (independent review findings)](#13-risk-register-independent-review-findings)
14. [Operational Readiness](#14-operational-readiness)
15. [Roadmap](#15-roadmap)

---

## 1. Mission & Scope

This service is the **governance and traceability backbone** for an AI Software
Engineering Engine built on the SASE framework. Its single responsibility:

> **Every AI-generated artifact must be traceable end-to-end — from the PRD that
> motivated it, through the Spec/Blueprint/Prompt/RAG context the agent used, to
> the human decisions that authorized it — and the paper's hard rules must be
> enforced in code, not documentation.**

**Deliberately NOT in scope for Phase 1:**

| Excluded | Why |
|---|---|
| LLM calls (Ollama/Qwen/DeepSeek) | Agents don't exist yet; the contract comes first |
| Structured RAG / vector store | Roadmap step 4 |
| Product/Spec/Coder/Reviewer agents | They will call this API once built |
| Blueprint authoring beyond seeds | Approval is a human act, not pre-filled |

This is roadmap **step 2 of 5+**. Nothing else should be built until this layer
proves an end-to-end chain works (it does — see §11).

---

## 2. Architecture

```
                        ┌─────────────────────────────────────────────┐
                        │              ARTIFACT CHAIN                 │
                        └─────────────────────────────────────────────┘

  PRD ──< User Story ──< Acceptance Criteria
   │            │
   │            └──< Spec ──(human validation gate §3.5)──┐
   │                                                      ▼
   └──────────────────────────────────────► Agent Run (provenance record)
                                              │
                              ambiguity? ─────┤
                                              ▼
                                     CRP (Consultation Request Pack)
                                              │ high/critical ⇒ run BLOCKED
                                              ▼
                                     VCR (Version Controlled Resolution)
                                        — ONLY path to resolve a CRP —
                                              │
                                              ▼
                       MRP (Merge-Readiness Pack) ◄── evidence from CI
                                              │
                                   check-ready gate (§5.6.5)
                                              │
                                              ▼
                                  Human Decision → Merge authorization

                        ┌─────────────────────────────────────────────┐
                        │               SERVICE LAYERS                │
                        └─────────────────────────────────────────────┘

  FastAPI app (api/main.py, 12 routes)
      ├── routers/        HTTP surface, one module per aggregate
      ├── security.py     require_human_actor — identity guard dependency
      ├── gates.py        pure decision functions that RAISE on violation
      ├── audit.py        record_audit() — same-transaction audit entries
      ├── ids.py          atomic human-readable ID generation
      ├── models.py       SQLAlchemy 2 ORM (mirrors DDL exactly)
      └── database.py     engine/sessionmaker, DATABASE_URL-driven
                    │
                    ▼
              PostgreSQL 16 (migrations/001_init.sql, auto-applied on first boot)
```

**Key architectural decisions:**

1. **Gates are enforced at the point of action**, not at artifact creation:
   the §3.5 check runs when a code-gen Agent Run is *requested*; the CRP gate
   runs when merge *approval* is attempted.
2. **Single resolution chokepoint**: `POST /vcrs` is the only code path that
   transitions a CRP to `resolved`. One VCR per related artifact (409 on duplicate).
3. **Transactional audit**: `record_audit()` adds the audit row inside the same
   DB transaction as the artifact write — an audit entry can never exist without
   its artifact or vice versa (`audit.py`).
4. **Dual source of truth by design**: Postgres holds *relationships* between
   artifacts (queryable, enforceable); `.ai-engineering/` files hold the human-
   readable *content* of each artifact, linked via `body_ref`.

---

## 3. Technology Stack

| Component | Version | Role |
|---|---|---|
| Python | 3.12 | Runtime |
| FastAPI | 0.115.0 | HTTP framework |
| uvicorn[standard] | 0.30.6 | ASGI server (port 8000) |
| SQLAlchemy | 2.0.35 | ORM |
| Pydantic | 2.9.2 | Request/response validation |
| PostgreSQL | 16 | Source of truth (psycopg2-binary 2.9.9) |
| pytest / httpx | 8.3.3 / 0.27.2 | Testing |
| Docker Compose | 3.9 schema | Local orchestration |

---

## 4. Data Model

All tables defined in `migrations/001_init.sql`; mirrored 1:1 by `api/models.py`.

### Enums
- `artifact_confidence`: `human_authored | inferred | confirmed`
- `crp_severity`: `low | medium | high | critical`
- `crp_status`: `open | resolved | blocking`
- `mrp_status`: `draft | ready_for_ai_review | ready_for_human_review | needs_revision | blocked_by_consultation | approved | rejected`
- `agent_role`: `product_agent | spec_agent | coder_agent | reviewer_agent | security_agent | legacy_discovery_agent`

### Tables

| Table | PK | Purpose / notable columns |
|---|---|---|
| `id_counters` | key | Atomic sequence counters behind all IDs (UPSERT..RETURNING) |
| `projects` | id | Unit owning its RAG/Blueprint scope. `stack`, `is_legacy` |
| `prds` | id | Requirement root. `body_ref`, `confidence`, `created_by` (`human:`/`agent:` prefix convention) |
| `user_stories` | id | FK → prds. `confidence` |
| `acceptance_criteria` | id | FK → user_stories |
| `specs` | id | FK → projects, optional user_stories. **`human_validated` hard gate flag** + who/when |
| `blueprints` | (id, version) | Versioned architecture rules. `scope`: `org` \| `project:<id>` \| `stack:<stack>` |
| `prompts` | (id, version) | Prompt versioning — a prompt change shifts output as much as a model change (§3.7.4) |
| `agent_runs` | id | Full provenance: agent_role, task_type, model/provider/runtime/temp/context-window, prompt_id+version (FK), system/user prompt hashes, RAG flags (enabled, doc ids, query hash, index version), reflection_iterations, tools_used[], generated_files[], commit_hash, status lifecycle |
| `crps` | id | Blocking issue + context_summary JSONB + options_considered + agent_recommendation + required_decision + required_role + default_policy (`block_generation`) |
| `vcrs` | id | Decision record: decision_status, selected_option, rationale, decided_by/role, update_* flags per artifact type, required_updates JSONB, `promoted_to_org_memory` curation gate |
| `mrps` | id | Per-PR readiness: PR ref, branch, commit, created_by_agent_run, requirement ID arrays, blueprint ref, per-check evidence fields (unit/integration/e2e tests, coverage %, lint, static analysis, complexity, security scan, dep scan), ai_review_status+notes, open_crp_ids[], status, human_reviewer |
| `audit_log` | bigserial | Append-only: actor_type (`agent|human|system`), actor_id, action, artifact ref, context JSONB, tools_used, result, human_decision |

Indexes: `agent_runs(project_id)`, `crps(status, severity)`, `mrps(status)`,
`audit_log(artifact_type, artifact_id)`.

---

## 5. ID Scheme

Human-readable, greppable IDs generated atomically in `api/ids.py` via a single
`INSERT .. ON CONFLICT DO UPDATE .. RETURNING value` against `id_counters`
(row-locked per statement — concurrency-safe).

| Pattern | Example |
|---|---|
| `PRD-<DOMAIN>-<seq>` | PRD-AUTH-001 |
| `US-<DOMAIN>-<seq>` | US-AUTH-003 |
| `AC-<us-id>-<seq>` | AC-AUTH-003-01 |
| `SPEC-<DOMAIN>-<NAME>` | SPEC-AUTH-SESSION-REFRESH |
| `BP-<LAYER>-<seq>` | BP-SPRINGBOOT-001 |
| `RUN-<MODEL>-<year>-<seq>` | RUN-DS-2026-00045 |
| `CRP-<DOMAIN>-<year>-<seq>` | CRP-AUTH-2026-004 |
| `MRP-PR-<n>` | MRP-PR-145 |
| `VCR-<related-artifact-id>` | VCR-CRP-AUTH-2026-004 |

Deliberate property: an engineer can grep any domain prefix across the whole
`.ai-engineering/` tree and the database to find every touching artifact.

Actor convention everywhere: `human:<name>` vs `agent:<role>` prefixes.

---

## 6. API Reference

Base URL `http://localhost:8000` · Interactive docs at `/docs`.
🔒 = human gate: requires `Authorization: Bearer <token>` (Phase 2 — authoritative) or legacy `X-Acting-As: human:<name>` until `SASE_REQUIRE_HUMAN_TOKEN` is set (401 if missing, 403 if not human).

### Projects — `api/routers/projects.py`
| Method/Path | Description |
|---|---|
| `POST /projects` | Create project (409 if exists). Body: `{id, name, stack, is_legacy}` |
| `GET /projects` | List all |
| `GET /projects/{id}` | Fetch one (404) |

### Requirements — `api/routers/requirements.py`
| Method/Path | Description |
|---|---|
| `POST /prds` | Create PRD under a project; auto-ID from `domain` |
| `GET /prds/{id}` | Fetch PRD |
| `POST /user-stories` | Attach user story to PRD |
| `POST /acceptance-criteria` | Attach AC to user story |
| `POST /specs` | Create spec (409 on duplicate ID) |
| `GET /specs/{id}` | Fetch spec incl. validation state |
| `POST /specs/{id}/validate` 🔒 | **The only path** setting `human_validated=True`. Validator = header identity |

### Agent Runs — `api/routers/agent_runs.py`
| Method/Path | Description |
|---|---|
| `POST /agent-runs` | Start run. If `task_type=code_generation` + `spec_id` → §3.5 gate fires (409 unless validated) |
| `PATCH /agent-runs/{id}` | Update status/tools/files/commit/mrp; terminal statuses stamp `finished_at` |
| `GET /agent-runs/{id}` | Fetch provenance record |

### CRPs — `api/routers/crp.py`
| Method/Path | Description |
|---|---|
| `POST /crps` | Raise consultation request. Severity validated (422 otherwise). High/critical ⇒ referenced Agent Run set to `blocked` |
| `GET /crps?status=open` | List, ordered critical→low (CASE ordering) then oldest first |
| `GET /crps/{id}` | Fetch |

### MRPs — `api/routers/mrp.py`
| Method/Path | Description |
|---|---|
| `POST /mrps` | Create pack for a PR number (409 dup). Auto-attaches currently-open CRPs tied to its spec_ids |
| `PATCH /mrps/{id}/evidence` | CI/scanners post incremental check results |
| `POST /mrps/{id}/check-ready` | Evaluates §5.6.5 gate → flips status to `ready_for_human_review` or `needs_revision`, returns exact blocking reasons |
| `POST /mrps/{id}/human-decision` 🔒 | Records approve/reject/needs_revision. Approve re-runs CRP gate + readiness gate (409 with reasons) |
| `GET /mrps/{id}` | Fetch |

### VCRs — `api/routers/vcr.py`
| Method/Path | Description |
|---|---|
| `POST /vcrs` 🔒 | Record human decision. If related artifact is a CRP → closes it (only resolution path). 422 bad type, 404 missing, 409 duplicate resolution |
| `POST /vcrs/{id}/promote` 🔒 | Curation gate (§4): explicit human act to promote into Org memory |
| `GET /vcrs/{id}` | Fetch |

### Traceability — `api/routers/traceability.py`
| Method/Path | Description |
|---|---|
| `GET /traceability/chain/{mrp_id}` | Reconstructs MRP → Specs → PRD → Agent Run → CRPs → VCRs; returns `fully_traceable: bool` |
| `GET /traceability/audit/{type}/{id}` | Ordered action history for one artifact |

### Health
| Method/Path | Description |
|---|---|
| `GET /health` | Liveness (does not ping DB — see Risk Register L6) |

---

## 7. Hard Gates & Security

Implemented in `api/gates.py` + `api/security.py` — functions that raise
HTTPException, "not documentation someone might skip."

| # | Gate | Enforcement point | Failure |
|---|---|---|---|
| G1 | Spec must be human-validated before code-gen (§3.5) | `POST /agent-runs` when task_type=code_generation | 409 |
| G2 | No open High/Critical CRP may block merge (§3.6.3, §3.7.8) | MRP human-decision approval | 409 |
| G3 | MRP readiness table (§5.6.5): unit tests passed, integration passed/NA, security scan passed, ≥1 Spec, Blueprint version present, no open CRPs, not rejected | `POST /{id}/check-ready` + approval | reasons list / 409 |
| G4 | Generated code needs existing Agent Run (§3.7.8) | `gates.agent_run_must_exist_for_generated_code` | 409 |
| G5 | Human-only endpoints verify identity via `Authorization: Bearer` (authoritative, Phase 2) or legacy `X-Acting-As: human:` prefix until `SASE_REQUIRE_HUMAN_TOKEN` is set | validate-spec, human-decision, both VCR writes | 401 / 403 |
| G6 | High/Critical CRP blocks its referencing Agent Run (`status=blocked`) | `POST /crps` | state change |

**Identity model caveat (updated by Phase 2):** real authn now EXISTS —
`POST /auth/login` issues bearer tokens and a valid token is the
authoritative human identity at every G5 gate. The legacy `X-Acting-As`
prefix path remains open only while `SASE_REQUIRE_HUMAN_TOKEN` is unset;
setting that env var makes token auth mandatory (fail-closed). Agents are
unaffected: they act under `agent:`/`ci:` identities on non-human
endpoints and cannot obtain tokens.

### Token-flow migration status (2026-08-26 review)

| Component | Status |
|---|---|
| Server human gates (G5) | ✅ accept Bearer (authoritative) |
| Orchestrator printed instructions | ✅ print both flows (`human_curl_auth`) |
| SpringBoot agent printed instructions | ✅ same |
| EngineClient | ✅ optional `bearer_token=` + `SASE_HUMAN_TOKEN` env |
| Agent roles (`agent:*`, `ci:*`) | N/A — no migration needed (never call human gates) |
| Live E2E suite | ✅ **token-first** (`_human_auth`: real login when `SASE_LIVE_*` set; legacy fallback only credential-less) |
| Gate proof trio | ✅ live test proves valid-token-passes / invalid-token-401 / spoofed-header-loses (audit-verified) |
| Docs (README quickstart/walkthrough) | ✅ token flow shown as preferred |
| Remaining before flag flip | owner go-ahead only (see blockers below) |

**Remaining `X-Acting-As` usages after this migration:** (1) legacy fallback
in `_human_auth` — dead code once the flag flips; (2) negative gate tests
proving agent/anonymous identities are REJECTED (must keep); (3) historical
change-log sections (immutable history). No positive human action anywhere
depends on a forged identity string anymore.

**Blockers before enabling `SASE_REQUIRE_HUMAN_TOKEN=1`:** none technical.
Owner decisions: provide `SASE_LIVE_*` credentials wherever the E2E runs,
and give explicit go-ahead.

### Hardening additions (2026-08-26 batch — P1–P8, evolutionary)

- **CI evidence fail-closed (P3):** `require_ci_actor` returns **503 when
  `SASE_CI_TOKEN` is unset** — an unconfigured deployment can no longer
  accept machine evidence silently. Token comparison is constant-time
  (`hmac.compare_digest`), as is the perimeter middleware's. No hardcoded
  fallback tokens exist anywhere; docker-compose supplies a dev value.
- **LLM transport (P1):** Ollama host/model come from env
  (`SASE_OLLAMA_HOST`, `SASE_OLLAMA_MODEL`, defaults unchanged);
  transient failures (URLError / HTTP 5xx) retry up to 2× with linear
  backoff; HTTP 4xx fails immediately. The LLM abstraction is unchanged.
- **AgentRun provenance (P2):** runs now record `model_version`,
  `prompt_id`, `prompt_version`, `system_prompt_hash` (sha256 prefix of
  the exact system prompt) — previously dead columns, no schema change.
- **Orphan-run reaper (P4):** on API startup, runs still `running` older
  than `SASE_ORPHAN_RUN_HOURS` (default 24h) are marked `failed` by the
  system actor `orphan-reaper` with an audit entry, reusing the existing
  terminal-transition + audit machinery. Non-fatal on error.
- **Tool safety (P5):** coder agents stage only the files they wrote
  (no `git add -A`); security scan dispatches JVM patterns for
  `.java/.kt/.scala` files instead of scanning them with Python rules.
- **Evidence persistence (P7):** `MRPEvidenceUpdate.execution_context`
  carries full test output (last 8k chars), scan findings, lint output,
  and run metadata into the append-only audit context — statuses stay on
  MRP columns, raw evidence lives in audit JSONB. No new evidence system.
- **Blueprint audit (P8):** blueprint create/update are audited like every
  other mutating endpoint (blueprint version is merge-gating evidence).
- Plan-before-write is designed but NOT implemented:
  `docs/P6_A_PLAN_BEFORE_WRITE_DESIGN.md` (Phase B enforcement requires
  separate approval).

### Phase 2: human identity (2026-08-26, additive)

Real authn now plugs into the exact seam `require_human_actor` documented:

- **Tables (migration 003):** `users` (username PK, PBKDF2 password hash,
  is_active) and `api_tokens` (sha256 of raw token as PK — raw shown once,
  never stored; expiry + revocation + last_used_at).
- **Endpoints:** `POST /auth/login` → bearer token (audited
  success/failure, timing-equalized against unknown users);
  `GET /auth/me` → introspection.
- **`require_human_actor` decision order:** (1) valid
  `Authorization: Bearer` → authoritative `human:<username>` identity,
  any X-Acting-As value ignored; (2) invalid/expired/revoked bearer → 401;
  (3) no bearer + `SASE_REQUIRE_HUMAN_TOKEN` set → 401 fail-closed;
  (4) otherwise legacy X-Acting-As prefix check (default, unchanged).
- **Crypto:** stdlib only — PBKDF2-HMAC-SHA256 (200k iterations,
  salted), `secrets.token_hex(32)`, constant-time comparisons.
- **Bootstrap:** `scripts/create_user.py` (interactive getpass or
  `SASE_USER_PASSWORD` for scripted runs).
- **Agents unaffected:** tokens are issued only after a password check;
  no agent role has or can obtain credentials.
- Not implemented (awaiting approval): rate limiting, refresh tokens,
  OIDC/mTLS, password reset.

---

## 8. Audit & Traceability

- Every mutating endpoint calls `record_audit(...)` **inside the same
  transaction** as its artifact write (`api/audit.py`) — atomicity guarantee.
- Append-only is currently **convention**: deployment is expected to apply
  `REVOKE UPDATE, DELETE ON audit_log FROM <app_role>; GRANT INSERT, SELECT ...`
  (documented in `audit.py` docstring, not yet automated — Risk Register B4).
- The §3.7 questions answerable today:
  - *"Which requirement produced this code?"* → `GET /traceability/chain/{mrp}`
  - *"What did the agent use?"* → `agent_runs`: prompt hashes, RAG doc ids,
    index version, temperature, tools
  - *"Who decided what, when?"* → `vcrs` + `audit_log.human_decision`
  - *"Is this auditable end-to-end?"* → chain response `fully_traceable`

---

## 9. Blueprints

Two seed Blueprints ship at repo root `/blueprints/` (project-scoped overrides
belong in `.ai-engineering/blueprints/`). Both intentionally carry
`approved_by: <fill in — pending first human approval>` — approving them is a
real human milestone, not boilerplate.

| File | Scope | Key rules |
|---|---|---|
| `org-wide/BP-ERROR-HANDLING-001.md` | org | `Result<T>` outcomes instead of raw business exceptions (paper §4.2.3 worked example) |
| `stacks/springboot/BP-SPRINGBOOT-001.md` | stack:springboot | Layered arch (no layer skipping), constructor injection only, DTO/entity separation, jakarta.validation, JUnit5+Mockito unit / Testcontainers integration (no H2), explicit anti-pattern list |

`jboss-legacy/` stack directory exists, empty — reserved for legacy-discovery work.

---

## 10. Configuration & Deployment

```bash
docker compose up --build     # postgres:16 + api (first boot applies migrations/)
# API on :8000, docs at :8000/docs
```

| Setting | Value | Source |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://sase:sase@localhost:5432/sase` (default) | env var, `database.py` |
| `SASE_CI_TOKEN` | unset → evidence endpoints **503 fail-closed**; compose sets dev value | env var, `security.py` |
| `SASE_API_TOKEN` | unset = perimeter open; set → all requests need `X-API-Token` | env var, `main.py` |
| `SASE_OLLAMA_HOST` / `SASE_OLLAMA_MODEL` | `http://localhost:11434` / `qwen2.5-coder:7b` | agent layer LLM transport (P1) |
| `SASE_MODEL_VERSION` | unset | optional AgentRun provenance tag (P2) |
| `SASE_ORPHAN_RUN_HOURS` | `24` | startup reaper threshold for stale 'running' runs (P4) |
| Compose DB creds | sase/sase/sase | docker-compose.yml |
| Ports | host 5433→5432 (postgres), 8000 (api) | docker-compose.yml |
| Commented services | redis:7 (:6379), qdrant (:6333), ollama (:11434) | phases 4–6 |

Air-gap note (compose comment): Ollama container must not be exposed beyond the
internal compose network in air-gapped deployments.

---

## 13. Testing

| Suite | Needs live stack? | Status |
|---|---|---|
| `tests/test_gates_unit.py` | No — fakes for DB/session | ✅ pass |
| `tests/test_agents_unit.py`, `tests/test_coder_unit.py` | No — pure functions/fakes | ✅ pass |
| `tests/test_hardening_batch.py` (17 tests, 2026-08-26 batch) | No — retry/reaper/scan/provenance units | ✅ pass |
| `tests/test_traceability_chain.py` (E2E chain walk) | Yes — asserts both gates return 409, resolves CRP, verifies `fully_traceable` | ⏸ auto-skips until `docker compose up` |

Full DB-free run: `<venv-python> -m pytest tests --ignore=tests/test_traceability_chain.py`
(79 passed as of the 2026-08-26 hardening batch; E2E verified separately
against the live compose stack).

Unit coverage: MRP readiness matrix, CRP gates, agent-run terminal state machine,
identity guards incl. CI fail-closed behavior, perimeter middleware, LLM retry
backoff semantics (transient vs 4xx), orphan-reaper transition + audit,
language-aware security scan, surgical-staging contracts, evidence context pass-through.

---

## 14. Change Log (2026-08-24 session)

Fixes applied after initial full-project read (all verified by tests):

1. **`api/ids.py` — race condition fixed.** `_next_seq` INSERT-then-SELECT could
   hand duplicate sequence values to concurrent requests (PK collisions).
   Replaced with single atomic `INSERT .. ON CONFLICT DO UPDATE .. RETURNING value`.
2. **`api/security.py` (new) + routers — human-decision forgery blocked.**
   Previously any caller could post `"validated_by": "human:anyone"` /
   `"human_reviewer": "..."` in the body and pass every gate. Human-only endpoints
   now take identity from `X-Acting-As` header; body fields accepted-but-ignored
   for compatibility. README walkthrough updated.
3. **`api/routers/crp.py` — severity ordering fixed.** Alphabetical `.desc()`
   ranked `medium > low > high > critical`; replaced with CASE priority order.
4. **`api/gates.py` — dead parameter removed** (`project_id` was never used by
   `no_open_high_or_critical_crp_blocks_merge`).
5. **Tests added/reworked** (see §11); integration test now skips gracefully
   instead of erroring when the stack is down.

### Hardening round 2 (same session)

Fixes for the HIGH findings from the independent review (§13):

- **B1 — evidence forgery closed.** New `require_ci_actor` (`api/security.py`):
  `PATCH /mrps/{id}/evidence` now demands an `X-Acting-As: ci:/system:` identity
  and, when set, a matching `SASE_CI_TOKEN`/`X-CI-Token` pair; audit rows use that
  real actor id instead of hardcoded `ci-pipeline`.
- **B2 — perimeter token.** Optional shared-secret middleware in `api/main.py`:
  with `SASE_API_TOKEN` set, every request needs header `X-API-Token`; unset keeps
  local dev unchanged.
- **B3 — Agent Run terminal state machine.** `assert_run_patchable` (`api/gates.py`)
  rejects unknown statuses (422) and any patch on a completed/failed/blocked run
  (409) — provenance of finished runs is immutable per §3.7.8.
- **B4 — append-only audit enforced + guarded reads.** `migrations/002_audit_lockdown.sql`
  adds BEFORE UPDATE/DELETE triggers on `audit_log` (apply manually to existing
  volumes); `GET /traceability/audit/*` now requires any well-formed actor via
  `require_any_actor`. `/traceability/chain/{mrp_id}` left open by design.

---

## 15. Risk Register (independent review-agent findings)

Verdict: **conditional approve for phase-1 internal use** — strong gate
architecture, but not yet load-bearing. Do not connect real agents or expose
beyond localhost before clearing the HIGH items.

### HIGH (blocking-class)
| # | Finding | Location | Fix direction |
|---|---|---|---|
| B1 | `PATCH /mrps/{id}/evidence` unauthenticated; audit row hardcoded to actor `ci-pipeline` → test/security evidence forgeable, gate silently bypassed | mrp.py:update_evidence | Authenticated CI identity (token/mTLS) |
| B2 | `X-Acting-As` spoofable; port 8000 open unauthenticated → human gates hold only at network perimeter | api/security.py | Real authn: OIDC/mTLS |
| B3 | Finished Agent Runs remain fully mutable (status/commit_hash/mrp_id) by anyone; no terminal-state machine → provenance corruptible | agent_runs.py:update_agent_run | Transition rules (e.g. no updates after completed/failed/blocked) |
| B4 | Append-only audit enforced nowhere (comment-only REVOKE); `GET /traceability/audit/*` exposes the trail unauthenticated | audit.py, migrations | DB-level REVOKE + trigger; guard audit reads |

### MEDIUM
| # | Finding | Fix direction |
|---|---|---|
| M1 | Merge gate filters CRPs only by `spec_id` — a CRP raised with only `agent_run_id` (spec null) escapes the block entirely (hole in core guarantee) | include agent_run_id in filter |
| M2 | ORM uses String where DDL uses ENUMs → invalid values become 500 IntegrityError instead of 422 | align types or Literal-validate |
| M3 | Counter row lock held till commit → serialization hot spot on concurrent creates | short transactions / sequences |
| M4 | Concurrent `validate_spec` both succeed; last writer wins on validator/at | reject if already validated |
| M5 | No listing/pagination for PRDs, Specs, MRPs, VCRs, Agent Runs; CRP list unbounded | paginated list endpoints |
| M6 | Evidence/status fields free-text; typos silently bypass literal gate comparisons | Enum/Literal validation |
| M7 | E2E test uses hardcoded PR 9999 (breaks re-runs); no tests for evidence-forgery path, duplicate VCR, pre-ready approval, audit contents | unique fixtures + cases |

### LOW
L1 duplicate `decided_by` field in VCRCreate (Pydantic keeps last silently) ·
L2 mixed mutable/callable defaults style · L3 Postgres-only TEXT[] columns block
SQLite-based testing · L4 missing FKs (mrp.blueprint_*, agent_runs.mrp_id) let
dangling refs silently degrade `fully_traceable` · L5 repeated inline imports ·
L6 `/health` doesn't ping DB (dead Postgres still reports ok) · L7 raw ORM returns
without response_model on several GETs.

### Positives recorded by reviewer
Gates enforced at enforcing call sites · transactional audit · single VCR
resolution chokepoint · atomic ID upsert · correct severity ordering ·
negative-path gate tests exist.

---

## 16. Operational Readiness

Order in which things break first in production (per review):

1. **Migrations** — raw SQL auto-applies only on first boot of an empty volume;
   no Alembic. Schema change #2 has no path.
2. **Backups** — none documented; the governance memory is unrecoverable if lost.
3. **AuthN perimeter** — default `sase:sase` credentials committed; ports
   5432/8000 published to host.
4. **Logging/observability** — zero application logging; no correlation IDs
   linking HTTP requests to audit rows.
5. **Rate limiting** — none; counter-flood / audit-noise possible.
6. **CORS** — unconfigured (will surprise a future review UI).
7. **CI** — no pipeline config despite CI-ready unit tests.

Minimum before internal multi-user use: clear B1–B4, add Alembic, restrict DB
port, document backup procedure, wire the unit tests into CI.

---

## 17. Roadmap

From README, in order:

1. **Human approval of the two seed Blueprints** (fill `approved_by`, expand
   Spring Boot Blueprint to team conventions).
2. **Wire Ollama** (Qwen-72B, DeepSeek-671B) via the commented compose block —
   needs GPU/network machine.
3. **Product + Spec Agents** calling `/prds`, `/user-stories`, `/acceptance-criteria`,
   `/specs` — keeping `POST /specs/{id}/validate` human-only.
4. **Structured RAG pipeline** as a separate service; separate vector index from
   Blueprint storage.
5. **Coder Agent + Reflection loop + isolated Reviewer Agent** using
   `/agent-runs`, `/crps`, `/mrps`.

Exit criterion already met at backbone level: the ten-step README walkthrough
and the E2E test demonstrate a fully traceable chain with working gates.

---

*End of documentation. Sources: full source read of every file in the repository;
independent review-agent report (18 findings); session fix log.*
