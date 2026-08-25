"""
Unit tests for the Coding Agent's pure mechanics: FILE-block parsing,
code-fence stripping, and the offline security scan. No network, no DB,
no Ollama.
"""

import pytest

from agents.coder_agent import (parse_file_blocks, run_lint, security_scan,
                                _pseudo_pr_number)
from agents.config import ROLES
from agents.engine_client import EngineClient, PolicyViolation


RAW = """Here is my implementation.

=== FILE: todo.py ===
```python
def main():
    print("todo")
```
=== END FILE ===

=== FILE: test_todo.py ===
import todo

def test_smoke():
    assert True
=== END FILE ===
"""


def test_parse_file_blocks_extracts_both_files():
    files = parse_file_blocks(RAW)
    assert set(files) == {"todo.py", "test_todo.py"}
    assert "def main():" in files["todo.py"]


def test_parse_strips_code_fence():
    files = parse_file_blocks(RAW)
    assert not files["todo.py"].startswith("```")
    assert 'print("todo")' in files["todo.py"]


def test_parse_ignores_chatter_outside_blocks():
    assert "implementation" not in parse_file_blocks(RAW)["test_todo.py"]


def test_parse_raises_on_unterminated_block():
    with pytest.raises(RuntimeError):
        parse_file_blocks("=== FILE: a.py ===\nx = 1\n")


def test_security_scan_flags_dynamic_exec():
    bad = {"x.py": "value = eval(user_input)\n"}
    ok, findings = security_scan(bad)
    assert not ok and any("eval" in f for f in findings)


def test_security_scan_passes_clean_cli():
    ok, findings = security_scan({
        "todo.py": "import json\n\ndef add(tasks, text):\n"
                   "    tasks.append({'text': text})\n"
                   "    return tasks\n",
        "test_todo.py": "def test_x():\n    assert True\n",
    })
    assert ok and findings == []


def test_coder_cannot_validate_specs_or_patch_evidence():
    client = EngineClient(role=ROLES["coder"])
    with pytest.raises(PolicyViolation):
        client.post("/specs/SPEC-X/validate", {})
    # evidence endpoint is CI-token-only territory
    with pytest.raises(PolicyViolation):
        client.patch("/mrps/MRP-1/evidence", {"unit_tests_status": "passed"})


def test_test_runner_cannot_create_agent_runs():
    client = EngineClient(role=ROLES["test_runner"])
    with pytest.raises(PolicyViolation):
        client.post("/agent-runs", {"project_id": "x"})


def test_pr_number_is_deterministic_and_run_unique():
    from agents.coder_agent import _pseudo_pr_number
    assert _pseudo_pr_number("SPEC-TODO-CORE") == \
           _pseudo_pr_number("SPEC-TODO-CORE")
    # retries (new run id) must not collide with the persistent DB
    assert _pseudo_pr_number("SPEC-TODO-CORE", "RUN-QW-2026-00003") != \
           _pseudo_pr_number("SPEC-TODO-CORE", "RUN-QW-2026-00004")


def test_run_lint_compiles_clean_source(tmp_path):
    (tmp_path / "ok.py").write_text("x = 1\n", encoding="utf-8")
    ok, _ = run_lint(tmp_path)
    assert ok


def test_run_lint_rejects_syntax_errors(tmp_path):
    (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    ok, out = run_lint(tmp_path)
    assert not ok
