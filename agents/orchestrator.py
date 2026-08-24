"""
Pipeline orchestrator v0 — walks the SASE lifecycle and STOPS at every
human gate. This is deliberately a plain sequential function, not a
framework: each step is one governed API call whose audit trail is the
engine's job, not ours. (LangGraph comes later if/when loops and
branching are actually needed.)

  idea -> project -> PRD -> user story -> ACs -> spec
       -> STOP: human spec validation  (Gate 1 / §3.5)
       -> coder agent run ...          (next milestone)
"""

import sys

from agents.config import ROLES
from agents.engine_client import EngineClient
from agents.llm import TemplateLLM, pick_backend
from agents.product_agent import ProductAgent
from agents.spec_agent import SpecAgent

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


def run_pipeline(project_id: str = "todo-cli", domain: str = "TODO",
                 use_ollama: bool | None = None,
                 base_url: str = "http://localhost:8000") -> PipelineResult:
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

    out = PipelineResult(project_id=project_id)

    # 1. Project
    product.ensure_project(project_id, "Simple To-Do CLI", "python-cli")
    print(f"[product] project ready: {project_id}")

    # 2. PRD (template key 'PRD' offline / LLM-generated online)
    prd = product.draft_prd(project_id, domain, "Simple To-Do CLI",
                            "a minimal todo cli")
    out["prd_id"] = prd["id"]
    print(f"[product] PRD: {prd['id']}")

    # 3. User story
    story_body = _template_for(product, "US")
    us = product.draft_user_story(prd["id"], domain, story_body)
    out["user_story_id"] = us["id"] if isinstance(us, dict) and "id" in us else None
    print(f"[product] user story: {out.user_story_id}")

    # 4. Acceptance criteria
    ac_body = _template_for(product, "AC")
    ac = product.draft_acceptance_criteria(out.user_story_id, ac_body)
    out["ac_id"] = ac.get("id") if isinstance(ac, dict) else None
    print(f"[product] acceptance criteria: {out.ac_id}")

    # 5. Spec — then HARD STOP before validation.
    body = spec.llm.generate(
        "You are the Specification Agent...",
        f"SPEC\nStory: {story_body}\nProduce YAML.")
    sp = spec.engine.post("/specs", {
        "project_id": project_id,
        "user_story_id": out.user_story_id,
        "domain": domain,
        "name": "core-cli",
        "format": "yaml",
        "body_ref": body,
        "confidence": "inferred",
    })
    out["spec_id"] = sp["id"]
    print(f"[spec] spec drafted: {sp['id']}")

    # 6. HUMAN GATE
    print("\n=== HUMAN GATE (§3.5) ===")
    print(f"Review and validate with:\n"
          f"  curl -X POST {base_url}/specs/{sp['id']}/validate \\\n"
          f"    -H 'Content-Type: application/json' \\\n"
          f"    -H 'X-Acting-As: human:m.barani' -d '{{}}'")
    return out


def _template_for(agent: ProductAgent, key: str) -> str:
    llm = agent.llm
    if isinstance(llm, TemplateLLM):
        return llm.generate("", key)
    return llm.generate(
        "You are the Product Agent...", f"{key}\nIdea: minimal todo cli")


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
    result = run_pipeline(**kwargs)
    print("\nresult:", dict(result))

