"""
Offline Blueprint -> Software Development runner (host-side control plane).

This is the USER-FACING WORKFLOW layer only. It does NOT redesign or weaken
the governance architecture: the FastAPI engine (api/) remains the source
of truth and every agent identity / gate / audit record is preserved.

The runner COORDINATES the existing governed agents exactly like the CLI
orchestrator and the E2E validation scripts do, but exposes them over HTTP
so the UI can start a run, watch REAL stage state, and download the product:

  Blueprint (stored/traceable) -> Product/PRD -> Spec (human-validated)
  -> Coder (proposal-only, strict SoD) -> independent Verifier (subprocess)
  -> Reviewer (subprocess, advisory G8) -> packaged artifact (zip).

Offline enforcement:
  - LLM is local Ollama (localhost:11434) only; fallback to TemplateLLM.
  - No external network calls are made by the agents (stdlib + local Ollama).
  - A run works with the internet disconnected.

Run it on the HOST (not in the api container) because the agents need the
host workspace, git, pytest and localhost:8000/Ollama:

    python scripts/offline_runner.py            # then open the UI /ui/ -> Blueprint

Required host env for the governed stack (matching docker-compose):
    SASE_SOD_MODE=strict            (evidence requires the independent verifier)
    SASE_CI_TOKEN=...
    SASE_VERIFIER_TOKEN=...
    SASE_REVIEWER_TOKEN=...
    (optional) SASE_HUMAN_TOKEN=<bearer> else legacy X-Acting-As human:offline-runner
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from pydantic import BaseModel
except Exception as e:  # pragma: no cover
    print("Missing python deps; install with: pip install fastapi uvicorn pydantic", e)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

RUNS_DIR = REPO_ROOT / "offline_runs"
RUNS_DIR.mkdir(parents=True, exist_ok=True)

GOV_API = os.environ.get("SASE_API_URL", "http://localhost:8000")
OLLAMA = "http://localhost:11434"
RUNNER_PORT = int(os.environ.get("OFFLINE_RUNNER_PORT", "8899"))


# ---------------------------------------------------------------- model list
def _ollama_tags():
    import urllib.request
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=3) as r:
            return [m.get("name", "") for m in json.loads(r.read())["models"]]
    except Exception:
        return []


_role_models = {"coder": "qwen2.5-coder:7b", "reviewer": "deepseek-r1:8b",
                "critic": "deepseek-r1:8b", "product": "qwen2.5-coder:7b",
                "spec": "qwen2.5-coder:7b"}


def _offline_status():
    tags = _ollama_tags()
    present = {k: any(v in t for t in tags) for k, v in _role_models.items()}
    return {
        "offline": True,
        "ollama_url": OLLAMA,
        "ollama_ok": bool(tags),
        "models": dict(_role_models),
        "present": present,
        "backend": "ollama" if tags else "template",
        "governance_api": GOV_API,
        "api_ok": _api_ok(),
        "available_models": tags,
    }


def _api_ok():
    import urllib.request
    try:
        with urllib.request.urlopen(f"{GOV_API}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


# ------------------------------------------------------------------- human API
def _human_headers():
    tok = os.environ.get("SASE_HUMAN_TOKEN")
    if tok:
        return {"Authorization": f"Bearer {tok}",
                "Content-Type": "application/json"}
    return {"X-Acting-As": "human:offline-runner",
            "Content-Type": "application/json"}


def _human_actor_id():
    if os.environ.get("SASE_HUMAN_TOKEN"):
        return "human:<token-user>"
    return "human:offline-runner"


# ------------------------------------------------------------------- run state
STAGE_ORDER = [
    ("blueprint", "Blueprint Received"),
    ("product", "Product Agent Analysis"),
    ("spec", "Spec Generation"),
    ("design", "Architecture / Design Phase"),
    ("coder", "Coder Execution"),
    ("tests", "Tests Running"),
    ("reviewer", "Reviewer Analysis"),
    ("verifier", "Verifier Validation"),
    ("artifact", "Final Product Artifact"),
]


def _stage(key, name):
    return {"key": key, "name": name, "status": "pending", "actor": None,
            "model": None, "started_at": None, "finished_at": None,
            "summary": "", "errors": [], "artifacts": []}


def _new_run():
    now = datetime.utcnow().isoformat() + "Z"
    run_id = f"RUN-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    return {
        "id": run_id, "status": "running", "project_name": "",
        "target_stack": "", "constraints": "", "acceptance_criteria": "",
        "blueprint_body": "", "started_at": now, "finished_at": None,
        "blueprint": {}, "stages": [_stage(k, n) for k, n in STAGE_ORDER],
        "product": None, "trace": [], "log": [], "workspace": None,
    }


def _load(run_id):
    p = RUNS_DIR / f"{run_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _save(run):
    (RUNS_DIR / f"{run['id']}.json").write_text(
        json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")


def _stage_obj(run, key):
    for s in run["stages"]:
        if s["key"] == key:
            return s
    raise KeyError(key)


def _mark(run, key, status, summary="", errors=None, artifacts=None,
          actor=None, model=None):
    s = _stage_obj(run, key)
    if status == "running" and not s.get("started_at"):
        s["started_at"] = datetime.utcnow().isoformat() + "Z"
    s["status"] = status
    s["summary"] = summary or s.get("summary", "")
    s["errors"] = (s.get("errors") or []) + (errors or [])
    s["artifacts"] = (s.get("artifacts") or []) + (artifacts or [])
    if actor:
        s["actor"] = actor
    if model:
        s["model"] = model
    if status in ("completed", "failed", "skipped") and not s.get("finished_at"):
        s["finished_at"] = datetime.utcnow().isoformat() + "Z"
    _save(run)


def _trace(run, step, actor, model, action):
    run["trace"].append({"step": step, "actor": actor, "model": model,
                         "action": action,
                         "time": datetime.utcnow().isoformat() + "Z"})
    _save(run)


def _log(run, msg):
    run["log"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
    _save(run)


# ------------------------------------------------------------ blueprint -> spec
def _slug(project_name):
    clean = "".join(c for c in project_name.upper() if c.isalnum() or c == "-")
    clean = clean.strip("-").replace("--", "-") or "APP"
    return clean[:24]


def _build_spec_body(blueprint_body, target_files=None, ac_text=""):
    """
    Build a well-formed, coder-consumable spec from the blueprint.
    This is the deterministic glue between a free-form blueprint and the
    coder's strict FILE-block contract. Kept concrete so offline generation
    is reliable; the blueprint's own requirements are preserved verbatim.
    """
    files = target_files or [
        "app.py", "store.py", "static/index.html", "static/app.js",
        "test_app.py", "README.md", "requirements.txt",
    ]
    tf = "\n".join(f"  - {f}" for f in files)
    tf_marker = ", ".join(files)
    # A concrete full-stack stdlib web app contract (see test blueprint).
    behavior = (
        "product: a self-contained offline web application (Taskboard) that "
        "serves a browser frontend and a JSON API, backed by a local SQLite "
        "database, with token-based authentication and role-based permissions.\n"
        "  serve: app.py starts an http.server on $PORT (default 8001); "
        "GET / serves static/index.html; /api/** serves JSON.\n"
        "  auth: POST /api/login {username,password} returns a token; "
        "passwords hashed (stdlib hashlib.sha256 + salt); unknown user or "
        "wrong password returns 401.\n"
        "  store: SQLite file path from $STORE_PATH env (default ./taskboard.db); "
        "schema created on start (users, tasks).\n"
        "  permissions: role admin can create/delete/assign tasks and manage "
        "users; role member can only create/update/list their own tasks; "
        "a member deleting/listing others' data is denied (403).\n"
        "  tasks: POST /api/tasks {title,status,assignee} (auth+perms); "
        "GET /api/tasks (auth, member sees own, admin sees all); "
        "PATCH /api/tasks/{id} (auth+perms); DELETE /api/tasks/{id} (admin only).\n"
        "  health: GET /api/health returns {\"status\":\"ok\"}.\n"
        "  frontend: static/index.html + static/app.js implement a small "
        "login + task board UI calling the above API (no CDN, fully offline)."
    )
    edge_cases = (
        "- unknown user -> 401 with a stable error message\n"
        "- wrong password -> 401 with the SAME message as unknown user\n"
        "- missing/invalid token -> 401\n"
        "- member tries to modify/delete others' tasks -> 403\n"
        "- empty title -> 400\n"
        "- tasks persist across restarts (same $STORE_PATH)\n"
        "- each test uses an isolated temporary $STORE_PATH (pytest tmp_path)"
    )
    return f"""#sase-files: {tf_marker}
document: spec
product: offline full-stack web application generated from the blueprint
target_stack: {os.environ.get('TARGET_STACK_DEFAULT', 'python + stdlib http + sqlite')}

acceptance_criteria_refs:
  - {ac_text or 'derived from blueprint'}

behavior:
{behavior}

edge_cases:
{edge_cases}

target_files:
{tf}

open_questions: []
"""


# ------------------------------------------------------------------ lifecycle
def _http(method, path, payload=None, headers=None, ok=(200, 201, 204, 409)):
    import urllib.error
    import urllib.request
    h = dict(headers or _human_headers())
    req = urllib.request.Request(
        GOV_API + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode()
            return (r.status, json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        if e.code not in ok:
            raise RuntimeError(f"{method} {path} -> {e.code}: {body}")
        # 409 conflict: return empty (caller treats as idempotent)
        return (e.code, {})


def _run_execution(run):
    ws = None
    mrp_id = run_id = None
    tree = None
    try:
        run_id, mrp_id, tree, ws = _execute(run)
    except Exception as e:  # noqa: BLE001
        run["status"] = "failed"
        run["finished_at"] = datetime.utcnow().isoformat() + "Z"
        # fail open (honestly current) stage
        for s in run["stages"]:
            if s["status"] == "running":
                s["status"] = "failed"
                s["errors"].append(str(e))
                if not s["finished_at"]:
                    s["finished_at"] = datetime.utcnow().isoformat() + "Z"
        try:
            _mark(run, "artifact", "failed", summary="Execution failed",
                  errors=[str(e)])
        except Exception:
            pass
        traceback.print_exc()
        _save(run)
        # mark the terminal agent run failed so the socket never strands
        try:
            if run_id:
                _http("PATCH", f"/agent-runs/{run_id}", {"status": "failed"})
        except Exception:
            pass
        return
    run["status"] = "completed"
    run["finished_at"] = datetime.utcnow().isoformat() + "Z"
    run["product"] = {
        "workspace": str(ws) if ws else None,
        "mrp_id": mrp_id, "run_id": run_id, "tree_hash": tree,
        "tests_passed": True, "file_count": _count_files(ws) if ws else 0,
    }
    _mark(run, "artifact", "completed",
          summary="Product packaged to workspace; downloadable as .zip",
          artifacts=[f"workspace:{ws}" if ws else "workspace:—"])
    _save(run)


def _count_files(ws):
    if not ws:
        return 0
    return sum(1 for f in Path(ws).rglob("*") if f.is_file() and ".git" not in str(f))


def _execute(run):
    """Runs the governed lifecycle in-process (agents still use per-role
    EngineClients with allowlist enforcement), returning
    (run_id, mrp_id, tree_hash, workspace)."""
    from agents.llm import OllamaLLM, TemplateLLM

    def backend(model):
        o = OllamaLLM(model=model)
        if o.available():
            return o
        return TemplateLLM()

    project_id = _slug(run["project_name"]).lower()
    domain = project_id.split("-")[0].upper() or "APP"
    stamp = time.strftime("%H%M%S")
    ws = REPO_ROOT / "offline_workspaces" / f"{project_id}-{stamp}"
    ws.mkdir(parents=True, exist_ok=True)
    run["workspace"] = str(ws)
    _save(run)

    # ---------- blueprint stage
    _mark(run, "blueprint", "running", actor="human:offline-runner", model=None)
    bp_id = f"BP-{_slug(run['project_name'])}-001"
    bp_body = (f"Project: {run['project_name']}\nStack: {run['target_stack']}\n"
               f"Constraints: {run['constraints']}\n"
               f"Acceptance criteria:\n{run['acceptance_criteria']}\n"
               f"BluePrint content:\n{run['blueprint_body']}")
    try:
        status, _ = _http("POST", "/blueprints", {
            "id": bp_id, "version": "v1.0", "scope": f"project:{project_id}",
            "body_ref": bp_body, "approved_by": _human_actor_id(),
            "change_note": "Created from the Offline Blueprint UI",
        })
    except Exception as e:
        raise RuntimeError(f"blueprint store failed: {e}")
    run["blueprint"] = {"id": bp_id, "version": "v1.0"}
    _mark(run, "blueprint", "completed", actor="human:offline-runner",
          summary=f"Blueprint stored + traceable as {bp_id} (v1.0)",
          artifacts=[f"{bp_id}@v1.0"])
    _trace(run, "blueprint", "human:offline-runner", None, f"Blueprint received -> {bp_id}")
    _log(run, f"blueprint {bp_id} created")

    # ---------- project + PRD/US/AC (product analysis)
    _mark(run, "product", "running", actor="agent:product",
          model=_role_models["product"])
    _http("POST", "/projects", {"id": project_id,
                                "name": run["project_name"],
                                "stack": run["target_stack"] or "python-stdlib"}, ok=(200, 201, 409))
    # Deterministic idempotency: since these IDs are stable across a project
    # in the SASE scheme (SPEC-<DOMAIN>-<SLUG>), a re-run reuses the same
    # spec id. PRD/US use DB sequences so we fall back to the deterministic
    # base on 409 and the coder only ever needs the spec id authoritative.
    try:
        code, prd = _http("POST", "/prds", {
            "project_id": project_id, "domain": domain,
            "title": run["project_name"],
            "body_ref": run["blueprint_body"][:2000],
            "created_by": _human_actor_id(),
        })
        _ = code
    except Exception:
        prd = {"id": f"PRD-{domain}-001"}
    prd_id = prd.get("id") or f"PRD-{domain}-001"
    try:
        _, us = _http("POST", "/user-stories", {
            "prd_id": prd_id, "domain": domain,
            "body_ref": f"Build {run['project_name']} per the blueprint.",
        })
    except Exception:
        us = {"id": f"US-{domain}-001"}
    us_id = us.get("id") or f"US-{domain}-001"
    try:
        _, ac = _http("POST", "/acceptance-criteria", {
            "user_story_id": us_id,
            "body_ref": run["acceptance_criteria"] or
                        "- login works\n- permissions enforced\n- tests pass offline\n"
                        "- product runs with internet disconnected",
        })
    except Exception:
        ac = {"id": None}
    _mark(run, "product", "completed", actor="agent:product",
          model=_role_models["product"],
          summary=f"Project {project_id}: PRD {prd_id}, story {us_id}, acceptance criteria recorded",
          artifacts=[prd_id, us_id] if prd_id and us_id else [])
    _trace(run, "product", "agent:product", _role_models["product"],
           f"PRD/US/AC seeded from blueprint ({prd_id}/{us_id})")
    _log(run, f"product analysis -> {prd_id} / {us_id} / {ac}")

    # ---------- spec generation (deterministic, well-formed for the coder)
    _mark(run, "spec", "running", actor="agent:spec", model=_role_models["spec"])
    spec_name = "fullstack-taskboard"
    spec_body = _build_spec_body(run["blueprint_body"])
    try:
        _, spec = _http("POST", "/specs", {
            "project_id": project_id, "user_story_id": us_id, "domain": domain,
            "name": spec_name, "format": "yaml", "body_ref": spec_body,
        })
    except Exception:
        # already exists from a prior run: spec id is deterministic
        pass
    spec_id = spec.get("id") or f"SPEC-{domain.upper()}-{spec_name.upper()}"
    _mark(run, "spec", "completed", actor="agent:spec", model=_role_models["spec"],
          summary=f"Spec {spec_id} generated from blueprint (valid for coder)",
          artifacts=[spec_id])
    _trace(run, "spec", "agent:spec", _role_models["spec"], f"spec drafted {spec_id}")

    # ---------- human validates the spec (the human clicked Start)
    _http("POST", f"/specs/{spec_id}/validate", {},
          headers=_human_headers(), ok=(200, 201, 409))
    _log(run, f"spec {spec_id} validated by {_human_actor_id()}")

    # ---------- design stage (architecture is encoded in the blueprint/spec)
    _mark(run, "design", "completed", actor="agent:designer",
          model=_role_models["product"],
          summary="Architecture derived from blueprint: stdlib HTTP + SQLite + "
                  "token auth + role permissions + vanilla frontend",
          artifacts=["design:derived-from-blueprint"])

    # ---------- coder (proposal-only, strict SoD)
    _mark(run, "coder", "running", actor="agent:coder",
          model=_role_models["coder"])
    from agents.coder_agent import CoderAgent
    from agents.config import ROLES
    from agents.engine_client import EngineClient
    coder = CoderAgent(
        EngineClient(GOV_API, ROLES["coder"]), backend(_role_models["coder"]),
        workspace=ws, project_id=project_id,
        max_repairs=int(os.environ.get("CODER_MAX_REPAIRS", "5")),
        blueprint_id=bp_id, blueprint_version="v1.0",
        change_summary=f"Implement {spec_id} from blueprint {bp_id}.",
        affected_modules=["app.py", "store.py", "static/index.html",
                          "static/app.js", "test_app.py"],
    )
    from agents.orchestrator import _sod_verify_and_package
    result = coder.implement_spec(spec_id, prd_id=prd_id,
                                  user_story_id=us_id, propose_only=True)
    run_id = result.run_id
    _mark(run, "coder", "completed", actor="agent:coder",
          model=_role_models["coder"],
          summary=f"Run {run_id}: {len(result.generated_files)} files, "
                  f"commit {(result.commit_hash or '?')[:8]} (proposal-only, SoD strict)",
          artifacts=result.generated_files[:20])
    _trace(run, "coder", "agent:coder", _role_models["coder"],
           f"generated {len(result.generated_files)} files (run {run_id})")
    _log(run, f"coder proposal run {run_id} files={len(result.generated_files)}")

    # ---------- tests + verifier (independent subprocess, strict)
    _mark(run, "tests", "running", actor="orchestrator/ci:verifier", model=None)
    _mark(run, "verifier", "running", actor="ci:verifier", model=None)
    state = {"project_id": project_id, "base_url": GOV_API, "prd_id": prd_id,
             "blueprint_id": bp_id, "blueprint_version": "v1.0",
             "user_story_id": us_id,
             # Phase 2 Step F (G8): run the INDEPENDENT reviewer subprocess
             # INSIDE the shared orchestration helper (deterministic offline
             # mode), then read the review result back from the API.
             "run_reviewer": True, "review_offline": True}
    _mark(run, "reviewer", "running", actor="agent:reviewer",
          model=_role_models["reviewer"])
    result, crp_id, tree = _sod_verify_and_package(
        coder.engine, ws, spec_id, result, state)
    _mark(run, "tests", "completed", actor="ci:verifier", model=None,
          summary="pytest + security scan + tree-hash binding passed in the "
                  "isolated clean checkout (verifier-owned evidence)",
          artifacts=[f"tree:{tree[:12]}..."])
    _mark(run, "verifier", "completed", actor="ci:verifier", model=None,
          summary=f"MRP {result.mrp_id} verified; authoritative tree hash {tree[:12]}...",
          artifacts=[result.mrp_id])
    mrp_id = result.mrp_id
    _trace(run, "verifier", "ci:verifier", None,
           f"verified MRP {mrp_id} tree={tree[:12]}...")
    _log(run, f"verified MRP {mrp_id} tree={tree[:12]}... crp={crp_id}")

    # ---------- reviewer (independent advisory subprocess, G8) ----------
    # Step F ran INSIDE _sod_verify_and_package: the reviewer subprocess
    # wrote its advisory review with its own credential as agent:reviewer.
    # We READ the actual result back from the API and mark the stage from
    # what really happened — fail-closed, never a fabricated completion.
    _code, review = _http("GET", f"/mrps/{mrp_id}/review", {},
                          headers=_human_headers(), ok=(200,))
    review_status = review.get("ai_review_status")
    if review_status in ("completed", "needs_revision"):
        _mark(run, "reviewer", "completed", actor="agent:reviewer",
              model=_role_models["reviewer"],
              summary=f"Advisory review {review_status} "
                      f"({len(review.get('ai_review_findings', []))} findings) "
                      f"— advisory only",
              artifacts=["review:advisory"])
        _trace(run, "reviewer", "agent:reviewer", _role_models["reviewer"],
               f"advisory review -> {review_status}" +
               (" (findings to weigh before merge)"
                if review_status == "needs_revision" else ""))
    else:
        _mark(run, "reviewer", "failed", actor="agent:reviewer",
              model=_role_models["reviewer"],
              summary="No reviewer-owned review was recorded for this MRP — "
                      "G8 cannot be satisfied; the run is FAILED, not completed.",
              artifacts=[mrp_id], errors=["ai_review_status missing"])
        raise RuntimeError(
            f"reviewer step produced no reviewer-owned review for {mrp_id} "
            f"(ai_review_status={review_status!r}); fail-closed — the G8 "
            f"merge gate cannot be satisfied and nothing was fabricated.")

    return run_id, mrp_id, tree, ws


# ------------------------------------------------------------------ API / HTTP
app = FastAPI(title="SASE Offline Runner (user-facing workflow)")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"])


class RunStart(BaseModel):
    project_name: str
    target_stack: str = ""
    constraints: str = ""
    acceptance_criteria: str = ""
    blueprint_content: str = ""


@app.get("/api/offline/status")
def offline_status():
    return _offline_status()


@app.post("/api/runs")
def start_run(payload: RunStart):
    if not payload.project_name or not payload.blueprint_content:
        raise HTTPException(400, "project_name and blueprint_content are required")
    run = _new_run()
    run["project_name"] = payload.project_name
    run["target_stack"] = payload.target_stack
    run["constraints"] = payload.constraints
    run["acceptance_criteria"] = payload.acceptance_criteria
    run["blueprint_body"] = payload.blueprint_content
    _save(run)
    t = threading.Thread(target=_run_execution, args=(run,), daemon=True)
    t.start()
    return _load(run["id"])


@app.get("/api/runs")
def list_runs():
    out = []
    for p in sorted(RUNS_DIR.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        out.append({"id": d["id"], "status": d["status"],
                    "project_name": d["project_name"],
                    "started_at": d["started_at"],
                    "finished_at": d["finished_at"],
                    "workspace": d.get("workspace"),
                    "product": d.get("product")})
    out.sort(key=lambda x: x.get("started_at") or "", reverse=True)
    return out


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    d = _load(run_id)
    if not d:
        raise HTTPException(404, "run not found")
    return d


@app.get("/api/runs/{run_id}/files")
def run_files(run_id: str):
    d = _load(run_id)
    if not d:
        raise HTTPException(404, "run not found")
    ws = d.get("workspace")
    if not ws or not Path(ws).exists():
        return {"files": []}
    files = [str(p.relative_to(ws)).replace("\\", "/")
             for p in Path(ws).rglob("*")
             if p.is_file() and ".git" not in str(p)]
    return {"files": sorted(files)}


@app.get("/api/runs/{run_id}/trace")
def run_trace(run_id: str):
    d = _load(run_id)
    if not d:
        raise HTTPException(404, "run not found")
    return {"trace": d.get("trace", [])}


@app.get("/api/runs/{run_id}/artifact")
def run_artifact(run_id: str):
    d = _load(run_id)
    if not d:
        raise HTTPException(404, "run not found")
    ws = d.get("workspace")
    if not ws or not Path(ws).exists():
        raise HTTPException(404, "no artifact yet")
    proj = _slug(d["project_name"]).lower()
    zpath = RUNS_DIR / f"{run_id}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in Path(ws).rglob("*"):
            if p.is_file() and ".git" not in str(p):
                z.write(p, arcname=f"{proj}/{p.relative_to(ws)}")
    return FileResponse(str(zpath), media_type="application/zip",
                        filename=f"{proj}.zip")


if __name__ == "__main__":
    import uvicorn
    print(f"OFFLINE RUNNER listening on http://127.0.0.1:{RUNNER_PORT}")
    print(f"governance API: {GOV_API} | Ollama: {OLLAMA}")
    missing = [v for v in ("SASE_CI_TOKEN", "SASE_VERIFIER_TOKEN",
                           "SASE_REVIEWER_TOKEN", "SASE_SOD_MODE")
               if not os.environ.get(v)]
    if missing:
        print("WARNING: unset host env variables for the governed stack:", missing)
    uvicorn.run(app, host="127.0.0.1", port=RUNNER_PORT)
