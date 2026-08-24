"""
Specification Agent (agent:spec) — user story -> technical spec.

May create specs but can NEVER validate one: POST /specs/{id}/validate is
absent from its allowlist and, independently, the server rejects any
'agent:' identity there (Gate 5 / §3.5). After drafting, the pipeline
STOPS until a human validates — that stop is the product, not a bug.
"""

from agents.engine_client import EngineClient
from agents.llm import LLMBackend

SYSTEM_PROMPT = """You are the Specification Agent in a governed AI
engineering organization. Convert a user story into a precise technical
specification (YAML): behavior, inputs/outputs, edge cases, and how each
acceptance criterion is satisfied. Never invent requirements that are not
in the story; list open questions under `open_questions:` instead."""


class SpecAgent:
    def __init__(self, engine: EngineClient, llm: LLMBackend):
        self.engine = engine
        self.llm = llm

    def draft_spec(self, project_id: str, user_story_id: str, domain: str,
                   name: str, story_text: str) -> dict:
        body = self.llm.generate(
            SYSTEM_PROMPT,
            f"SPEC\nStory: {story_text}\nProduce the YAML spec now.")
        return self.engine.post("/specs", {
            "project_id": project_id,
            "user_story_id": user_story_id,
            "domain": domain,
            "name": name,
            "format": "yaml",
            "body_ref": body,
            "confidence": "inferred",
        })
