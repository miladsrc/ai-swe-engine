---
id: SPEC-SPEC-xxx
type: SPEC
status: draft
source_repo_path: IdeaProjects/ai-swe-engine
source_commit: postgres:SPEC-xxx
updated: 2026-09-15
---

# SPEC-SPEC-xxx — Title

> [!WARNING] Read-only / Non-SoT — SoT is Postgres (`specs` table) + `GET /specs/{id}` + Git. This card is a reference; do not paste the SPEC body.

## Summary (knowledge — write here)

Explanatory summary: intent, key components, and validation state. Mention `human_validated` and gate G1 without duplicating the body.

## SoT References (do not paste body)

- **DB table:** `specs` — `id=SPEC-xxx` — `project_id=...` — `human_validated: true/false` — `human_validated_by/at`
- **API:** `GET /specs/SPEC-xxx` · `POST /specs/{id}/validate` (requires `require_human_actor` Bearer)
- **Gate:** `api/gates.py:spec_must_be_human_validated_before_code_gen`
- **Repo path:** `IdeaProjects/ai-swe-engine/api/routers/requirements.py`
- **Commit:** `source_commit` in frontmatter

## Traceability Links

- PRD:: [[PRD-PRD-xxx]]
- US:: [[US-US-xxx]]
- AC:: [[AC-AC-xxx]]
- RUN:: [[RUN-RUN-xxx]]
- MRP:: [[MRP-MRP-PR-xxx]]

## Validation

- Validated by: `human:m.barani` (from `specs.human_validated_by`)
- Validated at: `2026-xx-xx` (from `specs.human_validated_at`)
- API proof: `GET /specs/SPEC-xxx` shows `human_validated: true`

## Context & Decisions

- Related ADR:: [[ADR-ADR-xxx-title]]
- Related Incident:: [[INC-yyyy-mm-dd-slug]]

## Lessons / Notes

- What was clarified during spec review; open questions that were resolved.
