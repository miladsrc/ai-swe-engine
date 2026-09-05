"""swe-help — hand a blueprint to a local AI and get code files back.

A very simple helper (no dependencies beyond Python's standard library):
you give it a software blueprint (a plain-text description of what you want),
it sends that to a local AI model running in Ollama, and it writes whatever
code the AI produces into an output folder for you to inspect / fix / use.

Usage:
  python swe-help.py "Write a Python TODO CLI with add/list/done commands"
  python swe-help.py --file blueprint.txt
  python swe-help.py --file blueprint.txt --out C:/Users/m.barani/Desktop/todo-code
  python swe-help.py --file blueprint.txt --model qwen2.5:7b --host http://localhost:11434
  python swe-help.py --file blueprint.txt --verify   # run the produced tests too

What it does, step by step:
  1. Reads your blueprint (from the command line or from a .txt/.md file).
  2. Asks the local AI (default: qwen2.5-coder:7b) to produce code, telling it
     to mark each file with a "=== FILE: path ===" header.
  3. Splits the AI's answer into individual files and writes them under the
     output folder (default: ./swe-help-out/run-<timestamp>).
  4. Also saves the raw AI response and a copy of the blueprint for reference.
  No internet. No cloud. No configuration files. Python 3.8+.

Notes:
  - The AI is a proposal machine: always read / test / fix the code yourself.
  - If the AI's output has no "=== FILE: ... ===" markers, everything lands in
    a single file called generated_output.txt so you never lose the answer.
  - Model choice is a practical hardware/reliability decision. On this
    CPU-only machine the reliable models are qwen2.5-coder:7b (code) and
    qwen2.5:7b (general). Larger models (14b/27b) can hang or return nothing.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

FILE_MARKER_PREFIX = "=== FILE:"
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_HOST = "http://localhost:11434"

SYSTEM_PROMPT = (
    "You are an expert software engineer working from a blueprint. "
    "Write complete, working, minimal code. "
    "Mark the start of every file with a line exactly like: "
    '=== FILE: relative/path/file.name ===\n'
    "Write each file's full content after its marker. "
    "Do not add extra commentary outside the files. "
    "Keep the solution simple and runnable.\n"
    "Testing rules: if you produce test_*.py files, each test must be fully "
    "self-contained — use a unique temporary data file per test (for example a "
    "temp folder or a file path only that test uses) and never depend on the "
    "order in which the tests run. Tests must pass when run with 'pytest' in a "
    "fresh, empty folder."
)


def _ask_ollama(model: str, host: str, blueprint: str, timeout: int) -> str:
    """One local LLM call. Returns the model's text reply."""
    payload = json.dumps({
        "model": model,
        "system": SYSTEM_PROMPT,
        "prompt": blueprint,
        "stream": False,
        "options": {"temperature": 0.2},
    }).encode()
    req = urllib.request.Request(
        host.rstrip("/") + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode()).get("response", "")


def _split_files(raw: str) -> tuple[dict[str, str], str | None]:
    """Split the model reply into {path: content} using === FILE: markers.

    Returns (files, leftover): files keyed by path, and any text that appeared
    before the first marker (usually the model's intro) as 'leftover'.
    """
    files: dict[str, str] = {}
    lines = raw.splitlines()
    current_path: str | None = None
    current_lines: list[str] = []
    leftover: list[str] = []

    def flush() -> None:
        nonlocal current_path, current_lines
        if current_path is not None:
            content = "\n".join(current_lines).strip() + "\n"
            # Some models wrap each file in markdown code fences
            # (```python ... ```) even when asked to use === FILE: markers.
            # Strip one leading fence line and one trailing fence line.
            content_lines = content.splitlines()
            if (content_lines and content_lines[0].startswith("```") and
                    content_lines[-1].startswith("```")):
                content = "\n".join(content_lines[1:-1]).strip() + "\n"
            files[current_path] = content
        current_path = None
        current_lines = []

    for line in lines:
        if line.strip().startswith(FILE_MARKER_PREFIX) and "===" in line:
            flush()
            # e.g. '=== FILE: app.py ==='  ->  'app.py'
            path = line.split(FILE_MARKER_PREFIX, 1)[1].rsplit("===", 1)[0].strip()
            current_path = path.lstrip("/\\")
        elif current_path is not None:
            current_lines.append(line)
        else:
            leftover.append(line)
    flush()

    leftover_txt = "\n".join(leftover).strip() or None
    return files, leftover_txt


def _main() -> int:
    ap = argparse.ArgumentParser(
        description="Hand a blueprint to a local Ollama AI and save the files it writes.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("blueprint", nargs="?", help="blueprint text on the command line")
    src.add_argument("--file", help="path to a blueprint .txt/.md file")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"local Ollama model (default: {DEFAULT_MODEL})")
    ap.add_argument("--host", default=DEFAULT_HOST, help="Ollama host (default: localhost:11434)")
    ap.add_argument("--out", default=None, help="output folder (default: ./swe-help-out/run-<timestamp>)")
    ap.add_argument("--timeout", type=int, default=300, help="seconds to wait for the model (default: 300)")
    ap.add_argument("--verify", action="store_true",
                    help="after generating, copy the files to a temp folder and run "
                         "any test_*.py with pytest there (isolated, so leftover "
                         "state cannot fool the result)")
    args = ap.parse_args()

    if args.file:
        blueprint = Path(args.file).read_text(encoding="utf-8")
        print(f"[swe-help] blueprint read from {args.file} ({len(blueprint)} chars)")
    else:
        blueprint = args.blueprint
        print(f"[swe-help] blueprint from command line ({len(blueprint)} chars)")

    # Sanity check: is Ollama up and is the model installed?
    try:
        with urllib.request.urlopen(args.host.rstrip("/") + "/api/tags", timeout=5) as r:
            tags = json.loads(r.read().decode()).get("models", [])
        present = any(args.model in t.get("name", "")
                      for t in tags)
        if not present:
            print(f"[swe-help] ERROR: model '{args.model}' not found in Ollama. "
                  f"Available: {[t['name'] for t in tags]}")
            print("            Pull it first, e.g.:  ollama pull " + args.model)
            return 2
    except Exception as e:
        print(f"[swe-help] ERROR: cannot reach Ollama at {args.host}: {e}")
        print("            Is Ollama running? (start it, then retry)")
        return 2

    out_dir = Path(args.out) if args.out else (
        Path.cwd() / "swe-help-out" / f"run-{datetime.now():%Y%m%d-%H%M%S}")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[swe-help] asking local model  {args.model}  …")
    started = time.time()
    try:
        raw = _ask_ollama(args.model, args.host, blueprint, args.timeout)
    except urllib.error.HTTPError as e:
        print(f"[swe-help] ERROR: Ollama returned HTTP {e.code}: {e.read()[:300]}")
        return 1
    except Exception as e:
        print(f"[swe-help] ERROR: model call failed: {e}")
        print("            This usually means the model is too big/slow for this machine.")
        print("            Try a smaller reliable model, e.g. --model qwen2.5:7b")
        return 1
    elapsed = time.time() - started

    # Always keep the raw answer.
    Path(out_dir / "raw_model_output.txt").write_text(raw, encoding="utf-8")
    Path(out_dir / "blueprint.txt").write_text(blueprint, encoding="utf-8")

    files, leftover = _split_files(raw)

    if not files:
        print(f"[swe-help] the model replied in {elapsed:.0f}s but produced no "
              f"'=== FILE: … ===' markers.")
        print(f"           Full reply saved to {out_dir / 'raw_model_output.txt'}")
        print(f"           (copied as {out_dir / 'generated_output.txt'})")
        Path(out_dir / "generated_output.txt").write_text(raw, encoding="utf-8")
        return 0

    # Skip the UTF-8 BOM problem on Windows: write with utf-8, not utf-8-sig,
    # so files are clean for every editor.
    for path, content in files.items():
        target = out_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")

    print(f"[swe-help] done in {elapsed:.0f}s — wrote {len(files)} file(s) to:")
    print(f"           {out_dir}")
    for path in sorted(files):
        print(f"             {path}  ({len(files[path])} chars)")
    print("[swe-help] IMPORTANT: treat this as a first draft. Read it, test it,")
    print("            and fix it before trusting it.")

    if args.verify:
        _verify_in_temp(out_dir, files)

    return 0


def _verify_in_temp(out_dir: Path, files: dict[str, str]) -> None:
    """Copy generated files into a fresh temp folder and run test_*.py there.

    Isolation matters: the model's tests may use relative paths / files that
    accumulate state (e.g. todo.json). Running in a clean folder shows whether
    the produced code passes on its own, without being fooled by leftovers.
    """
    import shutil
    import subprocess
    import tempfile

    test_files = [p for p in files if Path(p).name.startswith("test_") and
                  Path(p).suffix == ".py"]
    if not test_files:
        print("[swe-help --verify] no test_*.py produced — nothing to run.")
        return

    tmp = Path(tempfile.mkdtemp(prefix="swe-help-verify-"))
    try:
        for path, content in files.items():
            target = tmp / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        print(f"[swe-help --verify] running pytest in isolated folder {tmp} …")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=str(tmp), capture_output=True, text=True, timeout=600)
        print(result.stdout.strip() or result.stderr.strip())
        if result.returncode == 0:
            print("[swe-help --verify] RESULT: PASS — the generated code's tests pass "
                  "in a clean folder.")
        else:
            print("[swe-help --verify] RESULT: FAIL — the generated draft has bugs or "
                  "test issues. Fix the files in the output folder, then re-run "
                  "pytest there.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(_main())