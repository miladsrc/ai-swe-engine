# .ai-engineering/ — human-readable artifact mirror

Every row in the Postgres tables (`migrations/001_init.sql`) has a
corresponding file here, referenced by that row's `body_ref` column.
Postgres is the queryable source of truth for *relationships between*
artifacts (traceability, gating); these files are the readable source
of truth for the *content* of one artifact.

| Directory | Contains | ID pattern |
|---|---|---|
| `prd/` | Product Requirement Documents | `PRD-<DOMAIN>-<seq>.md` |
| `user-stories/` | User Stories | `US-<DOMAIN>-<seq>.md` |
| `acceptance-criteria/` | Acceptance Criteria | `AC-<us-id>-<seq>.md` |
| `specs/` | Machine-readable Specs (OpenSpec/spec-kit) | `SPEC-<DOMAIN>-<NAME>.yaml` |
| `blueprints/` | **Project-scoped** Blueprint overrides only — stack-wide and org-wide Blueprints live in `/blueprints/` at the repo root, not here | `BP-<LAYER>-<seq>.md` |
| `prompts/` | Versioned prompt templates | `prompt-<purpose>-v<version>.md` |
| `agent-runs/` | Agent Run Records | `RUN-<MODEL>-<year>-<seq>.yaml` |
| `crp/` | Consultation Request Packs | `CRP-<DOMAIN>-<year>-<seq>.yaml` |
| `mrp/` | Merge-Readiness Packs | `MRP-PR-<n>.yaml` |
| `resolutions/` | Version Controlled Resolutions | `VCR-<related-artifact-id>.yaml` |
| `evaluations/` | Evaluation run results | `EVAL-<name>.yaml` |

Nothing writes here automatically yet — until the agents exist (roadmap
step 5+), populate these by hand to match whatever you create through
the API, so `body_ref` values actually resolve to something real.
