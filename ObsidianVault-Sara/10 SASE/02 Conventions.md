---
id: SASE-CONVENTIONS
type: knowledge
status: active
source_repo_path: IdeaProjects/ai-swe-engine/docs/MASTER_PLAN.md
source_commit: 69c93b9
updated: 2026-09-15
---

# Conventions — Naming, Frontmatter, and SoT Boundaries

## 1. Metadata Convention (every Markdown note)

```yaml
---
id: MRP-MRP-PR-78001
type: MRP
status: ready_for_human_review
source_repo_path: IdeaProjects/ai-swe-engine
source_commit: 69c93b9
updated: 2026-09-15
---
```

| Field | Meaning | Example |
|---|---|---|
| `id` | Vault filename without `.md` | `MRP-MRP-PR-78001` |
| `type` | One of `PRD, US, AC, SPEC, RUN, CRP, MRP, VCR, ADR, INC, MTG, knowledge, index` | `MRP` |
| `status` | Domain status | `ready_for_human_review`, `validated`, `open`, `resolved` |
| `source_repo_path` | Repo or DB pointer — where SoT lives | `IdeaProjects/ai-swe-engine` or `postgres:mrps/MRP-PR-78001` |
| `source_commit` | Git SHA or DB identifier | `69c93b9` or `postgres:MRP-PR-78001` |
| `updated` | ISO date of this vault note | `2026-09-15` |

Additional optional fields: `source_api: GET /traceability/chain/MRP-PR-78001`, `source_line: api/gates.py:197`.

## 2. Naming Convention (filenames)

```
PRD-PRD-xxx.md              e.g. PRD-PRD-TODO-008.md
SPEC-SPEC-xxx.md            e.g. SPEC-SPEC-TODO-SPRING-BOOT-TODO-REST-API.md
RUN-RUN-xxx.md              e.g. RUN-RUN-QW-2026-00011.md
MRP-MRP-PR-xxx.md           e.g. MRP-MRP-PR-78001.md
CRP-CRP-xxx.md              e.g. CRP-CRP-TODO-2026-008.md
VCR-VCR-xxx.md              e.g. VCR-VCR-001.md
ADR-ADR-xxx-title.md        e.g. ADR-ADR-002-genuine-sod-isolation.md
INC-yyyy-mm-dd-slug.md      e.g. INC-2026-08-26-h2-users-reserved.md
MTG-yyyy-mm-dd-topic.md     e.g. MTG-2026-09-15-obsidian-km.md
```

- Use the **exact SoT ID** after the prefix. For MRP, keep the `PR-` as in DB (`MRP-MRP-PR-78001.md` not `MRP-78001.md`).
- Slugs are kebab-case, lower-case, no spaces.

## 3. SoT Boundaries — What Goes Where

### Keep as REFERENCE only (link, do not paste)

- SPEC bodies → `GET /specs/{id}` · `IdeaProjects/ai-swe-engine/api/routers/requirements.py`
- MRP evidence → `GET /evidence/run/{run_id}` · `PATCH /mrps/{id}/evidence`
- CRP / VCR rows → `GET /crps/{id}` · `GET /vcrs/{id}`
- Migration SQL → `IdeaProjects/ai-swe-engine/migrations/*.sql` (e.g. `005_mrps_verified_tree_hash.sql`)
- Source code / generated artifacts → `IdeaProjects/todo-springboot/` · `git show <sha>`
- Audit rows → `GET /traceability/audit/{type}/{id}`

### Keep as REAL Markdown knowledge in the vault

- Explanatory summaries (why a gate exists)
- Conceptual mappings (OBS tree, CBAC types, service dependencies)
- Architecture context (distributed-monolith realities, Hazelcast vs DB)
- Incident RCA, troubleshooting steps, lessons learned
- Decisions and meeting outcomes
- Links and relationships between concepts

## 4. Linking Rules

- Within vault: `[[MRP-MRP-PR-78001]]`, `[[ADR-ADR-002-genuine-sod-isolation]]`, `[[INC-2026-08-26-h2-users-reserved]]`
- To SoT: always include `source_repo_path` + `source_commit` + `source_api` or `source_line` in frontmatter or body.
- Traceability cards in `20 Traceability/` must start with callout:

```markdown
> [!WARNING] Read-only / Non-SoT — SoT is Postgres + Git. This card is a reference.
```

## 5. Vault High-Level Structure (frozen for Step 1)

```
00 Home.md
10 SASE/
20 Traceability/        # Read-only / Non-SoT
30 Cloud-Platform/
40 Knowledge/
50 Incidents/
60 Decisions/
70 Meetings/
99 Templates/
```

No automation scripts in Step 1. No `sync_sase_to_vault.py`. No repo modifications.

## 6. Frontmatter Examples

**Traceability card:**
```yaml
---
id: MRP-MRP-PR-78001
type: MRP
status: ready_for_human_review
source_repo_path: IdeaProjects/ai-swe-engine
source_commit: postgres:MRP-PR-78001
updated: 2026-09-15
---
```

**Incident:**
```yaml
---
id: INC-2026-08-26-h2-users-reserved
type: INC
status: resolved
source_repo_path: IdeaProjects/todo-springboot
source_commit: 59bb740
updated: 2026-09-15
---
```

**Meeting:**
```yaml
---
id: MTG-2026-09-15-obsidian-km
type: MTG
status: decided
source_repo_path: IdeaProjects/ai-swe-engine/docs/PROGRESS
source_commit: 69c93b9
updated: 2026-09-15
---
```
