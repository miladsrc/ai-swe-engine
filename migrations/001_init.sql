-- SASE traceability backbone
-- Every table here is a durable, queryable mirror of the corresponding
-- .ai-engineering/ YAML/Markdown artifact. The files are the human-readable
-- source of truth for a single artifact; this schema is what makes the
-- *chain* across artifacts queryable and enforceable.

-- Atomic sequence counters backing the human-readable ID scheme in api/ids.py
CREATE TABLE id_counters (
    key     TEXT PRIMARY KEY,
    value   INTEGER NOT NULL
);

CREATE TYPE artifact_confidence AS ENUM ('human_authored', 'inferred', 'confirmed');
CREATE TYPE crp_severity AS ENUM ('low', 'medium', 'high', 'critical');
CREATE TYPE crp_status AS ENUM ('open', 'resolved', 'blocking');
CREATE TYPE mrp_status AS ENUM ('draft', 'ready_for_ai_review', 'ready_for_human_review',
                                 'needs_revision', 'blocked_by_consultation', 'approved', 'rejected');
CREATE TYPE agent_role AS ENUM ('product_agent', 'spec_agent', 'coder_agent',
                                 'reviewer_agent', 'security_agent', 'legacy_discovery_agent');

-- ---------------------------------------------------------------------
-- Projects (a project is the unit that owns its own RAG/Blueprint scope,
-- per v3 §4's three-tier memory split)
-- ---------------------------------------------------------------------
CREATE TABLE projects (
    id              TEXT PRIMARY KEY,           -- e.g. 'demo-springboot', 'legacy-claims-jboss'
    name            TEXT NOT NULL,
    stack           TEXT NOT NULL,              -- 'springboot' | 'jboss-legacy' | 'csharp' | 'python'
    is_legacy       BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Requirement chain: PRD -> User Story -> Acceptance Criteria -> Spec
-- ---------------------------------------------------------------------
CREATE TABLE prds (
    id              TEXT PRIMARY KEY,           -- PRD-<DOMAIN>-<seq>
    project_id      TEXT NOT NULL REFERENCES projects(id),
    title           TEXT NOT NULL,
    body_ref        TEXT NOT NULL,              -- path to .ai-engineering/prd/<id>.md
    confidence      artifact_confidence NOT NULL DEFAULT 'human_authored',
    created_by      TEXT NOT NULL,              -- 'human:<name>' or 'agent:product_agent'
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE user_stories (
    id              TEXT PRIMARY KEY,           -- US-<DOMAIN>-<seq>
    prd_id          TEXT NOT NULL REFERENCES prds(id),
    body_ref        TEXT NOT NULL,
    confidence      artifact_confidence NOT NULL DEFAULT 'human_authored',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE acceptance_criteria (
    id              TEXT PRIMARY KEY,           -- AC-<DOMAIN>-<seq>-<n>
    user_story_id   TEXT NOT NULL REFERENCES user_stories(id),
    body_ref        TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE specs (
    id                  TEXT PRIMARY KEY,       -- SPEC-<DOMAIN>-<NAME>
    project_id          TEXT NOT NULL REFERENCES projects(id),
    user_story_id       TEXT REFERENCES user_stories(id),
    format              TEXT NOT NULL DEFAULT 'yaml',   -- openspec | spec-kit | yaml
    body_ref            TEXT NOT NULL,
    confidence          artifact_confidence NOT NULL DEFAULT 'human_authored',
    human_validated      BOOLEAN NOT NULL DEFAULT FALSE, -- hard gate: no code-gen until true
    human_validated_by  TEXT,
    human_validated_at  TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Blueprints (versioned, human-approved, non-negotiable architecture rules)
-- ---------------------------------------------------------------------
CREATE TABLE blueprints (
    id              TEXT NOT NULL,              -- BP-<LAYER>-<seq>, e.g. BP-SPRINGBOOT-001
    version         TEXT NOT NULL,              -- e.g. 'v1.4'
    scope           TEXT NOT NULL,              -- 'org' | 'project:<project_id>' | 'stack:<stack>'
    body_ref        TEXT NOT NULL,
    approved_by     TEXT NOT NULL,
    change_note     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);

-- ---------------------------------------------------------------------
-- Prompt versioning (per §3.7.4 — a prompt change can shift output quality
-- as much as a model or Blueprint change, so it must be independently tracked)
-- ---------------------------------------------------------------------
CREATE TABLE prompts (
    id              TEXT NOT NULL,              -- prompt-<purpose>
    version         TEXT NOT NULL,              -- e.g. '2.3'
    target_model    TEXT NOT NULL,              -- 'qwen-72b' | 'deepseek-671b'
    purpose         TEXT NOT NULL,
    body_ref        TEXT NOT NULL,
    owner           TEXT NOT NULL,
    approved_by     TEXT,
    change_note     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, version)
);

-- ---------------------------------------------------------------------
-- Agent Run Record (per §3.7.3) — written for every execution, success or fail
-- ---------------------------------------------------------------------
CREATE TABLE agent_runs (
    id                      TEXT PRIMARY KEY,   -- RUN-<MODEL>-<year>-<seq>
    project_id              TEXT NOT NULL REFERENCES projects(id),
    agent_role              agent_role NOT NULL,
    task_type               TEXT NOT NULL,
    prd_id                  TEXT REFERENCES prds(id),
    user_story_id           TEXT REFERENCES user_stories(id),
    spec_id                 TEXT REFERENCES specs(id),
    blueprint_ids           TEXT[] NOT NULL DEFAULT '{}',
    model_provider          TEXT NOT NULL DEFAULT 'local',
    model_name              TEXT NOT NULL,      -- 'DeepSeek-671B' | 'Qwen-72B'
    model_version           TEXT,
    runtime                 TEXT NOT NULL DEFAULT 'ollama',
    temperature             NUMERIC,
    context_window          INTEGER,
    prompt_id               TEXT,
    prompt_version          TEXT,
    system_prompt_hash      TEXT,
    user_prompt_hash        TEXT,
    rag_retrieval_enabled   BOOLEAN NOT NULL DEFAULT FALSE,
    rag_retrieved_doc_ids   TEXT[] NOT NULL DEFAULT '{}',
    rag_query_hash          TEXT,
    rag_index_version       TEXT,
    started_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at             TIMESTAMPTZ,
    status                  TEXT NOT NULL DEFAULT 'running',  -- running|completed|failed|blocked
    reflection_iterations   INTEGER NOT NULL DEFAULT 0,
    tools_used              TEXT[] NOT NULL DEFAULT '{}',
    generated_files         TEXT[] NOT NULL DEFAULT '{}',
    commit_hash             TEXT,
    mrp_id                  TEXT,
    FOREIGN KEY (prompt_id, prompt_version) REFERENCES prompts(id, version)
);

-- ---------------------------------------------------------------------
-- CRP — Consultation Request Pack (§3.6)
-- ---------------------------------------------------------------------
CREATE TABLE crps (
    id                      TEXT PRIMARY KEY,   -- CRP-<DOMAIN>-<year>-<seq>
    project_id              TEXT NOT NULL REFERENCES projects(id),
    agent_run_id            TEXT REFERENCES agent_runs(id),
    prd_id                  TEXT REFERENCES prds(id),
    user_story_id           TEXT REFERENCES user_stories(id),
    spec_id                 TEXT REFERENCES specs(id),
    severity                crp_severity NOT NULL,
    status                  crp_status NOT NULL DEFAULT 'open',
    blocking_issue_title    TEXT NOT NULL,
    blocking_issue_body     TEXT NOT NULL,
    context_summary         JSONB NOT NULL DEFAULT '{}',
    options_considered      JSONB NOT NULL DEFAULT '[]',
    agent_recommendation    JSONB,
    required_decision       TEXT NOT NULL,
    required_role           TEXT NOT NULL,      -- e.g. 'Security Architect', 'Product Owner'
    default_policy          TEXT NOT NULL DEFAULT 'block_generation',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- VCR — Version Controlled Resolution (§3.7.6): every human decision,
-- recorded once, reusable forever after.
-- ---------------------------------------------------------------------
CREATE TABLE vcrs (
    id                      TEXT PRIMARY KEY,   -- VCR-<related-artifact-id>
    related_artifact_type   TEXT NOT NULL,      -- 'CRP' | 'MRP'
    related_artifact_id     TEXT NOT NULL,
    decision_status         TEXT NOT NULL,      -- approved | approved_with_changes | rejected
    selected_option         TEXT,
    rationale               TEXT NOT NULL,
    decided_by              TEXT NOT NULL,
    decided_role            TEXT,
    decided_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    update_prd              BOOLEAN NOT NULL DEFAULT FALSE,
    update_user_story       BOOLEAN NOT NULL DEFAULT FALSE,
    update_spec             BOOLEAN NOT NULL DEFAULT FALSE,
    update_blueprint        BOOLEAN NOT NULL DEFAULT FALSE,
    update_tests            BOOLEAN NOT NULL DEFAULT FALSE,
    required_updates        JSONB NOT NULL DEFAULT '[]',
    promoted_to_org_memory  BOOLEAN NOT NULL DEFAULT FALSE  -- v3 §4 curation gate
);

-- ---------------------------------------------------------------------
-- MRP — Merge-Readiness Pack (§5.6)
-- ---------------------------------------------------------------------
CREATE TABLE mrps (
    id                      TEXT PRIMARY KEY,   -- MRP-PR-<n>
    project_id              TEXT NOT NULL REFERENCES projects(id),
    pull_request_ref        TEXT NOT NULL,
    branch_name             TEXT NOT NULL,
    commit_hash             TEXT,
    created_by_agent_run    TEXT REFERENCES agent_runs(id),
    prd_id                  TEXT REFERENCES prds(id),
    user_story_ids          TEXT[] NOT NULL DEFAULT '{}',
    acceptance_criteria_ids TEXT[] NOT NULL DEFAULT '{}',
    spec_ids                TEXT[] NOT NULL DEFAULT '{}',
    blueprint_id            TEXT,
    blueprint_version       TEXT,
    change_summary          TEXT,
    affected_modules        TEXT[] NOT NULL DEFAULT '{}',
    unit_tests_status       TEXT,                -- passed|failed|not_applicable
    integration_tests_status TEXT,
    e2e_tests_status        TEXT,
    test_coverage_pct       NUMERIC,
    lint_status             TEXT,
    static_analysis_status  TEXT,
    complexity_status       TEXT,
    security_scan_status    TEXT,
    dependency_scan_status  TEXT,
    ai_review_status        TEXT,                -- passed | passed_with_notes | failed
    ai_review_notes         JSONB NOT NULL DEFAULT '[]',
    human_review_focus      TEXT,
    open_crp_ids            TEXT[] NOT NULL DEFAULT '{}',
    status                  mrp_status NOT NULL DEFAULT 'draft',
    human_reviewer          TEXT,
    reviewed_at             TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Append-only audit log. Revoke UPDATE/DELETE at the role level in
-- deployment — see README for the exact GRANT/REVOKE statements.
-- ---------------------------------------------------------------------
CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    actor_type      TEXT NOT NULL,       -- 'agent' | 'human' | 'system'
    actor_id        TEXT NOT NULL,
    model_version   TEXT,
    action          TEXT NOT NULL,
    artifact_type   TEXT,
    artifact_id     TEXT,
    context         JSONB,
    tools_used      TEXT[] NOT NULL DEFAULT '{}',
    result          TEXT,
    human_decision  TEXT,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_agent_runs_project ON agent_runs(project_id);
CREATE INDEX idx_crps_status ON crps(status, severity);
CREATE INDEX idx_mrps_status ON mrps(status);
CREATE INDEX idx_audit_log_artifact ON audit_log(artifact_type, artifact_id);
