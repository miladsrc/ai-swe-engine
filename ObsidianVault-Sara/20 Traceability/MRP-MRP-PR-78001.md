---
id: MRP-MRP-PR-78001
type: MRP
status: ready_for_human_review
source_repo_path: IdeaProjects/ai-swe-engine
source_commit: postgres:MRP-PR-78001
updated: 2026-09-15
---

# MRP-PR-78001 — Todo Spring Boot REST API

> [!WARNING] Read-only / Non-SoT — SoT is **Postgres** (`mrps`, `agent_runs`, `specs`, `crps`, `vcrs`, `audit_log`) + **Git** + SASE APIs. This card is a reference and knowledge wrapper. Do not paste SoT bodies here.

## Chain Overview

```
PRD-TODO-008  (postgres:prds/PRD-TODO-008)
  └─ US-TODO-008  (postgres:user_stories/US-TODO-008)
       └─ AC-TODO-008-01  (postgres:acceptance_criteria/AC-TODO-008-01)
            └─ SPEC-TODO-SPRING-BOOT-TODO-REST-API  (postgres:specs/SPEC-TODO-SPRING-BOOT-TODO-REST-API, human_validated=true)
                 └─ RUN-QW-2026-00011  (postgres:agent_runs/RUN-QW-2026-00011, commit 4e78f92)
                      ├─ CRP(s)  (postgres:crps/* — if any, see CRP section)
                      └─ MRP-PR-78001  (postgres:mrps/MRP-PR-78001, verified_tree_hash, G7/G8)
                           └─ VCR(s)  (postgres:vcrs/* — resolves CRP)
```

Wikilinks (create stub cards as needed): `[[PRD-PRD-TODO-008]]` → `[[SPEC-SPEC-TODO-SPRING-BOOT-TODO-REST-API]]` → `[[RUN-RUN-QW-2026-00011]]` → `[[MRP-MRP-PR-78001]]`

## Knowledge Summary (what this chain achieved)

End-to-end SASE flow for a Spring Boot Todo REST API — seeded PRD/US/AC/SPEC, human-validated SPEC, offline code generation via `qwen2.5-coder:7b` in a local workspace (`IdeaProjects/todo-springboot`), Maven tests (16 tests: 6 controller + 10 service), MRP created with blueprint `BP-SPRINGBOOT-TODO-001`. Demonstrates G1 (human validation) + verifier-aware evidence path. Fix required: `javax.persistence → jakarta.persistence` for Spring Boot 3.x, Lombok 1.18.46 for JDK 26, Mockito pure-mock test fix.

> Full SoT bodies: see references below. This paragraph is the only Markdown knowledge here.

## SoT References (link, do not paste)

| Artifact | SoT Location | Identifier |
|---|---|---|
| **PRD** | `postgres:prds` + `GET /prds/PRD-TODO-008` | `PRD-TODO-008` — `project_id=todo-springboot` |
| **US** | `postgres:user_stories` + `GET /user-stories/US-TODO-008` | `US-TODO-008` — `prd_id=PRD-TODO-008` |
| **AC** | `postgres:acceptance_criteria` | `AC-TODO-008-01` — `user_story_id=US-TODO-008` |
| **SPEC** | `postgres:specs` + `GET /specs/SPEC-TODO-SPRING-BOOT-TODO-REST-API` | `SPEC-TODO-SPRING-BOOT-TODO-REST-API` — `human_validated=true` — validated by `human:m.barani` |
| **AgentRun** | `postgres:agent_runs` + `GET /agent-runs/RUN-QW-2026-00011` | `RUN-QW-2026-00011` — `spec_id=SPEC-TODO-SPRING-BOOT-TODO-REST-API` — `status=completed` — `commit=4e78f92` |
| **Workspace** | `IdeaProjects/todo-springboot` (local git) | `git show 4e78f92 --stat` — 10 Java files + tests |
| **Blueprint** | `postgres:blueprints` | `BP-SPRINGBOOT-TODO-001 v1.0` |
| **MRP** | `postgres:mrps` + `GET /mrps/MRP-PR-78001` | `MRP-PR-78001` — `status=ready_for_human_review` — `verified_tree_hash` (migration `005_mrps_verified_tree_hash.sql`) |
| **Evidence** | `PATCH /mrps/MRP-PR-78001/evidence` + `GET /evidence/run/RUN-QW-2026-00011` | `execution_context`, `provenance`, `verified_tree_hash` |
| **CRP** | `postgres:crps` + `GET /crps/{id}` | Live query via `gates.py:no_open_high_or_critical_crp_blocks_merge` (not stale `open_crp_ids`) |
| **VCR** | `postgres:vcrs` + `GET /vcrs/{id}` | Only path to resolve CRP (`api/routers/vcr.py`) |
| **Audit** | `postgres:audit_log` + `GET /traceability/audit/mrp/MRP-PR-78001` | actor `human:m.barani` / `ci:verifier` / `agent:reviewer` |
| **Chain API** | `GET /traceability/chain/MRP-PR-78001` | Returns `fully_traceable` when gates pass |
| **Spec validation gate** | `IdeaProjects/ai-swe-engine/api/gates.py:spec_must_be_human_validated_before_code_gen` | G1 |
| **Merge gate** | `IdeaProjects/ai-swe-engine/api/gates.py:mrp_ready_for_merge` | G7/G8 |

### Exact repo paths & lines (for verification)

- Models: `IdeaProjects/ai-swe-engine/api/models.py` — `class MRP`, `class AgentRun`, `class Spec` (`human_validated`), `class VerificationRequest`
- Gates: `IdeaProjects/ai-swe-engine/api/gates.py:1-241` — `mrp_ready_for_merge`, `_verifier_evidence_tree_hash`, `_reviewer_completed_review`
- Security: `IdeaProjects/ai-swe-engine/api/security.py` — `require_human_actor`, `require_verifier_actor` (`ci:verifier` + `SASE_VERIFIER_TOKEN`), `require_reviewer_actor`
- Routers: `IdeaProjects/ai-swe-engine/api/routers/requirements.py` (SPEC validate), `agent_runs.py` (G1), `mrp.py` (evidence + human-decision), `vcr.py` (resolve CRP), `traceability.py` (chain)
- Migrations: `IdeaProjects/ai-swe-engine/migrations/005_mrps_verified_tree_hash.sql`, `006_verification_requests.sql`, `007_reviewer.sql`
- Workspace: `IdeaProjects/todo-springboot/` — `pom.xml` (Spring Boot 3.x, Lombok 1.18.46), `src/main/java/...`, `src/test/java/...`

## Traceability Links

- PRD:: [[PRD-PRD-TODO-008]] — `GET /prds/PRD-TODO-008`
- US:: US-TODO-008 — `postgres:user_stories/US-TODO-008`
- AC:: AC-TODO-008-01 — `postgres:acceptance_criteria/AC-TODO-008-01`
- SPEC:: [[SPEC-SPEC-TODO-SPRING-BOOT-TODO-REST-API]] — `GET /specs/SPEC-TODO-SPRING-BOOT-TODO-REST-API` — **body not pasted**
- RUN:: [[RUN-RUN-QW-2026-00011]] — `GET /agent-runs/RUN-QW-2026-00011` — commit `4e78f92` — `git show 4e78f92`
- CRP:: (if any) `GET /crps?spec_id=SPEC-TODO-SPRING-BOOT-TODO-REST-API` — **data not pasted**
- MRP:: **this card** — `GET /mrps/MRP-PR-78001`
- VCR:: `GET /vcrs?related_artifact_id=CRP-xxx` — **data not pasted**

## Verification (how to prove this card, without copying SoT)

```bash
# 1. Chain (fully_traceable when gates pass)
curl -H "Authorization: Bearer $SASE_HUMAN_TOKEN" http://localhost:8000/traceability/chain/MRP-PR-78001 | jq

# 2. SPEC validation
curl -H "Authorization: Bearer $SASE_HUMAN_TOKEN" http://localhost:8000/specs/SPEC-TODO-SPRING-BOOT-TODO-REST-API | jq .human_validated

# 3. AgentRun + commit
curl http://localhost:8000/agent-runs/RUN-QW-2026-00011 | jq
git -C IdeaProjects/todo-springboot show 4e78f92 --stat

# 4. MRP evidence (read-only export)
curl http://localhost:8000/evidence/run/RUN-QW-2026-00011 | jq

# 5. G7/G8 readiness
curl -X POST http://localhost:8000/mrps/MRP-PR-78001/check-ready | jq

# 6. Audit
curl -H "Authorization: Bearer $SASE_HUMAN_TOKEN" "http://localhost:8000/traceability/audit/mrp/MRP-PR-78001" | jq
```

## Related Knowledge

- Gates map: `[[10 SASE/01 Gates and Traceability]]`
- ADR-002 SoD isolation: `[[60 Decisions/ADR-ADR-002-genuine-sod-isolation]]` → `docs/ADR/ADR-002-genuine-sod-isolation.md`
- Stack lesson (jakarta vs javax, Lombok JDK26): to be added in `40 Knowledge/` (not here — this card stays reference-only)
- Incident template: `[[99 Templates/Tmpl-Incident]]` (if RCA needed for the H2 `users` table fix, create `50 Incidents/INC-2026-08-26-h2-users-reserved.md`)

## Status & Next Human Action

- **Current MRP status (SoT):** `ready_for_human_review` (from `mrps.status`)
- **Blocking gates (SoT):** `POST /mrps/MRP-PR-78001/check-ready` — G7 requires `verified_tree_hash` + verifier evidence `ci:verifier`; G8 requires `ai_review_status==completed` by `agent:reviewer` (strict mode)
- **Human decision (SoT only):** `POST /mrps/MRP-PR-78001/human-decision` with `Bearer` — never via vault

---
*Card type: MRP reference · SoT: Postgres + Git + SASE APIs · Commit `4e78f92` · Updated 2026-09-15*
