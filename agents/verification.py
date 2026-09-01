"""
Orchestrator-owned verification steps (Phase 2 Separation of Duties).

Every step here runs OUTSIDE any agent process and binds its result to an
immutable git tree hash, so "tests passed" can only ever mean "these exact
committed bytes passed, verified by a process that wrote none of them."

Design: docs/PHASES/PHASE-2.md (steps B/C/D/E). Stdlib + git only.
Provenance rule: results from this module carry provenance="tool" and
runner="orchestrator" — that combination is what gate G7 will demand.
"""

import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from agents.scanner import security_scan


@dataclass
class StepResult:
    name: str
    passed: bool
    output: str = ""
    tree_hash: str | None = None
    runner: str = "orchestrator"
    provenance: str = "tool"


# ------------------------------------------------------------- git helpers ----

def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True, check=True).stdout.strip()


def head_commit(workspace: Path) -> str:
    """The commit whose bytes we are about to verify."""
    return _git("rev-parse", "HEAD", cwd=workspace)


def tree_hash(workspace: Path) -> str:
    """Immutable content hash of the committed tree at HEAD (git tree object).
    Two checkouts of the same commit always share this hash regardless of
    timestamps — exactly the binding evidence needs."""
    return _git("rev-parse", "HEAD^{tree}", cwd=workspace)


@contextmanager
def clean_checkout(workspace: Path, commit: str):
    """
    Materialize EXACTLY the committed bytes in a temporary git worktree so
    verification cannot observe (or be poisoned by) the agent's working dir,
    untracked leftovers, or later edits. Always cleaned up.
    """
    tmp = Path(tempfile.mkdtemp(prefix="sase-verify-"))
    try:
        _git("worktree", "add", "--detach", str(tmp), commit, cwd=workspace)
        yield tmp
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(tmp)],
                       cwd=workspace, capture_output=True, text=True)
        subprocess.run(["git", "worktree", "prune"], cwd=workspace,
                       capture_output=True, text=True)


# ------------------------------------------------------------ verify steps ----

def run_tests_step(workspace: Path, expected_tree: str | None = None,
                   command: list[str] | None = None) -> StepResult:
    """
    Independent test execution against a clean checkout of HEAD. The exit
    code of a REAL test runner decides; nothing else does. If expected_tree
    is given and the checkout's tree differs, the step fails closed — the
    bytes moved after the coder handed off.
    """
    commit = head_commit(workspace)
    tree = tree_hash(workspace)
    if expected_tree and tree != expected_tree:
        return StepResult(
            name="test_execution", passed=False,
            output=f"content drift: workspace tree {tree} != bound "
                   f"{expected_tree}; refusing to certify",
            tree_hash=tree)
    with clean_checkout(workspace, commit) as checkout:
        cmd = command or [sys.executable, "-m", "pytest", "-q"]
        proc = subprocess.run(cmd, cwd=checkout, capture_output=True,
                              text=True, timeout=600)
        return StepResult(name="test_execution",
                          passed=proc.returncode == 0,
                          output=(proc.stdout + proc.stderr)[-20000:],
                          tree_hash=tree)


def run_scan_step(checkout_or_files, expected_tree: str | None = None) -> StepResult:
    """
    Deterministic security scan over the SAME bound bytes. Accepts either a
    clean-checkout directory (scans every source file on disk) or a
    {path: content} dict (legacy path).
    """
    if isinstance(checkout_or_files, dict):
        files = checkout_or_files
        tree = expected_tree
    else:
        root = Path(checkout_or_files)
        files = {}
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in (".py", ".java", ".kt", ".scala") \
                    and "site-packages" not in str(p):
                rel = p.relative_to(root).as_posix()
                files[rel] = p.read_text(encoding="utf-8", errors="replace")
        tree = expected_tree or (
            tree_hash(root) if (root / ".git").exists() else None)
    ok, findings = security_scan(files)
    return StepResult(name="security_scan", passed=ok,
                      output="\n".join(findings)[:8000], tree_hash=tree)


def run_lint_step(checkout: Path) -> StepResult:
    """Bytecode compilation over the clean checkout (Python projects)."""
    proc = subprocess.run([sys.executable, "-m", "compileall", "-q", "."],
                          cwd=checkout, capture_output=True, text=True,
                          timeout=120)
    return StepResult(name="lint", passed=proc.returncode == 0,
                      output=(proc.stdout + proc.stderr)[-4000:])
