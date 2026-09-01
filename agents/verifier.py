"""
Independent Verifier — remote execution boundary (Phase 2 SoD Steps 2 + 2B).

Two invocation modes share one verification core:

1) stdin subprocess mode (Step 2, unchanged contract):
       python -m agents.verifier        (stdin: JSON envelope; stdout: JSON result)
   Used by the legacy local-dev path. The Orchestrator passes only immutable
   references and never holds the verifier credential.

2) RUNNER mode (Step 2B, remote execution boundary):
       python -m agents.verifier --claim \
           [--api http://localhost:8000] [--timeout 900]
   Runs inside a SEPARATELY-ADMINISTERED execution context (GitLab runner /
   VM) under an authority m.barani cannot administer. It:
       - atomically claims ONE pending verification request from the API
         (POST /verification-requests/claim-next, authenticated as ci:verifier);
       - fetches/checkouts the EXACT pinned commit from the request;
       - runs tests/scan/lint in a clean, read-only checkout;
       - computes the AUTHORITATIVE tree hash from that actual checkout;
       - PATCHes trusted evidence to /mrps/{mrp_id}/evidence as ci:verifier;
       - completes the request (passed/failed/error) with the tree hash.
   The token is read ONLY from this process's own environment
   (SASE_VERIFIER_TOKEN), which in the genuine deployment lives only in the
   separately-administered CI/secret store — never on the local Orchestrator.

Credential rule: SASE_VERIFIER_TOKEN is consumed ONLY here. The Orchestrator
must never reference this name (asserted by the security tests).
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from agents import verification as V
from agents.config import ROLES
from agents.engine_client import EngineClient

# Credential consumed ONLY here — the Orchestrator must never reference this
# name anywhere in its own code (asserted by a Step 2 test).
VERIFIER_TOKEN_ENV = "SASE_VERIFIER_TOKEN"

REQUIRED_FIELDS = ("workspace", "commit", "mrp_id", "run_id", "base_url")


def _emit_failure(message: str, code: int = 1) -> None:
    """Emit a machine-readable failure and exit non-zero."""
    print(json.dumps({"ok": False, "error": message}))
    sys.exit(code)


def _verify_and_write(token: str, workspace: Path, commit: str, mrp_id: str,
                      run_id: str, base_url: str,
                      test_command: list[str] | None = None) -> dict:
    """
    Shared core: verify the EXACT pinned commit in a clean, read-only
    checkout; compute the authoritative tree hash from that checkout; write
    trusted evidence to the API as ci:verifier with `token`; return the
    machine-readable result. Returns (for caller to emit/complete). Raises
    on operational/protocol failure (never on a negative code result).
    """
    if not workspace.is_dir():
        raise RuntimeError(f"workspace not found: {workspace}")

    # ---- verification against a clean, read-only checkout of the pin ----
    with V.clean_checkout(workspace, commit) as checkout:
        # Authoritative tree hash computed FROM THE ACTUAL CHECKOUT, not
        # from anything a caller supplied (the caller only supplied the
        # pinned commit). This is the anti-reuse fingerprint.
        authoritative_tree = V.tree_hash(checkout)
        tests = V.run_tests_step(checkout, expected_tree=authoritative_tree,
                                 command=test_command)
        scan = V.run_scan_step(checkout, expected_tree=authoritative_tree)
        lint = V.run_lint_step(checkout)

    passed = tests.passed and scan.passed and lint.passed

    # ---- write trusted evidence using the verifier's OWN credential ----
    client = EngineClient(base_url, ROLES["verifier"], ci_token=token)
    payload = {
        "unit_tests_status": "passed" if tests.passed else "failed",
        "integration_tests_status": "not_applicable",
        "security_scan_status": "passed" if scan.passed else "failed",
        "static_analysis_status": "passed" if lint.passed else "failed",
        "lint_status": "passed" if lint.passed else "failed",
        "verified_tree_hash": authoritative_tree,
        "execution_context": {
            "runner": "ci:verifier",
            "provenance": "tool",
            "sod_mode": "strict",
            "tree_hash": authoritative_tree,
            "run_id": run_id,
            "test_output": tests.output[-8000:],
            "security_findings": [l for l in scan.output.splitlines() if l][:20],
            "lint_output": lint.output[-4000:],
        },
    }
    client.patch(f"/mrps/{mrp_id}/evidence", payload)

    return {
        "ok": True,
        "passed": passed,
        "tree_hash": authoritative_tree,
        "test_passed": tests.passed,
        "scan_passed": scan.passed,
        "lint_passed": lint.passed,
        "test_output": tests.output[-4000:],
        "security_findings": [l for l in scan.output.splitlines() if l][:20],
        "lint_output": lint.output[-2000:],
    }


def _run(envelope: dict) -> None:
    """
    Step 2 stdin-subprocess contract (unchanged). Parses immutable refs from
    a JSON envelope on stdin, verifies, writes evidence, prints a JSON result.
    """
    missing = [k for k in REQUIRED_FIELDS if k not in envelope or not envelope[k]]
    if missing:
        _emit_failure(f"verifier envelope missing required field(s): {missing}")

    workspace = Path(envelope["workspace"]).resolve()
    commit = envelope["commit"]
    mrp_id = envelope["mrp_id"]
    run_id = envelope["run_id"]
    base_url = envelope["base_url"]
    test_command = envelope.get("test_command")

    token = os.environ.get(VERIFIER_TOKEN_ENV)
    if not token:
        _emit_failure(f"{VERIFIER_TOKEN_ENV} is not set in the verifier "
                      f"environment; cannot write trusted evidence.", 2)

    try:
        result = _verify_and_write(token, workspace, commit, mrp_id, run_id,
                                   base_url, test_command=test_command)
    except Exception as exc:  # noqa: BLE001
        _emit_failure(f"verification aborted: {exc}")
    print(json.dumps(result))
    sys.exit(0)


def _run_claimed(api_base: str, timeout: int) -> None:
    """
    Step 2B RUNNER mode: claim a pending verification request and execute it.
    Intended to run under a SEPARATELY-ADMINISTERED principal (GitLab runner /
    VM), never the local Orchestrator's.
    """
    token = os.environ.get(VERIFIER_TOKEN_ENV)
    if not token:
        _emit_failure(f"{VERIFIER_TOKEN_ENV} is not set in the verifier "
                      f"environment; cannot claim/write trusted evidence.", 2)

    client = EngineClient(api_base, ROLES["verifier"], ci_token=token,
                          timeout=max(timeout, 60))
    try:
        req = client.post("/verification-requests/claim-next", {})
    except Exception as exc:  # noqa: BLE001
        _emit_failure(f"claim failed: {exc}")

    worktree = Path(req["worktree_ref"])
    commit = req["commit"]
    mrp_id = req["mrp_id"]
    run_id = req["run_id"]
    request_id = req["id"]

    # The API base the verifier itself uses for evidence may differ from the
    # one supplied for claim (kept same here). Evidence is written under the
    # verifier's OWN credential, never credentials from the request.
    try:
        result = _verify_and_write(token, worktree, commit, mrp_id, run_id,
                                   api_base)
    except Exception as exc:  # noqa: BLE001
        try:
            client.post(f"/verification-requests/{request_id}/complete", {
                "status": "error",
                "failure_reason": f"verifier operational failure: {exc}",
            })
        except Exception:  # noqa: BLE001
            pass
        _emit_failure(f"verification aborted: {exc}")

    # Complete the request with the authoritative tree hash (non-secret).
    status = "passed" if result["passed"] else "failed"
    complete = {
        "status": status,
        "verified_tree_hash": result["tree_hash"],
        **({"failure_reason": "one or more verification steps failed"}
           if status == "failed" else {}),
    }
    try:
        client.post(f"/verification-requests/{request_id}/complete", complete)
    except Exception as exc:  # noqa: BLE001
        _emit_failure(f"request completion failed (evidence already written): {exc}")

    print(json.dumps(result))
    sys.exit(0)


def _claim_forever(api_base: str, timeout: int, once: bool) -> None:
    """Polling worker loop: claim & run one request (or loop) as a runner."""
    while True:
        try:
            # claim-next 404s when nothing is pending -> treat as idle.
            _run_claimed(api_base, timeout)
            if once:
                return
            return  # a single claim per invocation for the harness/test
        except SystemExit:
            raise
        except Exception as exc:  # noqa: BLE001
            if once:
                print(json.dumps({"ok": False, "error": str(exc)}))
                sys.exit(1)
            time.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Independent Verifier (Step 2 / Step 2B remote mode).")
    parser.add_argument("--claim", action="store_true",
                        help="RUNNER mode: claim + execute one pending "
                             "verification request via the API.")
    parser.add_argument("--api", default=os.environ.get("SASE_API_URL",
                                                        "http://localhost:8000"),
                        help="API base URL (runner mode).")
    parser.add_argument("--timeout", type=int,
                        default=int(os.environ.get("VERIFIER_TIMEOUT", "900")),
                        help="per-request timeout seconds (runner mode).")
    args = parser.parse_args()

    if args.claim:
        _claim_forever(args.api, args.timeout, once=True)
        return

    raw = sys.stdin.read()
    try:
        envelope = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        _emit_failure("verifier envelope is not valid JSON")
    _run(envelope)


if __name__ == "__main__":
    main()
