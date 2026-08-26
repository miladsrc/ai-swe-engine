# AI-SWE-ENGINE MASTER DEVELOPMENT PLAN

**Version:** 1.1
**Date:** 2026-08-25 (v1.1 status sync 2026-08-26)
**Status:** Phase 0 COMPLETE; Phase 1 COMPLETE; hardening batch + interstitial Human Identity milestone COMPLETE; Phase 2 (Separation of Duties) next

---

## 1. Product Definition

### 1.1 Product Identity

ai-swe-engine is a human-governed, air-gapped Autonomous Software Engineering Engine: a deterministic orchestration and governance system that uses local LLMs (via Ollama) as generative subordinates to carry a human-authored software requirement through planning, specification, coding, testing, security validation, evidence generation, and human-gated merge - fully operable offline, with no cloud AI or external assistant dependency at runtime.

### 1.2 Mission

Let a human describe a software requirement in natural language and receive a working, tested, security-scanned, auditable code change - where every irreversible decision requires explicit human approval, and every LLM output is treated as an unverified proposal until it passes a deterministic check.

### 1.3 Non-Goals

- Not a general-purpose chatbot or ad hoc coding assistant.
- Not a substitute for human judgment on intent-level correctness - it verifies mechanical correctness (tests pass, scans clean), not did we build the right thing.
- Not, anywhere in this roadmap, an unattended system for large or security-sensitive changes.
- Not dependent on Sara, or any external AI, for runtime operation.
- Not a cloud service - no design assumption of internet connectivity, ever.

### 1.4 Core Principles (Non-Negotiable)

1. Sara is external, advisory-only, never a runtime dependency. If Sara disappears, the engine keeps running.
2. The engine is the product. It must run offline, air-gapped, on local LLMs, with deterministic governance, with no cloud AI dependency.
3. The human is final authority over requirement acceptance, spec approval, dependency additions, security exceptions, architecture changes, and merge approval.
4. LLMs generate; deterministic software governs. State transitions, permissions, evidence, validation, policy, merge gates, and audit are never delegated to model judgment.

### 1.5 Trust Boundaries

- Outer boundary - Human <-> Sara: advisory only, no execution rights in either direction.
- Air-gap boundary: everything inside must function with zero internet access.
- Inner boundary - LLM output <-> Governance Engine: no LLM output becomes approved or true without passing a deterministic gate.

### 1.6 Security Model

- Least trust for LLM output: every LLM output is an untrusted proposal until verified.
- Separation of duties: the component that produces an artifact is never the component that certifies it.
- Immutable, provenance-tagged evidence: every fact in the audit trail is tagged human / deterministic-tool / LLM-sourced.
- Fail-closed gates: missing or ambiguous evidence blocks progress; it never defaults to proceed.

### 1.7 Is / Is Not

| This product IS | This product is NOT |
|---|---|
| An offline governance + orchestration engine that turns requirements into reviewed, evidence-backed code changes | An autonomous agent trusted by default |
| A system where autonomy expands only as reliability evidence accumulates | A cloud-dependent AI coding tool |
| A system where LLMs propose and deterministic code decides | A system where LLM confidence substitutes for proof |
---

## 2. Final Target Architecture

`
                          HUMAN
                    approves / reviews
                     /              \\
              consults              operates
                  |                     |
                  v                     v
                SARA          AIR-GAPPED ai-swe-engine
        (external, advisory,        |
         read-only evidence      Orchestrator (deterministic
         access, zero write/      control loop / state machine)
         execution rights)            |
                                +-----+-----+---------+----------+
                                v     v     v         v          v
                            Product  Spec  Coder    Test      Security
                             Agent  Agent  Agent    Agent      Agent
                              (LLM) (LLM)  (LLM)   (det. exec, (det. scan
                                |     |      |      LLM-authored + LLM
                                |     |      |       tests)    narrative)
                                +-----+--+---+----------+----------+
                                         v
                                  Reviewer Agent (LLM,
                                  risk narrative only -
                                  never the decision)
                                         |
                                         v
                                  Ollama (local LLM backend)
                                         |
                          +--------------+--------------+
                          v              v               v
                     PostgreSQL       Qdrant          Redis
                    (system of      (semantic /       (conditional -
                     record)        project memory)   coordination only)
                          |
                          v
                Governance Engine (deterministic:
                 state machine, MRP / CRP / VCR,
                 policy enforcement)
                          |
                          v
                 Evidence Store (immutable,
                  provenance-tagged)
                          |
                          v
              Merge Gate (deterministic) -> Safe Merge
`

### Component Responsibilities

| Component | Type | Responsibility | Trust Level |
|---|---|---|---|
| Human | External | Final authority on all irreversible decisions | Authoritative |
| Sara | External | Architecture advice, documentation help, review of exported evidence | Advisory, zero execution rights |
| Orchestrator | Deterministic code | Sequences agents, invokes gates, owns retry/failure logic | Trusted |
| Product / Spec Agents | LLM | Turn requirement into structured spec + acceptance criteria (proposals) | Untrusted until gated |
| Coder Agent | LLM | Writes code against an approved spec (proposal) | Untrusted until gated |
| Test execution | Deterministic process | Runs tests, reports pass/fail as fact | Trusted (ground truth) |
| Security Agent | Deterministic scan + LLM narrative | Scan result is fact; narrative is advisory | Scan trusted, narrative untrusted |
| Reviewer Agent | LLM | Produces risk narrative for human review | Untrusted, advisory only |
| Ollama | Infrastructure | Local inference backend for all agent LLM calls | N/A |
| PostgreSQL | Deterministic store | System of record: runs, evidence, decisions, audit | Trusted |
| Qdrant | Deterministic store | Semantic/project memory for retrieval-grounded generation | Retrieval trusted, generated output using it is not |
| Redis | Deterministic store (conditional) | Ephemeral coordination only | Trusted, non-authoritative |
| Governance Engine | Deterministic code | State machine, MRP/CRP/VCR, policy enforcement | Trusted |
| Evidence Store | Deterministic, immutable | Provenance-tagged record of what happened | Trusted |
| Merge Gate | Deterministic code | Final authorization check | Trusted |
---

## 3. Development Phases

### PHASE 0 - Foundational Agent Loop

**Goal:** Prove an offline, LLM-backed engineering loop can run end-to-end with basic governance.

**Why this phase exists:** Without a working baseline loop, no governance or autonomy work has anything to attach to.

**Current problem solved:** Upstream agent prompts were poor (Qwen behaved like a chatbot); no real coding agent existed; no end-to-end offline proof existed.

**Architecture changes:** Introduced agents/prompts.py, agents/coder_agent.py, agents/coder_prompts.py; refactored orchestrator to stop bypassing SpecAgent.

**New components:** ProductAgent + SpecAgent prompts with worked examples; CoderAgent; _enforce_ac_refs governance post-processor.

**Changed components:** Orchestrator (no more inline one-liner bypass); US/AC endpoints (fixed empty-context body_ref bug).

**Dependencies:** Ollama running Qwen; PostgreSQL; existing MRP/CRP/VCR scaffolding.

**Security impact:** Established the pattern of a governance post-processing layer (AC-reference enforcement) - first instance of deterministic code checks LLM output.

**Human approval points:** Merge approval (exercised once, successfully).

**Implementation tasks:** Prompt engineering; orchestrator refactor; bug fixes; CoderAgent build-out; docs rewrite; docker-compose Ollama scaffolding.

**Tests required:** Unit tests for agents and endpoints; full run test (offline loop end-to-end).

**Success criteria:** A real requirement produces real files, passing tests, passing security scan, and a merged commit - achieved (RUN-QW-2026-00009, commit c8790ed5).

**Definition of Done:** 58 tests passing, clean working tree, one full successful run on record, docs updated.

**Status:** COMPLETE.

**Possible future improvements:** Expand worked examples as new failure modes are discovered; this phases governance pattern (_enforce_ac_refs) should be the template for every future agent-output check.

---

### PHASE 1 - Governance Integrity Hardening

**Goal:** Close known integrity gaps before adding any further capability.

**Why this phase exists:** Two governance-critical bugs are already known. Building memory, autonomy, or new agents on top of an unverified governance layer means every future phase inherits unverified trust.

**Current problem solved:** CRP endpoint bypassing the terminal-state guard; open_crp_ids snapshot missing CRPs raised after MRP creation; no provenance tagging on evidence; no way for Sara to review results without manual log copying.

**Architecture changes:** Add provenance field (source: human | tool | llm) to every evidence record; make evidence append-only; add a read-only evidence/report export endpoint.

**New components:** Evidence provenance schema; read-only export API (for Saras advisory role).

**Changed components:** CRP endpoint (enforce assert_run_patchable unconditionally); CRP snapshot logic (include CRPs raised after MRP creation).

**Dependencies:** None beyond existing PostgreSQL.

**Security impact:** High - this phase closes the only known ways the governance layer can currently be bypassed or show a misleading state.

**Human approval points:** Sign-off that both known bugs are verifiably closed (with a regression test proving the bypass path now fails correctly).

**Implementation tasks:** Fix both bugs; add provenance column/logic to evidence writes; build export endpoint; write regression tests reproducing the original bugs.

**Tests required:** Regression test that attempts the CRP bypass and asserts it is rejected; regression test with a CRP raised post-MRP-creation, asserting it appears in open_crp_ids; provenance-tag assertion tests on every evidence-writing code path.

**Success criteria:** Both bugs have failing-then-passing regression tests; every evidence record has a non-null provenance tag; export endpoint returns a runs full evidence trail read-only.

**Definition of Done:** All above tests merged and passing; no evidence-writing path in the codebase lacks a provenance tag (verified by a lint/check rule, not manual review).

**Status:** COMPLETE (2026-08-25). Both bugs closed with regression tests; provenance tagging on evidence; read-only evidence export endpoint (`GET /evidence/run/{id}`); commits 13f61a5 + 367a5d7. Follow-up hardening batch (2026-08-26): fail-closed CI token, orphan-run reaper, evidence persistence, blueprint audit, LLM retry, surgical staging, language-aware scan — see CHANGELOG.

**Possible future improvements:** Move evidence storage to a genuinely append-only construct (e.g., write-once table constraints or a hash-chained log) once volume justifies it.
---

### INTERSTITIAL MILESTONE - Human Identity (approved 2026-08-24/26, COMPLETE)

NOT a numbered phase - an approved security workstream executed between
Phase 1 and Phase 2 because every later phase depends on trustworthy human
identity at the gates. Scope: users + api_tokens tables (migration 003),
PBKDF2 password hashing, bearer tokens (sha256-at-rest), POST /auth/login +
/auth/me, authoritative Bearer identity in require_human_actor,
SASE_REQUIRE_HUMAN_TOKEN fail-closed flag (currently OFF), full token-flow
migration of tests/docs/tooling incl. live gate-proof trio.
Full record: docs/PHASES/HUMAN-IDENTITY.md. Commits: 3e0d294, a2ed450 (8e08cc1).

---

### PHASE 2 - Separation of Duties

**Status:** Planned - NEXT UP. (Note: the completed Human Identity
milestone above is NOT this phase; separation of duties has not started.)

**Goal:** Remove the conflict of interest where the Coder Agent both writes code and certifies its own tests.

**Why this phase exists:** An agent should never be the sole judge of its own output - this is the same principle that keeps Sara outside the engine, applied one layer down.

**Current problem solved:** CoderAgent currently reads specs, writes files, and runs pytest and the security scan itself.

**Architecture changes:** Test execution and security scanning move to steps invoked directly by the Orchestrator, not by the Coder Agent; Coder Agents role narrows to produce code + proposed tests.

**New components:** Independent Test-execution step (deterministic, orchestrator-invoked); formalized Security Agent boundary (deterministic scan step + separate LLM narrative call).

**Changed components:** agents/coder_agent.py (remove direct pytest/scan invocation); Orchestrator (add explicit test/scan steps between Coder Agent output and MRP).

**Dependencies:** Phase 1s provenance tagging (so its visible in evidence who ran the test - orchestrator, not the agent that wrote the code).

**Security impact:** Medium-high - removes a structural self-attestation risk without requiring any change to the underlying tools.

**Human approval points:** None new - this is an internal integrity change, not a new decision point.

**Implementation tasks:** Extract test/scan invocation from CoderAgent into orchestrator-owned steps; update evidence schema so provenance reflects orchestrator-run, not agent-run; add Reviewer Agent as an explicit, separate LLM call producing risk narrative only.

**Tests required:** Test proving Coder Agent output alone cannot mark a run as tested/scanned; test proving orchestrator-run steps populate evidence with correct provenance.

**Success criteria:** No code path exists where CoderAgents own process determines pass/fail; Reviewer Agent exists as a distinct call in the trace.

**Definition of Done:** Architecture diagram and code agree; a code review confirms no agent certifies its own output.

**Status:** see heading note above - Planned, next up.

**Possible future improvements:** Same separation-of-duties principle should be applied to any future agent that both proposes and would otherwise self-verify (e.g., a future Refactor Agent).

---

### PHASE 3 - Semantic Memory Integration (Qdrant)

**Goal:** Ground agent generation in real project/repo context instead of relying purely on prompt content.

**Why this phase exists:** Without retrieval, agents can only reason about what fits in a single prompt - this is the primary cause of plausible but wrong output on anything beyond a toy example.

**Current problem solved:** No project or repository memory exists; every run effectively starts cold.

**Architecture changes:** Stand up Qdrant; add an indexing pipeline (repo to embeddings); wire retrieval calls into Product, Spec, and Coder Agents.

**New components:** Qdrant service; indexing job/pipeline; retrieval interface used by agents.

**Changed components:** Product/Spec/Coder Agent prompts (now include retrieved context); Postgres schema (add structured project-fact tables alongside Qdrants embeddings).

**Dependencies:** A real, non-trivial repository to index (the current todo.py-sized examples wont stress-test this meaningfully).

**Security impact:** Low directly, but retrieval quality becomes a new failure mode to monitor.

**Human approval points:** None new.

**Implementation tasks:** Deploy Qdrant (docker-compose, uncommented); build indexing pipeline; integrate retrieval into agent prompt construction; instrument how often retrieved context is used vs. ignored by the model.

**Tests required:** Retrieval correctness tests (does the right file get retrieved for a given query); agent-output-quality tests comparing with/without retrieval on a fixed task set.

**Success criteria:** Measurable reduction in human-review rejections at the spec/final-review checkpoint attributable to better-grounded generation.

**Definition of Done:** Qdrant is a required, always-on service (moved out of commented out in docker-compose); retrieval is used by all three agents; a before/after quality comparison exists in evidence.

**Status:** Planned.

**Possible future improvements:** Expand indexing to include past run outcomes (episodic memory) so retrieval surfaces we tried this before and it failed because X.

---

### PHASE 4 - Bounded Self-Repair (L1 Autonomy)

**Goal:** Let the engine retry and correct itself within a run, without requiring a human for every failure.

**Why this phase exists:** Currently a single test or scan failure presumably halts the run; real engineering iterates.

**Current problem solved:** No feedback loop exists between a failing test/scan and a revised attempt.

**Architecture changes:** Orchestrator gains a bounded retry loop: on test/scan failure, feed the failure back to the Coder Agent with a fixed attempt limit before escalating to a human.

**New components:** Retry/attempt-tracking logic in the Orchestrator; repair attempt record type in evidence.

**Changed components:** Evidence schema (record each attempt, not just the final one); Governance Engine (recognize in bounded repair as a distinct run state).

**Dependencies:** Phase 2 (separation of duties) should exist first, so repair attempts dont reintroduce self-attestation.

**Security impact:** Medium - an infinite or excessive retry loop is itself a risk (resource exhaustion, repeated exposure to a bad approach); the attempt limit must be a hard, deterministic cap.

**Human approval points:** Merge approval remains required regardless of how many repair attempts occurred; a run that exhausts its retry budget must escalate to a human, not silently fail closed with no notification.

**Implementation tasks:** Add attempt counter and cap to run state; wire failure context back into Coder Agents next prompt; add escalation path when the cap is hit.

**Tests required:** Test that a run stops retrying at the cap; test that every attempt (not just the last) is recorded in evidence; test that escalation actually notifies/surfaces to the human.

**Success criteria:** A deliberately-broken first attempt self-corrects within the retry budget on a controlled test case, and evidence shows the full attempt history.

**Definition of Done:** L1 is formally reachable and demonstrated on at least 3 distinct induced-failure scenarios.

**Status:** Planned - this is the point at which the system first exercises autonomy above L0.

**Possible future improvements:** Make the retry cap adaptive based on task complexity once enough run history exists to justify it (Phase 8 territory, not now).
---

### PHASE 5 - Coordination Layer (Redis) - Conditional

**Goal:** Add ephemeral coordination infrastructure - only if and when its actually needed.

**Why this phase exists:** Redis appears in the current roadmap without a justified responsibility. This phase exists to name the trigger condition, not to mandate the work.

**Current problem solved:** None yet - there is no current concurrency problem. This phase is a placeholder with an explicit go/no-go gate, not a commitment.

**Trigger condition (go/no-go):** Only proceed if the engine needs to support multiple concurrent runs requiring distributed locks or queues, or a caching need emerges with measured latency pressure that Postgres cant satisfy. If neither condition is real by the time Phase 4 is done, skip this phase and revisit later.

**Architecture changes (if triggered):** Add Redis for run-locking, inter-agent task queues, and short-TTL caches.

**New components (if triggered):** Redis service; lock/queue abstraction used by the Orchestrator.

**Changed components (if triggered):** Orchestrator (coordination calls); nothing else - Redis must never become a source of truth.

**Dependencies:** A real concurrent-run requirement.

**Security impact:** Low if scoped correctly (ephemeral only); high if misused as durable state.

**Human approval points:** None new.

**Implementation tasks (if triggered):** Deploy Redis; implement locks/queues; add a hard rule that nothing written to Redis is ever the only copy of a fact.

**Tests required (if triggered):** Test that losing Redis mid-run degrades gracefully (falls back to serialized/sequential behavior) rather than corrupting state.

**Success criteria:** Concurrent runs no longer race on shared resources; Postgres remains authoritative for everything Redis touches.

**Definition of Done:** Redis, if added, is provably non-authoritative - the system can lose it and recover without data loss, verified by a chaos-style test.

**Status:** Deferred pending justification - do not implement speculatively.

---

### PHASE 6 - Limited Safe Automation (L2 Autonomy)

**Goal:** Allow unattended merges for a narrow, deterministically-defined class of low-risk changes.

**Why this phase exists:** This is the first point where removing a human gate is actually justified - but only for a class of change small and well-understood enough that deterministic checks can be trusted as sufficient.

**Current problem solved:** Every merge currently requires a human, even for trivial, fully-covered, non-security-path changes.

**Architecture changes:** Define an explicit, code-enforced safe change class policy (e.g., single file, no security-sensitive path touched, full test coverage, no new dependencies); Governance Engine gains an L2 merge path that checks this policy and merges without human sign-off when satisfied.

**New components:** Change-classification policy engine (deterministic); L2 merge path in the Merge Gate.

**Changed components:** Merge Gate (branches into human-gated vs. policy-gated paths); Evidence Store (must flag every L2 merge clearly as autonomous for later audit).

**Dependencies:** Phases 1-4 must be solid - this phase amplifies trust in the gates, so the gates must already be proven trustworthy.

**Security impact:** High - this is the first time the system can change production code without a human in the loop.

**Human approval points:** Defining and updating the safe-change-class policy remains a human decision, even though individual merges within that class dont require per-merge approval.

**Implementation tasks:** Define and codify the policy; implement classification logic; implement the L2 merge path; add mandatory post-merge notification.

**Tests required:** Tests proving the classifier correctly excludes anything touching security-sensitive paths; tests proving L2 merges are reversible; tests proving the policy itself cannot be altered by an agent.

**Success criteria:** A real trivial change merges autonomously; a real non-trivial change is correctly rejected from the L2 path.

**Definition of Done:** At least 20 L2-eligible runs completed with zero incidents before this phase is considered stable.

**Status:** Planned - do not attempt before Phases 1-4 are complete and stable.

---

### PHASE 7 - Delegated Engineering (L3 Autonomy)

**Goal:** Support multi-file feature work with only checkpoint-level human approval, rather than step-by-step gates.

**Why this phase exists:** This is the level at which the system starts resembling an autonomous software engineer for real feature work, not just isolated small changes.

**Architecture changes:** Governance Engine gains an L3 run mode where only spec-approval and final-review are human-gated; everything between (including bounded self-repair from Phase 4) runs unattended.

**New components:** Possibly a Refactor Agent or Migration Agent if feature scope demands cross-cutting changes.

**Changed components:** Reviewer Agents role strengthens - its risk narrative at the final-review checkpoint becomes the primary human-facing summary of a much larger unattended stretch of work.

**Dependencies:** A demonstrated, evidence-backed track record from Phase 6; retrieval quality from Phase 3 must be strong.

**Security impact:** High - mandatory human spec approval is retained specifically because its the checkpoint that catches intent-level errors nothing else catches.

**Human approval points:** Spec approval (before any code is written) and final review (before merge) - both mandatory, non-optional.

**Implementation tasks:** Build L3 run mode; strengthen Reviewer Agent narrative generation; add any new specialist agents the feature scope requires.

**Tests required:** End-to-end tests on real multi-file features; specific tests verifying that no merge occurs at L3 without passing both checkpoints.

**Success criteria:** A genuinely multi-file feature completes with only two human touchpoints.

**Definition of Done:** At least 10 L3 runs completed successfully with human satisfaction confirmed at both checkpoints.

**Status:** Future - not to be attempted before Phase 6 is stable.

---

### PHASE 8 - High-Confidence Automation (L4) & Platform Maturity

**Goal:** Broaden autonomous change classes based on accumulated reliability evidence; formalize platform identity.

**Why this phase exists:** This is the long-term horizon - where the system has earned the autonomous software engineering platform name.

**Architecture changes:** Expand the L2/L3 safe-change-class definitions based on historical reliability data; consider (only if justified by real need) multi-repo or multi-project support.

**New components:** Reliability-tracking dashboard/report (built from Phase 1s evidence data) used to justify any expansion of autonomy scope.

**Changed components:** Governance Engines policy definitions, updated incrementally and only by human decision.

**Dependencies:** A substantial, real history of L2/L3 runs with measured outcomes.

**Security impact:** Ongoing - this phase is never finished, its a continuous evidence-gated expansion process.

**Human approval points:** Every expansion of autonomy scope remains a human decision, permanently.

**Implementation tasks:** Build reliability reporting; formalize the process for reviewing and expanding autonomy scope.

**Tests required:** Ongoing regression and reliability tracking, not a one-time test suite.

**Success criteria:** A defined, broad set of change classes operate reliably at L2/L3 with a clean incident history over a meaningful time window.

**Definition of Done:** This phase has no fixed done - its re-evaluated on a recurring cadence.

**Status:** Long-term horizon; do not pursue platform or AI OS framing before this phase is substantially underway.
---

## 4. Current State Analysis
*(Status sync 2026-08-26.)*

### Already Completed
- Phase 0 in full (see PHASE 0 status).
- Phase 1 in full: both governance bugs closed with regression tests; provenance tagging; evidence export endpoint.
- Hardening batch P1-P8: env-configurable LLM + retry, AgentRun provenance fields populated, fail-closed secrets, orphan-run reaper, surgical git staging, language-aware security scan, execution-evidence persistence, blueprint audit.
- Interstitial Human Identity milestone: users/tokens/login, authoritative Bearer at human gates, token-flow migration complete, strict flag ready but OFF.
- Designer agent + blueprints router exist (from a parallel session; designer role uncommitted at time of writing).
- 101 unit tests + live E2E chain passing.

### Partially Completed
- Infra roadmap: PostgreSQL + API active; Redis, Qdrant present only as commented-out scaffolding.

### Missing
- Separation of duties between Coder Agent and test verification (Phase 2).
- Semantic memory / retrieval (Qdrant not yet wired in) (Phase 3).
- Any self-repair/retry loop beyond the coder's bounded reflection (Phase 4).
- Any codified autonomy-level policy.
- An air-gap dependency audit.

### Technical Debt
- Resolved: CRP terminal-state bypass; open_crp_ids snapshot staleness (both Phase 1).
- Open: prompts table has no writers (provenance hashes reference code history); evidence-export endpoint is anonymous (documented gap, fix awaiting approval); Spring Boot/designer agents carry placeholder upstream ids; rate limiting absent on /auth/login.

### Architectural Risks
- Coder Agent self-attesting its own tests (conflict of interest - Phase 2 target).
- No mechanism yet to catch wrong-but-working LLM output beyond human review.
- Human identity strict mode available but disabled (permissive legacy header path still open by design).

---

## 5. Autonomy Model

| Level | Allowed Actions | Forbidden Actions | Required Approvals | Required Evidence |
|---|---|---|---|---|
| L0 - Human-controlled | Propose spec, code, tests | Merge without approval | Every stage | Full trace, human-approved at each gate |
| L1 - Bounded self-repair | Retry/correct within fixed attempt cap | Exceed cap without escalating; merge without approval | Merge approval only | All attempts recorded |
| L2 - Limited safe automation | Merge unattended for codified low-risk class | Merge outside defined class; alter class definition | Policy definition (human, once) | Every L2 merge flagged as autonomous |
| L3 - Delegated engineering | Run full multi-file feature unattended between checkpoints | Skip either checkpoint | Spec approval + final review | Full trace of unattended stretch |
| L4 - High-confidence automation | Broad, evidence-justified change classes | Expand scope without human review | Periodic human review of autonomy scope | Continuous reliability reporting |

---

## 6. Memory Architecture

### External Sara Memory (outside the engine entirely)
| Type | Storage |
|---|---|
| Architecture discussions | Saras own memory/notes |
| User preferences | Saras own memory/notes |
| Development history | Saras own memory/notes |

### Internal Engine Memory
| Type | Storage | Notes |
|---|---|---|
| Working memory | In-process / Redis (only if Phase 5 triggered) | Never authoritative |
| Execution state | PostgreSQL | Authoritative |
| Repository knowledge | Read live from git/filesystem; indexed into Qdrant | Never cached as truth |
| Semantic memory | Qdrant | Retrieval aid, not ground truth |
| Episodic memory | PostgreSQL + Qdrant | |
| Engineering decisions | PostgreSQL | Must be queryable/auditable |
| Artifacts | Filesystem + PostgreSQL references | |
| Evidence | PostgreSQL, immutable/append-only | The record everything else is audited against |

---

## 7. Agent Architecture

### Product Agent
- Purpose: Turn a human requirement into a structured product understanding.
- Input: Raw human requirement text.
- Output: Structured product brief (proposal).
- Human checkpoints: Requirement acceptance.

### Spec Agent
- Purpose: Convert the product brief into a specification and acceptance criteria.
- Input: Approved product brief.
- Output: Spec + AC (proposal), passed through _enforce_ac_refs.
- Human checkpoints: Spec approval.

### Coder Agent
- Purpose: Write code implementing an approved spec.
- Input: Approved spec.
- Output: Code + proposed tests (proposal only, post-Phase 2).
- Human checkpoints: None directly (gated by deterministic test/scan results).

### Test Execution (not an LLM agent)
- Purpose: Independently run tests against Coder Agent output.
- Input: Code + tests from Coder Agent.
- Output: Pass/fail fact.
- Human checkpoints: None - deterministic ground truth.

### Security Agent
- Purpose: Scan code for known vulnerability patterns; narrate findings.
- Input: Code diff.
- Output: Scan result (fact) + narrative explanation (proposal).
- Human checkpoints: Security exceptions (human-only, explicit).

### Reviewer Agent
- Purpose: Produce a risk narrative summarizing a run for human review.
- Input: Full run evidence trail.
- Output: Risk narrative (advisory only).
- Human checkpoints: Final review (especially critical at L3+).

---

## 8. Governance Model

- **State machine:** Every run moves through defined states. Terminal-state guards must be unconditionally enforced (Phase 1 fix).
- **Approval gates:** Requirement acceptance, spec approval, dependency additions, security exceptions, architecture changes, merge approval.
- **Evidence model:** Every fact is a provenance-tagged, immutable record.
- **Audit trail:** Complete, queryable history of a run, reconstructable without re-invoking any LLM.
- **MRP:** Formal record proposing a merge, carrying its evidence trail.
- **CRP:** Formal record of a requested change; must respect terminal-state guards.
- **VCR:** The review step confirming evidence supports the proposed merge.
- **Merge gate:** Deterministic final check - branches into human-gated (L0/L1/L3) and policy-gated (L2) paths.
- **Failure handling:** Bounded retry (L1, Phase 4) with a hard cap, then escalation to a human.
- **Recovery process:** A failed or escalated run remains inspectable via its evidence trail.

---

## 9. Documentation System

Every project document must carry this header block:

`
Objective:
Current status:
Owner:
Created date:
Last update:
Phase:
Dependencies:
Tests:
Evidence:
Completion criteria:
Future improvements:
`

---

## 10. Daily Development Tracking Model

`
DATE:
Todays objective:
Why this objective matters:
Expected outcome:
Implementation completed:
Tests added:
Tests passed:
Evidence produced:
Human approvals:
Problems discovered:
Remaining work:
Can this be considered complete?
If not: Why?
Next action:
`

---

## 11. Test Strategy

| Test Level | Purpose | Proves |
|---|---|---|
| Unit | Individual function/agent-output correctness | A component behaves correctly in isolation |
| Integration | Multi-component interaction | Components work together correctly |
| Agent | LLM output structure/quality against fixed cases | Prompts and post-processing produce usable output |
| Workflow | Full run, requirement to merge | The end-to-end pipeline functions |
| Security | Scanner correctness, narrative-cant-override-fact | The security gate cant be talked past |
| Regression | Known-bug scenarios | Previously fixed issues stay fixed |
| Governance | State machine transitions, terminal-state guards | The governance layer is structurally sound |
| Air-gap | No outbound network calls during a run | The system genuinely works offline |
| Failure simulation | Induced test/scan/service failures | Bounded repair and escalation behave correctly |

---

## 12. Release Roadmap

| Milestone | Capabilities | Limitations | Security Level | Autonomy Level |
|---|---|---|---|---|
| Prototype | Single-file changes, full human gating | No retrieval, no repair loop | Basic scan only | L0 |
| Alpha | Retrieval-grounded generation, bounded self-repair | No unattended merges | Provenance-tagged evidence | L0-L1 |
| Beta | Limited safe automation for narrow change class | Narrow class only | Immutable evidence, air-gap audited | L0-L2 |
| Production-ready | Delegated engineering with checkpoint approval | Human spec + final review mandatory | Full audit trail | L0-L3 |

---

## 13. Biggest Risks

- **Technical:** Retry loops (Phase 4) or misused Redis (Phase 5) introducing state corruption.
- **AI:** Wrong-but-working output - code that passes tests but solves the wrong problem.
- **Security:** Premature expansion of L2 safe-change-class definition.
- **Architecture:** Reintroducing a conflict of interest anywhere a new agent is added.
- **Operational:** Air-gap violations from transitive dependencies.
- **Documentation:** Roadmap drift - phases getting reordered or skipped informally.
- **Human dependency:** Over-relying on Saras advisory output as verified fact.

---

## 14. Final Product Description - Example: Add OAuth Authentication

**What Sara does:** Nothing inside the engine. Externally, Sara may help draft the initial requirement phrasing, discuss architectural implications, or later review the exported evidence trail - purely advisory, no execution.

**What the human approves:** Requirement acceptance; the generated spec (mandatory checkpoint); any new dependency; the final review before merge.

**What ai-swe-engine does:** Orchestrator sequences Product Agent -> Spec Agent -> human spec approval -> Coder Agent implementation attempt -> independent test execution -> security scan -> bounded self-repair -> Reviewer Agent risk narrative -> human final review -> merge gate.

**What the local LLM does:** Drafts the product brief, spec, acceptance criteria, code, tests, and risk narrative - all as proposals, none authoritative.

**What deterministic systems do:** Enforce AC-reference validity; run and interpret tests as ground truth; run and interpret the security scan as ground truth; construct the immutable, provenance-tagged evidence trail; enforce that security-sensitive changes never qualify for L2.

**How the final merge happens:** Only after the deterministic Merge Gate confirms: spec was human-approved, tests pass, security scan is clean, no unresolved CRPs exist, and a human has completed final review.