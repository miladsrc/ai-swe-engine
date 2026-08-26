from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    id: str
    name: str
    stack: str
    is_legacy: bool = False


class ProjectOut(ProjectCreate):
    created_at: datetime

    class Config:
        from_attributes = True


class PRDCreate(BaseModel):
    project_id: str
    domain: str = Field(..., description="Used to build the PRD-<DOMAIN>-<seq> id")
    title: str
    body_ref: str
    confidence: str = "human_authored"
    created_by: str


class PRDOut(BaseModel):
    id: str
    project_id: str
    title: str
    body_ref: str
    confidence: str
    created_by: str
    created_at: datetime

    class Config:
        from_attributes = True


class UserStoryCreate(BaseModel):
    prd_id: str
    domain: str
    body_ref: str
    confidence: str = "human_authored"


class AcceptanceCriteriaCreate(BaseModel):
    user_story_id: str
    body_ref: str


class SpecCreate(BaseModel):
    project_id: str
    user_story_id: Optional[str] = None
    domain: str
    name: str
    format: str = "yaml"
    body_ref: str
    confidence: str = "human_authored"


class SpecValidate(BaseModel):
    # Identity is taken from the X-Acting-As header (api/security.py);
    # this field is accepted for backwards compatibility but ignored.
    validated_by: Optional[str] = None


class AgentRunCreate(BaseModel):
    project_id: str
    agent_role: str
    task_type: str
    model_name: str
    model_short: str = Field(..., description="short code for the ID, e.g. 'DS' or 'QW'")
    # P2: provenance fields backed by EXISTING agent_runs columns — they
    # were dead weight until agents started sending them.
    model_version: Optional[str] = Field(
        None, description="Model version tag (e.g. SASE_MODEL_VERSION env)")
    prompt_id: Optional[str] = None
    prompt_version: Optional[str] = None
    system_prompt_hash: Optional[str] = Field(
        None, description="Short sha256 of the system prompt actually used")
    prd_id: Optional[str] = None
    user_story_id: Optional[str] = None
    spec_id: Optional[str] = None
    blueprint_ids: List[str] = []
    rag_retrieval_enabled: bool = False
    rag_retrieved_doc_ids: List[str] = []


class AgentRunUpdate(BaseModel):
    status: str
    reflection_iterations: Optional[int] = None
    tools_used: Optional[List[str]] = None
    generated_files: Optional[List[str]] = None
    commit_hash: Optional[str] = None
    mrp_id: Optional[str] = None


class CRPCreate(BaseModel):
    project_id: str
    domain: str
    agent_run_id: Optional[str] = None
    prd_id: Optional[str] = None
    user_story_id: Optional[str] = None
    spec_id: Optional[str] = None
    severity: str
    blocking_issue_title: str
    blocking_issue_body: str
    context_summary: Dict[str, Any] = {}
    options_considered: List[Dict[str, Any]] = []
    agent_recommendation: Optional[Dict[str, Any]] = None
    required_decision: str
    required_role: str
    default_policy: str = "block_generation"


class VCRCreate(BaseModel):
    related_artifact_type: str  # 'CRP' | 'MRP'
    related_artifact_id: str
    decision_status: str
    selected_option: Optional[str] = None
    rationale: str
    decided_by: str
    decided_role: Optional[str] = None
    update_prd: bool = False
    update_user_story: bool = False
    update_spec: bool = False
    update_blueprint: bool = False
    update_tests: bool = False
    required_updates: List[str] = []
    # Identity is taken from the X-Acting-As header (api/security.py);
    # this field is accepted for backwards compatibility but ignored.
    decided_by: Optional[str] = None


class MRPCreate(BaseModel):
    project_id: str
    pull_request_number: int
    branch_name: str
    created_by_agent_run: Optional[str] = None
    prd_id: Optional[str] = None
    user_story_ids: List[str] = []
    acceptance_criteria_ids: List[str] = []
    spec_ids: List[str] = []
    blueprint_id: Optional[str] = None
    blueprint_version: Optional[str] = None
    change_summary: Optional[str] = None
    affected_modules: List[str] = []


class MRPEvidenceUpdate(BaseModel):
    unit_tests_status: Optional[str] = None
    integration_tests_status: Optional[str] = None
    e2e_tests_status: Optional[str] = None
    test_coverage_pct: Optional[float] = None
    lint_status: Optional[str] = None
    static_analysis_status: Optional[str] = None
    complexity_status: Optional[str] = None
    security_scan_status: Optional[str] = None
    dependency_scan_status: Optional[str] = None
    ai_review_status: Optional[str] = None
    ai_review_notes: Optional[List[str]] = None
    human_review_focus: Optional[str] = None
    # Phase 1: Provenance tagging - tracks who/what produced this evidence
    # Must be one of: "human", "tool", "llm"
    provenance: Optional[str] = Field(None, description="Source of evidence: human | tool | llm")
    # P7: raw execution evidence (full test output, scan findings, lint
    # output, run metadata). Stored in the audit entry context — NOT as
    # MRP columns — so the evidence JSONB carries what actually happened,
    # not just pass/fail badges.
    execution_context: Optional[Dict[str, Any]] = Field(
        None, description="Raw execution evidence persisted into the audit context")


class MRPHumanDecision(BaseModel):
    decision: str  # 'approved' | 'rejected' | 'needs_revision'
    rationale: Optional[str] = None
    # Identity is taken from the X-Acting-As header (api/security.py);
    # this field is accepted for backwards compatibility but ignored.
    human_reviewer: Optional[str] = None


class BlueprintCreate(BaseModel):
    id: str = Field(..., description="BP-<LAYER>-<seq>, e.g. BP-ANGULAR-FRONTEND-001")
    version: str = Field(..., description="e.g. 'v1.0'")
    scope: str = Field(..., description="'org' | 'project:<id>' | 'stack:<stack>'")
    body_ref: str = Field(..., description="Blueprint content (markdown/yaml)")
    approved_by: str = Field(..., description="Who approved: 'human:<name>' or 'agent:<role>'")
    change_note: Optional[str] = None


class BlueprintOut(BaseModel):
    id: str
    version: str
    scope: str
    body_ref: str
    approved_by: str
    change_note: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------- Phase 2: auth ----

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class LoginResponse(BaseModel):
    # Raw bearer token — shown exactly once, never stored server-side.
    token: str
    token_type: str = "bearer"
    expires_at: Optional[datetime] = None
    username: str


class MeResponse(BaseModel):
    username: str
    display_name: Optional[str] = None
    actor_id: str
