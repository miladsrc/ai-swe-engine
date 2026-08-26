"""
Coding Agent (agent:coder) — validated spec -> real files in a local git
workspace -> real pytest run -> Agent Run Record + MRP in the engine.

Governance properties (mirrors the rest of the agent layer):
- The LLM only produces file CONTENT; every governance action (agent-run
  record, MRP, CRP) is a governed API call whose identity is agent:coder
  and whose allowlist is enforced client-side AND server-side.
- Test evidence is never judged into existence: unit_tests_status is set
  from the exit code of an actual `python -m pytest` subprocess, and it
  is PATCHed to the engine by the LLM-free ci:test-runner identity with
  the CI token (§5.6.5).
- If the spec carries open_questions the coder cannot decide alone, it
  raises ONE high-severity CRP — which hard-blocks merge until a human
  resolves it with a VCR (§3.6.3).
"""

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from agents.coder_prompts import CODER_SYSTEM, coder_instruction, repair_instruction
from agents.engine_client import EngineClient
from agents.llm import LLMBackend, prompt_hash

# P2: prompt provenance. The prompts table has no writers yet; until a
# human-approved prompt registry exists, we record the identifier, a
# version constant, and the hash of the EXACT system prompt used so any
# run's generation inputs can be reproduced/verified from code history.
CODER_PROMPT_ID = "python-coder"
PROMPT_VERSION = "v1"


def prompt_provenance(system_prompt: str,
                      prompt_id: str = CODER_PROMPT_ID) -> dict:
    return {
        "prompt_id": prompt_id,
        "prompt_version": PROMPT_VERSION,
        "system_prompt_hash": prompt_hash(system_prompt),
    }

FILE_BLOCK = re.compile(
    r"=== FILE:\s*(?P<path>[\w./\\-]+)\s*===\n(?P<content>.*?)=== END FILE ===",
    re.DOTALL,
)


@dataclass
class CoderResult:
    run_id: str
    mrp_id: str | None = None
    crp_id: str | None = None
    commit_hash: str | None = None
    generated_files: list[str] = field(default_factory=list)
    tests_passed: bool = False
    test_output: str = ""
    security_passed: bool = True
    security_findings: list[str] = field(default_factory=list)
    lint_passed: bool = True
    lint_output: str = ""
    reflection_iterations: int = 0


class CoderAgent:
    def __init__(self, engine: EngineClient, llm: LLMBackend,
                 workspace: str | Path, project_id: str = "todo-cli",
                 max_repairs: int = 3):
        self.engine = engine
        self.llm = llm
        self.workspace = Path(workspace)
        self.project_id = project_id
        self.max_repairs = max_repairs

    # ------------------------------------------------------------------ main

    def implement_spec(self, spec_id: str, prd_id: str | None = None,
                       user_story_id: str | None = None) -> CoderResult:
        spec = self.engine.get(f"/specs/{spec_id}")
        spec_yaml = spec["body_ref"]
        questions = extract_open_questions(spec_yaml)

        # §3.7.8: provenance record FIRST — code exists only under a run.
        run = self.engine.post("/agent-runs", {
            "project_id": self.project_id,
            "agent_role": "coder_agent",
            "task_type": "code_generation",
            "model_name": getattr(self.llm, "model", "template-offline"),
            "model_version": getattr(self.llm, "version", None),
            "model_short": "QW",
            "prd_id": prd_id,
            "user_story_id": user_story_id,
            "spec_id": spec_id,
            **prompt_provenance(CODER_SYSTEM),
        })
        run_id = run["id"]

        try:
            raw = self._generate_code(spec_yaml)
            files = parse_file_blocks(raw)
            if not files:
                raise RuntimeError("LLM produced no parsable FILE blocks")
            written: list[str] = list(self._write_files(files))

            passed, output = run_tests(self.workspace)

            # Bounded reflection loop (AgentRunUpdate.reflection_iterations):
            # failing pytest output goes back to the model; the REAL test
            # run decides again after every repair attempt.
            repairs = 0
            while not passed and repairs < self.max_repairs:
                repairs += 1
                print(f"[coder] tests failed, repair attempt {repairs}/"
                      f"{self.max_repairs}...")
                raw = self.llm.generate(
                    CODER_SYSTEM,
                    repair_instruction(spec_yaml, files, output))
                try:
                    new_files = parse_file_blocks(raw)
                except RuntimeError:
                    break  # malformed repair output; stop looping
                if not new_files:
                    break
                files = new_files
                written.extend(self._write_files(files))
                passed, output = run_tests(self.workspace)

            sec_ok, sec_findings = security_scan(files)
            lint_ok, lint_output = run_lint(self.workspace)
            # P5: stage ONLY the files this run wrote (surgical staging) —
            # `git add -A` would sweep in leftovers from earlier runs.
            written = sorted(set(written))
            commit = self._commit(run_id, spec_id, written)
            result = CoderResult(
                run_id=run_id,
                generated_files=written,
                tests_passed=passed,
                test_output=output,
                commit_hash=commit,
                security_passed=sec_ok,
                security_findings=sec_findings[:20],
                lint_passed=lint_ok,
                lint_output=lint_output,
                reflection_iterations=repairs,
            )

            # GET /specs does not echo the name; derive it from the id
            # (SPEC-<DOMAIN>-<name...>) for branch naming.
            spec_name = "-".join(spec_id.split("-")[2:]).lower() or "impl"
            mrp = self.engine.post("/mrps", {
                "project_id": self.project_id,
                "pull_request_number": _pseudo_pr_number(spec_id, run_id),
                "branch_name": f"agent/{spec_name}-{run_id.lower()[-6:]}",
                "created_by_agent_run": run_id,
                "prd_id": prd_id,
                "user_story_ids": [spec["user_story_id"]] if spec.get("user_story_id") else [],
                "spec_ids": [spec_id],
                "blueprint_id": "BP-PYTHON-CLI-001",
                "blueprint_version": "v1.0",
                "change_summary": f"Implement {spec_id} per validated spec "
                                  f"(agent run {run_id}).",
                "affected_modules": ["todo.py"],
            })
            result.mrp_id = mrp["id"]

            # Terminal state decision (§3.7.8: exactly ONE terminal patch):
            # open questions -> blocked (CRP below enforces it server-side);
            # failing tests -> failed; otherwise completed.
            if questions:
                final_status = "blocked"
            elif passed:
                final_status = "completed"
            else:
                final_status = "failed"
            self.engine.patch(f"/agent-runs/{run_id}", {
                "status": final_status,
                "generated_files": result.generated_files,
                "commit_hash": commit,
                "mrp_id": mrp["id"],
                "tools_used": ["ollama:local", "pytest"],
                "reflection_iterations": result.reflection_iterations or None,
            })

            # Raised AFTER the terminal patch: POST /crps marks high/critical
            # runs blocked server-side, and terminal runs are immutable.
            if questions:
                result.crp_id = self._raise_crp(spec_id, run_id, questions)
            return result
        except Exception as e:
            # Run stays non-terminal until we mark it; a crash must not
            # leave an immortal 'running' row.
            try:
                self.engine.patch(f"/agent-runs/{run_id}",
                                  {"status": "failed"})
            except Exception:
                pass
            raise RuntimeError(f"coder run {run_id} failed: {e}") from e

    # -------------------------------------------------------------- helpers

    def _generate_code(self, spec_yaml: str) -> str:
        return self.llm.generate(CODER_SYSTEM, coder_instruction(spec_yaml))

    def _write_files(self, files: dict[str, str]) -> list[str]:
        """Write files inside the workspace; returns the relative paths
        actually written (P5: used for surgical git staging)."""
        written = []
        for rel, content in files.items():
            path = (self.workspace / rel).resolve()
            if self.workspace.resolve() not in path.parents:
                raise RuntimeError(f"refusing to write outside workspace: {rel}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            written.append(rel)
        return written

    def _commit(self, run_id: str, spec_id: str,
                paths: list[str] | None = None) -> str:
        def git(*args: str) -> str:
            return subprocess.run(["git", *args], cwd=self.workspace,
                                  capture_output=True, text=True, check=True
                                  ).stdout.strip()
        # P5: stage only this run's generated files. A missing/empty list
        # falls back to `add -A` for backward compatibility with callers
        # that don't track paths (e.g. the Spring Boot __main__ script).
        if paths:
            git("add", "--", *paths)
        else:
            git("add", "-A")
        if not git("status", "--porcelain"):
            return git("rev-parse", "HEAD")  # nothing new; reuse HEAD
        git("commit", "-m",
            f"agent:coder implement {spec_id} (engine run {run_id})")
        return git("rev-parse", "HEAD")

    def _raise_crp(self, spec_id: str, run_id: str,
                   questions: list) -> str:
        bullets = "\n".join(f"- {q}" for q in questions)
        crp = self.engine.post("/crps", {
            "project_id": self.project_id,
            "domain": spec_id.split("-")[1] if "-" in spec_id else "TODO",
            "agent_run_id": run_id,
            "spec_id": spec_id,
            "severity": "high",
            "blocking_issue_title":
                f"Spec {spec_id} carries unresolved open questions",
            "blocking_issue_body":
                f"The validated spec lists open questions that require a\n"
                f"product decision before the implementation can be merged:\n"
                f"{bullets}",
            "required_decision":
                "Answer each open question (or approve proceeding with the "
                "agent's stated default).",
            "required_role": "Product Owner",
        })
        return crp["id"]


# ------------------------------------------------------------------ pure funcs

def extract_open_questions(spec_yaml: str) -> list[str]:
    """
    Tolerant open_questions extraction. The spec bodies our own LLMs
    draft are YAML-shaped but not always valid YAML (markdown backticks
    are a reserved char), so strict safe_load is a nice-to-have, not a
    requirement — fall back to line parsing of the open_questions block.
    """
    try:
        parsed = yaml.safe_load(spec_yaml) or {}
        return [str(q) for q in (parsed.get("open_questions") or [])]
    except yaml.YAMLError:
        pass
    out, capture = [], False
    for line in spec_yaml.splitlines():
        if line.strip().startswith("open_questions:"):
            capture = True
            continue
        if capture:
            if re.match(r"^\s+-\s+\S", line):
                out.append(line.strip()[2:].strip().strip("`"))
            elif line.strip() and not line[0].isspace() and not line.startswith("- "):
                break  # next top-level key ends the block
    return out


def parse_file_blocks(raw: str) -> dict[str, str]:
    """Split the LLM's delimited output into {path: content}. Strict: any
    text outside blocks is ignored; a block missing its END marker raises."""
    files = {}
    for m in FILE_BLOCK.finditer(raw):
        path = m.group("path").strip().replace("\\\\", "/").lstrip("/")
        files[path] = _strip_code_fence(m.group("content"))
    if "=== FILE:" in raw and len(files) != raw.count("=== FILE:"):
        raise RuntimeError("malformed FILE block(s): missing === END FILE ===")
    return files


def _strip_code_fence(content: str) -> str:
    """7B models love wrapping file bodies in ```python fences even when
    told not to. Strip one outer fence pair if present."""
    stripped = content.strip("\n")
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        lines = lines[1:]                       # drop ```python / ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines)
    return content


# Patterns that have no business in an offline stdlib-only CLI tool.
# NOTE: plain open(path, 'w') is legitimate (the store file) and must
# NOT be flagged — v0 of this scanner did and produced a false positive.
_DANGEROUS_PY = re.compile(
    r"\b(eval|exec|compile)\s*\(|\bos\.system\b|\bsubprocess\.\w*shell\b"
    r"|\bsocket\.(socket|create_connection)\b|\bpickle\.loads?\b"
    r"|\b__import__\s*\(", re.MULTILINE)

# P5: Java/Kotlin sources were previously scanned with the Python
# patterns verbatim, which matched nothing useful. These are the
# equivalent dynamic-execution / raw-deserialization red flags for JVM
# code generated by the Spring Boot coder agent.
_DANGEROUS_JVM = re.compile(
    r"\bRuntime\s*\.\s*getRuntime\s*\(\s*\)\s*\.\s*exec"
    r"|\bnew\s+ProcessBuilder\b|\bClass\s*\.\s*forName\s*\("
    r"|\bsun\.misc\.Unsafe\b|\bObjectInputStream\b"
    r"|\bXMLDecoder\b", re.MULTILINE)

_SCAN_RULES: tuple[tuple[tuple[str, ...], "re.Pattern[str]"], ...] = (
    ((".java", ".kt", ".scala"), _DANGEROUS_JVM),
)


def _pattern_for(path: str) -> "re.Pattern[str]":
    for extensions, pattern in _SCAN_RULES:
        if path.endswith(extensions):
            return pattern
    return _DANGEROUS_PY


def security_scan(files: dict[str, str]) -> tuple[bool, list[str]]:
    """
    Real (if naive) offline scan: the generated source is inspected for
    dynamic-execution / shell / raw-socket patterns. Evidence comes from
    this function's output, never from an LLM's self-assessment.

    Language-aware since P5: JVM files (.java/.kt/.scala) are checked
    against JVM patterns; everything else against the Python patterns.
    """
    findings = []
    for path, content in files.items():
        pattern = _pattern_for(path)
        for i, line in enumerate(content.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if pattern.search(line):
                findings.append(f"{path}:{i}: {line.strip()[:80]}")
    return (not findings), findings


def run_lint(workspace: Path) -> tuple[bool, str]:
    """Offline lint proxy: bytecode compilation catches syntax errors."""
    proc = subprocess.run([sys.executable, "-m", "compileall", "-q", "."],
                          cwd=workspace, capture_output=True, text=True,
                          timeout=120)
    return proc.returncode == 0, proc.stdout + proc.stderr


def run_tests(workspace: Path) -> tuple[bool, str]:
    """REAL evidence: pytest's exit code decides, nothing else does."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"], cwd=workspace,
        capture_output=True, text=True, timeout=600)
    return proc.returncode == 0, proc.stdout + proc.stderr


def _pseudo_pr_number(spec_id: str, run_id: str = "") -> int:
    """No remote hosting exists (fully offline); MRs still need a stable
    PR number. Derived from spec id + run sequence so retries against the
    persistent DB never collide."""
    return 70000 + (sum(ord(c) for c in spec_id)
                    + int(re.findall(r"(\d+)$", run_id)[0] if re.findall(r"(\d+)$", run_id) else 0)) % 30000


def record_ci_evidence(ci_engine: EngineClient, mrp_id: str,
                       tests_passed: bool, security_passed: bool,
                       lint_passed: bool,
                       execution_context: dict | None = None) -> dict:
    """
    The LLM-free ci:test-runner identity records what the REAL subprocess
    checks reported. Every status here traces to an executed command or
    scan — never to a model's opinion (§5.6.5).

    P7: `execution_context` (optional) carries the raw evidence — full
    test output, scan findings, lint output, run metadata — which the
    server stores in the append-only audit entry context.
    """
    payload = {
        "unit_tests_status": "passed" if tests_passed else "failed",
        "integration_tests_status": "not_applicable",
        "security_scan_status": "passed" if security_passed else "failed",
        "static_analysis_status": "passed" if lint_passed else "failed",
        "lint_status": "passed" if lint_passed else "failed",
    }
    if execution_context is not None:
        payload["execution_context"] = execution_context
    return ci_engine.patch(f"/mrps/{mrp_id}/evidence", payload)
