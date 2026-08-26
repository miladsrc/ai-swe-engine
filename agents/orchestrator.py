"""
Pipeline orchestrator v1 — walks the SASE lifecycle and STOPS at every
human gate. This is deliberately a plain sequential function, not a
framework: each step is one governed API call whose audit trail is the
engine's job, not ours. (LangGraph comes later if/when loops and
branching are actually needed.)

  idea -> project -> PRD -> user story -> ACs -> spec
       -> STOP: human spec validation  (Gate 1 / §3.5)
       -> coder agent run ...          (next milestone)

v1 changes over v0:
- prompts moved to agents/prompts.py (explicit output contracts — see
  module docstring there for why);
- the spec step goes through SpecAgent.draft_spec instead of an inline
  one-liner prompt;
- every created artifact + body is persisted to .pipeline_state.json so
  `--spec-only` can regenerate just the spec against the existing chain
  (the engine has no list/GET routes for stories and ACs).

Usage:
  python -m agents.orchestrator --online        # full chain via Ollama
  python -m agents.orchestrator --offline       # full chain via templates
  python -m agents.orchestrator --spec-only     # redraft ONLY the spec
                                                # from saved state
"""

import json
import os
import sys
from pathlib import Path

from agents.config import ROLES
from agents.engine_client import EngineClient, human_curl_auth, print_human_auth_hint
from agents.llm import TemplateLLM, pick_backend
from agents.product_agent import ProductAgent
from agents.spec_agent import SpecAgent

# Agents' coding target: a real local git repo, one level up.
WORKSPACE = Path(__file__).resolve().parents[2] / "todo-cli"
# P3: no hardcoded token fallback. The CI client sends X-CI-Token only
# when SASE_CI_TOKEN is set; the server fail-closes (503) if it isn't
# configured on the deployment (docker-compose provides a dev value).

STATE_FILE = Path(__file__).resolve().parent.parent / ".pipeline_state.json"

# Offline templates for the demo project so the chain is exercisable
# before Ollama has finished pulling the model.
DEMO_TEMPLATES = {
    "PRD": """# PRD: Simple To-Do CLI

## Problem
The user needs a minimal command-line tool to track tasks locally.

## Goals
- Add a task with a description
- List pending tasks
- Mark a task done

## Non-goals
- Multi-user, sync, GUI, reminders.

## Success criteria
- A first-time user can add/list/complete a task without reading docs
  beyond --help.

## Open questions for human review
- Where is the data file stored by default?
""",
    "US": """As a terminal user, I want to add, list, and complete tasks from
the command line so that I can track my work without leaving the shell.""",
    "AC": """- `todo add "text"` persists a task and prints its id
- `todo list` prints pending tasks newest-first with ids
- `todo done <id>` marks the task complete; unknown id exits non-zero
- Data survives process restart (file-backed storage)""",
    "SPEC": """artifact: SPEC-TODO-CORE
story: US-TODO-001
behavior:
  add:
    - stores task text + created_at + unique id in todos.json
    - prints assigned id
  list:
    - prints pending tasks newest-first as "<id> <text>"
  done:
    - marks matching id complete
    - unknown id -> stderr message, exit code 1
storage:
  file: todos.json (alongside cwd or --store override)
edge_cases:
  - empty task text rejected with exit code 2
  - corrupt store file -> clear error, non-zero exit
acceptance_criteria_refs:
  - AC-TODO-001-01
open_questions:
  - default storage location (cwd vs home dir) — needs product decision""",
}


class PipelineResult(dict):
    """dict with attribute access so steps read nicely."""


def _run_code_phase(base_url: str, use_ollama: bool | None,
                    spec_id: str | None) -> None:
    """
    Gate 1 must already be open (spec human-validated — the server
    rejects the agent-run otherwise). Coder writes real files into the
    workspace repo, pytest decides pass/fail, CI identity records
    evidence; everything after that is human gates.
    """
    from agents.coder_agent import CoderAgent, record_ci_evidence

    if spec_id is None:
        if not STATE_FILE.exists():
            sys.exit("No --spec given and no .pipeline_state.json to read "
                     "it from.")
        spec_id = json.loads(
            STATE_FILE.read_text(encoding="utf-8"))["spec_id"]

    coder = CoderAgent(
        EngineClient(base_url, ROLES["coder"]),
        _backend(ROLES["coder"].model, use_ollama),
        workspace=WORKSPACE,
        max_repairs=int(os.environ.get("CODER_MAX_REPAIRS", "5")))
    print(f"[coder] implementing {spec_id} -> {WORKSPACE}")
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) \
        if STATE_FILE.exists() else {}
    result = coder.implement_spec(
        spec_id, prd_id=state.get("prd_id"),
        user_story_id=state.get("user_story_id"))
    print(f"[coder] run {result.run_id}: tests="
          f"{'PASS' if result.tests_passed else 'FAIL'} security="
          f"{'PASS' if result.security_passed else 'FAIL'} "
          f"commit={result.commit_hash[:8] if result.commit_hash else '?'}")
    print(f"[coder] files: {result.generated_files}")
    if result.crp_id:
        print(f"[coder] CRP raised (open questions): {result.crp_id}")

    # Evidence comes from the LLM-free CI role, token-authenticated.
    ci = EngineClient(base_url, ROLES["test_runner"],
                      ci_token=os.environ.get("SASE_CI_TOKEN"))
    record_ci_evidence(ci, result.mrp_id, result.tests_passed,
                       result.security_passed, result.lint_passed,
                       execution_context={
                           "test_output": result.test_output[-8000:],
                           "security_findings": result.security_findings,
                           "lint_passed": result.lint_passed,
                           "lint_output": (result.lint_output or "")[-4000:],
                           "generated_files": result.generated_files,
                           "reflection_iterations": result.reflection_iterations,
                       })
    print(f"[ci] evidence recorded on {result.mrp_id}")

    print("\n=== HUMAN GATES (§3.6.3 / §5.6) ===")
    _print_human_auth_hint()
    if result.crp_id:
        vcr_body = json.dumps({
            "related_artifact_type": "CRP",
            "related_artifact_id": result.crp_id,
            "decision_status": "approved_with_changes",
            "rationale": "<your decision>",
        })
        print(f"1. Resolve CRP with a VCR:\n"
              f"  curl -X POST {base_url}/vcrs "
              f"-H 'Content-Type: application/json' \\\n"
              f"    {human_curl_auth()} -d '{vcr_body}'")
        print("2. Then approve the merge:")
    else:
        print("1. Approve the merge:")
    print(f"  curl -X POST {base_url}/mrps/{result.mrp_id}/human-decision \\\n"
          f"    -H 'Content-Type: application/json' \\\n"
          f"    {human_curl_auth()} -d '{{\"decision\": \"approved\"}}'")


def run_pipeline(project_id: str = "todo-cli", domain: str = "TODO",
                 use_ollama: bool | None = None,
                 base_url: str = "http://localhost:8000",
                 spec_only: bool = False,
                 spec_name: str = "core") -> PipelineResult:
    """
    Runs the pre-human-gate half of the lifecycle. Idempotent-ish:
    existing artifacts are reused where the API allows lookup.
    Returns every artifact id it touched.
    """
    # Roles: separate client per role — identities never mix.
    product = ProductAgent(EngineClient(base_url, ROLES["product"]),
                           _backend(ROLES["product"].model, use_ollama))
    spec = SpecAgent(EngineClient(base_url, ROLES["spec"]),
                     _backend(ROLES["spec"].model, use_ollama))

    if spec_only:
        return _run_spec_only(product, spec, project_id, domain, spec_name)

    out = PipelineResult(project_id=project_id)

    # 1. Project
    product.ensure_project(project_id, "Simple To-Do CLI", "python-cli")
    print(f"[product] project ready: {project_id}")

    # 2. PRD (template key 'PRD' offline / LLM-generated online)
    prd = product.draft_prd(project_id, domain, "Simple To-Do CLI",
                            "a minimal todo cli")
    out["prd_id"] = prd["id"]
    print(f"[product] PRD: {prd['id']}")

    # 3. User story — drafted FROM the PRD body, not from a bare idea.
    us = product.draft_user_story(prd["id"], domain, prd["body_ref"])
    out["user_story_id"] = us.get("id") if isinstance(us, dict) else None
    out["story_body"] = us.get("body_ref", "")
    print(f"[product] user story: {out['user_story_id']}")

    # 4. Acceptance criteria — drafted FROM the story, not the idea.
    ac = product.draft_acceptance_criteria(out["user_story_id"],
                                           out["story_body"])
    out["ac_id"] = ac.get("id") if isinstance(ac, dict) else None
    out["ac_body"] = ac.get("body_ref", "")
    print(f"[product] acceptance criteria: {out['ac_id']}")

    # 5. Spec — through the real agent, with story + AC context.
    sp = spec.draft_spec(project_id, out["user_story_id"], [out["ac_id"]],
                         out["story_body"], out["ac_body"],
                         name=spec_name, domain=domain)
    out["spec_id"] = sp["id"]
    _save_state(out)
    print(f"[spec] spec drafted: {sp['id']}")

    # 6. HUMAN GATE
    print("\n=== HUMAN GATE (§3.5) ===")
    print_human_auth_hint(base_url)
    print(f"Review and validate with:\n"
          f"  curl -X POST {base_url}/specs/{sp['id']}/validate \\\n"
          f"    -H 'Content-Type: application/json' \\\n"
          f"    {human_curl_auth()} -d '{{}}'")
    return out


def _run_spec_only(product: ProductAgent, spec: SpecAgent,
                   project_id: str, domain: str,
                   spec_name: str = "core") -> PipelineResult:
    """Regenerate only the spec, reusing ids/bodies persisted by the last
    full run. Fails loudly if no state exists."""
    if not STATE_FILE.exists():
        sys.exit(f"No {STATE_FILE} — run the full pipeline once first.")
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if state.get("project_id") != project_id:
        sys.exit(f"State is for project '{state.get('project_id')}', "
                 f"not '{project_id}'.")
    print(f"[spec-only] reusing {state['user_story_id']} / {state['ac_id']}")
    sp = spec.draft_spec(
        project_id, state["user_story_id"], [state["ac_id"]],
        state.get("story_body", ""), state.get("ac_body", ""),
        name=spec_name, domain=domain)
    print(f"[spec] spec drafted: {sp['id']}")
    print("\n=== HUMAN GATE (§3.5) ===")
    print_human_auth_hint("http://localhost:8000")
    print(f"Review and validate with:\n"
          f"  curl -X POST http://localhost:8000/specs/{sp['id']}/validate "
          f"-H 'Content-Type: application/json' "
          f"{human_curl_auth()} -d '{{}}'")
    return PipelineResult(state | {"spec_id": sp["id"]})


def _save_state(out: dict) -> None:
    STATE_FILE.write_text(json.dumps(out, indent=2), encoding="utf-8")


def _backend(model: str, use_ollama: bool | None) -> object:
    if use_ollama is True:
        from agents.llm import OllamaLLM
        return OllamaLLM(model=model)
    if use_ollama is False:
        return TemplateLLM(DEMO_TEMPLATES)
    return pick_backend(model)


if __name__ == "__main__":
    kwargs = {}
    if "--offline" in sys.argv:
        kwargs["use_ollama"] = False
    if "--online" in sys.argv:
        kwargs["use_ollama"] = True
    if "--spec-only" in sys.argv:
        kwargs["spec_only"] = True
    # --name <slug> : spec name (id = SPEC-<DOMAIN>-<NAME>). Change it when
    # the previous spec id already exists — the engine has no DELETE.
    if "--name" in sys.argv:
        kwargs["spec_name"] = sys.argv[sys.argv.index("--name") + 1]
    # --code : run ONLY the coding phase against an already-validated spec
    # (--spec <id> optional; defaults to the last drafted spec).
    if "--code" in sys.argv:
        spec_id = None
        if "--spec" in sys.argv:
            spec_id = sys.argv[sys.argv.index("--spec") + 1]
        _run_code_phase("http://localhost:8000",
                        kwargs.get("use_ollama"), spec_id)
        sys.exit(0)
    result = run_pipeline(**kwargs)
    print("\nresult:", dict(result))
