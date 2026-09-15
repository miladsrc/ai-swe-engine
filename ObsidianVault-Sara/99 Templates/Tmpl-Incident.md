---
id: INC-yyyy-mm-dd-slug
type: INC
status: open
source_repo_path: IdeaProjects/ai-swe-engine
source_commit: 69c93b9
updated: 2026-09-15
---

# INC-yyyy-mm-dd-slug — Title

## Summary

One-paragraph summary of the incident: symptom, impact, and resolution state.

## Timeline

| When | What | Source |
|---|---|---|
| 2026-xx-xx HH:MM | Symptom observed | `source_repo_path` + log/API |
| 2026-xx-xx HH:MM | Investigation step | `api/...:line` |
| 2026-xx-xx HH:MM | Fix applied | `git show <sha>` |

## Root Cause (RCA)

- **Cause:** ...
- **Why it happened:** ...
- **Why it was not caught:** ...

## Fix

- **SoT reference:** `IdeaProjects/ai-swe-engine/...` · `git show <sha> --stat` · `migrations/xxx.sql:line`
- **Vault note:** Explain the fix conceptually; do not paste migration SQL or full diff. Link to commit/SHA.

## Verification

- Tests: `pytest ...` — result
- API proof: `GET /...` — result
- Audit: `GET /traceability/audit/...`

## Related

- SPEC:: [[SPEC-SPEC-xxx]]
- RUN:: [[RUN-RUN-xxx]]
- MRP:: [[MRP-MRP-PR-xxx]]
- ADR:: [[ADR-ADR-xxx-title]]

## Lessons Learned

- What to watch for next time.
- What to add to `40 Knowledge/` as troubleshooting.

## Follow-ups

- [ ] Action item 1
- [ ] Action item 2
