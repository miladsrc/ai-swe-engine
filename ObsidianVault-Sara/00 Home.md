---
id: HOME
type: index
status: active
source_repo_path: IdeaProjects/ai-swe-engine/docs/MASTER_PLAN.md
source_commit: 69c93b9
updated: 2026-09-15
---

# Sara Knowledge Vault — Home

> **Principle:** `docs/MASTER_PLAN.md` + Git repository = **Source of Truth (SoT)**. This vault is a **Knowledge Management layer only** — for context, relationships, decisions, incidents, meeting outcomes, RCA, and troubleshooting. If any conflict arises, Git wins.

## What This Vault Is / Is Not

| This vault IS | This vault IS NOT |
|---|---|
| Knowledge graph connecting SASE, cloud-platform, and lessons learned | Source of Truth for code, contracts, or SASE gates |
| Place for explanatory summaries, conceptual maps, RCA, decisions | Place to duplicate SPEC bodies, MRP evidence, or migration SQL |
| Read/write KM layer you can browse, link, and query with Dataview | Part of the SASE runtime or merge workflow |

## Vault Structure (Step 1)

```
00 Home.md
10 SASE/              — SoT index & conceptual maps (links to repo, not copies)
20 Traceability/      — READ-ONLY / Non-SoT — reference cards only
30 Cloud-Platform/    — Sahba platform knowledge (from PROJECT_DOCUMENTATION)
40 Knowledge/         — Stack, patterns, troubleshooting
50 Incidents/         — RCA & incident notes
60 Decisions/         — ADRs & decision records (mirrors repo ADRs)
70 Meetings/          — Meeting outcomes & action items
99 Templates/         — Templates for consistent notes
```

- **10 SASE** → Index to `ai-swe-engine` SoT. Never copy gate logic; link to `api/gates.py`, `api/models.py`, `docs/MASTER_PLAN.md`.
- **20 Traceability** → **READ-ONLY / Non-SoT**. Cards like `MRP-MRP-PR-78001.md` link `PRD → SPEC → RUN → CRP/MRP → VCR` via IDs + repo paths + commit hashes + API identifiers. Bodies stay in Postgres/Git.
- **30 Cloud-Platform** → Curated knowledge from `PROJECT_DOCUMENTATION` (OBS/CBAC, Spring Boot 2.5.6, Liquibase, Postgres, Hazelcast, Eureka, RabbitMQ).

## Quick Links

- SASE SoT: `[[10 SASE/00 SASE Index|SASE Index]]`
- Gates & Traceability: `[[10 SASE/01 Gates and Traceability]]`
- Conventions: `[[10 SASE/02 Conventions]]`
- Traceability (read-only): `[[20 Traceability/_README|Traceability README]]` → example: `[[20 Traceability/MRP-MRP-PR-78001|MRP-PR-78001]]`
- Templates: `[[99 Templates/Tmpl-PRD|Tmpl-PRD]]` · `[[99 Templates/Tmpl-SPEC|Tmpl-SPEC]]` · `[[99 Templates/Tmpl-Incident|Tmpl-Incident]]` · `[[99 Templates/Tmpl-Meeting|Tmpl-Meeting]]`

## Metadata Convention (all notes)

```yaml
---
id: SPEC-SPEC-TODO-SPRING-BOOT-TODO-REST-API
type: SPEC
status: validated
source_repo_path: IdeaProjects/ai-swe-engine
source_commit: 69c93b9
updated: 2026-09-15
---
```

Fields: `id` (vault filename without .md), `type` (PRD/SPEC/RUN/MRP/CRP/VCR/ADR/INC/MTG), `status`, `source_repo_path`, `source_commit` (Git SHA or `postgres:<id>` for DB artifacts), `updated` (ISO date).

## Naming Convention

```
PRD-PRD-xxx.md
SPEC-SPEC-xxx.md
RUN-RUN-xxx.md
MRP-MRP-PR-xxx.md
CRP-CRP-xxx.md
VCR-VCR-xxx.md
ADR-ADR-xxx-title.md
INC-yyyy-mm-dd-slug.md
MTG-yyyy-mm-dd-topic.md
```

> See `[[10 SASE/02 Conventions]]` for full rules and examples.

## How to Use This Vault

1. Start from `[[10 SASE/00 SASE Index]]` for SoT pointers.
2. Follow traceability via `20 Traceability/` cards — they are **references**, not copies.
3. Add knowledge (RCA, decisions, mappings) in `40/50/60/70` as real Markdown.
4. Never paste SPEC bodies, MRP evidence, migration SQL, or generated code here — link to them.

---
*Vault created: 2026-09-15 · Step 1 only · No automation · No repo modifications · SARA v2 Gateway was DOWN, executed directly with disclosure.*
