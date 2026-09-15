---
id: SASE-INDEX
type: index
status: active
source_repo_path: IdeaProjects/ai-swe-engine/docs/MASTER_PLAN.md
source_commit: 69c93b9
updated: 2026-09-15
---

# SASE Index — Source of Truth Pointers

> This note is an **index only**. The repository is the Source of Truth. Do not duplicate SoT content here — link to it.

## Source of Truth

- **Master Plan:** `IdeaProjects/ai-swe-engine/docs/MASTER_PLAN.md` (v1.1, 2026-08-25) — product definition, phases 0–9, principles, governance model
- **Architecture:** `IdeaProjects/ai-swe-engine/docs/ARCHITECTURE.md` — depends on MASTER_PLAN
- **Full Documentation:** `IdeaProjects/ai-swe-engine/docs/FULL_DOCUMENTATION.md`
- **Gap Analysis:** `IdeaProjects/ai-swe-engine/docs/GAP_ANALYSIS.md`
- **Changelog:** `IdeaProjects/ai-swe-engine/docs/CHANGELOG/CHANGELOG.md`
- **Progress:** `IdeaProjects/ai-swe-engine/docs/PROGRESS/`

## ADRs (Decision Records — SoT in `docs/ADR/`)

- [[60 Decisions/ADR-ADR-001-sara-is-external|ADR-001: Sara is External]] → `docs/ADR/ADR-001-sara-is-external.md` — Sara is advisory-only, never runtime.
- [[60 Decisions/ADR-ADR-002-genuine-sod-isolation|ADR-002: Genuine SoD Isolation]] → `docs/ADR/ADR-002-genuine-sod-isolation.md` — Verifier=`ci:verifier`, Reviewer=`agent:reviewer`, genuine isolation target.

> ADRs in `60 Decisions/` are **knowledge mirrors** with links back to repo. The `.md` in `docs/ADR/` is canonical.

## Traceability Chain (SoT in Postgres + Git)

`Project → PRD → US → AC → SPEC (human_validated) → AgentRun → CRP → MRP (verified_tree_hash, G7/G8) → VCR → Audit`

- SoT models: `IdeaProjects/ai-swe-engine/api/models.py`
- Gates: `IdeaProjects/ai-swe-engine/api/gates.py` — `mrp_ready_for_merge` (G7/G8)
- Routers: `IdeaProjects/ai-swe-engine/api/routers/` (14 routers)
- Read-only chain API: `GET /traceability/chain/{mrp_id}`
- Evidence export: `GET /evidence/run/{run_id}`

See `[[01 Gates and Traceability]]` for the conceptual map and `[[20 Traceability/_README|Traceability README]]` for the read-only card convention.

## Phases (from MASTER_PLAN)

| Phase | Name | Status (in MASTER_PLAN) |
|---|---|---|
| 0 | Foundational Agent Loop | COMPLETE |
| 1 | Governance Integrity Hardening | COMPLETE |
| Interstitial | Human Identity | COMPLETE |
| 2 | Separation of Duties | NEXT — Design complete, G7/G8 partially implemented |
| 3 | Semantic Memory (Qdrant) | Planned |
| 4 | Bounded Self-Repair L1 | Planned |
| 9 | Platform UI / Human Ops Layer | Deferred |

## How to Navigate

- For **why** something exists → `docs/MASTER_PLAN.md` + ADRs
- For **how it is enforced** → `api/gates.py` + `api/security.py`
- For **what happened in a specific chain** → `20 Traceability/MRP-MRP-PR-xxx.md` (reference card, not SoT)
- For **lessons/RCA** → `50 Incidents/` and `40 Knowledge/`
