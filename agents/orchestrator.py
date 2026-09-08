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
import subprocess
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
    rejects the agent-run otherwise).

    Two modes (Phase 2 SoD, SASE_SOD_MODE):
      legacy (default) — coder runs its own tests/scan; unchanged flow.
      strict           — coder is PROPOSAL-ONLY; the orchestrator owns
                         verification via agents/verification.py and binds
                         evidence to the committed tree hash.
    """
    sod_mode = os.environ.get("SASE_SOD_MODE", "legacy")
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
    print(f"[coder] implementing {spec_id} -> {WORKSPACE} "
          f"(sod_mode={sod_mode})")
    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) \
        if STATE_FILE.exists() else {}

    if sod_mode == "strict":
        _run_code_phase_strict(coder, base_url, spec_id, state,
                               use_ollama)
        return

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
                           "runner": "coder-process",
                           "sod_mode": "legacy",
                       })
    print(f"[ci] evidence recorded on {result.mrp_id} (runner=coder-process)")

    _print_human_gate_instructions(base_url, result.crp_id, result.mrp_id)


def _run_code_phase_strict(coder, base_url: str, spec_id: str,
                           state: dict, use_ollama) -> None:
    """
    Phase 2 SoD strict flow (docs/PHASES/PHASE-2.md steps A-H):
    proposal -> snapshot -> independent verification (verifier subprocess,
    Step 2) -> independent review (reviewer subprocess, Step F/G8) -> MRP ->
    terminal patch -> CRP.
    """
    from agents.coder_agent import (CoderResult, extract_open_questions)

    result = coder.implement_spec(spec_id, prd_id=state.get("prd_id"),
                                  user_story_id=state.get("user_story_id"),
                                  propose_only=True)
    print(f"[coder] PROPOSAL ONLY: run {result.run_id}, commit "
          f"{(result.commit_hash or '?')[:8]}, files={result.generated_files}")

    pkg_state = dict(state)
    pkg_state.setdefault("project_id", coder.project_id)
    pkg_state["base_url"] = base_url
    # Phase 2 Step F (G8): the strict flow always arranges the independent
    # Reviewer subprocess after verification. Offline pipelines (use_ollama is
    # False, the deterministic template mode) review offline; online/auto
    # pipelines let the reviewer pick its own available backend.
    pkg_state["run_reviewer"] = True
    pkg_state["review_offline"] = (use_ollama is False)
    result, crp_id, tree = _sod_verify_and_package(
        coder.engine, WORKSPACE, spec_id, result, pkg_state)
    _print_human_gate_instructions(base_url, crp_id, result.mrp_id)


def _run_verifier_subprocess(workspace: Path, commit: str, mrp_id: str,
                             run_id: str, base_url: str,
                             test_command: list[str] | None = None) -> dict:
    """
    Spawn the Independent Verifier as a SEPARATE OS subprocess
    (python -m agents.verifier) and parse its machine-readable stdout result.

    The Orchestrator passes ONLY immutable references (workspace, pinned
    commit, MRP id, run id, base URL) via stdin — never executable code or
    arbitrary authority. It deliberately does NOT read or pass the verifier
    credential (SASE_VERIFIER_TOKEN): the subprocess reads it from its own
    inherited environment, so the Orchestrator process never holds it.

    Returns the verifier's JSON result dict. Raises RuntimeError on a
    protocol/operational failure (non-zero exit or unparseable output).

    DEV/CONTAINMENT path (Step 2B): the genuine remote runner claims work via
    the request API instead. This direct stdin mode is retained for the local
    legacy path and low-level tests. See docs/ADR/ADR-002.
    """
    repo_root = Path(__file__).resolve().parent.parent
    envelope = {
        "version": 1,
        "workspace": str(workspace.resolve()),
        "commit": commit,
        "mrp_id": mrp_id,
        "run_id": run_id,
        "base_url": base_url,
    }
    if test_command:
        envelope["test_command"] = test_command

    # env=None inherits the parent environment; the verifier subprocess reads
    # SASE_VERIFIER_TOKEN itself. The orchestrator code below never references
    # that variable name.
    proc = subprocess.run(
        [sys.executable, "-m", "agents.verifier"],
        input=json.dumps(envelope), text=True, capture_output=True,
        cwd=repo_root, env=None, timeout=int(os.environ.get("VERIFIER_TIMEOUT", "900")),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"verifier subprocess failed (exit {proc.returncode}): "
            f"{(proc.stdout or '').strip()[-1500:] or (proc.stderr or '').strip()[-1500:]}")
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"verifier returned non-JSON output: "
                           f"{proc.stdout[:2000]}")
    if not result.get("ok"):
        raise RuntimeError(f"verifier reported failure: {result.get('error')}")
    return result


def _spawn_verifier_runner(api_base: str) -> None:
    """
    DEV/CONTAINMENT shim: spawn the verifier RUNNER-mode subprocess
    (python -m agents.verifier --claim) which atomically claims the pending
    verification request via the API, verifies the pinned commit, writes
    evidence, and completes the request. This stands in for the genuine
    separately-administered remote runner.

    The runner reads SASE_VERIFIER_TOKEN from its own inherited environment
    (env=None) — the Orchestrator's code never references that variable name.
    In a genuine deployment the runner executes under a separate authority and
    secret store, which THIS local subprocess cannot reproduce (see
    docs/ADR/ADR-002 and test_sod_remote_boundary).
    """
    repo_root = Path(__file__).resolve().parent.parent
    subprocess.run(
        [sys.executable, "-m", "agents.verifier", "--claim",
         "--api", api_base],
        cwd=repo_root, env=None,
        timeout=int(os.environ.get("VERIFIER_TIMEOUT", "900")),
    )


def _run_reviewer_subprocess(mrp_id: str, run_id: str, base_url: str,
                             offline: bool) -> dict:
    """
    Step F (Phase 2 I3, gate G8): run the INDEPENDENT Reviewer as a SEPARATE
    OS subprocess (python -m agents.reviewer --review) and parse its
    machine-readable stdout result.

    The Orchestrator passes ONLY immutable references (mrp_id, run_id, base
    URL) on the command line and does NOT pass or reference the reviewer
    credential: the subprocess inherits the parent environment and reads it
    from there, so the Orchestrator never holds it and could never
    self-certify a review. The Orchestrator NEVER writes the review fields
    itself (it has no /review route nor the reviewer role).

    The Reviewer is ADVISORY ONLY (G8 SoD requirement 3). A "completed" or
    "needs_revision" outcome is BOTH a legitimate advisory verdict to surface
    to the human — neither is raised here. Only an operational/protocol
    failure (non-zero exit, unparseable output, or a distinct 'ok:false') is
    treated as fail-closed, consistent with the Verifier subprocess path.

    Offline mode: --offline makes the reviewer use the deterministic
    TemplateLLM REVIEW backend (no model invocation), so the local pipeline
    stays runnable without Ollama while the reviewer still writes the real
    review PATCH with its own credential.
    """
    repo_root = Path(__file__).resolve().parent.parent
    cmd = [sys.executable, "-m", "agents.reviewer", "--review",
           "--mrp", mrp_id, "--api", base_url]
    if offline:
        cmd.append("--offline")
    # The subprocess INHERITS the parent environment — including the
    # reviewer credential, which it reads itself. Only RUN_ID is supplied for
    # review provenance. The orchestrator code below never references the
    # reviewer credential variable by name.
    env = dict(os.environ)
    env["RUN_ID"] = run_id
    proc = subprocess.run(
        cmd, cwd=repo_root, env=env, capture_output=True, text=True,
        timeout=int(os.environ.get("REVIEWER_TIMEOUT", "600")),
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"reviewer subprocess failed (exit {proc.returncode}): "
            f"{(proc.stdout or '').strip()[-1500:] or (proc.stderr or '').strip()[-1500:]}")
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"reviewer returned non-JSON output: "
                           f"{proc.stdout[:2000]}")
    if not result.get("ok", False):
        raise RuntimeError(f"reviewer reported failure: {result}")
    return result


def _poll_verification_request(coder_engine, request_id: str,
                               max_wait: int = 920, poll_ms: int = 500) -> dict:
    """
    Poll non-secret status until the request is terminal (passed/failed/
    expired/error). Fail-closed on timeout. Returns the status schema dict.
    """
    import time as _time
    waited = 0
    while waited < max_wait:
        status = coder_engine.get(f"/verification-requests/{request_id}/status")
        if status["status"] in ("passed", "failed", "expired", "error"):
            return status
        _time.sleep(poll_ms / 1000.0)
        waited += poll_ms
    raise RuntimeError(
        f"verification request {request_id} did not reach a terminal state "
        f"within {max_wait}s (fail-closed).")


def _sod_verify_and_package(coder_engine, workspace: Path, spec_id: str,
                            result, state: dict):
    """
    SoD coordination + packaging (steps B-H), shared by the CLI strict flow
    AND the validation demo script — one code path, so the demo validates the
    real machinery.

    Step 2B boundary: the Orchestrator no longer performs verification and it
    does NOT hold the verifier credential. It COORDINATES only:
      - creates the MRP (without manufacturing verified_tree_hash),
      - enqueues an IMMUTABLE verification request (run_id, pinned commit,
        worktree ref) via POST /verification-requests,
      - arranges execution by the independent Verifier (here a dev/containment
        runner shim; genuinely a separately-administered remote runner),
      - polls ONLY non-secret status until terminal,
      - reads the AUTHORITATIVE verified_tree_hash back from the request,
      - Step F (G8): arranges the INDEPENDENT Reviewer as a separate
        subprocess whose advisory review it does NOT write itself,
      - raises the CRP and applies the single terminal patch.

    The Verifier (agents/verifier.py --claim) computes the tree hash from the
    actual pinned checkout and writes trusted evidence with its own
    credential. The Reviewer (agents/reviewer.py --review) writes ONLY its
    advisory review fields with its OWN credential. The Orchestrator
    submits, waits, reads, and coordinates — nothing more.

    Returns (result, crp_id, tree_hash). tree_hash is the authoritative value
    reported back by the verification request.
    """
    from agents import verification as V
    from agents.coder_agent import extract_open_questions

    # MRP must exist before the Verifier can write evidence against it.
    spec = coder_engine.get(f"/specs/{spec_id}")
    questions = extract_open_questions(spec["body_ref"])

    spec_name = "-".join(spec_id.split("-")[2:]).lower() or "impl"
    from agents.coder_agent import _pseudo_pr_number as _prn
    mrp = coder_engine.post("/mrps", {
        "project_id": state["project_id"],
        "pull_request_number": _prn(spec_id, result.run_id),
        "branch_name": f"agent/{spec_name}-{result.run_id.lower()[-6:]}",
        "created_by_agent_run": result.run_id,
        "prd_id": state.get("prd_id"),
        "user_story_ids": [spec["user_story_id"]] if spec.get("user_story_id") else [],
        "spec_ids": [spec_id],
        "blueprint_id": state.get("blueprint_id", "BP-PYTHON-CLI-001"),
        "blueprint_version": state.get("blueprint_version", "v1.0"),
        "change_summary": f"Implement {spec_id} per validated spec "
                          f"(agent run {result.run_id}, SoD strict).",
        "affected_modules": result.generated_files,
        # NOTE: verified_tree_hash is intentionally NOT set here — the
        # Orchestrator must not manufacture the authoritative tree hash. The
        # Verifier computes and returns it via the verification request.
    })
    result.mrp_id = mrp["id"]

    # Step 2B: enqueue an immutable verification request (NO secrets).
    commit = V.head_commit(workspace)
    req = coder_engine.post("/verification-requests", {
        "run_id": result.run_id,
        "mrp_id": result.mrp_id,
        "commit": commit,
        "worktree_ref": str(workspace.resolve()),
    })
    request_id = req["id"]
    print(f"[verify] enqueued verification request {request_id} "
          f"(commit {commit[:8]}…); awaiting verifier runner…")

    # Arrange execution by the independent Verifier. Genuine deployment: a
    # separately-administered remote runner claims it. DEV/CONTAINMENT shim:
    # spawn the standalone --claim runner locally (env=None; it reads its own
    # credential). The Orchestrator never touches the credential.
    _spawn_verifier_runner(state["base_url"])

    # Poll non-secret status until terminal (fail-closed).
    vr = _poll_verification_request(coder_engine, request_id)

    if vr["status"] != "passed":
        raise RuntimeError(
            f"verification request {request_id} did not PASS: "
            f"status={vr['status']} reason={vr.get('failure_reason')}")

    tree = vr.get("verified_tree_hash")
    if not tree:
        raise RuntimeError("verification request passed but carried no "
                           "authoritative tree hash")

    # The request only reports pass/fail; tests/scan/lint all passed together
    # for a 'passed' status. Expose them as True for reporting.
    tests_passed = scan_passed = lint_passed = True
    print(f"[verify] verifier PASS tree={tree[:12]}…")

    # Step F (Phase 2 I3, G8): the INDEPENDENT Reviewer. Coordinated here but
    # executed as a SEPARATE subprocess under ITS OWN credential; the
    # Orchestrator never writes review fields and never touches the reviewer
    # credential. Opt-in via state["run_reviewer"] so the legacy demo scripts
    # that document G8 as an explicit later step keep their exact behavior.
    if state.get("run_reviewer"):
        review = _run_reviewer_subprocess(
            result.mrp_id, result.run_id, state["base_url"],
            offline=bool(state.get("review_offline")))
        review_status = review.get("ai_review_status", "unknown")
        n_findings = len(review.get("findings") or [])
        print(f"[review] independent review recorded on {result.mrp_id}: "
              f"status={review_status} findings={n_findings} (advisory-only)")
        if review_status == "needs_revision":
            print("[review] ADVISORY: the independent reviewer found issues. "
                  "A human must weigh them before any merge (G8 is "
                  "advisory-only).")

    # CRP BEFORE the single terminal patch (terminal runs are immutable).
    crp_id = None
    if questions:
        crp_id = coder_engine.post("/crps", {
            "project_id": state["project_id"],
            "domain": spec_id.split("-")[1] if "-" in spec_id else "TODO",
            "agent_run_id": result.run_id,
            "spec_id": spec_id,
            "severity": "high",
            "blocking_issue_title":
                f"Spec {spec_id} carries unresolved open questions",
            "blocking_issue_body": "See spec open_questions.",
            "required_decision": "Answer each open question.",
            "required_role": "Product Owner",
        })["id"]

    final_status = ("blocked" if questions else
                    "completed" if (tests_passed and scan_passed
                                    and lint_passed) else "failed")
    coder_engine.patch(f"/agent-runs/{result.run_id}", {
        "status": final_status,
        "commit_hash": result.commit_hash,
        "mrp_id": result.mrp_id,
        "tools_used": ["ollama:local", "pytest",
                       "verification:remote-request"],
        "reflection_iterations": 0,
    })
    result.tests_passed = tests_passed
    result.security_passed = scan_passed
    result.lint_passed = lint_passed
    return result, crp_id, tree


def _print_human_gate_instructions(base_url: str, crp_id: str | None,
                                   mrp_id: str) -> None:
    print("\n=== HUMAN GATES (§3.6.3 / §5.6) ===")
    _print_human_auth_hint()
    if crp_id:
        vcr_body = json.dumps({
            "related_artifact_type": "CRP",
            "related_artifact_id": crp_id,
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
    print(f"  curl -X POST {base_url}/mrps/{mrp_id}/human-decision \\\n"
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
