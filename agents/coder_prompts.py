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
the program persists data, its storage path MUST be overridable (e.g. a \
STORE/DB_PATH environment variable) and every test must point it at its \
own fresh temporary file (pytest tmp_path).
B. Tests must exercise the real program (subprocess invoking the module, \
or an in-process callable) and assert real behavior, not mocks of it.
C. When a spec edge case says "error message", the exact wording is your \
choice — but tests must assert the SAME wording the program prints."""


def spec_target_files(spec_yaml: str) -> list[str]:
    """Derive the explicit target-file list from the spec, if present.

    The spec may carry an explicit line either as YAML:
        target_files:
          - app.py
          - static/index.html
    or as a markdown marker:
        #sase-files: app.py, static/index.html
    When neither is present we fall back to the historical CLI contract
    (todo.py + test_todo.py) so existing callers/tests stay unchanged.
    This keeps the *which files to generate* decision blueprint-driven
    without weakening the governance/gates boundaries.
    """
    files: list[str] = []
    capture = False
    for line in spec_yaml.splitlines():
        s = line.strip()
        if s.lower().startswith("#sase-files:"):
            for part in s.split(":", 1)[1].replace(",", " ").split():
                if part.strip():
                    files.append(part.strip())
            break
        if s.lower().startswith("target_files:"):
            capture = True
            continue
        if capture:
            if s.startswith("- "):
                files.append(s[2:].strip())
            elif s and not s.startswith(("-", "#", ":")) and not s[0].isspace():
                break  # first non-list, non-indented token ends the block
    return files or ["todo.py", "test_todo.py"]


def coder_instruction(spec_yaml: str, files: list[str] | None = None) -> str:
    files = files or spec_target_files(spec_yaml)
    bullets = "\n".join(f"- {f}" for f in files)
    return (
        "Implement this specification.\n\n"
        "Files to produce (exactly these, no more, no fewer):\n"
        f"{bullets}\n\n"
        "Each file must be COMPLETE and runnable. Include one or more pytest "
        "tests (in a *_test.py / test_*.py module) covering every behavior "
        "and edge case in the specification. If the product has a persistent "
        "store (file/db), its path MUST be overridable via an environment "
        "variable and every test must point it at a fresh temporary location "
        "so tests are deterministic and order-independent.\n\n"
        f"SPECIFICATION:\n{spec_yaml}"
    )


PARAMETER_INSTRUCTION ="""



"""

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
1. The program PERSISTS its data to a path that comes from an environment \
variable (e.g. STORE/DB_PATH/STATE_FILE, with a sensible default) — \
otherwise data written by one invocation can never be read by another.
2. Every behavior AND edge case from the specification is implemented.
3. Tests are deterministic and order-independent, use pytest tmp_path for \
any persisted store, and exercise the REAL program (not mocks).
4. No shared module state between tests."""


def repair_instruction(spec_yaml: str, files: dict, test_output: str) -> str:
    bodies = "\n".join(
        f"=== FILE: {path} ===\n{content}\n=== END FILE ==="
        for path, content in sorted(files.items()))
    return (f"SPECIFICATION (unchanged, still authoritative):\n{spec_yaml}\n\n"
            + REPAIR_INSTRUCTION.format(files=bodies,
                                        test_output=test_output[-3000:]))
