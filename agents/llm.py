"""
Local LLM backend (Ollama) with an offline template fallback.

v0 rule: the LLM drafts content; it NEVER performs governance actions.
Governance (IDs, gates, audit) happens server-side no matter which
backend produced the text, so swapping Ollama out for any model cannot
weaken the chain.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.request

# P1 hardening: configuration comes from the environment where available;
# constructor defaults stay backward-compatible for existing callers/tests.
DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_RETRIES = 2          # extra attempts after the first failure
RETRY_BACKOFF_SECONDS = 2.0  # linear backoff: 2s after attempt 1, 4s after 2


class LLMBackend:
    def generate(self, system: str, user: str) -> str:
        raise NotImplementedError


class OllamaLLM(LLMBackend):
    def __init__(self, model: str | None = None,
                 host: str | None = None, timeout: int = 600,
                 retries: int | None = None):
        self.model = (model
                      or os.environ.get("SASE_OLLAMA_MODEL")
                      or "qwen2.5-coder:7b")
        self.host = (host
                     or os.environ.get("SASE_OLLAMA_HOST")
                     or DEFAULT_OLLAMA_HOST).rstrip("/")
        self.timeout = timeout
        self.retries = DEFAULT_RETRIES if retries is None else retries
        # Best-effort version tag for AgentRun provenance (P2); operators
        # can pin it via SASE_MODEL_VERSION when they care about exactness.
        self.version = os.environ.get("SASE_MODEL_VERSION") or None

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags",
                                        timeout=3) as resp:
                tags = json.loads(resp.read().decode())
                return any(self.model in t.get("name", "")
                           for t in tags.get("models", []))
        except Exception:
            return False

    def _build_request(self, system: str, user: str) -> urllib.request.Request:
        payload = json.dumps({
            "model": self.model,
            "system": system,
            "prompt": user,
            "stream": False,
            "options": {"temperature": 0.2},
        }).encode()
        return urllib.request.Request(
            f"{self.host}/api/generate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")

    def generate(self, system: str, user: str) -> str:
        """
        Single LLM call with bounded retry on TRANSIENT failures only:
        connection errors/timeouts (URLError) and HTTP 5xx are retried up
        to `retries` times with linear backoff; HTTP 4xx fails immediately
        (the request itself is wrong — retrying cannot help).
        """
        req = self._build_request(system, user)
        last_err: Exception | None = None
        for attempt in range(1 + max(0, self.retries)):
            if attempt > 0:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            try:
                with urllib.request.urlopen(
                        req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode()).get("response", "")
            except urllib.error.HTTPError as e:
                # NB: HTTPError subclasses URLError — check it FIRST.
                last_err = e
                if 500 <= e.code < 600 and attempt < self.retries:
                    continue
                raise RuntimeError(
                    f"Ollama at {self.host} rejected the request "
                    f"(HTTP {e.code}): {e}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = e
        raise RuntimeError(
            f"Ollama unreachable at {self.host} after "
            f"{1 + max(0, self.retries)} attempt(s): {last_err}") from last_err


def prompt_hash(system_prompt: str) -> str:
    """Stable short hash of a system prompt, for AgentRun provenance."""
    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:32]


class TemplateLLM(LLMBackend):
    """
    Deterministic offline backend used when Ollama/model is not ready yet.
    Produces well-formed artifacts from structured input so the whole
    pipeline can be exercised before the model lands. Output quality is
    deliberately plain — the point is the GOVERNANCE flow, not prose.
    """

    def __init__(self, templates: dict[str, str] | None = None):
        self.templates = templates or {}

    def available(self) -> bool:
        return True

    def generate(self, system: str, user: str) -> str:
        key = user.split("\n")[0].strip()          # first line = template key
        body = self.templates.get(key)
        if body is None:
            raise RuntimeError(
                f"TemplateLLM has no template named {key!r}. "
                f"Available: {sorted(self.templates)}")
        return body


def pick_backend(model: str) -> LLMBackend:
    """Prefer local Ollama; fall back to deterministic templates."""
    ollama = OllamaLLM(model=model)
    if ollama.available():
        return ollama
    return TemplateLLM()
