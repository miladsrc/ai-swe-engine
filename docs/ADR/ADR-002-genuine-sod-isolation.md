# ADR-002 — Phase 2 must target genuine (real) Separation of Duties isolation, not only logical separation

**Status:** Accepted (decision made 2026-08-31; implementation NOT yet started)
**Type:** Architecture Decision Record + **TERMINAL HANDOFF / history for the next session**
**Owners:** m.barani (decision) · Sara (audit + authoring)
**Also logged in:** Sara persistent memory `~/.config/opencode/memory/sara.md`

> ⚠️ **NEXT TERMINAL MUST READ THIS HANDOFF FIRST.** See §13 (Handoff rules) before any implementation.

---

## 1. Current project state (as of this session)

| Attribute | Value |
|---|---|
| Repository | `ai-swe-engine` (C:\Users\m.barani\IdeaProjects\ai-swe-engine) |
| Branch | `main` |
| HEAD / latest commit | `69c93b9` (`docs: full sync — SoD design, dashboard, Phase 9, progress updates`) |
| Working tree | **DIRTY** (see uncommitted changes below) |
| Remote | github `miladsrc/ai-swe-engine` (main pushed at 69c93b9; uncommitted work below NOT pushed) |
| Test status | Full suite (all incl. live, API in strict): **121 passed, 3 skipped, 1 FAILED**. The 1 failure = `tests/test_traceability_chain.py::test_full_chain_and_gates` (expects pre-SoD evidence path). Non-live unit suite: **117 passed**. Dedicated G7 DB-free tests: **7 passed**. Live G7 API-layer test: **1 passed**. |
| Deployment/runtime | Docker: `ai-swe-engine-api-1` Up, `ai-swe-engine-postgres-1` Up (healthy). API rebuilt + restarted 2026-08-31 (35 min old at handoff). |
| SASE_SOD_MODE | **`strict`** — actively set in the running API container and in `docker-compose.yml` |
| Uncommitted changes | `agents/orchestrator.py`, `api/gates.py`, `api/models.py`, `api/routers/mrp.py`, `api/schemas.py`, `docker-compose.yml` (modified) + `migrations/005_mrps_verified_tree_hash.sql`, `tests/test_sod_g7.py` (untracked) |
| Live DB migration state | **migration 005 applied**: `mrps.verified_tree_hash` column present (confirmed via information_schema). Migration 004 (prompt registry) also applied. |

**Important:** None of the P0/P1 G7 work is committed yet. The next terminal must commit after confirming, per the owner's commit protocol (never commit unless explicitly requested).

---

## 2. What Phase 2 means

**Phase 2 = Separation of Duties (SoD).** The conflict-of-interest to remove: the Coder writing code must not also certify its own tests/security posture.

- **Human Identity** (users/tokens/login) was treated as an **interstitial milestone** (`docs/PHASES/HUMAN-IDENTITY.md`) and is **separate from** the current SoD Phase 2. It is complete and NOT part of this SoD scope.
- Phase 2 design doc: `docs/PHASES/PHASE-2.md` (steps A–H, gates G7/G8, increments I1/I2/I3, rollout flag `SASE_SOD_MODE`).

---

## 3. What has been completed

### Implemented + tests passing
- **`agents/verification.py`** / **I1** — orchestrator-owned verification steps: `tree_hash()` (`HEAD^{tree}`), `clean_checkout` git-worktree context manager, `run_tests_step` (fail-closed on drift), `run_scan_step`, `run_lint_step`; `StepResult` with `runner="orchestrator"`, `provenance="tool"`.
- **Proposal-only Coder path** — `CoderAgent.implement_spec(propose_only=True)`: generates, writes, commits, then STOPS (returns `verification_pending=True`; runs no tests/scan/lint, creates no MRP).
- **Strict orchestration path** — `orchestrator._run_code_phase_strict` + `_sod_verify_and_package` drive steps A–H behind `SASE_SOD_MODE`.
- **Provenance plumbing** — `AgentRunUpdate.status` Optional for proposal patches; prompt registry migration 004; evidence `execution_context{runner, provenance, tree_hash}`.
- **Migration 005** — `migrations/005_mrps_verified_tree_hash.sql` adds **`mrps.verified_tree_hash`** (text). **APPLIED to live DB.**
- **`verified_tree_hash` wiring** — `api/models.py` MRP column; `api/schemas.py` on `MRPCreate` + `MRPEvidenceUpdate`; `api/routers/mrp.py` `create_mrp` writes it; `orchestrator._sod_verify_and_package` sends `verified_tree_hash=tree` at MRP create.
- **G7 implementation** — `api/gates.py`: `_sod_strict()` (reads `SASE_SOD_MODE` at call time) + `_orchestrator_evidence_tree_hash(db, mrp)` (scans audit_log `update_mrp_evidence` for `execution_context.runner=="orchestrator"`, returns its tree_hash); `mrp_ready_for_merge` blocks (reasons `"verification not independently owned …"`) when: no bound hash, no orchestrator evidence, or tree-hash mismatch.
- **G7 regression tests** — `tests/test_sod_g7.py`: 7 DB-free gate-logic tests (coder self-cert reject, non-orch reject, wrong-hash reject, missing-hash reject, missing-evidence reject, match accept, legacy-inert) + 1 **live API-layer** test (full validated spec chain → coder evidence NOT ready → orchestrator evidence MATCHING → ready).
- **Strict-mode deployment** — `docker-compose.yml` `SASE_SOD_MODE: "strict"`; API image rebuilt + container restarted; confirmed `SASE_SOD_MODE=strict` in the running container.

### Important existing bypasses (NOT yet fixed)
- **SpringBoot standalone flow** — `python -m agents.coder_springboot` (its `__main__`, `coder_springboot.py:306`) calls `implement_spec` **without** `propose_only=True` → runs its own maven tests + `security_scan`, creates MRP, records evidence with **no orchestrator runner** → legacy self-certification path.
- **Designer flow** — `DesignerAgent` (`agents/designer_agent.py`) runs **no** verification at all, creates its own MRP; completely outside verification.py. `cod_designer` role in `config.py`.
- **Security scanner still lives in coder module** — `verification.py:20` imports `security_scan` from `agents/coder_agent.py`. (Deterministic/LLM-free, but architecturally coder-owned.)

---

## 4. What G7 means (exact definition to preserve)

**G7 = trusted verification evidence must come from the dedicated independent verification authority and must be bound to the exact code/tree being verified.**

- Evidence must be owned by the verifier identity (runner not coder/orchestrator) and bound to the exact tree.
- **Why tree hash exists:** the tree hash is the **fingerprint of the exact repository tree that was verified** — it prevents old/stale verification evidence from being reused after the code changes. G7 compares evidence `execution_context.tree_hash` to `mrps.verified_tree_hash`; a mismatch means the verified bytes are not the merged bytes → block.

---

## 5. What G8 means (exact definition to preserve)

**G8 = a genuine independent reviewer has examined the MRP and produced a traceable review.**

- G8 is **NOT** the human approval and **NOT** a reviewer-controlled merge decision.
- Reviewer findings remain **advisory**; the **human remains final authority**.
- Future G8 enforcement (not yet implemented): require `ai_review_status == "completed"` AND an audit record with `actor_id == agent:reviewer`.

---

## 6. Major architecture decision (this session — do NOT reverse)

We do **NOT** want "fake" agent separation where agents are merely Python classes/prompts running in the same control process (that's today's reality — see §7).

**Target = REAL but MINIMAL isolation.** Security-sensitive responsibilities get real execution + capability boundaries.

**Recommended minimum architecture:**
- **Coder/task agents** can propose/edit code but **cannot write trusted verification evidence**.
- **Verification** runs as a separate **subprocess/process** with its **own identity and credentials**.
- **Reviewer** runs as a separate **subprocess/process** with its **own identity and credentials**.
- **Orchestrator** coordinates workflow but **does NOT hold verifier credentials** and **does NOT write verifier evidence** (avoids becoming a privileged "god process" that creates AND certifies).
- **G7** validates verifier evidence + exact tree-hash binding.
- **G8** validates genuine reviewer presence/traceability.
- **Human** remains final approval authority.
- **No microservices / message bus / framework redesign** for now.

---

## 7. Important current finding (critical distinction)

**Today the agent layer is NOT genuinely isolated.**

- `ProductAgent` / `SpecAgent` / `CoderAgent` / `DesignerAgent` are mostly **classes/components inside the same orchestrator control process**.
- `verification.py` is **orchestrator-owned and in-process** today.
- **Reviewer Agent does not yet exist** (only a `reviewer` role in `config.py:67-74`).
- Separate **permissions/identities exist at the API boundary** (allowlists in `config.py` + `api/security.py` `require_ci_actor`/`require_human_actor`), but **execution authority is not fully separated**.
- Security scanner logic lives in `coder_agent.py`, imported by `verification.py`.
- SpringBoot standalone flow and Designer flow have **SoD bypass/legacy behavior**.

**Distinction to preserve:** *logical separation exists; genuine execution isolation does not yet fully exist.*

---

## 8. Agreed target architecture (store exact conceptual flow)

```
User
→ Orchestrator
→ Planner / task agents / Coder
→ Independent Verifier subprocess
→ G7
→ Independent Reviewer subprocess
→ G8
→ Human
→ Merge
```

**Responsibility rule:** `Coder ≠ Verifier ≠ Reviewer ≠ Human`

(Planner is optional/future; Product/Spec agents can remain low-risk components.)

---

## 9. What we should NOT do (explicit constraints)

- Do NOT redesign the whole architecture.
- Do NOT introduce microservices yet.
- Do NOT introduce LangGraph / message buses / new orchestration frameworks.
- Do NOT create fake in-process "agents" and call them independent.
- Do NOT delete/modify the existing demo MRPs **71577–71583** without explicit approval (owner is holding them).
- Do NOT start Phase 3 yet.
- Do NOT implement Reviewer Agent before the execution-boundary design is settled.
- Do NOT weaken G7 just to make old tests green (see §11 — fix the old test instead).

---

## 10. Immediate next work (priority sequence for next terminal)

**P0:**
1. Extract Verification into a genuine subprocess boundary.
2. Give verifier its own identity/token.
3. Ensure neither Coder nor Orchestrator can write verifier evidence.
4. Move `security_scan` into a neutral verification-owned module.
5. Make G7 trust verifier identity + tree hash.
6. Route all relevant code-generation variants (SpringBoot, Designer) through the same strict verification path.

**P1:**
7. Implement Reviewer as a separate subprocess.
8. Give Reviewer a narrow read-only / review-note-only permission set.
9. Implement G8 requiring a real reviewer identity/audit record + completed review.
10. Keep reviewer advisory; never make reviewer the final approver.

**P2:**
11. Make strict SoD the normal production path.
12. Run full strict-mode E2E.
13. Prove a real MRP reaches human review and approval.
14. Then reassess readiness for Phase 3.

---

## 11. Current G7 work status (explicit)

- G7 implementation **exists**.
- Migration 005 **exists and is applied** to the live DB.
- Dedicated G7 tests **pass** (7 DB-free + 1 live API-layer).
- Strict mode is **currently enabled** in the running deployment.
- The **full suite is NOT completely green** because the old `test_traceability_chain.py::test_full_chain_and_gates` still assumes the **pre-SoD** evidence path (its MRP has no `verified_tree_hash` / orchestrator evidence → G7 correctly blocks → 409).
- **That failing test should be UPDATED to the strict model, NOT weaken G7.**

---

## 12. Handoff storage / retrieval

Where this handoff is stored:
1. **Project ADR (primary, findable in-repo):** `docs/ADR/ADR-002-genuine-sod-isolation.md` — this file.
2. **Sara persistent memory:** `C:\Users\m.barani\.config\opencode\memory\sara.md` (appended 2026-08-31 entry with the same facts).

**Title:** ADR-002 — Phase 2 must target genuine (real) Separation of Duties isolation, not only logical separation
**Key:** `ADR-002-genuine-sod-isolation`
**Path:** `docs/ADR/ADR-002-genuine-sod-isolation.md`

---

## 13. Handoff rules for the next terminal

> **NEXT TERMINAL MUST READ THIS HANDOFF FIRST.**

The next session MUST:
1. Read this handoff / history (the two locations in §12).
2. Confirm the current git / DB / runtime state (§1) — verify HEAD, dirty files, containers, `SASE_SOD_MODE=strict`, migration 005 applied.
3. Summarize the architecture decision (§6, §8) back to the user.
4. **Do NOT start implementation until the current state is re-confirmed** with the user.
5. Continue from the agreed **P0/P1** sequence (§10) once confirmation is given.
6. Follow the standing rules: never commit unless asked; propose destructive/DB/schema changes before acting; keep the Architectural Preservation Rule (§9, ADR-001) intact.

---

## 14. Step 2B — Genuine Remote Verifier Execution Boundary (addendum, 2026-08-31)

### Verdict
**Genuine remote boundary: `BLOCKED`.** No implementation performed on this
machine satisfies the genuine threat model. Reason: every verifier execution
context available here (a local GitLab runner, a Docker container) runs under
the **same local administrator** `m.barani` who is in `BUILTIN\Administrators`
and controls the Docker daemon. That principal could `docker inspect` the
runner/verifier container, read the verifier credential, and forge verifier
evidence — collapsing the segregation of duties. A genuine boundary requires a
**separately-administered** remote runner / VM / GitLab that `m.barani` cannot
administer, which is not present on this machine.

### Approved scope (user decision): local DEV/CONTAINMENT harness only
The local GitLab CE + Docker runner created for this work is a **dev /
containment harness** — clearly labeled — to exercise the protocol, the
secret-delivery path, and its security tests. It is **NOT** represented as (nor
tested as) a genuine security boundary, and it carries **test-only** secrets
(no production credentials).

### What was built (Step 2B implementation)
- `VerificationRequest` model + `migrations/006_verification_requests.sql`
  (idempotent by `run_id`, atomically claimed, TTL fail-closed).
- API router `api/routers/verification_requests.py`:
  - `POST /verification-requests` (any actor) — enqueue immutable request;
  - `GET /verification-requests/{id}/status` (any actor) — non-secret status;
  - `POST /verification-requests/claim-next` (verifier-only, atomic) — claim;
  - `POST /verification-requests/{id}/complete` (verifier-only) — finish.
  The Orchestrator can create + read; **only** `ci:verifier` + its own token
  can claim/complete.
- `agents/verifier.py` gained a **runner mode** (`--claim`): claims a pending
  request, verifies the pinned commit in a clean checkout, computes the
  authoritative tree hash, writes evidence as `ci:verifier`, completes the
  request. Stdin-subprocess mode retained as the dev/legacy path.
- `agents/orchestrator.py::_sod_verify_and_package` is now a **coordinator**:
  enqueues a request, arranges a verifier runner, polls terminal status,
  reads the authoritative tree hash back. It never holds the verifier
  credential (asset by tests).
- `.gitlab-ci.yml` — contained verifier job (tagged `sod-verifier`) that
  reads a Protected+Masked test-only `SASE_VERIFIER_TOKEN` and runs the
  runner mode. Harness-only.
- Tests `tests/test_sod_remote_boundary.py` (authority isolation, request
  lifecycle security, TTL fail-closed, and the same-user/local-admin-not-
  genuine demonstration) + updated AST tests in `tests/test_sod_verifier.py`.

### Proven / NOT proven
**Proven:** the request protocol, atomic claim, credential/authority split,
TTL fail-closed, and that a same-user/local-admin context is demonstrably NOT
a genuine boundary.
**NOT proven:** a genuine remote-runner integration test (no separate infra) —
the local runner proves protocol mechanics only. The remote-runner test is
intentionally NOT faked. Genuine boundary remains **BLOCKED** until
separately-administered remote runner/VM/GitLab infra is provided.
