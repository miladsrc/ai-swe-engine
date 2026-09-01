"""
DB-free regression tests for the hardening batch (P1-P5, P7):
  P1 - env-configurable Ollama + bounded transient-failure retry
  P2 - AgentRun provenance helpers (prompt id/version/hash)
  P3 - covered in test_gates_unit.py (fail-closed CI gate)
  P4 - orphan-run reaper (pure logic + fake session)
  P5 - surgical staging contract + language-aware security scan
  P7 - execution_context rides through MRPEvidenceUpdate

Run: pytest tests/test_hardening_batch.py  (no Postgres / API needed)
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

import agents.llm as llm_mod
from agents.scanner import _pattern_for, security_scan
from agents.coder_agent import (
    CODER_SYSTEM,
    parse_file_blocks,
    prompt_provenance,
    record_ci_evidence,
)
from agents.llm import OllamaLLM, TemplateLLM, prompt_hash
from api.schemas import MRPEvidenceUpdate
from api.routers.agent_runs import _orphan_cutoff, reap_orphan_runs


# ------------------------------------------------------------ P1: LLM ----

def test_prompt_hash_stable_and_short():
    h1 = prompt_hash("hello")
    h2 = prompt_hash("hello")
    assert h1 == h2 and len(h1) == 32 and h1 != prompt_hash("world")


def test_ollama_host_and_model_from_env(monkeypatch):
    monkeypatch.setenv("SASE_OLLAMA_HOST", "http://10.0.0.5:11434")
    monkeypatch.setenv("SASE_OLLAMA_MODEL", "mistral:7b")
    o = OllamaLLM()
    assert o.host == "http://10.0.0.5:11434"
    assert o.model == "mistral:7b"


def test_ollama_defaults_preserved(monkeypatch):
    monkeypatch.delenv("SASE_OLLAMA_HOST", raising=False)
    monkeypatch.delenv("SASE_OLLAMA_MODEL", raising=False)
    o = OllamaLLM()
    assert o.host == "http://localhost:11434"
    assert o.model == "qwen2.5-coder:7b"


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b'{"response": "MODEL OK"}'


class _FlakyUrnopen:
    """urllib.urlopen stand-in failing N times, then succeeding."""

    def __init__(self, fail_times, exc):
        self.fail_times = fail_times
        self.exc = exc
        self.calls = 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeResponse()


def test_generate_retries_transient_urlerror_then_succeeds(monkeypatch):
    import urllib.error
    flaky = _FlakyUrnopen(2, urllib.error.URLError("conn reset"))
    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)  # fast test
    out = OllamaLLM(retries=2).generate("sys", "user")
    assert out == "MODEL OK"
    assert flaky.calls == 3


def test_generate_exhausts_retries_then_raises(monkeypatch):
    import urllib.error
    flaky = _FlakyUrnopen(99, urllib.error.URLError("down"))
    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(llm_mod.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="unreachable"):
        OllamaLLM(retries=2).generate("sys", "user")


def test_generate_does_not_retry_http_4xx(monkeypatch):
    import urllib.error
    flaky = _FlakyUrnopen(
        99, urllib.error.HTTPError("url", 404, "nf", {}, None))
    calls = {"n": 0}

    def counting(req, timeout=None):
        calls["n"] += 1
        raise flaky.exc

    monkeypatch.setattr(llm_mod.urllib.request, "urlopen", counting)
    with pytest.raises(RuntimeError, match="HTTP 404"):
        OllamaLLM(retries=3).generate("sys", "user")
    assert calls["n"] == 1  # fail fast on client errors


# ------------------------------------------------------------ P2: provenance ----

def test_prompt_provenance_fields():
    prov = prompt_provenance(CODER_SYSTEM)
    assert prov["prompt_id"] == "python-coder"
    assert prov["prompt_version"] == "v1"
    assert prov["system_prompt_hash"] == prompt_hash(CODER_SYSTEM)


def test_prompt_provenance_java_id():
    prov = prompt_provenance("JAVA SYSTEM", "java-coder")
    assert prov["prompt_id"] == "java-coder"


# ------------------------------------------------------------ P4: reaper ----

def _ts(**kw):
    return datetime.now(timezone.utc) - timedelta(**kw)


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._scalars = _FakeScalars(rows)

    @property
    def scalars(self):
        return lambda: self._scalars


class _FakeRun:
    def __init__(self, run_id, started_at):
        self.id = run_id
        self.status = "running"
        self.started_at = started_at
        self.finished_at = None


class _FakeDb:
    def __init__(self, rows):
        self.rows = rows
        self.audit = []
        self.commits = 0

    def execute(self, stmt):
        return _FakeResult(self.rows)

    def add(self, obj):
        from api.models import AuditLog
        assert isinstance(obj, AuditLog)
        self.audit.append(obj)

    def commit(self):
        self.commits += 1


def test_orphan_cutoff_math():
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    assert _orphan_cutoff(now, 24.0) == now - timedelta(hours=24)
    assert _orphan_cutoff(now, 1.5) == now - timedelta(minutes=90)


def test_reaper_marks_stale_running_failed_and_audits():
    stale = _FakeRun("RUN-QW-2026-00001", _ts(hours=30))
    db = _FakeDb([stale])
    reaped = reap_orphan_runs(db, max_age_hours=24.0)
    assert reaped == ["RUN-QW-2026-00001"]
    assert stale.status == "failed"
    assert db.commits == 1
    entry = db.audit[0]
    assert entry.actor_type == "system"
    assert entry.actor_id == "orphan-reaper"
    assert entry.action == "reap_orphan_run"
    assert entry.result == "failed"


def test_reaper_noop_when_nothing_stale():
    db = _FakeDb([])
    assert reap_orphan_runs(db, max_age_hours=24.0) == []
    assert db.commits == 0 and db.audit == []


# ------------------------------------------------------------ P5: scan/staging ----

def test_security_scan_java_patterns_apply_to_java_files():
    ok, findings = security_scan({
        "src/Main.java": 'Runtime.getRuntime().exec("rm -rf /");\n',
        "src/Pb.java": "new ProcessBuilder(cmd).start();\n",
    })
    assert not ok
    assert all(f.startswith("src/") for f in findings)
    assert len(findings) == 2


def test_security_scan_python_patterns_do_not_hit_python_false_positives():
    # Java-only constructs are normal identifiers-free in python files;
    # conversely python's eval must be caught by the python rule set.
    ok_bad, findings = security_scan({"tool.py": 'x = eval(user_input)\n'})
    assert not ok_bad and findings
    ok_clean, _ = security_scan({"tool.py": 'with open(path, "w") as f:\n'
                                             '    f.write(data)\n'})
    assert ok_clean


def test_pattern_for_dispatch_by_extension():
    assert _pattern_for("A.java") is not _pattern_for("a.py")
    assert _pattern_for("X.kt") is _pattern_for("A.java")


def test_parse_file_blocks_still_works_after_refactor():
    raw = ("=== FILE: todo.py ===\nprint('hi')\n=== END FILE ===\n"
           "=== FILE: sub/test_todo.py ===\ndef test_x(): pass\n=== END FILE ===")
    files = parse_file_blocks(raw)
    assert sorted(files) == ["sub/test_todo.py", "todo.py"]


# ------------------------------------------------------------ P7: evidence ----

def test_evidence_update_accepts_execution_context():
    payload = MRPEvidenceUpdate(
        unit_tests_status="passed",
        execution_context={"test_output": "...", "security_findings": []},
    )
    data = payload.model_dump(exclude_unset=True)
    assert data["execution_context"]["test_output"] == "..."
    ctx = data.pop("execution_context")
    assert "execution_context" not in data  # never an MRP column


class _CaptureClient:
    def __init__(self):
        self.payload = None

    def patch(self, path, payload):
        self.payload = payload
        return {"ok": True}


def test_record_ci_evidence_includes_execution_context():
    client = _CaptureClient()
    record_ci_evidence(client, "MRP-PR-1", True, True, True,
                       execution_context={"test_output": "full output"})
    assert client.payload["execution_context"] == {"test_output": "full output"}
    assert client.payload["unit_tests_status"] == "passed"


def test_record_ci_evidence_without_context_is_backward_compatible():
    client = _CaptureClient()
    record_ci_evidence(client, "MRP-PR-1", False, True, False)
    assert "execution_context" not in client.payload
