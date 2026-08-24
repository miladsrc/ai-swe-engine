"""
Product Agent (agent:product) — idea -> PRD -> user stories -> ACs.

May ONLY create requirements artifacts (see config.ROLES['product']).
It cannot validate specs, start agent runs, or touch code — the client
raises PolicyViolation before any such request leaves this process.
"""

from agents.engine_client import EngineClient
from agents.llm import LLMBackend

SYSTEM_PROMPT = """You are the Product Agent in a governed AI engineering
organization. Convert the human's idea into a concise PRD, 1-3 user
stories, and testable acceptance criteria. Flag ambiguities as explicit
questions instead of guessing. Output structured markdown."""


class ProductAgent:
    def __init__(self, engine: EngineClient, llm: LLMBackend):
        self.engine = engine
        self.llm = llm

    def ensure_project(self, project_id: str, name: str, stack: str) -> None:
        try:
            self.engine.get(f"/projects/{project_id}")
            return  # already exists — idempotent re-runs are fine
        except RuntimeError as e:
            if "404" not in str(e):
                raise
        self.engine.post("/projects",
                         {"id": project_id, "name": name, "stack": stack})

    def draft_prd(self, project_id: str, domain: str, title: str,
                  idea: str) -> dict:
        body = self.llm_body(idea)
        return self.engine.post("/prds", {
            "project_id": project_id,
            "domain": domain,
            "title": title,
            "body_ref": body,
            "confidence": "inferred",   # honest confidence: needs review
            "created_by": self.engine.role.identity,
        })

    def draft_user_story(self, prd_id: str, domain: str,
                         story_text: str) -> dict:
        return self.engine.post("/user-stories", {
            "prd_id": prd_id,
            "domain": domain,
            "body_ref": story_text,
            "confidence": "inferred",
        })

    def draft_acceptance_criteria(self, user_story_id: str,
                                  ac_text: str) -> dict:
        return self.engine.post("/acceptance-criteria", {
            "user_story_id": user_story_id,
            "body_ref": ac_text,
        })

    def llm_body(self, idea: str) -> str:
        return self.llm.generate(
            SYSTEM_PROMPT,
            f"PRD\nIdea: {idea}\nProduce the PRD markdown now.")
