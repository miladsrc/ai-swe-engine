"""
Local LLM backend (Ollama) with an offline template fallback.

v0 rule: the LLM drafts content; it NEVER performs governance actions.
Governance (IDs, gates, audit) happens server-side no matter which
backend produced the text, so swapping Ollama out for any model cannot
weaken the chain.
"""

import json
import urllib.error
import urllib.request


class LLMBackend:
    def generate(self, system: str, user: str) -> str:
        raise NotImplementedError


class OllamaLLM(LLMBackend):
    def __init__(self, model: str = "qwen2.5-coder:7b",
                 host: str = "http://localhost:11434", timeout: int = 600):
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags",
                                        timeout=3) as resp:
                tags = json.loads(resp.read().decode())
                return any(self.model in t.get("name", "")
                           for t in tags.get("models", []))
        except Exception:
            return False

    def generate(self, system: str, user: str) -> str:
        payload = json.dumps({
            "model": self.model,
            "system": system,
            "prompt": user,
            "stream": False,
            "options": {"temperature": 0.2},
        }).encode()
        req = urllib.request.Request(
            f"{self.host}/api/generate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode()).get("response", "")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Ollama unreachable at {self.host}: {e}") from e


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
