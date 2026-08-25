# Phase 4 Knowledge Report — ai-swe-engine

> **Investigator:** Sara (supervisor agent)
> **Date:** 2026-08-24
> **Scope:** Evidence-based analysis of Phase 4 from repository + project documentation
> **Status:** READ-ONLY investigation — no implementation proposed

---

## Table of Contents

1. [Current Project State](#1-current-project-state)
2. [Phase 4 Requirements](#2-phase-4-requirements)
3. [Redis Role](#3-redis-role)
4. [Existing Code Support](#4-existing-code-support)
5. [Dependencies](#5-dependencies)
6. [Architecture](#6-architecture)
7. [Risks / Conflicts](#7-risks--conflicts)
8. [Unknown Information](#8-unknown-information)
9. [Gate for Approval](#9-gate-for-approval)

---

## 1. CURRENT PROJECT STATE

### What Phase 1–3 Already Implement

**Phase 1 — Traceability backbone (v0.1.0):**
- FastAPI + PostgreSQL schema (`migrations/001_init.sql`) for artifact chain: Project → PRD → User Story → Acceptance Criteria → Spec → Blueprint → Agent Run → CRP → MRP → VCR → Audit Log
- Hard gates in `api/gates.py` (§3.5, §3.6.3, §5.6.5)
- Identity-guarded endpoints (`api/security.py`): `X-Acting-As: human:<name>` + CI token auth
- Append-only audit log (`002_audit_lockdown.sql` triggers)
- Atomic ID generation (`api/ids.py`)
- 37+ tests passing

**Phase 2 — Agent layer + local LLM (v0.2.0):**
- 6 role-defined agents (`agents/config.py`): product, spec, coder, reviewer, reflection, test_runner
- Prompt contracts (`agents/prompts.py`, `agents/coder_prompts.py`)
- Local LLM backends (`agents/llm.py`): OllamaLLM + TemplateLLM fallback
- Orchestrator pipeline (`agents/orchestrator.py`): `--online`, `--offline`, `--code`, `--spec-only`
- Coder agent with reflection loop (`agents/coder_agent.py`)
- Engine client with allowlists (`agents/engine_client.py`)

**Phase 3 — NOT explicitly defined anywhere in the repository.** The roadmap in `docs/FULL_DOCUMENTATION.md` §17 lists:
1. Human approval of seed Blueprints
2. Wire Ollama
3. Product + Spec Agents calling API
4. **Structured RAG pipeline** (separate service, vector index)
5. Coder Agent + Reflection + Reviewer

Phases 1 and 2 are built. **Phase 3 appears to have been absorbed into Phase 2** (Ollama, Product/Spec agents, Coder agent are all built). There is no explicit "Phase 3" label anywhere.

### What Infrastructure Exists

| Service | Status | Port |
|---|---|---|
| PostgreSQL 16 | Running (`docker compose up`) | host 5433 |
| API (FastAPI) | Running | host 8000 |
| Ollama | Host-installed (winget) | host 11434 |
| Redis | **Commented out** in docker-compose.yml | — |
| Qdrant | **Commented out** in docker-compose.yml | — |

### What Is Already Connected
- API ↔ PostgreSQL (direct SQLAlchemy, `DATABASE_URL`)
- Agents ↔ API (HTTP via `EngineClient`, allowlists enforced)
- Agents ↔ Ollama (direct HTTP to `localhost:11434`)
- Agent ↔ Local git workspace (filesystem writes, subprocess pytest)

### What Is Missing
- No Redis anywhere (not installed, not configured, not imported)
- No background workers
- No queues or job processing
- No LangGraph (explicitly deferred — see §3 below)
- No RAG / vector store (Qdrant commented out)
- No async task execution
- No pub/sub or event handling
- No caching layer

---

## 2. PHASE 4 REQUIREMENTS

### Explicit References Found

**Reference 1:** `docker-compose.yml` (lines 38–63, now updated)
```yaml
# Commented out Redis:7 (:6379), Qdrant (:6333), Ollama (:11434)
# Labeled "phases 4–6"
```

**Reference 2:** `docs/FULL_DOCUMENTATION.md` line 321
```
| Commented services | redis:7 (:6379), qdrant (:6333), ollama (:11434) | phases 4–6 |
```

**Reference 3:** `docs/FULL_DOCUMENTATION.md` §1 (Mission & Scope)
```
| Structured RAG / vector store | Roadmap step 4 |
```

**Reference 4:** `docs/FULL_DOCUMENTATION.md` §17 (Roadmap)
```
4. Structured RAG pipeline as a separate service; separate vector index from
   Blueprint storage.
```

**Reference 5:** `agents/orchestrator.py` line 5
```python
# LangGraph comes later if/when loops and branching are actually needed.
```

**Reference 6:** `README.md` "What's NOT here yet"
```
- RAG pipeline: no vector store, chunking, or reranking. Blueprints are read as plain YAML.
```

### What Phase 4 Is Actually Supposed to Accomplish

Based on the evidence, Phase 4 = **Structured RAG pipeline**. Specifically:
- A separate service for vector-based retrieval
- Separate vector index from Blueprint storage
- Chunking + reranking for document retrieval
- Redis is listed alongside it as infrastructure, but its exact role is not specified in any repo file

**There is NO detailed Phase 4 design document, specification, or requirements file anywhere in the repository.** The only evidence is:
1. Docker-compose comments labeling Redis/Qdrant as "phases 4–6"
2. Roadmap item #4: "Structured RAG pipeline as a separate service"
3. Orchestrator code comment: "LangGraph comes later if/when loops and branching are actually needed"

---

## 3. REDIS ROLE

### Confirmed Facts

| Fact | Evidence |
|---|---|
| Redis is mentioned in docker-compose.yml | Line 41: `# redis:7 (:6379)` — commented out |
| Redis is labeled "phases 4–6" | `FULL_DOCUMENTATION.md` line 321 |
| Redis is NOT in requirements.txt | Only fastapi/uvicorn/sqlalchemy/psycopg2/pydantic/dotenv/pytest/httpx |
| Redis is NOT imported in any Python file | grep across entire codebase = 0 Python hits |
| Redis is NOT configured in any env var | No `REDIS_URL`, `REDIS_HOST`, etc. anywhere |

### What Redis Is Intended To Do (from reference design doc)

The project documentation folder contains `21-AGENTIC-AI-PLATFORM.md` — a **reference design** (not implemented) for a production Agentic AI platform. In that document, Redis appears in these roles:

| Role | Quote |
|---|---|
| Rate limiting | "Per-principal and per-task token buckets (Redis)" (§11.2) |
| Working memory | "Redis / in-activity context" (§8.2) |
| Conversation memory | "Redis/Postgres" (§8.2) |
| Caching | "cache (Redis)" (§23) |
| Locks | "Redis: rate limits, locks, cache" (§1 diagram) |
| Technology selection | "Redis: Working memory, rate-limit buckets, cache, locks" (§23) |

### Interpretation (clearly labeled as such)

The reference design (`21-AGENTIC-AI-PLATFORM.md`) is a **completely separate project** — a large enterprise platform with Kafka, Temporal, Vault, OIDC, 12+ services. The ai-swe-engine is a **smaller, offline-first implementation** of some SASE concepts.

Redis in the ai-swe-engine docker-compose was likely carried over as a placeholder from the reference design's technology choices. **No one has defined what Redis specifically does in this project.** The three possible roles based on the reference design:

1. **Cache** — could reduce LLM API calls or database queries
2. **Queue** — could support background jobs (agent tasks, CRP processing)
3. **Rate limiting** — token buckets for LLM usage

**None of these are confirmed by any code, design doc, or requirement in the repository.**

---

## 4. EXISTING CODE SUPPORT

| Component | Exists? | Evidence |
|---|---|---|
| Redis dependencies (redis-py, aioredis) | **NO** | Not in requirements.txt |
| Redis configuration (env vars, settings) | **NO** | No REDIS_* variables anywhere |
| Redis client code | **NO** | grep returns 0 Python hits for redis/Redis |
| Background workers | **NO** | No Celery, no arq, no custom workers |
| Queues | **NO** | No queue imports, no job models |
| LangGraph checkpoints/state | **NO** | Explicitly deferred ("comes later if/when needed") |
| Retry mechanisms | **NO** | Coder agent has bounded reflection loop, but no distributed retry |
| Job/task models | **NO** | No job table, no task queue schema |
| Environment variables for Redis | **NO** | Only DATABASE_URL, SASE_API_TOKEN, SASE_CI_TOKEN, TODO_STORE, CODER_MAX_REPAIRS |
| Docker configuration for Redis | **Commented out** | docker-compose.yml line 41-43, labeled "phases 4–6" |

---

## 5. DEPENDENCIES

### Already Installed (requirements.txt)

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
sqlalchemy==2.0.35
psycopg2-binary==2.9.9
pydantic==2.9.2
python-dotenv==1.0.1
pytest==8.3.3
httpx==0.27.2
```

### Referenced but Not Installed
- **Redis** (redis-py or aioredis) — commented out in docker-compose, no Python package
- **Qdrant** — commented out in docker-compose, no Python package
- **LangGraph** — mentioned in orchestrator.py comment only, no import or package

### Completely Missing (would be needed for a RAG pipeline)
- Vector DB client (qdrant-client, chromadb, or pgvector)
- Embedding model (sentence-transformers, or Ollama embeddings)
- Document chunking library (langchain-text-splitters, unstructured)
- Reranking model/library
- A separate service or module for the RAG pipeline

---

## 6. ARCHITECTURE

### Current Architecture (v0.2.0)

```
┌─────────────────────────────────────────────────────────┐
│                    HUMAN DECISIONS                        │
│  (X-Acting-As: human:<name>)                            │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│              SASE TRACEABILITY ENGINE                    │
│  FastAPI + PostgreSQL (localhost:8000)                  │
│  Hard gates · Audit log · Identity guard                │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTP (allowlists)
                      ▼
┌─────────────────────────────────────────────────────────┐
│                  AGENT LAYER                             │
│  Product → Spec → Coder (reflection loop)              │
│  Orchestration via agents/orchestrator.py              │
└──────┬────────────────────┬────────────────────────────┘
       │                    │
       ▼                    ▼
┌──────────────┐   ┌────────────────────┐
│ LOCAL GIT    │   │ LOCAL LLM          │
│ WORKSPACE    │   │ Ollama + Qwen 7B   │
│ (filesystem) │   │ (localhost:11434)  │
└──────────────┘   └────────────────────┘
```

### What Phase 4 Would Add (based on roadmap item #4)

```
┌─────────────────────────────────────────────────────────┐
│              SASE TRACEABILITY ENGINE                    │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│              STRUCTURED RAG PIPELINE                     │
│  Separate service (TBD)                                 │
│  Chunking · Embedding · Vector index · Reranking       │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│              VECTOR DATABASE                             │
│  Qdrant (commented: localhost:6333)                     │
│  OR pgvector extension on existing Postgres             │
└─────────────────────────────────────────────────────────┘

Role of Redis (UNDEFINED):
  Option A: Cache layer between API and RAG service
  Option B: Job queue for async RAG indexing
  Option C: Session/state management for long-running queries
  Option D: Rate limiting for embedding API calls
  Option E: Not needed at this scale
```

---

## 7. RISKS / CONFLICTS

| Risk | Severity | Detail |
|---|---|---|
| **No Phase 4 design exists** | HIGH | The roadmap says "Structured RAG pipeline" but there is zero specification — no data model, no API contract, no service boundary. Implementing without design = guesswork. |
| **Duplicated state** | MEDIUM | PostgreSQL already holds artifact relationships + body_ref. A vector DB would hold chunks of the same content. Cache invalidation between them is a real problem. |
| **Redis vs Postgres overlap** | MEDIUM | Postgres already provides: session management (via DB sessions), audit logging, transactional state. Adding Redis for "sessions" or "caching" risks splitting the source of truth. |
| **Offline/air-gapped constraint** | HIGH | The platform is explicitly offline-first. Qdrant/Redis add two more services to manage. If the vector DB goes down, does the whole RAG pipeline fail? Need graceful degradation. |
| **Local LLM integration** | MEDIUM | Ollama runs on the host, not in Docker. The RAG pipeline service would need to reach Ollama for embeddings, or use a separate embedding model. Network boundary between container and host. |
| **CI evidence requirements** | LOW | Current CI evidence is synchronous (pytest → PATCH /mrps/{id}/evidence). If RAG becomes async, evidence recording needs to handle async completion. |
| **Docker networking** | LOW | Postgres is on host 5433 (not 5432). Redis would be on 6379. Qdrant on 6333. Port mapping needs care to avoid conflicts with other services (Sara's Postgres on 5432). |
| **Security/auth** | MEDIUM | X-Acting-As is a seam, not real authn. Adding more services (RAG, Redis) expands the attack surface without improving authentication. |

---

## 8. UNKNOWN INFORMATION

### I DON'T KNOW

1. **What exactly is Phase 4?** The repository has NO design document, NO specification, and NO requirements file for Phase 4. The only evidence is a one-line roadmap item: "Structured RAG pipeline as a separate service; separate vector index from Blueprint storage."

2. **What role does Redis play?** Redis is listed in docker-compose comments and labeled "phases 4–6" but no file in the repository explains what Redis is FOR in this project. It could be cache, queue, rate limiting, session store, or unnecessary at this scale.

3. **What is Phase 5?** Not defined anywhere in the repository.

4. **Is LangGraph intended?** The orchestrator.py comment says "LangGraph comes later if/when loops and branching are actually needed." But the current orchestrator already has branching (--offline vs --online, --code vs --spec-only). When does LangGraph become needed?

5. **What is the vector index for?** Blueprints are YAML files. Specs are YAML. PRDs/stories/ACs are text. What exactly gets chunked, embedded, and queried? The reference design mentions RAG but the ai-swe-engine has no RAG-related code or configuration.

6. **What is the service boundary?** "Separate service" for RAG — is this a new FastAPI service? A module in the existing API? A sidecar container? No architecture decision is documented.

7. **What embedding model?** No embedding model is mentioned anywhere. Options: Ollama embeddings, sentence-transformers, OpenAI embeddings (requires internet — violates offline constraint).

8. **What is the chunking strategy?** No chunking library, no chunk size, no overlap strategy documented.

9. **What triggers RAG indexing?** When artifacts are created, do they automatically get indexed? Is it a background job? A webhook? Manual?

10. **What queries RAG?** The coder agent? The spec agent? The product agent? All of them? How does RAG context get injected into prompts?

---

## 9. GATE FOR APPROVAL

### What Phase 4 Means (Based on Sparse Evidence)

Phase 4 means: **Add a structured RAG pipeline** — a system that indexes project artifacts (blueprints, specs, PRDs, code) into a vector database and provides semantic search/retrieval to agents during generation.

Redis's role is **undefined**. It appears in docker-compose as infrastructure alongside Qdrant and Ollama, all labeled "phases 4–6." Without a design document, I cannot determine if Redis is needed, what it does, or whether it conflicts with the existing Postgres state.

### What Should NOT Be Changed

| Item | Reason |
|---|---|
| `api/gates.py` | Gate logic is correct and tested. RAG must not bypass or weaken gates. |
| `api/security.py` | Identity model is a seam, not broken. RAG service must use same auth model. |
| `api/audit.py` | Audit must cover RAG queries and index operations. |
| `migrations/001_init.sql` | Artifact chain is the source of truth. RAG is a read layer, not a replacement. |
| `agents/config.py` role allowlists | RAG operations must be governed by existing role policies. |
| Offline-first constraint | RAG must work without internet. No cloud embedding APIs. |
| `agents/llm.py` philosophy | "LLM produces content only; governance is server-side." RAG retrieval must also be governed. |

### Decisions Requiring Approval

1. **Phase 4 scope** — What exactly are we building? A design document is needed before any code.
2. **Redis role** — Is Redis needed? For what? Cache? Queue? Rate limiting? Or skip it?
3. **Vector DB choice** — Qdrant (separate container)? pgvector (extension on existing Postgres)? Something else?
4. **Embedding model** — Ollama embeddings? sentence-transformers? What runs offline on CPU?
5. **Service boundary** — New FastAPI service? Module in existing API? Sidecar?
6. **RAG indexing trigger** — Automatic on artifact creation? Background job? Manual?
7. **RAG query scope** — Which agents get RAG context? How is it injected into prompts?
8. **Chunking strategy** — What gets chunked? YAML? Markdown? Code? What size/overlap?

### What Would Be Implemented If Phase 4 Is Approved

**Nothing yet.** First step would be producing a Phase 4 design document covering:
- What "Structured RAG pipeline" means for this project (not the reference design)
- Redis role (or recommendation to skip it at this scale)
- Vector DB choice with tradeoffs
- Embedding model selection (offline-capable)
- Service architecture (new service vs module)
- Data flow: artifact creation → indexing → retrieval → prompt injection
- Gate integration: how RAG interacts with existing hard gates
- Testing strategy: unit tests for chunking/embedding, E2E for retrieval quality
- Risks and mitigations

Then the design would be presented for approval before writing any code.

---

*End of Phase 4 knowledge report.*
