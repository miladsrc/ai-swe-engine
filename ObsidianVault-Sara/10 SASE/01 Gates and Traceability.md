---
id: SASE-GATES-TRACEABILITY
type: knowledge
status: active
source_repo_path: IdeaProjects/ai-swe-engine/api/gates.py
source_commit: 69c93b9
updated: 2026-09-15
---

# Gates and Traceability — Conceptual Map

> Knowledge note. Enforcement lives in `api/gates.py` and `api/security.py`. This note explains, it does not enforce.

## The Chain

```
Project
  └─ PRD (requirements/PRD)
       └─ US (User Story)
            └─ AC (Acceptance Criteria)
                 └─ SPEC (id: SPEC-xxx, human_validated: bool)
                      └─ AgentRun (id: RUN-xxx, status: running|completed|blocked|failed)
                           ├─ CRP (id: CRP-xxx, severity, status: open|resolved|blocking)
                           └─ MRP (id: MRP-PR-xxx, verified_tree_hash, ai_review_status)
                                └─ VCR (resolves CRP, human decision)
                                     └─ Audit (append-only, hash-chained)
```

API to reconstruct: `GET /traceability/chain/{mrp_id}` returns `fully_traceable` only when gates pass.

## Gates (from `api/gates.py:mrp_ready_for_merge`)

| Gate | Check | Source |
|---|---|---|
| G1 | `spec_must_be_human_validated_before_code_gen` — SPEC must have `human_validated=true` before AgentRun | `gates.py` |
| G2 | `agent_run_must_exist_for_generated_code` | `gates.py` |
| G3 | MRP has `spec_ids`, `blueprint_version`, tests pass, security pass | `gates.py` |
| G4 | No open `high`/`critical` CRP blocking merge (live query, not stale snapshot) | `gates.py:no_open_high_or_critical_crp_blocks_merge` |
| G7 | **SoD strict:** `verified_tree_hash` present + verifier evidence `runner==ci:verifier` + hash match via `audit_log` | `gates.py:_verifier_evidence_tree_hash` |
| G8 | **Review strict:** `ai_review_status==completed` + audit actor `agent:reviewer` | `gates.py:_reviewer_completed_review` |

- `SASE_SOD_MODE=strict` enables G7/G8. Legacy mode = gates inert.
- Verifier identity: `ci:verifier` + `SASE_VERIFIER_TOKEN` (`api/security.py:require_verifier_actor`)
- Reviewer identity: `agent:reviewer` + `SASE_REVIEWER_TOKEN` (`api/security.py:require_reviewer_actor`)

## Traceability in Obsidian

- **SoT:** Postgres (`agent_runs`, `mrps`, `crps`, `vcrs`, `audit_log`) + Git commits.
- **Vault:** `20 Traceability/` cards are **read-only references**. They store IDs, repo paths, commit SHAs, API identifiers, and links — not bodies.
- **Linking:** Use wikilinks `[[PRD-PRD-xxx]] → [[SPEC-SPEC-xxx]] → [[RUN-RUN-xxx]] → [[MRP-MRP-PR-xxx]]`. Dataview can query `type: MRP` cards.

Example: `[[20 Traceability/MRP-MRP-PR-78001|MRP-PR-78001]]` chains `PRD-TODO-008 → SPEC → RUN-QW-2026-00011 → MRP-PR-78001`.

## What Stays Out of the Vault

Never paste: SPEC bodies, MRP evidence blobs, CRP/VCR rows, migration SQL, generated code. Link:

- SPEC body → `GET /specs/{id}` or `IdeaProjects/ai-swe-engine/...`
- MRP evidence → `PATCH /mrps/{id}/evidence` + `GET /evidence/run/{run_id}`
- CRP/VCR → `GET /crps/{id}`, `GET /vcrs/{id}`
- Commit → `git show <sha> --stat`
