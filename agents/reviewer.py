"""
Independent Reviewer — advisory review boundary (Phase 2 I3, gate G8).

Two invocation modes share one advisory review core, mirroring the
Verifier's (agents/verifier.py) subprocess/service boundary:

1) stdin subprocess mode:
       python -m agents.reviewer        (stdin: JSON envelope; stdout: JSON result)
   The Orchestrator hands it immutable references (mrp_id, run_id, base_url)
   and NEVER holds the reviewer credential.

2) RUNNER mode:
       python -m agents.reviewer --review \
           [--api http://localhost:8000] [--mrp MRP-...]
   Runs as a SEPARATE authority under its OWN credential. It:
       - reads the MRP, its spec, agent run, and evidence (read-only);
       - reflects on the generated output (REFLECTION boundary);
       - produces STRUCTURED advisory findings (severity/file/line/message);
       - writes ONLY the review fields via PATCH /mrps/{id}/review as
         agent:reviewer.

ADVISORY-ONLY (G8 SoD requirement 3): the Reviewer NEVER
  - writes verification evidence (unit/security/lint status),
  - modifies code, agent runs, or any other protected artifact,
  - approves a merge (a merge stays a human decision).
It produces review findings that a human weighs. Its identity is
agent:reviewer and its credential (SASE_REVIEWER_TOKEN) is consumed ONLY
here — a coder/orchestrator process cannot self-certify a review.

Model discipline (G8 requirement 5): the reviewer uses a DIFFERENT model
family (default deepseek-r1:8b) than the coder (qwen2.5-coder:7b) so a
correlated error on the generator is not repeated in review.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from agents.config import ROLES
from agents.engine_client import EngineClient
from agents.llm import LLMBackend, OllamaLLM, TemplateLLM
from api.routers import mrp
from tests.test_traceability_chain import client

# Credential consumed ONLY here. The Orchestrator never references this
# name (asserted by the G8 security tests).
REVIEWER_TOKEN_ENV = "SASE_REVIEWER_TOKEN"

REQUIRED_FIELDS = ("mrp_id", "run_id", "base_url")

REVIEW_SYSTEM = (
    "You are the independent Reviewer in a separation-of-duties pipeline. "
    "You are ADVISORY ONLY: you review AI-generated code for risks and "
    "produce STRUCTURED findings. You never approve a merge, never write "
    "verification evidence, and never modify code. Be specific and concise."
)

# Parsed from the model output; one per line:
#   SEVERITY|path:line|message
# e.g.  medium|todo.py:12|Handles empty input but not corrupt store
FINDING_RE = re.compile(
    r"(?P<severity>low|medium|high|critical)\s*\|\s*"
    r"(?P<file>[^:|]+)(?::(?P<line>\d+))?\s*\|\s*(?P<message>.+)",
    re.IGNORECASE,
)


def _emit_failure(message: str, code: int = 1) -> None:
    print(json.dumps({"ok": False, "error": message}))
    sys.exit(code)


def parse_findings(raw: str) -> list[dict]:
    """Convert the model's delimited findings to structured dicts."""
    findings = []
    for line in raw.splitlines():
        line = line.strip().lstrip("-").strip()
        m = FINDING_RE.match(line)
        if not m:
            continue
        findings.append({
            "severity": m.group("severity").lower(),
            "file": m.group("file").strip(),
            "line": int(m.group("line")) if m.group("line") else None,
            "message": m.group("message").strip(),
        })
    return findings


def _review_and_write(token: str, client: EngineClient, mrp_id: str,
                      run_id: str, llm: LLMBackend,
                      notes: list[str] | None = None) -> dict:
    """
    Shared advisory core: read the MRP + spec + run + evidence, reflect,
    produce structured findings, and write ONLY the review fields as
    agent:reviewer. Returns the machine-readable result. Raises on
    operational/protocol failure (never on a negative review verdict).
    """
    mrp = client.get(f"/mrps/{mrp_id}")
    spec_id = (mrp.get("spec_ids") or [None])[0]
    spec = client.get(f"/specs/{spec_id}") if spec_id else None
    run = client.get(f"/agent-runs/{run_id}") if run_id else None

    evidence_view = client.get(f"/evidence/run/{run_id}") if run_id else {}

    user = json.dumps({
        "mrp_id": mrp_id,
        "spec": (spec or {}).get("body_ref", ""),
        "generated_files": (run or {}).get("generated_files", []),
        "commit_hash": (run or {}).get("commit_hash"),
        "evidence": {
            "unit_tests_status": evidence_view.get("mrp_evidence", {}).get(
                "unit_tests_status"),
            "security_scan_status": evidence_view.get("mrp_evidence", {}).get(
                "security_scan_status"),
        },
        "instructions": ("List findings one per line as: "
                         "SEVERITY|path:line|message"),
    }, ensure_ascii=False)

    raw = llm.generate(REVIEW_SYSTEM, user)
    findings = parse_findings(raw)

    review_notes = list(notes or [])
    if not review_notes:
        review_notes = [find["message"] for find in findings]

    # ADVISORY ONLY: the reviewer's verdict is needs_revision or
    # completed — never an approval. It never asserts test/security status.
    status = "needs_revision" if findings else "completed"

    payload = {
        "ai_review_status": status,
        "ai_review_notes": review_notes[:20],
        "ai_review_findings": findings[:30],
    }
    # The reviewer's OWN credential, carried as X-Reviewer-Token.
    client.patch(f"/mrps/{mrp_id}/review", payload,
                 extra={"X-Reviewer-Token": token})

    return {
        "ok": True,
        "mrp_id": mrp_id,
        "advisory": True,
        "ai_review_status": status,
        "findings": findings,
        "notes": review_notes,
    }


def _run(envelope: dict) -> None:
    missing = [k for k in REQUIRED_FIELDS if k not in envelope or not envelope[k]]
    if missing:
        _emit_failure(f"reviewer envelope missing required field(s): {missing}")

    mrp_id = envelope["mrp_id"]
    run_id = envelope["run_id"]
    base_url = envelope["base_url"]

    token = os.environ.get(REVIEWER_TOKEN_ENV)
    if not token:
        _emit_failure(f"{REVIEWER_TOKEN_ENV} is not set in the reviewer "
                      f"environment; cannot write review fields.", 2)

    llm = _backend(ROLES["reviewer"].model,
                   envelope.get("offline") in (True, "true"))
    client = EngineClient(base_url, ROLES["reviewer"])

    try:
        result = _review_and_write(token, client, mrp_id, run_id, llm,
                                   notes=envelope.get("notes"))
    except Exception as exc:  # noqa: BLE001
        _emit_failure(f"review aborted: {exc}")
    print(json.dumps(result))
    sys.exit(0)


def _backend(model: str, offline: bool) -> LLMBackend:
    if offline:
        return TemplateLLM()
    ollama = OllamaLLM(model=model)
    if ollama.available():
        return ollama
    return TemplateLLM()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Independent Reviewer (G8, advisory review boundary).")
    parser.add_argument("--review", action="store_true",
                        help="runner mode: review the MRP with the given id "
                             "and write ONLY review fields.")
    parser.add_argument("--mrp", help="MRP id to review (runner mode).")
    parser.add_argument("--api", default=os.environ.get(
        "SASE_API_URL", "http://localhost:8000"),
        help="API base URL (runner mode).")
    parser.add_argument("--offline", action="store_true",
                        help="force the deterministic offline template backend.")
    args = parser.parse_args()

    if args.review:
        if not args.mrp:
            _emit_failure("--review requires --mrp <id>")
        envelope = {"mrp_id": args.mrp, "run_id": os.environ.get("RUN_ID", ""),
                    "base_url": args.api, "offline": args.offline}
        _run(envelope)
        return

    raw = sys.stdin.read()
    try:
        envelope = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        _emit_failure("reviewer envelope is not valid JSON")
    _run(envelope)


if __name__ == "__main__":
    main()
