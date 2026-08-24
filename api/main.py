import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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


@app.middleware("http")
async def require_perimeter_token(request: Request, call_next):
    """
    Optional shared-secret perimeter (B2): when SASE_API_TOKEN is set
    (non-empty), every request must carry header X-API-Token equal to it.
    Read per-request so tests and runtime changes don't need a reload;
    unset/empty means local dev behaves exactly as before.
    """
    expected = os.environ.get("SASE_API_TOKEN", "")
    if expected:
        provided = request.headers.get("X-API-Token")
        if not provided or provided != expected:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid X-API-Token header."},
            )
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok"}
