"""
Specification Agent (agent:spec) — user story + ACs -> technical spec.

May create specs but can NEVER validate one: POST /specs/{id}/validate is
absent from its allowlist and, independently, the server rejects any
'agent:' identity there (Gate 5 / §3.5). After drafting, the pipeline
STOPS until a human validates — that stop is the product, not a bug.
"""

from agents.engine_client import EngineClient
from agents.llm import LLMBackend, TemplateLLM
from agents.prompts import SPEC_SYSTEM, spec_instruction


class SpecAgent:
    def __init__(self, engine: EngineClient, llm: LLMBackend):
        self.engine = engine
        self.llm = llm

    def draft_spec(self, project_id: str, user_story_id: str, ac_ids: list,
                   story_text: str, ac_text: str, name: str = "core",
                   domain: str = "TODO") -> dict:
        body = self._generate(user_story_id, story_text, ac_ids, ac_text)
        return self.engine.post("/specs", {
            "project_id": project_id,
            "user_story_id": user_story_id,
            "domain": domain,
            "name": name,
            "format": "yaml",
            "body_ref": body,
            "confidence": "inferred",
        })

    def _generate(self, us_id: str, story_text: str, ac_ids: list,
                  ac_text: str) -> str:
        if isinstance(self.llm, TemplateLLM):
            # offline mode: first line selects the deterministic template
            return self.llm.generate("", "SPEC")
        body = self.llm.generate(
            SPEC_SYSTEM,
            spec_instruction(us_id, story_text, ac_ids, ac_text))
        return _enforce_ac_refs(body, ac_ids)


def _enforce_ac_refs(yaml_body: str, ac_ids: list) -> str:
    """
    Replace whatever the LLM wrote under `acceptance_criteria_refs:` with
    EXACTLY the real AC ids. Small models fabricate plausible ids
    (AC-X-02..05 when only -01 exists); fabricated references would
    silently break traceability, so like IDs/gates/audit this is
    enforced outside the LLM rather than trusted to prompting.
    """
    lines = yaml_body.splitlines()
    out, i, replaced = [], 0, False
    while i < len(lines):
        line = lines[i]
        if line.strip() == "acceptance_criteria_refs:":
            out.append("acceptance_criteria_refs:")
            out.extend(f"  - {aid}" for aid in ac_ids)
            replaced = True
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith("- "):
                i += 1
        else:
            out.append(line)
            i += 1
    if not replaced:
        out.append("acceptance_criteria_refs:")
        out.extend(f"  - {aid}" for aid in ac_ids)
    return "\n".join(out).rstrip() + "\n"
