"""
Reflection / Critic boundary (Phase 2 I3 reflection refactor; G8 SoD).

Boundaries (from ADR-002 SoD, Reflection refactor):
    Generator/Coder  - produces code
    Reflection/Critic- ANALYSIS of output: detects risks, produces structured
                       feedback, does NOT mutate protected artifacts
    Reviewer         - independent pre-merge advisory review (agents/reviewer.py)
    Verifier         - authoritative test/security/lint evidence (agents/verifier.py)

The Critic (identity `agent:critic`) is deliberately SEPARATE from the
Coder: reflection/review is no longer folded into the generation agent.
It reads a run's output and evidence, analyzes it for risks, and writes
STRUCTURED advisory feedback onto the MRP's own review fields (via the
same review-write endpoint as the reviewer). It does NOT:

  - generate or modify code            (no workspace writes, no git)
  - write verification evidence        (unit/security/lint status)
  - mutate agent runs                  (no PATCH /agent-runs/*)
  - approve a merge                    (advisory only)

Feeding it back is the ORCHESTRATOR's job (controlled orchestration): the
orchestrator decides what subset of critic feedback to route to a coder
repair pass. The Critic itself makes no generative or governance decision.
"""

import json
import sys
from dataclasses import dataclass, field

from agents.config import ROLES
from agents.engine_client import EngineClient
from agents.llm import LLMBackend, OllamaLLM, TemplateLLM
from agents.reviewer import REVIEWER_TOKEN_ENV, parse_findings


@dataclass
class Critique:
    """Structured reflection feedback (advisory only)."""
    run_id: str
    mrp_id: str | None
    findings: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    risk_level: str = "low"   # derived worst severity


CRITIC_SYSTEM = (
    "You are the Reflection/Critic in a separation-of-duties pipeline. "
    "You ANALYZE AI-generated code for correctness and security risks and "
    "return STRUCTURED findings. You do not rewrite code, you do not write "
    "verification evidence, and you do not approve merges. Be specific."
)


def _worst_risk(findings: list[dict]) -> str:
    rank = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    if not findings:
        return "low"
    return max((f.get("severity", "low") for f in findings),
               key=lambda s: rank.get(s, 0))


def run_critique(client: EngineClient, run_id: str, mrp_id: str | None,
                 llm: LLMBackend, token: str | None = None) -> Critique:
    """
    Read-only analysis of a run, producing advisory feedback. Optionally
    writes that feedback onto the MRP review fields (only when `token` is
    provided AND a critic role is bound) as agent:critic. The critic never
    runs tests/scan/lint and never writes evidence.
    """
    run = client.get(f"/agent-runs/{run_id}")
    evidence = client.get(f"/evidence/run/{run_id}") if run_id else {}

    user = json.dumps({
        "run_id": run_id,
        "generated_files": run.get("generated_files", []),
        "commit_hash": run.get("commit_hash"),
        "evidence": {
            "unit_tests_status": evidence.get("mrp_evidence", {}).get(
                "unit_tests_status"),
            "security_scan_status": evidence.get("mrp_evidence", {}).get(
                "security_scan_status"),
        },
        "instructions": "List findings one per line: SEVERITY|path:line|message",
    }, ensure_ascii=False)

    raw = llm.generate(CRITIC_SYSTEM, user)
    findings = parse_findings(raw)
    notes = [f["message"] for f in findings] or ["no risks identified"]

    critique = Critique(run_id=run_id, mrp_id=mrp_id, findings=findings,
                        notes=notes, risk_level=_worst_risk(findings))

    if token and mrp_id:
        # Advisory-only: write feedback onto the MRP review fields. Uses the
        # SAME review-write endpoint and credential discipline as the reviewer.
        client.patch(f"/mrps/{mrp_id}/review", {
            "ai_review_notes": notes,
            "ai_review_findings": findings,
        }, extra={"X-Reviewer-Token": token})
    return critique


def main(argv: list[str] | None = None) -> None:
    """CLI: python -m agents.critic --run <id> [--mrp <id>] [--offline]"""
    import argparse
    parser = argparse.ArgumentParser(description="Reflection/Critic boundary.")
    parser.add_argument("--run", required=True, help="agent run id to critique")
    parser.add_argument("--mrp", help="MRP id to attach advisory feedback to")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args(argv)

    llm = (TemplateLLM() if args.offline
           else OllamaLLM(ROLES["critic"].model))
    client = EngineClient(args.api, ROLES["critic"])
    token = _env_token() if args.mrp else None
    c = run_critique(client, args.run, args.mrp, llm, token=token)
    print(json.dumps({
        "ok": True, "run_id": c.run_id, "mrp_id": c.mrp_id,
        "risk_level": c.risk_level, "findings": c.findings, "notes": c.notes,
    }))


def _env_token() -> str | None:
    import os
    return os.environ.get(REVIEWER_TOKEN_ENV)


if __name__ == "__main__":
    main()
