"""Print diagnostic lines from the latest evidence test_output."""
import json
import os

path = os.path.join(os.environ["TEMP"], "ev.json")
entries = json.load(open(path, encoding="utf-8"))
for e in entries:
    t = e["context"]["execution_context"]["test_output"]
    print(f"=== {e['artifact_id']} (len={len(t)}) ===")
    keep = [l for l in t.splitlines() if any(
        k in l for k in ("Tests run", "Caused by", "APPLICATION FAILED",
                         "AssertionError", "[ERROR]", "expect"))]
    print("\n".join(keep[:25]))
