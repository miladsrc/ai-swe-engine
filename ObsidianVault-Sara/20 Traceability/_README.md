---
id: TRACEABILITY-README
type: index
status: active
source_repo_path: IdeaProjects/ai-swe-engine/api/routers/traceability.py
source_commit: 69c93b9
updated: 2026-09-15
---

# 20 Traceability — READ-ONLY / Non-SoT

> [!DANGER] This folder is **read-only / Non-SoT**. Source of Truth is **Postgres** (`prds`, `user_stories`, `acceptance_criteria`, `specs`, `agent_runs`, `crps`, `mrps`, `vcrs`, `audit_log`) + **Git** commits + SASE APIs. Cards here are **references only**.

## Purpose

Provide a browsable knowledge graph `PRD → US → AC → SPEC → RUN → CRP/MRP → VCR` with links, IDs, repo paths, commit hashes, and API identifiers — without duplicating SoT bodies.

## What a Card Contains

- Frontmatter with `id, type, status, source_repo_path, source_commit, updated`
- SoT pointers: DB table + id, API endpoint, repo file:line, Git SHA
- Wikilinks to related cards: `[[PRD-PRD-TODO-008]]`, `[[SPEC-SPEC-xxx]]`, `[[RUN-RUN-QW-2026-00011]]`
- One-paragraph **knowledge summary** (why, not what — the what stays in SoT)

## What a Card NEVER Contains

- SPEC bodies
- MRP evidence blobs
- CRP / VCR row dumps
- Migration SQL
- Source code or generated artifacts

Link to them instead.

## Naming

```
PRD-PRD-xxx.md
SPEC-SPEC-xxx.md
RUN-RUN-xxx.md
MRP-MRP-PR-xxx.md
CRP-CRP-xxx.md
VCR-VCR-xxx.md
```

See `[[10 SASE/02 Conventions]]` for full rules.

## Example

- `[[MRP-MRP-PR-78001|MRP-MRP-PR-78001]]` — full chain `PRD-TODO-008 → SPEC → RUN-QW-2026-00011 → CRP/MRP → VCR` with real IDs, commit `4e78f92`, and API references.

## How to Verify a Card

```bash
# Chain
curl -H "Authorization: Bearer <token>" http://localhost:8000/traceability/chain/MRP-PR-78001
# Evidence
curl http://localhost:8000/evidence/run/RUN-QW-2026-00011
# Audit
curl -H "Authorization: Bearer <token>" http://localhost:8000/traceability/audit/mrp/MRP-PR-78001
```
