"""
Real Coder <-> Verifier communication trace (strict SoD, live engine).

Drives the EXISTING governed machinery end-to-end and prints, at every
communication boundary, the real [comms] lines produced by
agents/engine_client.py (opt-in: SASE_ENGINE_TRACE=1). Nothing is mocked:
the Coder is the real agents/coder_agent.CoderAgent with a live Ollama
backend, the handoff is the real agents/orchestrator._sod_verify_and_package
(MRP -> immutable VerificationRequest), and the Verifier is the real
independent subprocess (agents/verifier.py --claim, ci:verifier identity).

Boundaries shown:
  CODER -> engine: GET /specs/{id}; POST /agent-runs; PATCH /agent-runs/{id}
  ORCH  -> engine: POST /mrps; POST /verification-requests; GET .../status
  VERIFIER (subprocess) -> engine: POST /verification-requests/claim-next;
                                    PATCH /mrps/{id}/evidence;
                                    POST /verification-requests/{id}/complete
  ORCH  <- engine: verifier PASS + authoritative verified_tree_hash
  G7    : evaluated with the REAL gate inputs (MRP.verified_tree_hash vs
          the verifier-owned audit evidence row), then the REAL
          POST /mrps/{id}/check-ready endpoint.

Coder quality varies (local 7B model, propose_only with no self-repair by
design in strict SoD): the demo retries up to ATTEMPTS fresh seed chains and
presents whichever run completes, with pass/fail labeled honestly. A failed
run is a REAL rejection by the verifier — that is the machinery working.

Usage (run from the repo root; requires the live docker stack):
  $env:SASE_ENGINE_TRACE   = "1"
  $env:SASE_VERIFIER_TOKEN = "dev-verifier-token-change-me"   # matches the API container
  $env:SASE_SOD_MODE       = "strict"
  python scripts/trace_coder_verifier.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

BASE = os.environ.get("SASE_BASE_URL", "http://localhost:8000")
STAMP = time.strftime("%H%M%S")
PROJECT = f"trace-demo-{STAMP}"
DOMAIN = "TRACE"
ATTEMPTS = int(os.environ.get("SASE_DEMO_ATTEMPTS", "3"))
SPEC_NAMES = [f"comms-demo-{STAMP}-a{i}" for i in range(1, ATTEMPTS + 1)]

from agents.coder_agent import CoderAgent
from agents.config import ROLES
from agents.engine_client import EngineClient
from agents.llm import OllamaLLM

SPEC_BODY = """#sase-files: todo.py, test_todo.py
document: spec
product: simple command-line TODO app
target_stack: python + stdlib
cli_contract:
  - exactly one command word: `add`, `list`, or `done`
  - `python todo.py add <text>` appends and saves a pending task
  - `python todo.py list` (NO extra argument) prints tasks as "<id>: [ ] <text>"
  - `python todo.py done <id>` marks a task done, printed "[x]"
  - storage path from $STORE (default ./todo.json)
edge_cases:
  - unknown command prints a clear error to stderr and exits non-zero
  - done with a missing id prints "Task not found." to stderr and exits non-zero
  - list with no tasks prints "No tasks." and exits 0
acceptance_criteria_refs:
  - derived from blueprint
target_files:
  - todo.py
  - test_todo.py
open_questions: []
"""


def human_client() -> EngineClient:
    """Unbound client that acts as human:m.barani (legacy gate header)."""
    return EngineClient(BASE, None)


def seed(api: EngineClient, spec_name: str):
    H = {"X-Acting-As": "human:m.barani"}
    try:
        api.request("POST", "/projects", {"id": PROJECT, "name": "Trace Demo",
                                          "stack": "python-stdlib"}, extra=H)
    except RuntimeError as exc:
        if "409" not in str(exc):
            raise  # the retry loop reuses the same project; conflict is fine
    prd = api.request("POST", "/prds", {"project_id": PROJECT, "domain": DOMAIN,
                                        "title": "Simple TODO CLI",
                                        "body_ref": "A stdlib-only command-line TODO app.",
                                        "created_by": "human:m.barani"}, extra=H)
    us = api.request("POST", "/user-stories", {"prd_id": prd["id"], "domain": DOMAIN,
                                               "body_ref": "As a user I add/list/done tasks from the CLI."},
                     extra=H)
    ac = api.request("POST", "/acceptance-criteria", {"user_story_id": us["id"],
                                                      "body_ref": "- add/list/done work\n- persists\n- missing id handled"},
                     extra=H)
    spec = api.request("POST", "/specs", {"project_id": PROJECT, "user_story_id": us["id"],
                                          "domain": DOMAIN, "name": spec_name, "body_ref": SPEC_BODY},
                       extra=H)
    api.request("POST", f"/specs/{spec['id']}/validate", {},
                extra={"X-Acting-As": "human:m.barani"})
    return prd["id"], us["id"], spec["id"]


def g7_verdict(mrp: dict, audit_rows: list[dict]):
    """Same inputs api/gates.py uses: MRP.verified_tree_hash (bound by the
    verifier-only evidence PATCH) vs the ci:verifier-owned audit evidence row."""
    bound = mrp.get("verified_tree_hash")
    evidenced = None
    for row in audit_rows:
        if row.get("action") != "update_mrp_evidence":
            continue
        ctx = row.get("context") or {}
        exec_ctx = ctx.get("execution_context") or {}
        if exec_ctx.get("runner") == "ci:verifier":
            evidenced = exec_ctx.get("tree_hash")
    reasons = []
    if not bound:
        reasons.append("verification not independently owned (MRP has no verifier-bound verified_tree_hash)")
    elif not evidenced:
        reasons.append("verification not independently owned (no verifier-owned evidence: runner != 'ci:verifier')")
    elif evidenced != bound:
        reasons.append("verification not independently owned (evidence tree_hash != MRP verified_tree_hash)")
    return (len(reasons) == 0), reasons, bound, evidenced


def try_attempt(seed_api: EngineClient, n: int, spec_name: str):
    """One full real pipeline run. Returns (result, tree) or (None, error)."""
    print(f"\n{'=' * 72}\nATTEMPT {n}/{ATTEMPTS} — spec {spec_name}\n{'=' * 72}")
    prd_id, us_id, spec_id = seed(seed_api, spec_name)

    print(f"\n--- [2] WHAT THE CODER RECEIVES ---")
    spec = seed_api.request("GET", f"/specs/{spec_id}",
                            extra={"X-Acting-As": "human:m.barani"})
    print(f"spec id: {spec['id']}  human_validated={spec.get('human_validated')}")

    print(f"\n--- [3] AGENT A: CODER STARTS (real llm, propose_only) ---")
    ws = Path(tempfile.mkdtemp(prefix="sase-comms-demo-"))
    def git(*args):
        subprocess.run(["git", *args], cwd=ws, check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.name", "agent:coder")
    git("config", "user.email", "coder@local")

    coder_engine = EngineClient(BASE, ROLES["coder"])
    coder = CoderAgent(coder_engine, OllamaLLM(ROLES["coder"].model),
                       workspace=ws, project_id=PROJECT,
                       blueprint_id="BP-TRACE-001", blueprint_version="v1.0",
                       change_summary=f"Implement {spec_id} per validated spec (SoD trace demo).")
    result = coder.implement_spec(spec_id, prd_id=prd_id, user_story_id=us_id,
                                  propose_only=True)
    # NOTE: ws is intentionally kept — the verifier subprocess checks out the
    # pinned commit FROM this worktree (worktree_ref is in the request).

    print(f"\n--- [4] CODER OUTPUT / ARTIFACT ---")
    print(f"run_id:           {result.run_id}")
    print(f"commit_hash:      {result.commit_hash}")
    print(f"generated_files:  {result.generated_files}")
    print(f"verification_pending: {result.verification_pending} (proposal-only, strict SoD)")

    print(f"\n--- [5] HANDOFF: ORCHESTRATOR -> VERIFIER (real SoD path) ---")
    from agents.orchestrator import _sod_verify_and_package
    state = {"project_id": PROJECT, "base_url": BASE, "prd_id": prd_id,
             "user_story_id": us_id, "blueprint_id": "BP-TRACE-001",
             "blueprint_version": "v1.0"}
    try:
        result, crp_id, tree = _sod_verify_and_package(
            coder_engine, ws, spec_id, result, state)
        print(f"\n>>> ATTEMPT {n} VERIFICATION: PASS (tree={tree[:12]}…)")
    except RuntimeError as exc:
        tree = None
        if "did not PASS" in str(exc):
            print(f"\n>>> ATTEMPT {n} VERIFICATION: REJECTED by the verifier "
                  f"(status from the request, not mocked).")
            print(f"    the MRP/evidence still exist and are auditable — "
                  f"shown in sections [6]-[8].")
        else:
            print(f"\n>>> ATTEMPT {n} OPERATIONAL FAILURE: {exc}")
    return result, tree, prd_id, us_id, spec_id


def main():
    print("=" * 72)
    print(f"SASE Coder <-> Verifier REAL communication trace "
          f"(SASE_ENGINE_TRACE={os.environ.get('SASE_ENGINE_TRACE')!r})")
    print("=" * 72)

    seed_api = human_client()
    outcome = None
    for n, spec_name in enumerate(SPEC_NAMES, 1):
        outcome = try_attempt(seed_api, n, spec_name)
        if outcome[1] is not None:  # a tree hash means verification PASSED
            break
    result, tree, *_ = outcome

    print(f"\n{'=' * 72}\nRESULT: the trace above is REAL (nothing mocked).")
    if tree is None:
        print(f"Verification was REJECTED in all {ATTEMPTS} attempts — codegen "
              "quality is the known #1 risk (local 7B, propose_only). "
              "The machinery (claim/evidence/complete/fail-closed) worked "
              "correctly every time. Showing the last attempt's MRP/evidence "
              "trail below.")
    else:
        print(f"Verification PASSED on the last attempt shown. "
              f"Authoritative tree hash: {tree[:12]}…")

    H = {"X-Acting-As": "human:m.barani"}
    mrp = seed_api.request("GET", f"/mrps/{result.mrp_id}", extra=H)
    audit = seed_api.request("GET", f"/traceability/audit/MRP/{result.mrp_id}", extra=H)

    print(f"\n--- [6] WHAT THE VERIFIER WROTE BACK (real evidence, real audit) ---")
    print(f"MRP {result.mrp_id}:")
    for k in ("unit_tests_status", "security_scan_status", "lint_status",
              "static_analysis_status", "verified_tree_hash", "status"):
        print(f"  {k} = {mrp.get(k)}")
    print("audit rows touching this MRP:")
    for row in audit:
        ctx = row.get("context") or {}
        exec_ctx = ctx.get("execution_context") or {}
        extra_info = ""
        if exec_ctx.get("runner"):
            extra_info = f" runner={exec_ctx.get('runner')}"
        if ctx.get("tree_hash") or exec_ctx.get("tree_hash"):
            extra_info += f" tree={ctx.get('tree_hash') or exec_ctx.get('tree_hash')}"
        print(f"  {row.get('timestamp','')} {row.get('actor_id','')}: {row.get('action')}{extra_info}")

    print(f"\n--- [7] G7: verifier-ownership + tree-hash binding ---")
    ready, reasons, bound, evidenced = g7_verdict(mrp, audit)
    print(f"MRP.verified_tree_hash               = {bound}")
    print(f"ci:verifier evidence tree_hash        = {evidenced}")
    print(f"G7 => {'ACCEPTS' if ready else 'REJECTS'}")
    for r in reasons:
        print(f"  block: {r}")

    print(f"\n--- [8] REAL GATE ENDPOINT: POST /mrps/{{id}}/check-ready ---")
    check = seed_api.request("POST", f"/mrps/{result.mrp_id}/check-ready", {},
                             extra=H)
    print(f"ready={check['ready']} status={check['status']}")
    for r in check["blocking_reasons"]:
        print(f"  block: {r}")
    print("(G8 'review' blockers come from the independent Reviewer agent, "
          "which is NOT part of this Coder+Verifier demo; G7 itself passed if shown above.)")

    print(f"\n=== DONE. run {result.run_id} mrp={result.mrp_id}"
          + (f" tree={tree[:12]}…" if tree else " (verification rejected)"))
    print(f"Recreate G7 inputs: GET /mrps/{result.mrp_id} and "
          f"GET /traceability/audit/MRP/{result.mrp_id}")


if __name__ == "__main__":
    main()