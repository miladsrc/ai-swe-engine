"""
End-to-end SoD validation demo: "Internal Task Manager".

Drives the REAL governed machinery with a deterministic proposal (the point
is validating TRUST BOUNDARIES, not LLM prose):

  human requirement -> PRD/US/AC/spec (seeded via API)
  -> human validates spec   (Bearer token, authoritative identity)
  -> CoderAgent.propose_only (deterministic FILE-block proposal, committed)
  -> orchestrator verification (clean checkout + tree hash + tests/scan/lint)
  -> evidence PATCH (runner=orchestrator, provenance=tool, tree_hash)
  -> MRP -> human approval (via the dashboard)

Usage:
  SASE_HUMAN_TOKEN=<token> SASE_CI_TOKEN=dev-ci-token-change-me \
      python scripts/run_demo_validation.py
"""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = os.environ.get("SASE_BASE_URL", "http://localhost:8000")
PROJECT = "demo-task-manager"
DOMAIN = "DTM"
WORKSPACE = Path(os.environ.get(
    "SASE_DEMO_WORKSPACE",
    str(Path(__file__).resolve().parents[2] / "demo-task-manager")))
PROPOSAL = Path(__file__).with_name("demo_proposal.txt").read_text("utf-8")

if not os.environ.get("SASE_HUMAN_TOKEN"):
    sys.exit("Set SASE_HUMAN_TOKEN (from POST /auth/login) to run the demo.")
if not os.environ.get("SASE_CI_TOKEN"):
    sys.exit("Set SASE_CI_TOKEN for evidence recording.")


def call(method, path, payload=None, token=None, ok=(200, 201)):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(payload).encode() if payload is not None else None,
                                 headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        if e.code in ok:
            # 409 re-run: fetch the existing artifact where possible
            if method == "POST" and path == "/projects":
                return {"id": payload["id"]}
            if path.startswith("/prds"):
                return _find_existing("/prds", token) or {}
            return {}
        raise RuntimeError(f"{method} {path} -> {e.code}: {body}") from e


def _find_existing(path, token):
    return None


def main():
    token = os.environ["SASE_HUMAN_TOKEN"]
    human = call("GET", "/auth/me", token=token)["actor_id"]
    print(f"[demo] acting human: {human}")

    # ---- governed chain: project -> PRD -> story -> AC -> spec -------------
    # Idempotent: on 409 re-use the deterministic ids from the prior run.
    FALLBACK = {"prd": f"PRD-{DOMAIN}-001", "us": f"US-{DOMAIN}-001",
                "spec": f"SPEC-{DOMAIN}-TASK-MANAGER-CORE"}
    call("POST", "/projects", {
        "id": PROJECT, "name": "Internal Task Manager (SoD demo)",
        "stack": "python-cli"}, token=token, ok=(200, 201, 409))
    try:
        prd = call("POST", "/prds", {
            "project_id": PROJECT, "domain": DOMAIN,
            "title": "Internal Task Manager",
            "body_ref": "Track internal tasks: create, update, list, complete.",
            "created_by": human}, token=token)
        us = call("POST", "/user-stories", {
            "prd_id": prd["id"], "domain": DOMAIN,
            "body_ref": "As an engineer I manage tasks via the TaskManager API."})
        ac = call("POST", "/acceptance-criteria", {
            "user_story_id": us["id"],
            "body_ref": "- create returns incrementing ids\n"
                        "- update/complete on unknown id raises KeyError\n"
                        "- empty titles rejected\n- list can exclude done"})
        spec = call("POST", "/specs", {
            "project_id": PROJECT, "user_story_id": us["id"], "domain": DOMAIN,
            "name": "task-manager-core", "body_ref":
                "behavior:\n"
                "  create: returns incrementing ids; empty title rejected\n"
                "  update: renames; unknown id raises KeyError\n"
                "  complete: marks done; unknown id raises KeyError\n"
                "  list: returns dicts; include_done=False filters done\n"
                "acceptance_criteria_refs:\n" + ac_body_ref(ac) +
                "\nopen_questions: []\n"}, token=None)
        ids = {"prd": prd["id"], "us": us["id"], "spec": spec["id"]}
    except RuntimeError as e:
        if "409" not in str(e):
            raise
        print("[demo] chain artifacts exist from a prior run — reusing ids")
        ids = dict(FALLBACK)
    print(f"[demo] chain ready: {ids['prd']} / {ids['us']} / {ids['spec']}")

    # ---- HUMAN GATE 1: validate the spec -----------------------------------
    r = urllib.request.Request(
        BASE + f"/specs/{ids['spec']}/validate", method="POST",
        data=b"{}", headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {token}"})
    try:
        urllib.request.urlopen(r)
        print(f"[demo] GATE 1 open: spec validated by {human}")
    except urllib.error.HTTPError as e:
        if e.code == 409:
            print("[demo] spec already validated")
        else:
            raise

    # ---- prepare the demo workspace repo -----------------------------------
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    if not (WORKSPACE / ".git").exists():
        def git(*a):
            subprocess.run(["git", *a], cwd=WORKSPACE, check=True,
                           capture_output=True)
        git("init")
        git("config", "user.name", "agent:coder")
        git("config", "user.email", "coder@local")
    # pytest must find package dir
    init = WORKSPACE / "pytest.ini"
    init.write_text("[pytest]\ntestpaths = .\n", encoding="utf-8")

    # ---- coder agent: PROPOSAL ONLY (deterministic backend) ----------------
    from agents.coder_agent import CoderAgent
    from agents.config import ROLES
    from agents.engine_client import EngineClient
    from agents.llm import TemplateLLM

    class FixedProposalLLM(TemplateLLM):
        """Deterministic stand-in: same FILE-block contract as qwen."""
        def generate(self, system, user):
            return PROPOSAL

        def available(self):
            return True

    coder = CoderAgent(EngineClient(BASE, ROLES["coder"]),
                       FixedProposalLLM(), workspace=WORKSPACE,
                       project_id=PROJECT)
    result = coder.implement_spec(ids["spec"], prd_id=ids["prd"],
                                  user_story_id=ids["us"], propose_only=True)
    print(f"[demo] PROPOSAL: run={result.run_id} "
          f"commit={(result.commit_hash or '?')[:8]} files={result.generated_files}")

    # ---- orchestrator-owned verification + packaging (shared code path) ---
    from agents.orchestrator import _sod_verify_and_package
    result, crp_id, tree = _sod_verify_and_package(
        coder.engine, WORKSPACE, ids["spec"], result,
        {"project_id": PROJECT, "base_url": BASE, "prd_id": ids["prd"]})

    print(f"\n=== DEMO RESULT ===")
    print(f"run:       {result.run_id}")
    print(f"tree hash: {tree}")
    print(f"tests:     {'PASS' if result.tests_passed else 'FAIL'} "
          f"(runner=orchestrator)")
    print(f"security:  {'PASS' if result.security_passed else 'FAIL'}")
    print(f"lint:      {'PASS' if result.lint_passed else 'FAIL'}")
    print(f"MRP:       {result.mrp_id}  CRP: {crp_id or 'none'}")
    print(f"Next: open {BASE}/ui/ -> Validation view -> approve MRP as {human}")


def ac_body_ref(ac):
    return "".join(f"  - {line}\n"
                   for line in ac.get("body_ref", "").splitlines())


if __name__ == "__main__":
    main()
