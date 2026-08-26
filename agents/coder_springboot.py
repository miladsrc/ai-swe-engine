"""
Spring Boot Coder Agent — adapts CoderAgent for Java/Maven projects.
Overrides test runner to use `mvn test` instead of `pytest`.
"""

import os
import subprocess
import sys
from pathlib import Path

from agents.coder_agent import (CoderAgent, record_ci_evidence, parse_file_blocks,
                                security_scan, prompt_provenance)
from agents.config import ROLES
from agents.engine_client import EngineClient, human_curl_auth, print_human_auth_hint
from agents.llm import pick_backend


# Java/Spring Boot specific prompts
JAVA_CODER_SYSTEM = """You are the Coding Agent in a governed AI engineering \
organization. You implement a technical specification as complete, \
runnable Java Spring Boot files.

OUTPUT CONTRACT — for EVERY file you produce, output exactly:

=== FILE: <relative/path> ===
<complete file content>
=== END FILE ===

HARD RULES:
1. Nothing outside FILE blocks. No explanations, no plans, no fences \
around the blocks.
2. File content must be COMPLETE and runnable — no "...", no TODOs, no \
truncated methods.
3. Implement EXACTLY what the spec's behavior/edge_cases require. Do not \
add extra features.
4. Include JUnit 5 test classes covering every behavior and edge case.
5. Java 17+ with Spring Boot 3.x, Spring Data JPA, H2 database.

ENGINEERING RULES (non-negotiable):
A. Use Maven project structure with pom.xml.
B. Tests must be DETERMINISTIC: use @BeforeEach to reset state, \
use H2 in-memory database for tests.
C. Include application.yml with proper configuration.
D. Model classes must use JPA annotations (@Entity, @Id, etc).
E. REST controllers must use proper HTTP status codes."""


def java_coder_instruction(spec_yaml: str) -> str:
    return (
        "Implement this specification as a Java Spring Boot application.\n\n"
        "Files to produce:\n"
        "- pom.xml : Maven build file with Spring Boot dependencies\n"
        "- src/main/java/com/example/todo/TodoApplication.java : Main class\n"
        "- src/main/java/com/example/todo/model/TodoItem.java : JPA entity\n"
        "- src/main/java/com/example/todo/repository/TodoRepository.java : Spring Data repository\n"
        "- src/main/java/com/example/todo/service/TodoService.java : Business logic\n"
        "- src/main/java/com/example/todo/controller/TodoController.java : REST controller\n"
        "- src/main/java/com/example/todo/exception/TodoNotFoundException.java : Exception\n"
        "- src/main/resources/application.yml : Configuration\n"
        "- src/test/java/com/example/todo/TodoControllerTest.java : Integration tests\n"
        "- src/test/java/com/example/todo/TodoServiceTest.java : Unit tests\n\n"
        f"SPECIFICATION:\n{spec_yaml}"
    )


JAVA_REPAIR_INSTRUCTION = """Your previous implementation FAILED its own test \
suite. Fix the code so every test passes AND the spec is still honored exactly.

Current file contents:
{files}

Maven test output (the failure evidence):
{test_output}

Output the CORRECTED COMPLETE version of every file you want to change, \
using the same FILE-block contract as before.

SELF-CHECK before you output (all must hold):
1. pom.xml has correct Spring Boot parent and dependencies.
2. Every behavior AND edge case from the specification is implemented.
3. Tests use @SpringBootTest with TestRestTemplate or MockMvc.
4. H2 database is configured for both main and test profiles."""


def java_repair_instruction(spec_yaml: str, files: dict, test_output: str) -> str:
    bodies = "\n".join(
        f"=== FILE: {path} ===\n{content}\n=== END FILE ==="
        for path, content in sorted(files.items()))
    return (f"SPECIFICATION (unchanged, still authoritative):\n{spec_yaml}\n\n"
            f"CURRENT FILES:\n{bodies}\n\n"
            f"TEST OUTPUT:\n{test_output}\n\n"
            f"Fix ALL failures while keeping the spec honored. Output corrected files.")


def run_maven_tests(workspace: Path) -> tuple[bool, str]:
    """REAL evidence: Maven's exit code decides, nothing else does."""
    # Check if mvnw exists, otherwise use system mvn
    mvn_cmd = workspace / "mvnw"
    if not mvn_cmd.exists():
        mvn_cmd = "mvn"
    
    try:
        proc = subprocess.run(
            [mvn_cmd, "test", "-q"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=600
        )
        return proc.returncode == 0, proc.stdout + proc.stderr
    except FileNotFoundError:
        return False, "Maven not found. Install Maven or add mvnw to project."
    except subprocess.TimeoutExpired:
        return False, "Maven test timed out after 600 seconds."


class SpringBootCoderAgent(CoderAgent):
    """Coder agent specialized for Spring Boot / Maven projects."""
    
    def __init__(self, engine, llm, workspace, project_id="todo-springboot", max_repairs=5):
        super().__init__(engine, llm, workspace, project_id, max_repairs)
    
    def _generate_code(self, spec_yaml: str) -> str:
        """Override to use Java-specific prompts."""
        return self.llm.generate(JAVA_CODER_SYSTEM, java_coder_instruction(spec_yaml))
    
    def implement_spec(self, spec_id, prd_id=None, user_story_id=None):
        """Override to use Maven tests instead of pytest."""
        spec = self.engine.get(f"/specs/{spec_id}")
        spec_yaml = spec["body_ref"]
        from agents.coder_agent import extract_open_questions
        questions = extract_open_questions(spec_yaml)

        # Create agent run record (P2: full prompt provenance)
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
            **prompt_provenance(JAVA_CODER_SYSTEM, "java-coder"),
        })
        run_id = run["id"]

        try:
            raw = self._generate_code(spec_yaml)
            files = parse_file_blocks(raw)
            if not files:
                raise RuntimeError("LLM produced no parsable FILE blocks")
            written: list[str] = list(self._write_files(files))

            # Use Maven tests instead of pytest
            passed, output = run_maven_tests(self.workspace)

            # Bounded reflection loop
            repairs = 0
            while not passed and repairs < self.max_repairs:
                repairs += 1
                print(f"[coder] tests failed, repair attempt {repairs}/{self.max_repairs}...")
                raw = self.llm.generate(
                    JAVA_CODER_SYSTEM,
                    java_repair_instruction(spec_yaml, files, output)
                )
                try:
                    new_files = parse_file_blocks(raw)
                except RuntimeError:
                    break  # malformed repair output; stop looping
                if not new_files:
                    break
                files = new_files
                written.extend(self._write_files(files))
                passed, output = run_maven_tests(self.workspace)

            # Security scan (language-aware since P5)
            sec_ok, sec_findings = security_scan(files)
            written = sorted(set(written))

            # Git commit with provenance — P5: stage only this run's files.
            commit = self._commit(run_id, spec_id, written)

            # Create MRP
            mrp = self.engine.post("/mrps", {
                "project_id": self.project_id,
                "pull_request_number": self._pseudo_pr_number(spec_id, run_id),
                "branch_name": f"agent/springboot-{run_id.lower()[-6:]}",
                "created_by_agent_run": run_id,
                "prd_id": prd_id,
                "user_story_ids": [user_story_id] if user_story_id else [],
                "spec_ids": [spec_id],
                "blueprint_id": "BP-SPRINGBOOT-TODO-001",
                "blueprint_version": "v1.0",
                "change_summary": f"Implement {spec_id} per validated spec (agent run {run_id}).",
                "affected_modules": ["src/main/java/com/example/todo"],
            })

            # Raise CRP if open questions — BEFORE the terminal patch
            # (POST /crps flips the run to 'blocked' server-side; a
            # terminal run can no longer be patched, so this must come
            # first. Same ordering rule as the Python coder agent.)
            crp_id = None
            if questions:
                crp_id = self._raise_crp(spec_id, run_id, questions)

            # Terminal state decision (§3.7.8: exactly ONE terminal patch)
            final_status = ("blocked" if questions
                            else "completed" if passed else "failed")
            self.engine.patch(f"/agent-runs/{run_id}", {
                "status": final_status,
                "reflection_iterations": repairs,
                "tools_used": ["maven", "java"],
                "generated_files": written,
                "commit_hash": commit,
                "mrp_id": mrp["id"],
            })

            from agents.coder_agent import CoderResult
            return CoderResult(
                run_id=run_id,
                mrp_id=mrp["id"],
                crp_id=crp_id,
                commit_hash=commit,
                generated_files=list(files.keys()),
                tests_passed=passed,
                test_output=output,
                security_passed=sec_ok,
                security_findings=sec_findings,
                lint_passed=True,
                reflection_iterations=repairs,
            )

        except Exception as e:
            # Run stays non-terminal until we mark it; guard the marker
            # itself so a secondary failure doesn't mask the root cause.
            try:
                self.engine.patch(f"/agent-runs/{run_id}",
                                  {"status": "failed"})
            except Exception:
                pass
            raise

    def _git_commit(self, spec_id, run_id):
        """Commit with provenance."""
        import re
        def git(*args):
            return subprocess.run(
                ["git"] + list(args),
                cwd=self.workspace,
                capture_output=True, text=True
            ).stdout.strip()
        
        git("add", "-A")
        git("commit", "-m",
            f"agent:coder implement {spec_id} (engine run {run_id})")
        return git("rev-parse", "HEAD")


if __name__ == "__main__":
    import json
    
    base_url = "http://localhost:8000"
    spec_id = "SPEC-TODO-SPRING-BOOT-TODO-REST-API"
    workspace = Path(r"C:\Users\m.barani\IdeaProjects\todo-springboot")
    
    # Create workspace if needed
    workspace.mkdir(parents=True, exist_ok=True)
    
    # Init git repo if needed
    if not (workspace / ".git").exists():
        subprocess.run(["git", "init"], cwd=workspace)
        subprocess.run(["git", "config", "user.name", "agent:coder"], cwd=workspace)
        subprocess.run(["git", "config", "user.email", "coder@local"], cwd=workspace)
    
    # Initialize LLM
    llm = pick_backend("qwen2.5-coder:7b")
    
    # Create agent
    coder = SpringBootCoderAgent(
        EngineClient(base_url, ROLES["coder"]),
        llm,
        workspace=workspace,
        project_id="todo-springboot",
        max_repairs=int(os.environ.get("CODER_MAX_REPAIRS", "5"))
    )
    
    print(f"[coder] implementing {spec_id} -> {workspace}")
    result = coder.implement_spec(
        spec_id,
        prd_id="PRD-TODO-008",
        user_story_id="US-TODO-008"
    )
    
    print(f"\n[coder] DONE: run={result.run_id}")
    print(f"  tests={'PASS' if result.tests_passed else 'FAIL'}")
    print(f"  security={'PASS' if result.security_passed else 'FAIL'}")
    print(f"  commit={result.commit_hash[:8] if result.commit_hash else '?'}")
    print(f"  files: {result.generated_files}")
    if result.crp_id:
        print(f"  CRP raised: {result.crp_id}")
    print(f"  MRP: {result.mrp_id}")
    
    # Record CI evidence (P3: token only from env — server fail-closes
    # when SASE_CI_TOKEN is unset on the deployment).
    ci = EngineClient(base_url, ROLES["test_runner"],
                      ci_token=os.environ.get("SASE_CI_TOKEN"))
    record_ci_evidence(ci, result.mrp_id, result.tests_passed,
                       result.security_passed, result.lint_passed)
    print(f"[ci] evidence recorded on {result.mrp_id}")
    
    print("\n=== HUMAN GATES ===")
    print_human_auth_hint(base_url)
    if result.crp_id:
        print(f"1. Resolve CRP: curl -X POST {base_url}/vcrs "
              f"{human_curl_auth()} ...")
    print(f"2. Approve merge: curl -X POST {base_url}/mrps/{result.mrp_id}/"
          f"human-decision {human_curl_auth()} ...")
