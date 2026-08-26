"""
Designer Agent (agent:designer) — reads DESIGN.md + blueprint + spec,
generates visually polished frontend code with proper design tokens.

This agent bridges the gap between "functional code" and "beautiful UI"
by using design system documents (DESIGN.md) as input. It follows the
Notion/Linear/Cal.com design philosophy extracted from real websites.

Key properties:
- Reads DESIGN.md tokens (colors, typography, spacing, components)
- Reads blueprint for project structure and tech stack
- Reads spec for functional requirements
- Generates HTML/CSS/JS that follows the design system
- Records agent run for traceability
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from agents.engine_client import EngineClient
from agents.llm import LLMBackend


DESIGNER_SYSTEM = """You are the Designer Agent in a governed AI engineering \
organization. You generate beautiful, production-quality frontend code based \
on a DESIGN.md design system document, a project blueprint, and a technical spec.

OUTPUT CONTRACT — for EVERY file you produce, output exactly:

=== FILE: <relative/path> ===
<complete file content>
=== END FILE ===

HARD RULES:
1. Nothing outside FILE blocks. No explanations, no plans.
2. File content must be COMPLETE and runnable.
3. Follow the DESIGN.md tokens EXACTLY — colors, typography, spacing, \
components, border-radius, shadows.
4. Implement ALL functional requirements from the spec.
5. Use the project structure from the blueprint.
6. Include responsive design for mobile + desktop.
7. Include smooth animations and transitions.
8. Use semantic HTML and accessible markup.

DESIGN PRINCIPLES:
- Read the DESIGN.md tokens and apply them to every CSS property
- Use the specified color palette, not generic colors
- Follow the typography hierarchy exactly
- Use the component patterns (buttons, cards, inputs) from DESIGN.md
- Apply the spacing system consistently
- Use the border-radius scale from DESIGN.md
- Follow the elevation/depth system for shadows
- Respect the responsive breakpoints and collapsing strategy"""


def designer_instruction(design_md: str, blueprint_body: str, spec_body: str) -> str:
    return (
        "Generate a complete frontend application based on these inputs.\n\n"
        "=== DESIGN SYSTEM (DESIGN.md) ===\n"
        f"{design_md}\n\n"
        "=== PROJECT BLUEPRINT ===\n"
        f"{blueprint_body}\n\n"
        "=== TECHNICAL SPEC ===\n"
        f"{spec_body}\n\n"
        "Output complete, runnable files following the design system exactly."
    )


@dataclass
class DesignerResult:
    run_id: str
    mrp_id: str | None = None
    commit_hash: str | None = None
    generated_files: list[str] = field(default_factory=list)
    reflection_iterations: int = 0


class DesignerAgent:
    def __init__(self, engine: EngineClient, llm: LLMBackend,
                 workspace: str | Path, project_id: str = "todo-frontend"):
        self.engine = engine
        self.llm = llm
        self.workspace = Path(workspace)
        self.project_id = project_id

    def implement_design(self, spec_id: str, blueprint_id: str,
                         design_md_path: str | Path,
                         prd_id: str | None = None,
                         user_story_id: str | None = None) -> DesignerResult:
        """Generate frontend code from design system + blueprint + spec."""

        # Read inputs
        spec = self.engine.get(f"/specs/{spec_id}")
        spec_body = spec["body_ref"]

        blueprint_versions = self.engine.get(f"/blueprints/{blueprint_id}")
        blueprint_body = blueprint_versions[0]["body_ref"] if blueprint_versions else ""

        design_md = Path(design_md_path).read_text(encoding="utf-8")

        # Create agent run
        run = self.engine.post("/agent-runs", {
            "project_id": self.project_id,
            "agent_role": "designer_agent",
            "task_type": "design_generation",
            "model_name": getattr(self.llm, "model", "template-offline"),
            "model_short": "QW",
            "prd_id": prd_id,
            "user_story_id": user_story_id,
            "spec_id": spec_id,
            "blueprint_ids": [blueprint_id],
        })
        run_id = run["id"]

        try:
            # Generate code via LLM
            raw = self.llm.generate(
                DESIGNER_SYSTEM,
                designer_instruction(design_md, blueprint_body, spec_body)
            )

            # Parse file blocks
            from agents.coder_agent import parse_file_blocks
            files = parse_file_blocks(raw)
            if not files:
                raise RuntimeError("LLM produced no parsable FILE blocks")

            # Write files
            for rel, content in files.items():
                path = (self.workspace / rel).resolve()
                if self.workspace.resolve() not in path.parents:
                    raise RuntimeError(f"refusing to write outside workspace: {rel}")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            # Git commit
            commit = self._commit(run_id, spec_id)

            # Update agent run
            self.engine.patch(f"/agent-runs/{run_id}", {
                "status": "completed",
                "reflection_iterations": 0,
                "tools_used": ["html", "css", "javascript", "design-system"],
                "generated_files": list(files.keys()),
                "commit_hash": commit,
            })

            # Create MRP
            mrp = self.engine.post("/mrps", {
                "project_id": self.project_id,
                "pull_request_number": self._pseudo_pr_number(spec_id, run_id),
                "branch_name": f"agent/design-{run_id.lower()[-6:]}",
                "created_by_agent_run": run_id,
                "prd_id": prd_id,
                "user_story_ids": [user_story_id] if user_story_id else [],
                "spec_ids": [spec_id],
                "blueprint_id": blueprint_id,
                "blueprint_version": "v1.0",
                "change_summary": f"Design system frontend for {spec_id} (agent run {run_id})",
                "affected_modules": list(files.keys()),
            })

            return DesignerResult(
                run_id=run_id,
                mrp_id=mrp["id"],
                commit_hash=commit,
                generated_files=list(files.keys()),
            )

        except Exception as e:
            self.engine.patch(f"/agent-runs/{run_id}", {"status": "failed"})
            raise

    def _commit(self, run_id: str, spec_id: str) -> str:
        def git(*args: str) -> str:
            return subprocess.run(
                ["git"] + list(args), cwd=self.workspace,
                capture_output=True, text=True, check=True
            ).stdout.strip()
        git("add", "-A")
        git("commit", "-m",
            f"agent:designer implement {spec_id} (engine run {run_id})")
        return git("rev-parse", "HEAD")

    def _pseudo_pr_number(self, spec_id: str, run_id: str = "") -> int:
        import re
        return 80000 + (sum(ord(c) for c in spec_id)
                        + int(re.findall(r"(\d+)$", run_id)[0]
                              if re.findall(r"(\d+)$", run_id) else 0)) % 30000
