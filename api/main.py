from fastapi import FastAPI
from api.routers import projects, requirements, agent_runs, crp, mrp, vcr, traceability

app = FastAPI(
    title="SASE Traceability Backbone",
    description=(
        "Implements the artifact chain from the SASE paper: "
        "PRD -> User Story -> Acceptance Criteria -> Spec -> Blueprint -> "
        "Agent Run -> Generated Code/Tests -> AI Review -> CRP (if needed) "
        "-> MRP -> Human Review -> VCR -> PR -> Commit -> Merge. "
        "This service owns artifact creation, gating, and audit — it does "
        "not itself call any LLM; agents call these endpoints as they work."
    ),
    version="0.1.0",
)

app.include_router(projects.router)
app.include_router(requirements.router)
app.include_router(agent_runs.router)
app.include_router(crp.router)
app.include_router(mrp.router)
app.include_router(vcr.router)
app.include_router(traceability.router)


@app.get("/health")
def health():
    return {"status": "ok"}
