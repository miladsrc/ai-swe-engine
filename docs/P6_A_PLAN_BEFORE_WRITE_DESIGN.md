# P6-A Design: Plan-Before-Write (Passive)

Status: **DESIGN ONLY — NOT IMPLEMENTED, NOT ENFORCED.**
Approved for documentation 2026-08-26. Enforced plan approval (**P6-B**)
requires explicit human approval and is **not** scheduled yet.

Reference inspiration: Coder's plan-mode (writes confined to a plan area,
implementation blocked until a human clicks "Implement"). Pattern adopted;
no Coder code or infrastructure (Terraform/workspaces) is used.

---

## 1. Problem

Today the coder agent's flow is:

```
validated Spec -> LLM emits FILE blocks -> written to disk IMMEDIATELY
              -> pytest loop -> commit -> MRP -> human review
```

The first human-visible artifact of generated code is the MRP — created
AFTER files exist on disk and after tests ran. A malicious or confused
model output reaches the workspace before any governance artifact can be
inspected. Everything else in SASE is "human verdict before irreversible
step"; writing into the workspace is currently the one ungated write.

## 2. Target flow (when both phases land)

```
Requirement -> Spec (human gate) -> AgentRun starts
    -> PLAN: parsed FILE blocks stored as a reviewable diff preview
    -> [P6-B only] human approves plan (new gate)
    -> implementation (files written) -> tests -> commit -> MRP
```

## 3. Phase A — passive (this document; no behavior change)

Phase A adds NO gate and changes NO execution order. It only makes the
plan *visible* by persisting what already exists in memory today:

- `CoderAgent.implement_spec` parses FILE blocks into `files` dict.
- That dict is ALREADY summarized into `CoderResult.generated_files`.
- Phase A would additionally attach a `plan` payload — per-file unified
  diff or file list + sizes — to the MRP evidence context via the P7
  `execution_context` channel (audit JSONB), so every MRPs' audit trail
  shows exactly which writes were proposed.

Implementation sketch (smallest path):
1. In `coder_agent.py`, build `execution_context["proposed_files"] =
   {path: len(content)} ` (or diffs) next to existing fields.
2. No schema change, no endpoint change, no new table.

Guarantees: forensic visibility ("what did the model propose before it
wrote?"). Zero risk to existing flows.

## 4. Phase B — enforcing (REQUIRES SEPARATE APPROVAL; not built)

Only after Phase A is running in production-like use:

1. New optional env flag `SASE_REQUIRE_PLAN_APPROVAL` (default off).
2. One new endpoint following the existing CRP/human-decision idiom:
   `POST /agent-runs/{id}/plan-approval` guarded by
   `require_human_actor` (api/security.py).
3. One gate function in `api/gates.py`, checked at run start of the
   write phase: if flag set and no recorded approval for the run ->
   agent stops after drafting and prints the plan + approval curl.
4. The agent's `_write_files` call is skipped until approval exists.

What Phase B deliberately does NOT do:
- It does not add a new artifact type/table (the AgentRun + audit log
  carry the plan and the decision).
- It does not change any existing phase boundary in MASTER_PLAN.md.
- It introduces no new framework.

Trade-offs:
- (+) closes the last ungated write; consistent with §3.5/§3.6.3 spirit.
- (-) adds one human round-trip per coding run when enabled.
- (-) qwen-7b repair loops need plan re-approval or an explicit
  "repair within approved plan" rule (design decision deferred).

## 5. Recommendation

Implement Phase A opportunistically with the next coder-agent change
(few lines, rides the P7 channel). Decide on Phase B separately after
Phase A evidence has been observed in real runs.
