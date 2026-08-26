"""
E3: frontend proposal run for the map demo (SoD strict mode).

Coder agent = PROPOSAL ONLY (deterministic Angular project files).
Orchestrator verification: clean worktree -> tree-hash binding ->
  npm install && ng build (independent) -> security scan.

Usage:
  SASE_HUMAN_TOKEN=<tok> SASE_CI_TOKEN=dev-ci-token-change-me \
      python scripts/run_e3_frontend.py
"""

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = os.environ.get("SASE_BASE_URL", "http://localhost:8000")
PROJECT = "sod-map-demo"
SPEC_ID = "SPEC-MAP-LOCATION-CRUD"
PRD_ID = "PRD-MAP-001"
US_ID = "US-MAP-001"
WORKSPACE = Path(os.environ.get(
    "SASE_MAP_FRONTEND_WS",
    str(Path(__file__).resolve().parents[2] / "demo-map-frontend")))
PROPOSAL = Path(__file__).with_name("demo_map_frontend_proposal.txt").read_text("utf-8")

if not os.environ.get("SASE_HUMAN_TOKEN"):
    sys.exit("Set SASE_HUMAN_TOKEN first.")
if not os.environ.get("SASE_CI_TOKEN"):
    sys.exit("Set SASE_CI_TOKEN first.")


class FixedProposalLLM:
    model = "proposal-template"

    def available(self):
        return True

    def generate(self, system, user):
        return PROPOSAL


def main():
    from agents.coder_agent import CoderAgent
    from agents.config import ROLES
    from agents.engine_client import EngineClient
    from agents.orchestrator import _sod_verify_and_package

    me = json.loads(urllib.request.urlopen(urllib.request.Request(
        BASE + "/auth/me", headers={
            "Authorization": "Bearer " + os.environ["SASE_HUMAN_TOKEN"]})).read())
    print(f"[e3] acting human: {me['actor_id']}")

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    if not (WORKSPACE / ".git").exists():
        def git(*a):
            subprocess.run(["git", *a], cwd=WORKSPACE, check=True,
                           capture_output=True)
        git("init")
        git("config", "user.name", "agent:coder")
        git("config", "user.email", "coder@local")

    coder = CoderAgent(EngineClient(BASE, ROLES["coder"]),
                       FixedProposalLLM(), workspace=WORKSPACE,
                       project_id=PROJECT)
    result = coder.implement_spec(SPEC_ID, prd_id=PRD_ID,
                                  user_story_id=US_ID, propose_only=True)
    print(f"[e3] PROPOSAL: run={result.run_id} "
          f"commit={(result.commit_hash or '?')[:8]} files={len(result.generated_files)}")

    result, crp_id, tree = _sod_verify_and_package(
        coder.engine, WORKSPACE, SPEC_ID, result,
        {"project_id": PROJECT, "base_url": BASE, "prd_id": PRD_ID,
         "blueprint_id": "BP-DEMO-MAP-001", "blueprint_version": "v1.0",
         # install deps then production build; npm exit code decides.
         "test_command": ["cmd", "/c",
                          "npm install --no-audit --no-fund && npx ng build"]})

    print("\n=== E3 RESULT ===")
    print(f"run:       {result.run_id}")
    print(f"tree hash: {tree}")
    print(f"ng build:  {'PASS' if result.tests_passed else 'FAIL'} (runner=orchestrator)")
    print(f"scan:      {'PASS' if result.security_passed else 'FAIL'}")
    print(f"MRP:       {result.mrp_id}  CRP: {crp_id or 'none'}")


if __name__ == "__main__":
    main()
