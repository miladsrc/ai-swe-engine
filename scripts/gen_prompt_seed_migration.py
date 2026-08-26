"""One-shot generator for migrations/004_prompt_registry.sql."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.coder_prompts import CODER_SYSTEM
from agents.coder_springboot import JAVA_CODER_SYSTEM

TEMPLATE = """-- Migration 004: seed the prompt registry.
-- agent_runs(prompt_id, prompt_version) carries a composite FK to prompts;
-- SoD provenance (P2) writes those fields, so the referenced rows must exist.
-- Bodies are seeded verbatim from agents/coder_prompts.py / coder_springboot.py.
-- APPLY MANUALLY on existing volumes:
--   docker exec -i ai-swe-engine-postgres-1 psql -U sase -d sase < migrations/004_prompt_registry.sql

INSERT INTO prompts (id, version, target_model, purpose, body_ref, owner, approved_by, change_note)
VALUES
 ('python-coder', 'v1', 'qwen2.5-coder:7b', 'Coder Agent system prompt (Python)',
  {cod}, 'sara', NULL, 'Seeded for SoD provenance FK integrity; HUMAN APPROVAL PENDING'),
 ('java-coder',   'v1', 'qwen2.5-coder:7b', 'Coder Agent system prompt (Spring Boot)',
  {java}, 'sara', NULL, 'Seeded for SoD provenance FK integrity; HUMAN APPROVAL PENDING')
ON CONFLICT (id, version) DO NOTHING;
"""


def dq(s: str) -> str:
    return "$sql$" + s + "$sql$"


out = TEMPLATE.format(cod=dq(CODER_SYSTEM), java=dq(JAVA_CODER_SYSTEM))
dest = Path(__file__).resolve().parents[1] / "migrations" / "004_prompt_registry.sql"
dest.write_text(out, encoding="utf-8")
print(f"wrote {dest} ({len(out)} chars)")
