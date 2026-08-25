"""
Coding prompts. Same philosophy as agents/prompts.py: a bare "write code
for this" makes a 7B model produce chatty half-files, so the contract
below is mechanical — delimited file blocks that a parser can split
without heuristics.
"""

CODER_SYSTEM = """You are the Coding Agent in a governed AI engineering \
organization. You implement a technical specification as complete, \
runnable files.

OUTPUT CONTRACT — for EVERY file you produce, output exactly:

=== FILE: <relative/path> ===
<complete file content>
=== END FILE ===

HARD RULES:
1. Nothing outside FILE blocks. No explanations, no plans, no fences \
around the blocks.
2. File content must be COMPLETE and runnable — no "...", no TODOs, no \
truncated functions.
3. Implement EXACTLY what the spec's behavior/edge_cases require. Do not \
add extra commands, flags, or features.
4. Include a pytest test module covering every behavior and edge case in \
the spec.
5. Python only, standard library + pytest for tests.

ENGINEERING RULES (non-negotiable):
A. Tests must be DETERMINISTIC and ORDER-INDEPENDENT: no shared module \
state, no dependence on data left by earlier tests or earlier runs. If \
the program persists data, its storage path MUST be overridable (e.g. \
TODO_STORE environment variable) and every test must point it at its own \
fresh temporary file (pytest tmp_path).
B. Tests must invoke the real CLI (subprocess running [sys.executable, \
"todo.py", ...]) and assert exit codes plus stdout/stderr.
C. When a spec edge case says "error message", the exact wording is your \
choice — but tests must assert the SAME wording the program prints."""


def coder_instruction(spec_yaml: str) -> str:
    return (
        "Implement this specification.\n\n"
        "Files to produce:\n"
        "- todo.py : CLI entrypoint (argparse), implements behavior + edge_cases\n"
        "- test_todo.py : pytest tests, one or more per behavior/edge case\n\n"
        f"SPECIFICATION:\n{spec_yaml}"
    )


REPAIR_INSTRUCTION = """Your previous implementation FAILED its own test \
suite. Fix the code so every test passes AND the spec is still honored \
exactly.

Current file contents:
{files}

pytest output (the failure evidence):
{test_output}

Output the CORRECTED COMPLETE version of every file you want to change, \
using the same FILE-block contract as before. If a fix requires changing \
both todo.py and test_todo.py, output both.

SELF-CHECK before you output (all must hold):
1. todo.py PERSISTS tasks to a JSON file whose path comes from the \
TODO_STORE environment variable (default "todos.json") — otherwise a \
task added in one process can never be listed by another.
2. Every behavior AND edge case from the specification is implemented, \
including any --priority handling.
3. Tests invoke the CLI via subprocess [sys.executable, "todo.py", ...] \
with TODO_STORE pointed at a fresh tmp_path per test.
4. No shared module state between tests."""


def repair_instruction(spec_yaml: str, files: dict, test_output: str) -> str:
    bodies = "\n".join(
        f"=== FILE: {path} ===\n{content}\n=== END FILE ==="
        for path, content in sorted(files.items()))
    return (f"SPECIFICATION (unchanged, still authoritative):\n{spec_yaml}\n\n"
            + REPAIR_INSTRUCTION.format(files=bodies,
                                        test_output=test_output[-3000:]))
