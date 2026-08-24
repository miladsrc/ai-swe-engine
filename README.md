# SASE Engine — Traceability Backbone (Phase 1)

This is the first real slice of the AI Software Engineering Engine, built
against the SASE (Structured Agentic Software Engineering) framework.
It implements **roadmap step 2**: the traceability backbone. Nothing
else in the roadmap — Blueprint authoring beyond the two seed files
here, Structured RAG, the Product/Spec/Coder/Reviewer agents themselves,
Ollama integration — is built yet. This is deliberate: per the roadmap,
those shouldn't be built until this layer can prove an end-to-end chain
works.

## What's actually here

- **Postgres schema** (`migrations/001_init.sql`) for every artifact in
  the chain: Project, PRD, User Story, Acceptance Criteria, Spec,
  Blueprint, Prompt, Agent Run, CRP, MRP, VCR, and an append-only audit
  log.
- **A FastAPI service** (`api/`) exposing that schema as a real API,
  with the paper's hard rules enforced in code (`api/gates.py`), not
  just documented:
  - A Spec cannot be used to start code-generation Agent Run until a
    human has called `POST /specs/{id}/validate` (§3.5).
  - An MRP cannot be approved while a High/Critical CRP tied to its
    Specs is still open (§3.6.3).
  - `POST /mrps/{id}/check-ready` implements the exact gate table from
    §5.6.5 (tests passing, security scan passed, Spec/Blueprint
    referenced, no open CRPs).
  - **Human-decision endpoints are identity-guarded** (`api/security.py`):
    `/specs/{id}/validate`, `/mrps/{id}/human-decision`, and both VCR
    endpoints require an `X-Acting-As: human:<name>` header — an agent can
    no longer forge a human sign-off through the request body. This header
    is the seam where real authn (OIDC/mTLS) plugs in later.
- **Two seed Blueprints** (`blueprints/`): an org-wide error-handling
  rule and the first Spring Boot stack Blueprint, both marked
  `approved_by: <fill in — pending first human approval>` — deliberately
  not pre-approved, because Blueprint approval is supposed to be a real
  human action (§3.7.5), not a placeholder I fill in for you.
- **The `.ai-engineering/` artifact tree** — currently empty directories
  with a README each; this is where the human-readable Markdown/YAML
  copy of each artifact lives, mirroring what's in Postgres.

## What is NOT here yet (and why)

- **No LLM calls.** No Ollama, no Qwen, no DeepSeek. This sandbox has no
  network access, so I couldn't pull models or test inference even if
  I'd wired it up — and more importantly, per the roadmap, the
  traceability backbone needs to prove itself with hand-authored
  artifacts before an agent touches it. The `docker-compose.yml` has
  Ollama/Qdrant/Redis commented in, ready for step 4 (Structured RAG)
  and beyond.
- **No agents.** The Product/Spec/Coder/Reviewer/Legacy-Discovery agents
  described in the architecture docs are not implemented. This service
  is what they'll call once they exist — it's the contract they write
  against, built first so the contract is solid.
- **No RAG.** No vector store, no chunking/reranking pipeline.

## Running it

You'll need Docker on your own machine (this environment can't run it
for you — no network access here).

```bash
docker compose up --build
```

This starts Postgres (auto-applying `migrations/001_init.sql` on first
boot) and the API on `http://localhost:8000`. Interactive API docs at
`http://localhost:8000/docs`.

## Proving the chain works — a manual walkthrough

This is the concrete version of the demo's exit criteria (v3 §1). Run
these in order against the API (curl or the `/docs` UI) to prove the
mechanism before trusting it with a real agent:

```bash
# 1. Create a project
curl -X POST localhost:8000/projects -H 'Content-Type: application/json' \
  -d '{"id":"demo-springboot","name":"Demo Spring Boot App","stack":"springboot"}'

# 2. Create a PRD
curl -X POST localhost:8000/prds -H 'Content-Type: application/json' \
  -d '{"project_id":"demo-springboot","domain":"AUTH","title":"User session auth",
       "body_ref":".ai-engineering/prd/PRD-AUTH-001.md","created_by":"human:you"}'
# -> note the returned id, e.g. PRD-AUTH-001

# 3. Create a User Story against it, then an Acceptance Criterion
curl -X POST localhost:8000/user-stories -H 'Content-Type: application/json' \
  -d '{"prd_id":"PRD-AUTH-001","domain":"AUTH","body_ref":".ai-engineering/user-stories/US-AUTH-001.md"}'

curl -X POST localhost:8000/acceptance-criteria -H 'Content-Type: application/json' \
  -d '{"user_story_id":"US-AUTH-001","body_ref":".ai-engineering/acceptance-criteria/AC-AUTH-001-01.md"}'

# 4. Create a Spec — try starting a code-gen Agent Run against it BEFORE
#    validating it, and confirm you get a 409 (this proves the §3.5 gate
#    actually blocks, not just documents, premature code-gen)
curl -X POST localhost:8000/specs -H 'Content-Type: application/json' \
  -d '{"project_id":"demo-springboot","user_story_id":"US-AUTH-001","domain":"AUTH",
       "name":"session-refresh","body_ref":".ai-engineering/specs/SPEC-AUTH-SESSION-REFRESH.yaml"}'

curl -X POST localhost:8000/agent-runs -H 'Content-Type: application/json' \
  -d '{"project_id":"demo-springboot","agent_role":"coder_agent","task_type":"code_generation",
       "model_name":"DeepSeek-671B","model_short":"DS","spec_id":"SPEC-AUTH-SESSION-REFRESH"}'
# -> expect HTTP 409, gate working as intended

# 5. Now validate the Spec and retry — expect success this time.
#    Human-decision endpoints require the X-Acting-As header with a
#    'human:' identity (see api/security.py) — an agent cannot forge it.
curl -X POST localhost:8000/specs/SPEC-AUTH-SESSION-REFRESH/validate \
  -H 'Content-Type: application/json' \
  -H 'X-Acting-As: human:you' -d '{}'

curl -X POST localhost:8000/agent-runs -H 'Content-Type: application/json' \
  -d '{"project_id":"demo-springboot","agent_role":"coder_agent","task_type":"code_generation",
       "model_name":"DeepSeek-671B","model_short":"DS","spec_id":"SPEC-AUTH-SESSION-REFRESH"}'
# -> note the returned run id, e.g. RUN-DS-2026-00001

# 6. Deliberately raise a CRP against this run, mirroring the paper's own
#    worked example (§3.6.4 — token refresh expiry ambiguity)
curl -X POST localhost:8000/crps -H 'Content-Type: application/json' \
  -d '{"project_id":"demo-springboot","domain":"AUTH","agent_run_id":"RUN-DS-2026-00001",
       "spec_id":"SPEC-AUTH-SESSION-REFRESH","severity":"high",
       "blocking_issue_title":"Ambiguous refresh-token expiry policy",
       "blocking_issue_body":"PRD does not specify exact expiry duration or policy differences per role.",
       "required_decision":"What refresh-token expiry should apply per role?",
       "required_role":"Security Architect"}'
# -> note the returned id, e.g. CRP-AUTH-2026-001

# 7. Resolve it as a VCR
curl -X POST localhost:8000/vcrs \
  -H 'Content-Type: application/json' \
  -H 'X-Acting-As: human:security-architect' \
  -d '{"related_artifact_type":"CRP","related_artifact_id":"CRP-AUTH-2026-001",
       "decision_status":"approved_with_changes","selected_option":"24h normal / 4h admin",
       "rationale":"Balances UX with risk for privileged accounts.","update_spec":true}'

# 8. Create an MRP for the resulting PR, add evidence, and confirm the
#    §5.6.5 gate blocks it until tests/security are recorded as passed
curl -X POST localhost:8000/mrps -H 'Content-Type: application/json' \
  -d '{"project_id":"demo-springboot","pull_request_number":1,"branch_name":"feature/session-refresh",
       "created_by_agent_run":"RUN-DS-2026-00001","prd_id":"PRD-AUTH-001",
       "spec_ids":["SPEC-AUTH-SESSION-REFRESH"],"blueprint_id":"BP-SPRINGBOOT-001","blueprint_version":"v1.0"}'

curl -X POST localhost:8000/mrps/MRP-PR-1/check-ready
# -> expect ready: false, with reasons listing missing test/security evidence

curl -X PATCH localhost:8000/mrps/MRP-PR-1/evidence -H 'Content-Type: application/json' \
  -d '{"unit_tests_status":"passed","security_scan_status":"passed"}'

curl -X POST localhost:8000/mrps/MRP-PR-1/check-ready
# -> expect ready: true

# 9. Record the human merge decision
curl -X POST localhost:8000/mrps/MRP-PR-1/human-decision \
  -H 'Content-Type: application/json' \
  -H 'X-Acting-As: human:you' \
  -d '{"decision":"approved"}'

# 10. Pull the full chain and confirm it's traceable end-to-end
curl localhost:8000/traceability/chain/MRP-PR-1
# -> fully_traceable: true
```

If all ten steps behave as annotated, the traceability backbone is
proven and it's safe to move on to roadmap step 3 (writing the rest of
the Spring Boot Blueprint) and step 5 (the actual Product/Spec agents
calling this API instead of curl).

## Next steps (in order, per the architecture docs)

1. Get a human to actually review and approve the two seed Blueprints
   (fill in `approved_by`, expand `BP-SPRINGBOOT-001.md` with whatever
   else your team's conventions require).
2. Wire up Ollama + pull Qwen-72B and DeepSeek-671B (commented block in
   `docker-compose.yml`), on a machine with the network access and GPU
   this sandbox doesn't have.
3. Build the Product Agent and Spec Agent as thin services that call
   this API's `/prds`, `/user-stories`, `/acceptance-criteria`, `/specs`
   endpoints instead of a human doing it by hand — but keep the
   `POST /specs/{id}/validate` step human-only, per §3.5.
4. Build the Structured RAG pipeline (chunking/embedding/reranking/
   access-control) as its own service, kept structurally separate from
   the Blueprint files — do not point the same vector index at both.
5. Build the Coder Agent + Reflection loop + isolated Reviewer Agent,
   calling `/agent-runs`, `/crps`, and `/mrps` as they work.

## Environment variables

- **`SASE_API_TOKEN`** — optional perimeter authentication. When set
  (non-empty), every request must carry header `X-API-Token` equal to it
  or get a 401 (`api/main.py` middleware). Unset by default: local dev is
  unaffected. Set it for any non-localhost deployment.
- **`SASE_CI_TOKEN`** — shared secret backing CI evidence identity
  (`api/security.py: require_ci_actor`). When set, `PATCH /mrps/{id}/evidence`
  additionally requires header `X-CI-Token` to match, so evidence can't be
  forged anonymously. `docker-compose.yml` sets the placeholder
  `dev-ci-token-change-me` — replace it with a real secret anywhere beyond
  localhost.
