"""
Phase 2 SoD — Step 2 (Independent Verifier boundary) tests.

Step 2 extracted a genuinely separate Verifier subprocess
(`python -m agents.verifier`) so the Orchestrator is NO LONGER the
verification authority. These tests assert the three cut-lines of that
boundary:

A. Source/authority (no runtime needed):
   - the Orchestrator source (agents/orchestrator.py) and the coordination
     module (agents/verification.py) NEVER reference the verifier credential
     name; only agents/verifier.py does. If the orchestrator could read the
     verifier token it could impersonate the verifier — that would collapse
     the segregation of duties.

B. DB-free API security logic:
   - require_verifier_actor / require_evidence_actor enforce the exact
     ci:verifier identity + its OWN SASE_VERIFIER_TOKEN; coders, the
     orchestrator, and generic CI identities are rejected; missing/unset
     credential is fail-closed; strict vs legacy dispatch.

C. Live subprocess integration (auto-skips without the API):
   - `python -m agents.verifier` computes the tree hash from the actual
     clean checkout, writes evidence with the verifier credential, and
     returns a machine-readable {ok, passed, tree_hash, ...} report.
   - a coder/orchestrator CI identity cannot write verifier-owned evidence
     against a real MRP in strict mode.

Run:
    pytest tests/test_sod_verifier.py -m "not live"   # A + B (no stack)
    pytest tests/test_sod_verifier.py                 # A + B + C (stack up)
"""

import json
import io
import ast
import os
import subprocess
import sys
import textwrap
import tokenize
from pathlib import Path

import pytest
from fastapi import HTTPException

from api.security import (
    require_verifier_actor,
    require_evidence_actor,
    VERIFIER_ACTOR,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
ORCHESTRATOR_SRC = (REPO_ROOT / "agents" / "orchestrator.py").read_text(
    encoding="utf-8")
COORDINATION_SRC = (REPO_ROOT / "agents" / "verification.py").read_text(
    encoding="utf-8")
VERIFIER_SRC = (REPO_ROOT / "agents" / "verifier.py").read_text(encoding="utf-8")

TOKEN_ENV = "SASE_VERIFIER_TOKEN"
VERIFIER_TOKEN = "dev-verifier-token-change-me"


def _code_tokens(src: str) -> set[str]:
    """Non-comment, non-docstring identifiers as NAME tokens only."""
    names: set[str] = set()
    try:
        tokens = tokenize.generate_tokens(io.StringIO(src).readline)
        for tok in tokens:
            if tok.type == tokenize.NAME and tok.string in {
                    TOKEN_ENV, "record_ci_evidence"}:
                names.add(tok.string)
    except tokenize.TokenError:
        pass
    return names


def _function_ast(src: str, func_name: str) -> ast.FunctionDef | None:
    """Return the AST node for the named top-level function, else None."""
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == func_name:
            return node
    return None


def _calls(fn: ast.FunctionDef, name: str) -> bool:
    """True if fn's body calls a function by `name` (incl. attributes)."""
    found = False

    def visit(node):
        nonlocal found
        if found:
            return
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id == name:
                found = True
            elif isinstance(f, ast.Attribute) and f.attr == name:
                found = True
        for child in ast.iter_child_nodes(node):
            visit(child)
    visit(fn)
    return found


def _reads_verifier_token(fn: ast.FunctionDef) -> bool:
    """
    True if fn's body reads SASE_VERIFIER_TOKEN from the environment
    (os.environ[TOKEN_ENV] or os.environ.get(TOKEN_ENV)) in executable code.
    Docstrings are skipped because ast.fix_missing / a docstring is the first
    statement; we walk only real statements and ignore the module docstring.
    """
    found = False

    def visit(node):
        nonlocal found
        if found:
            return
        # ignore docstrings (Constant str as the first statement of a body)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Module, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                rest = body[1:]
            else:
                rest = body
            for child in rest:
                visit(child)
            return
        if isinstance(node, ast.Subscript):
            # os.environ[SASE_VERIFIER_TOKEN]
            try:
                value = node.value
                if isinstance(value, ast.Attribute) and value.attr == "environ":
                    idx = node.slice
                    if isinstance(idx, ast.Constant) and idx.value == TOKEN_ENV:
                        found = True
                        return
            except Exception:
                pass
        if isinstance(node, ast.Call):
            f = node.func
            # os.environ.get("SASE_VERIFIER_TOKEN", ...)
            if isinstance(f, ast.Attribute) and f.attr == "get":
                args = node.args
                if args and isinstance(args[0], ast.Constant) \
                        and args[0].value == TOKEN_ENV:
                    found = True
                    return
        for child in ast.iter_child_nodes(node):
            visit(child)
    visit(fn)
    return found


def _sets_verified_tree_hash_at_create(fn: ast.FunctionDef) -> bool:
    """True if fn posts /mrps with a literal verified_tree_hash key."""
    found = False

    def visit(node):
        nonlocal found
        if found:
            return
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "verified_tree_hash":
                    found = True
                    return
        for child in ast.iter_child_nodes(node):
            visit(child)
    visit(fn)
    return found


# ------------------------------------------------------------ A. source ----

SOD_VERIFY_FN = "_sod_verify_and_package"


def test_orchestrator_strict_func_never_reads_verifier_credential():
    """
    The strict SoD coordinator (agents/orchestrator.py::_sod_verify_and_package)
    must be unable to read the verifier credential as executable code. If it
    reads SASE_VERIFIER_TOKEN from the environment, an orchestrator process
    could impersonate the verifier and self-certify — the SoD is void.
    """
    fn = _function_ast(ORCHESTRATOR_SRC, SOD_VERIFY_FN)
    assert fn is not None, f"{SOD_VERIFY_FN} not found in orchestrator.py"
    assert not _reads_verifier_token(fn), (
        f"the strict orchestration function reads {TOKEN_ENV} — it must "
        f"never hold the verifier credential")
    # The shared coordination module must not read it either.
    assert TOKEN_ENV not in _code_tokens(COORDINATION_SRC), (
        f"verification.py executes a reference to {TOKEN_ENV}")


def test_verifier_source_consumes_its_own_credential():
    """Only the verifier module may reference its own credential in code."""
    assert TOKEN_ENV in VERIFIER_SRC


def test_orchestrator_strict_func_no_longer_verifies_or_writes_evidence():
    """
    The strict SoD coordinator must not compute the authoritative tree hash or
    write verification evidence as executable code — that is the verifier
    subprocess's job in Step 2. The coder's own legacy/CI evidence path is
    OUTSIDE this function and untouched.
    """
    fn = _function_ast(ORCHESTRATOR_SRC, SOD_VERIFY_FN)
    assert fn is not None
    # It must not write verification evidence or call the authoritative steps.
    assert not _calls(fn, "record_ci_evidence"), (
        "orchestrator must not write verification evidence")
    assert not _calls(fn, "run_scan_step"), (
        "orchestrator must not run the security scan")
    assert not _calls(fn, "run_lint_step"), (
        "orchestrator must not run the linter")
    # It must not manufacture verified_tree_hash at MRP-create.
    assert not _sets_verified_tree_hash_at_create(fn), (
        "orchestrator must not set verified_tree_hash at MRP-create")


def test_verifier_spawned_first_class_stdin_envelope():
    """
    (Step 2B) The strict SoD coordinator NOW coordinates via the request
    protocol: it enqueues an immutable verification request (POST
    /verification-requests) and polls non-secret status — it never runs the
    authoritative verification in-process. The legacy stdin-subprocess path
    (`_run_verifier_subprocess`) is retained for dev/local tests and still
    hands an immutable JSON envelope over stdin.
    """
    assert "subprocess.run" in ORCHESTRATOR_SRC
    assert "agents.verifier" in ORCHESTRATOR_SRC
    # Coordinator enqueues + polls the request protocol (no secrets).
    assert "/verification-requests" in ORCHESTRATOR_SRC
    assert "_poll_verification_request" in ORCHESTRATOR_SRC
    # The legacy stdin envelope channel still hands immutable refs over stdin,
    # never executable/authority content.
    assert "input=json.dumps(envelope)" in ORCHESTRATOR_SRC


def test_coordinator_never_reads_verifier_credential_nor_verifies():
    """
    Step 2B: the coordinator path (`_spawn_verifier_runner`) must not itself
    read SASE_VERIFIER_TOKEN or compute/scan/lint. The runner subprocess reads
    its own credential; the Orchestrator submits, waits, and reads status only.
    """
    fn = _function_ast(ORCHESTRATOR_SRC, "_spawn_verifier_runner")
    assert fn is not None, "_spawn_verifier_runner not found"
    assert not _reads_verifier_token(fn), (
        f"{TOKEN_ENV} must only be consumed by the verifier runner subprocess")
    assert not _calls(fn, "run_scan_step")
    assert not _calls(fn, "run_lint_step")
    assert not _calls(fn, "record_ci_evidence")


# ------------------------------------------------------------- B. security ---

def test_verifier_requires_header():
    for missing in (None, ""):
        with pytest.raises(HTTPException) as exc:
            require_verifier_actor(x_acting_as=missing)
        assert exc.value.status_code == 401, f"{missing!r} must be rejected"


def test_verifier_rejects_other_identities():
    """Coders, the orchestrator, and generic CI may never write verifier evidence."""
    for forged in ("agent:coder_agent", "ci:test-runner", "orchestrator"):
        with pytest.raises(HTTPException) as exc:
            require_verifier_actor(x_acting_as=forged, x_ci_token=VERIFIER_TOKEN)
        assert exc.value.status_code == 403, f"{forged!r} must not pass"


def test_verifier_fails_closed_when_unconfigured(monkeypatch):
    """Unset SASE_VERIFIER_TOKEN -> evidence writes refused (503)."""
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    with pytest.raises(HTTPException) as exc:
        require_verifier_actor(x_acting_as=VERIFIER_ACTOR, x_ci_token=VERIFIER_TOKEN)
    assert exc.value.status_code == 503


def test_verifier_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, VERIFIER_TOKEN)
    with pytest.raises(HTTPException) as exc:
        require_verifier_actor(x_acting_as=VERIFIER_ACTOR, x_ci_token="wrong-token")
    assert exc.value.status_code == 403


def test_verifier_accepts_identity_and_token(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, VERIFIER_TOKEN)
    actor = require_verifier_actor(
        x_acting_as=VERIFIER_ACTOR, x_ci_token=VERIFIER_TOKEN)
    assert actor == VERIFIER_ACTOR


def test_generic_ci_token_is_not_accepted_for_verifier(monkeypatch):
    """
    Separation of credentials: even the correct generic CI token must NOT
    unlock the verifier-only path (it checks SASE_VERIFIER_TOKEN).
    """
    monkeypatch.setenv(TOKEN_ENV, VERIFIER_TOKEN)
    monkeypatch.setenv("SASE_CI_TOKEN", "dev-ci-token-change-me")
    with pytest.raises(HTTPException) as exc:
        require_verifier_actor(x_acting_as=VERIFIER_ACTOR,
                               x_ci_token="dev-ci-token-change-me")
    assert exc.value.status_code == 403


def test_evidence_actor_dispatches_to_verifier_in_strict(monkeypatch):
    """Strict mode: trusted evidence only from the verifier (its own token)."""
    monkeypatch.setenv("SASE_SOD_MODE", "strict")
    monkeypatch.setenv(TOKEN_ENV, VERIFIER_TOKEN)
    assert require_evidence_actor(
        x_acting_as=VERIFIER_ACTOR, x_ci_token=VERIFIER_TOKEN) == VERIFIER_ACTOR
    # ... and a self-declared verifier with the wrong token is rejected.
    with pytest.raises(HTTPException) as exc:
        require_evidence_actor(x_acting_as=VERIFIER_ACTOR, x_ci_token="nope")
    assert exc.value.status_code == 403


def test_evidence_actor_legacy_falls_back_to_ci(monkeypatch):
    """Legacy mode: outside strict, the shared CI identity is accepted."""
    monkeypatch.setenv("SASE_SOD_MODE", "legacy")
    monkeypatch.setenv("SASE_CI_TOKEN", "dev-ci-token-change-me")
    assert require_evidence_actor(
        x_acting_as="ci:test-runner", x_ci_token="dev-ci-token-change-me") \
        == "ci:test-runner"


# -------------------------------------------------------- C. integration ----

BASE = "http://localhost:8000"


def _api_reachable() -> bool:
    import httpx
    try:
        with httpx.Client(base_url=BASE, timeout=2) as c:
            return c.get("/health").status_code == 200
    except httpx.HTTPError:
        return False


def _make_repo(tmp_path: Path, with_failing_test=False) -> Path:
    """Create a throwaway git repo with one clean module + a passing test."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.py").write_text(
        "def greet():\n    return 'hello'\n", encoding="utf-8")
    (repo / "test_hello.py").write_text(
        textwrap.dedent(
            """
            def test_greet():
                from hello import greet
                assert greet() == 'hello'
            """
        ).strip() + "\n",
        encoding="utf-8")
    if with_failing_test:
        (repo / "test_hello.py").write_text(
            "def test_fail():\n    assert False\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"],
                   check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"],
                   check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
    return repo


def _run_verifier(workspace: Path, commit: str, mrp_id: str, run_id: str,
                  tmp_path: Path) -> subprocess.CompletedProcess:
    envelope = {
        "workspace": str(workspace),
        "commit": commit,
        "mrp_id": mrp_id,
        "run_id": run_id,
        "base_url": BASE,
        "test_command": [sys.executable, "-m", "pytest", "-q"],
    }
    env = os.environ.copy()
    env[TOKEN_ENV] = VERIFIER_TOKEN
    return subprocess.run(
        [sys.executable, "-m", "agents.verifier"],
        input=json.dumps(envelope), text=True, capture_output=True,
        cwd=REPO_ROOT, env=env, timeout=300)


@pytest.mark.live
@pytest.mark.skipif(not _api_reachable(),
                    reason="API not running at localhost:8000 — start the stack")
def test_verifier_subprocess_happy_path(tmp_path, monkeypatch):
    """The independent verifier computes + writes authoritative evidence."""
    import httpx
    monkeypatch.setenv(TOKEN_ENV, VERIFIER_TOKEN)

    repo = _make_repo(tmp_path)
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
        text=True).stdout.strip()

    import uuid
    suffix = uuid.uuid4().hex[:6].upper()
    domain = f"VS{suffix}"
    with httpx.Client(base_url=BASE, timeout=10) as c:
        c.post("/projects", json={
            "id": "test-sod-verifier", "name": "verifier", "stack": "python"})
        r = c.post("/prds", json={
            "project_id": "test-sod-verifier", "domain": domain,
            "title": "v", "body_ref": "n/a", "created_by": "human:pytest"})
        prd_id = r.json()["id"]
        r = c.post("/user-stories", json={
            "prd_id": prd_id, "domain": domain, "body_ref": "n/a"})
        us_id = r.json()["id"]
        c.post("/acceptance-criteria", json={"user_story_id": us_id, "body_ref": "n/a"})
        r = c.post("/specs", json={
            "project_id": "test-sod-verifier", "user_story_id": us_id,
            "domain": domain, "name": f"verifier-spec-{suffix}", "body_ref": "n/a"})
        assert r.status_code in (200, 409), r.text
        if r.status_code == 409:
            pytest.skip("spec id collision from a prior run")
        spec_id = r.json()["id"]
        c.post(f"/specs/{spec_id}/validate", json={"validated_by": None},
               headers={"X-Acting-As": "human:pytest"})
        r = c.post("/agent-runs", json={
            "project_id": "test-sod-verifier", "agent_role": "coder_agent",
            "task_type": "code_generation", "model_name": "none",
            "model_short": "ORCH", "spec_id": spec_id})
        run_id = r.json()["id"]
        # verified_tree_hash intentionally NOT set by the orchestrator.
        r = c.post("/mrps", json={
            "project_id": "test-sod-verifier",
            "pull_request_number": 31000 + int(suffix, 16) % 1000,
            "branch_name": f"agent/verifier-{suffix}",
            "created_by_agent_run": run_id,
            "prd_id": prd_id, "spec_ids": [spec_id],
            "blueprint_id": "BP-PYTHON-CLI-001", "blueprint_version": "v1.0"})
        assert r.status_code in (200, 409), r.text
        if r.status_code == 409:
            pytest.skip("MRP id collision from a prior run")
        mrp_id = r.json()["id"]

    proc = _run_verifier(repo, commit, mrp_id, run_id, tmp_path)

    # 0 exit = verification completed AND evidence written.
    assert proc.returncode == 0, (
        f"verifier exited {proc.returncode}: {proc.stdout}{proc.stderr}")

    # Machine-readable JSON without executable/authority instructions.
    result = json.loads(proc.stdout)
    assert result["ok"] is True
    assert result["passed"] is True
    assert result["test_passed"] is True
    assert isinstance(result["tree_hash"], str) and result["tree_hash"]
    # The authoritative tree hash must match the git tree of the pinned commit.
    git_tree_hash = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
        capture_output=True, text=True).stdout.strip()
    assert result["tree_hash"] == git_tree_hash, (
        "verifier tree hash must come from the actual checkout of the pin")

    # Evidence was actually written, bound to that tree hash, by ci:verifier.
    with httpx.Client(base_url=BASE, timeout=10) as c:
        # G8: an MRP is only merge-ready in strict mode once the independent
        # Reviewer has completed its advisory review — verifier evidence alone
        # is necessary-but-not-sufficient. Complete it as agent:reviewer.
        r = c.patch(f"/mrps/{mrp_id}/review",
                    headers={"X-Acting-As": "agent:reviewer",
                             "X-Reviewer-Token": os.environ.get(
                                 "SASE_REVIEWER_TOKEN",
                                 "dev-reviewer-token-change-me")},
                    json={"ai_review_status": "completed",
                          "ai_review_notes": ["verified and reviewed"]})
        assert r.status_code == 200, r.text
        r = c.post(f"/mrps/{mrp_id}/check-ready")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ready"] is True, body["blocking_reasons"]


@pytest.mark.live
@pytest.mark.skipif(not _api_reachable(),
                    reason="API not running at localhost:8000 — start the stack")
def test_verifier_subprocess_reports_failed_code(tmp_path, monkeypatch):
    """A failing code result is still a valid report (exit 0), passed=False."""
    import httpx
    monkeypatch.setenv(TOKEN_ENV, VERIFIER_TOKEN)
    repo = _make_repo(tmp_path, with_failing_test=True)
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
        text=True).stdout.strip()

    import uuid
    suffix = uuid.uuid4().hex[:6].upper()
    domain = f"VSF{suffix}"
    with httpx.Client(base_url=BASE, timeout=10) as c:
        c.post("/projects", json={
            "id": "test-sod-verifier", "name": "verifier", "stack": "python"})
        r = c.post("/prds", json={
            "project_id": "test-sod-verifier", "domain": domain,
            "title": "v", "body_ref": "n/a", "created_by": "human:pytest"})
        prd_id = r.json()["id"]
        r = c.post("/user-stories", json={
            "prd_id": prd_id, "domain": domain, "body_ref": "n/a"})
        us_id = r.json()["id"]
        c.post("/acceptance-criteria", json={"user_story_id": us_id, "body_ref": "n/a"})
        r = c.post("/specs", json={
            "project_id": "test-sod-verifier", "user_story_id": us_id,
            "domain": domain, "name": f"verifier-spec-{suffix}", "body_ref": "n/a"})
        assert r.status_code in (200, 409), r.text
        if r.status_code == 409:
            pytest.skip("spec id collision from a prior run")
        spec_id = r.json()["id"]
        c.post(f"/specs/{spec_id}/validate", json={"validated_by": None},
               headers={"X-Acting-As": "human:pytest"})
        r = c.post("/agent-runs", json={
            "project_id": "test-sod-verifier", "agent_role": "coder_agent",
            "task_type": "code_generation", "model_name": "none",
            "model_short": "ORCH", "spec_id": spec_id})
        run_id = r.json()["id"]
        r = c.post("/mrps", json={
            "project_id": "test-sod-verifier",
            "pull_request_number": 32000 + int(suffix, 16) % 1000,
            "branch_name": f"agent/verifier2-{suffix}",
            "created_by_agent_run": run_id,
            "prd_id": prd_id, "spec_ids": [spec_id],
            "blueprint_id": "BP-PYTHON-CLI-001", "blueprint_version": "v1.0"})
        assert r.status_code in (200, 409), r.text
        if r.status_code == 409:
            pytest.skip("MRP id collision")
        mrp_id = r.json()["id"]

    proc = _run_verifier(repo, commit, mrp_id, run_id, tmp_path)
    assert proc.returncode == 0, f"{proc.stdout}{proc.stderr}"
    result = json.loads(proc.stdout)
    assert result["ok"] is True
    assert result["passed"] is False
    assert result["test_passed"] is False
