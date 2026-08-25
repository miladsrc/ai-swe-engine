"""
Product Agent (agent:product) — idea -> PRD -> user stories -> ACs.

May ONLY create requirements artifacts (see config.ROLES['product']).
It cannot validate specs, start agent runs, or touch code — the client
raises PolicyViolation before any such request leaves this process.
"""

from agents.engine_client import EngineClient
from agents.llm import LLMBackend, TemplateLLM
from agents.prompts import (AC_INSTRUCTION, PRD_INSTRUCTION,
                            PRODUCT_SYSTEM, STORY_INSTRUCTION)


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
        body = self._generate("PRD", PRD_INSTRUCTION.format(idea=idea))
        out = self.engine.post("/prds", {
            "project_id": project_id,
            "domain": domain,
            "title": title,
            "body_ref": body,
            "confidence": "inferred",   # honest confidence: needs review
            "created_by": self.engine.role.identity,
        })
        # Server echoes body_ref here, but we set it from our own copy
        # regardless: the generated text is the source of truth.
        out["body_ref"] = body
        return out

    def draft_user_story(self, prd_id: str, domain: str, prd_body: str) -> dict:
        story_text = self._generate("US", STORY_INSTRUCTION.format(prd=prd_body))
        out = self.engine.post("/user-stories", {
            "prd_id": prd_id,
            "domain": domain,
            "body_ref": story_text,
            "confidence": "inferred",
        })
        # /user-stories does NOT echo body_ref — without this, callers get
        # "" and every downstream artifact is generated from an empty story.
        out["body_ref"] = story_text
        return out

    def draft_acceptance_criteria(self, user_story_id: str,
                                  story_body: str) -> dict:
        ac_text = self._generate("AC", AC_INSTRUCTION.format(story=story_body))
        out = self.engine.post("/acceptance-criteria", {
            "user_story_id": user_story_id,
            "body_ref": ac_text,
        })
        out["body_ref"] = ac_text          # same reason as above
        return out

    def _generate(self, template_key: str, instruction: str) -> str:
        """Online: send the full contract prompt. Offline: first-line key
        selects the deterministic demo template."""
        if isinstance(self.llm, TemplateLLM):
            return self.llm.generate("", template_key)
        return self.llm.generate(PRODUCT_SYSTEM, instruction)
