from sqlalchemy import (
    Column, String, Text, Boolean, TIMESTAMP, Numeric, Integer,
    ForeignKey, JSON, ARRAY, func
)
from sqlalchemy.dialects.postgresql import JSONB
from api.database import Base


class Project(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    stack = Column(String, nullable=False)
    is_legacy = Column(Boolean, nullable=False, default=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class PRD(Base):
    __tablename__ = "prds"
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    title = Column(String, nullable=False)
    body_ref = Column(Text, nullable=False)
    confidence = Column(String, nullable=False, default="human_authored")
    created_by = Column(String, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class UserStory(Base):
    __tablename__ = "user_stories"
    id = Column(String, primary_key=True)
    prd_id = Column(String, ForeignKey("prds.id"), nullable=False)
    body_ref = Column(Text, nullable=False)
    confidence = Column(String, nullable=False, default="human_authored")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class AcceptanceCriteria(Base):
    __tablename__ = "acceptance_criteria"
    id = Column(String, primary_key=True)
    user_story_id = Column(String, ForeignKey("user_stories.id"), nullable=False)
    body_ref = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class Spec(Base):
    __tablename__ = "specs"
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    user_story_id = Column(String, ForeignKey("user_stories.id"))
    format = Column(String, nullable=False, default="yaml")
    body_ref = Column(Text, nullable=False)
    confidence = Column(String, nullable=False, default="human_authored")
    human_validated = Column(Boolean, nullable=False, default=False)
    human_validated_by = Column(String)
    human_validated_at = Column(TIMESTAMP(timezone=True))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class Blueprint(Base):
    __tablename__ = "blueprints"
    id = Column(String, primary_key=True)
    version = Column(String, primary_key=True)
    scope = Column(String, nullable=False)
    body_ref = Column(Text, nullable=False)
    approved_by = Column(String, nullable=False)
    change_note = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class Prompt(Base):
    __tablename__ = "prompts"
    id = Column(String, primary_key=True)
    version = Column(String, primary_key=True)
    target_model = Column(String, nullable=False)
    purpose = Column(String, nullable=False)
    body_ref = Column(Text, nullable=False)
    owner = Column(String, nullable=False)
    approved_by = Column(String)
    change_note = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    agent_role = Column(String, nullable=False)
    task_type = Column(String, nullable=False)
    prd_id = Column(String, ForeignKey("prds.id"))
    user_story_id = Column(String, ForeignKey("user_stories.id"))
    spec_id = Column(String, ForeignKey("specs.id"))
    blueprint_ids = Column(ARRAY(String), default=list)
    model_provider = Column(String, default="local")
    model_name = Column(String, nullable=False)
    model_version = Column(String)
    runtime = Column(String, default="ollama")
    temperature = Column(Numeric)
    context_window = Column(Integer)
    prompt_id = Column(String)
    prompt_version = Column(String)
    system_prompt_hash = Column(String)
    user_prompt_hash = Column(String)
    rag_retrieval_enabled = Column(Boolean, default=False)
    rag_retrieved_doc_ids = Column(ARRAY(String), default=list)
    rag_query_hash = Column(String)
    rag_index_version = Column(String)
    started_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    finished_at = Column(TIMESTAMP(timezone=True))
    status = Column(String, default="running")
    reflection_iterations = Column(Integer, default=0)
    tools_used = Column(ARRAY(String), default=list)
    generated_files = Column(ARRAY(String), default=list)
    commit_hash = Column(String)
    mrp_id = Column(String)


class CRP(Base):
    __tablename__ = "crps"
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    agent_run_id = Column(String, ForeignKey("agent_runs.id"))
    prd_id = Column(String, ForeignKey("prds.id"))
    user_story_id = Column(String, ForeignKey("user_stories.id"))
    spec_id = Column(String, ForeignKey("specs.id"))
    severity = Column(String, nullable=False)
    status = Column(String, default="open")
    blocking_issue_title = Column(String, nullable=False)
    blocking_issue_body = Column(Text, nullable=False)
    context_summary = Column(JSONB, default=dict)
    options_considered = Column(JSONB, default=list)
    agent_recommendation = Column(JSONB)
    required_decision = Column(Text, nullable=False)
    required_role = Column(String, nullable=False)
    default_policy = Column(String, default="block_generation")
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class VCR(Base):
    __tablename__ = "vcrs"
    id = Column(String, primary_key=True)
    related_artifact_type = Column(String, nullable=False)
    related_artifact_id = Column(String, nullable=False)
    decision_status = Column(String, nullable=False)
    selected_option = Column(String)
    rationale = Column(Text, nullable=False)
    decided_by = Column(String, nullable=False)
    decided_role = Column(String)
    decided_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    update_prd = Column(Boolean, default=False)
    update_user_story = Column(Boolean, default=False)
    update_spec = Column(Boolean, default=False)
    update_blueprint = Column(Boolean, default=False)
    update_tests = Column(Boolean, default=False)
    required_updates = Column(JSONB, default=list)
    promoted_to_org_memory = Column(Boolean, default=False)


class MRP(Base):
    __tablename__ = "mrps"
    id = Column(String, primary_key=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=False)
    pull_request_ref = Column(String, nullable=False)
    branch_name = Column(String, nullable=False)
    commit_hash = Column(String)
    # Phase 2 SoD (G7): immutable git tree hash the orchestrator actually
    # verified. Compare against audit evidence execution_context.tree_hash.
    verified_tree_hash = Column(String)
    created_by_agent_run = Column(String, ForeignKey("agent_runs.id"))
    prd_id = Column(String, ForeignKey("prds.id"))
    user_story_ids = Column(ARRAY(String), default=list)
    acceptance_criteria_ids = Column(ARRAY(String), default=list)
    spec_ids = Column(ARRAY(String), default=list)
    blueprint_id = Column(String)
    blueprint_version = Column(String)
    change_summary = Column(Text)
    affected_modules = Column(ARRAY(String), default=list)
    unit_tests_status = Column(String)
    integration_tests_status = Column(String)
    e2e_tests_status = Column(String)
    test_coverage_pct = Column(Numeric)
    lint_status = Column(String)
    static_analysis_status = Column(String)
    complexity_status = Column(String)
    security_scan_status = Column(String)
    dependency_scan_status = Column(String)
    ai_review_status = Column(String)
    ai_review_notes = Column(JSONB, default=list)
    # Phase 2 I3 (G8): structured review findings written ONLY by the
    # independent agent:reviewer via PATCH /mrps/{id}/review — never by the
    # coder, the critic, or the orchestrator. Advisory-only: never approval.
    ai_review_findings = Column(JSONB, default=list)
    human_review_focus = Column(Text)
    open_crp_ids = Column(ARRAY(String), default=list)
    status = Column(String, default="draft")
    human_reviewer = Column(String)
    reviewed_at = Column(TIMESTAMP(timezone=True))
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class VerificationRequest(Base):
    """
    Step 2B — immutable remote-verification request record.

    The Orchestrator POSTs a request carrying ONLY immutable references
    (run_id, mrp_id, commit, worktree_ref) and NOTHING secret. A genuinely
    separately-administered Verifier (remote GitLab runner / VM, never the
    local Orchestrator's principal) atomically claims it, verifies the exact
    pinned commit, writes trusted evidence to the MRP as ci:verifier, and
    records completion here. The Orchestrator only ever reads non-secret
    status via GET.

    DEV/CONTAINMENT ONLY note: the local harness exercises this protocol
    and its security rules, but does NOT establish the genuine remote
    credential boundary (the local runner/admin is the same m.barani). See
    tests/test_sod_remote_boundary.py and docs/ADR/ADR-002 for the boundary
    carve-out.
    """
    __tablename__ = "verification_requests"
    id = Column(String, primary_key=True)          # VR-<seq>
    run_id = Column(String, nullable=False, unique=True)  # one logical request per run
    mrp_id = Column(String, nullable=False, index=True)
    commit = Column(String, nullable=False)        # EXACT pinned commit
    worktree_ref = Column(String, nullable=False)  # repo/object-store reference
    status = Column(String, nullable=False, default="pending")
    # at most: pending | running | passed | failed | expired | error
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    started_at = Column(TIMESTAMP(timezone=True))
    completed_at = Column(TIMESTAMP(timezone=True))
    expires_at = Column(TIMESTAMP(timezone=True))  # TTL -> fail closed
    lease_expires_at = Column(TIMESTAMP(timezone=True))  # atomic-pickup lease
    lease_holder = Column(String)                  # ci:verifier that claimed it
    verified_tree_hash = Column(String)            # authoritative hash, verifier-set
    # failure information (verifier-set, non-secret)
    failure_reason = Column(Text)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_type = Column(String, nullable=False)
    actor_id = Column(String, nullable=False)
    model_version = Column(String)
    action = Column(String, nullable=False)
    artifact_type = Column(String)
    artifact_id = Column(String)
    context = Column(JSONB)
    tools_used = Column(ARRAY(String), default=list)
    result = Column(String)
    human_decision = Column(String)
    timestamp = Column(TIMESTAMP(timezone=True), server_default=func.now())


# ---------------------------------------------------------------------------
# Phase 2: human identity (users + API tokens).
# Adds REAL authn at the seam api/security.py documented ("this header
# contract is the seam where that plugs in"). Agents are unaffected: no
# agent role can register or log in — these tables are human-only by
# construction (login requires a password check, tokens are issued only
# through it). Default behavior of every endpoint is unchanged until
# SASE_REQUIRE_HUMAN_TOKEN is set.
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"
    username = Column(String, primary_key=True)     # canonical, lowercased
    display_name = Column(String)
    # pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex> — stdlib only.
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class ApiToken(Base):
    __tablename__ = "api_tokens"
    # sha256(token) — the RAW token is shown once at login and never stored.
    token_hash = Column(String, primary_key=True)
    username = Column(String, ForeignKey("users.username"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    expires_at = Column(TIMESTAMP(timezone=True))
    revoked = Column(Boolean, nullable=False, default=False)
    last_used_at = Column(TIMESTAMP(timezone=True))
