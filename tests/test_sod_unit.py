"""
Phase 2 SoD unit tests — verification steps + proposal-only coder path.
DB-free; git + pytest subprocesses run against real temp repos.

Proves:
- tree-hash binding: stable per commit, changes with content
- clean checkout isolates verification from the agent's working dir
- test step fails CLOSED on content drift (expected_tree mismatch)
- scan step covers JVM + Python patterns over a real directory
- propose_only coder NEVER runs tests/scan/lint and returns a pending result
"""

import subprocess
from pathlib import Path

import pytest

from agents import verification as V
from agents.coder_agent import CoderAgent, CoderResult


# ------------------------------------------------------------ repo fixture ----

@pytest.fixture()
def git_repo(tmp_path):
    """A real git repo with one passing test file committed."""
    ws = tmp_path / "ws"
    (ws / "tests").mkdir(parents=True)
    code = 'def add(a, b):\n    return a + b\n'
    test = "from todo import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    (ws / "todo.py").write_text(code, encoding="utf-8")
    (ws / "tests" / "test_todo.py").write_text(test, encoding="utf-8")
    def git(*a):
        subprocess.run(["git", *a], cwd=ws, check=True, capture_output=True)
    git("init")
    git("config", "user.name", "t")
    git("config", "user.email", "t@local")
    git("add", "-A")
    git("commit", "-m", "init")
    return ws


# ------------------------------------------------------------ tree binding ----

def test_tree_hash_stable_and_changes_with_content(git_repo):
    h1 = V.tree_hash(git_repo)
    h2 = V.tree_hash(git_repo)
    assert h1 == h2 and len(h1) == 40
    (git_repo / "todo.py").write_text("def add(a, b):\n    return a * b\n",
                                      encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "change"], cwd=git_repo,
                   capture_output=True)
    assert V.tree_hash(git_repo) != h1, "tree hash must change with content"


def test_clean_checkout_contains_committed_bytes_only(git_repo):
    # untracked leftover must NOT appear in the clean checkout
    (git_repo / "leftover.py").write_text("x = 1\n", encoding="utf-8")
    commit = V.head_commit(git_repo)
    with V.clean_checkout(git_repo, commit) as co:
        assert (co / "todo.py").exists()
        assert not (co / "leftover.py").exists()


# ------------------------------------------------------------ verify steps ----

def test_run_tests_step_passes_and_binds_tree(git_repo):
    r = V.run_tests_step(git_repo, expected_tree=V.tree_hash(git_repo))
    assert isinstance(r, V.StepResult)
    assert r.passed and r.runner == "orchestrator" and r.provenance == "tool"
    assert r.tree_hash == V.tree_hash(git_repo)


def test_run_tests_step_fails_closed_on_content_drift(git_repo):
    stale = "0" * 40  # a tree hash that cannot match
    r = V.run_tests_step(git_repo, expected_tree=stale)
    assert not r.passed
    assert "content drift" in r.output


def test_run_tests_step_detects_real_failures(git_repo):
    (git_repo / "todo.py").write_text("def add(a, b):\n    return a - b\n",
                                      encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "break"], cwd=git_repo,
                   capture_output=True)
    r = V.run_tests_step(git_repo)
    assert not r.passed


def test_run_scan_step_over_directory_catches_java_and_python():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "A.java").write_text(
            "class A { void f() throws Exception { Runtime.getRuntime().exec(\"x\"); } }\n",
            encoding="utf-8")
        (root / "b.py").write_text("eval(user_input)\n", encoding="utf-8")
        r = V.run_scan_step(root)
        assert not r.passed
        assert any(".java" in l for l in r.output.splitlines())
        assert any(".py" in l for l in r.output.splitlines())


def test_run_lint_step_flags_syntax_errors(git_repo):
    (git_repo / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    commit = V.head_commit(git_repo)
    with V.clean_checkout(git_repo, commit) as co:
        pass
    # lint needs the file committed to be seen in a checkout; commit it
    subprocess.run(["git", "add", "-A"], cwd=git_repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "bad"], cwd=git_repo,
                   capture_output=True)
    commit = V.head_commit(git_repo)
    with V.clean_checkout(git_repo, commit) as co:
        r = V.run_lint_step(co)
    assert not r.passed


# --------------------------------------------- proposal-only coder path ----

def test_agent_run_update_status_is_optional_for_proposal_patches():
    """Phase 2 SoD: proposal-only metadata patches carry no status; the
    orchestrator applies the single terminal status later."""
    from api.schemas import AgentRunUpdate
    assert AgentRunUpdate().status is None
    assert AgentRunUpdate(generated_files=["a.py"]).status is None

class _FakeEngine:
    """Records calls; returns minimal shaped responses."""
    def __init__(self):
        self.calls = []

    def get(self, path):
        self.calls.append(("GET", path))
        if path.startswith("/specs/"):
            return {"body_ref": "open_questions:\n  - pick storage\n",
                    "user_story_id": "US-X"}
        raise AssertionError(path)

    def post(self, path, payload):
        self.calls.append(("POST", path))
        return {"id": "RUN-QW-2026-00001"}

    def patch(self, path, payload):
        self.calls.append(("PATCH", path, payload))
        return {"id": "RUN-QW-2026-00001", "status": payload.get("status")}


class _FakeLLM:
    model = "fake-model"

    def generate(self, system, user):
        return ("=== FILE: todo.py ===\nprint('hi')\n=== END FILE ===\n"
                "=== FILE: tests/test_todo.py ===\ndef test_x():\n    assert True\n"
                "=== END FILE ===")


def _make_agent(tmp_path):
    (tmp_path / ".git").mkdir()  # pretend repo for path resolution
    return CoderAgent(_FakeEngine(), _FakeLLM(), workspace=tmp_path,
                      project_id="p")


def test_propose_only_skips_verification_and_mrp(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path)
    monkeypatch.setattr(agent, "_commit",
                        lambda run_id, spec_id, paths=None: "c0ffee" * 5)
    r = agent.implement_spec("SPEC-P-1", propose_only=True)

    assert isinstance(r, CoderResult) and r.verification_pending is True
    assert r.mrp_id is None and crp_none(r)
    engine = agent.engine
    posts = [c for c in engine.calls if c[0] == "POST"]
    # The run-START record is required provenance (§3.7.8); but proposal-only
    # must never create MRPs or CRPs.
    assert all(p[1] == "/agent-runs" for p in posts), \
        f"proposal-only created something beyond the run record: {posts}"
    patches = [c for c in engine.calls if c[0] == "PATCH"]
    assert any(p[2].get("generated_files") == ["todo.py", "tests/test_todo.py"]
               or p[2].get("generated_files") ==
               ["tests/test_todo.py", "todo.py"] for p in patches)
    assert not any(p[2].get("status") for p in patches), \
        "proposal-only must NOT set terminal status"


def crp_none(r):
    return r.crp_id is None


def test_propose_only_never_invokes_test_or_scan(monkeypatch, tmp_path):
    agent = _make_agent(tmp_path)
    monkeypatch.setattr(agent, "_commit",
                        lambda run_id, spec_id, paths=None: "d" * 40)
    import agents.coder_agent as ca

    def boom(*a, **k):
        raise AssertionError("coder must not verify its own output")

    monkeypatch.setattr(ca, "run_tests", boom)
    monkeypatch.setattr(ca, "security_scan", boom)
    monkeypatch.setattr(ca, "run_lint", boom)
    agent.implement_spec("SPEC-P-1", propose_only=True)
