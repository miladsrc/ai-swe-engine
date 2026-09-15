---
id: PRD-PRD-xxx
type: PRD
status: draft
source_repo_path: IdeaProjects/ai-swe-engine
source_commit: postgres:PRD-xxx
updated: 2026-09-15
---

# PRD-PRD-xxx — Title

> [!WARNING] Read-only / Non-SoT — SoT is `IdeaProjects/ai-swe-engine` Postgres (`prds` table) + `GET /prds/{id}`. This card is a reference and knowledge wrapper.

## Summary (knowledge — write here)

One-paragraph explanatory summary: what problem this PRD solves, why it matters, and what is out of scope. Keep it conceptual; do not paste the SoT PRD body.

## SoT References (do not paste bodies)

- **Repo path:** `IdeaProjects/ai-swe-engine/api/routers/requirements.py` (POST /prds)
- **DB table:** `prds` — `id=PRD-xxx` — `project_id=...`
- **API:** `GET /prds/PRD-xxx` · `GET /traceability/chain/{mrp_id}` (downstream)
- **Commit:** `source_commit` in frontmatter (Git SHA or `postgres:PRD-xxx`)

## Traceability Links

- US:: [[US-US-xxx]]
- AC:: [[AC-AC-xxx]]
- SPEC:: [[SPEC-SPEC-xxx]]
- RUN:: [[RUN-RUN-xxx]]
- MRP:: [[MRP-MRP-PR-xxx]]

## Context & Decisions

- Related ADR:: [[ADR-ADR-xxx-title]]
- Related Incident:: [[INC-yyyy-mm-dd-slug]]
- Meeting:: [[MTG-yyyy-mm-dd-topic]]

## Lessons / Notes

- What was learned, what to watch for.
