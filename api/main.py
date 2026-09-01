import hmac
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from api.routers import (projects, requirements, agent_runs, crp, mrp, vcr,
                         traceability, evidence, blueprints, auth, dashboard,
                         verification_requests, review)

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
    version="0.2.0",
)

app.include_router(projects.router)
app.include_router(requirements.router)
app.include_router(agent_runs.router)
app.include_router(crp.router)
app.include_router(mrp.router)
app.include_router(vcr.router)
app.include_router(traceability.router)
app.include_router(evidence.router)
app.include_router(blueprints.router)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(verification_requests.router)
app.include_router(review.router)

# Governance Dashboard UI — a pure client layer over the API (static files,
# zero build tooling, air-gap safe). Served under /ui; / redirects there.
from fastapi.staticfiles import StaticFiles  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from starlette.responses import RedirectResponse  # noqa: E402

_UI_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                       "static", "ui")
if os.path.isdir(_UI_DIR):  # keeps tests/API-only deploys working
    _UI_INDEX = os.path.join(_UI_DIR, "index.html")

    # Human access flow entry points. Both serve the same SPA shell; the
    # client (static/ui/app.js boot) decides what to render based on the
    # path + session token. Registered BEFORE the /ui mount so they win.
    @app.get("/ui/login", include_in_schema=False)
    def ui_login_page():
        """Login page — the UI entry point for unauthenticated humans."""
        return FileResponse(_UI_INDEX)

    @app.get("/ui/dashboard", include_in_schema=False)
    def ui_dashboard_page():
        """Protected landing — client redirects to /ui/login without a token."""
        return FileResponse(_UI_INDEX)

    app.mount("/ui", StaticFiles(directory=_UI_DIR, html=True), name="ui")


@app.get("/", include_in_schema=False)
def root_redirect():
    return RedirectResponse(url="/ui/")


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
        # P3: constant-time comparison — no timing side channel.
        if not provided or not hmac.compare_digest(
                provided.encode(), expected.encode()):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid X-API-Token header."},
            )
    return await call_next(request)


@app.on_event("startup")
def reap_orphan_runs_on_startup() -> None:
    """
    P4: an agent process that dies mid-run leaves a 'running' row with no
    terminal patch (the in-process except-handler only covers caught
    exceptions). On every API startup, runs still marked 'running' after
    the configured age are flipped to 'failed' by the system actor
    'orphan-reaper', with an audit entry — reusing the exact transition
    and audit patterns of PATCH /agent-runs/{id}. Failures are logged,
    never fatal (the API must boot even if this sweep can't run).
    """
    from api.database import SessionLocal
    from api.routers.agent_runs import reap_orphan_runs

    try:
        db = SessionLocal()
        try:
            reaped = reap_orphan_runs(db)
        finally:
            db.close()
        if reaped:
            print(f"[startup] orphan-run reaper: marked failed: {reaped}")
    except Exception as e:  # pragma: no cover - depends on live DB state
        print(f"[startup] orphan-run reaper skipped: {e}")


@app.get("/health")
def health():
    return {"status": "ok"}
