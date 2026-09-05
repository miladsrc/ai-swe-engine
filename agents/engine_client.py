"""
HTTP client for the traceability backbone, identity- and policy-aware.

Every call carries X-Acting-As from the role's identity. The allowlist is
checked BEFORE the request is sent, so a misbehaving agent cannot even
attempt an out-of-mandate call — the violation is raised locally and (in
future work) becomes a CRP/audit event rather than a silent bypass.
"""

import json
import os
import re
import urllib.error
import urllib.request

from agents.config import RolePolicy


class PolicyViolation(PermissionError):
    """A role tried to use an endpoint outside its mandate."""


# Opt-in communication trace (SASE_ENGINE_TRACE=1). Prints the real
# request/response boundary between an agent (or the orchestrator) and the
# engine — method, path, actor identity, and a compact body outline.
# Never prints headers (tokens live there) and truncates body content.
def _compact(value, limit: int = 80) -> str:
    if isinstance(value, dict):
        if "execution_context" in value:  # evidence bodies are huge
            return f"{{... {len(value)} keys, context omitted}}"
        out = ", ".join(f"{k}={_compact(v, 40)}" for k, v in list(value.items())[:6])
        return "{" + out + "}"
    if isinstance(value, list):
        return f"[{len(value)} items]"
    s = str(value)
    return s[:limit] + ("…" if len(s) > limit else "")


_ENGINE_TRACE = os.environ.get("SASE_ENGINE_TRACE") == "1"


# ------------------------------------------------- human auth helpers ----
# Phase 2 token-flow migration (M1/M2/M3): additive only. Agents NEVER use
# these — they act under agent:/ci: identities on non-human endpoints.
# These exist for humans/tools that call HUMAN gates (spec validate,
# MRP human-decision, VCR) so printed instructions and scripted calls can
# move to bearer tokens before SASE_REQUIRE_HUMAN_TOKEN is enabled.

def human_curl_auth(name: str | None = None) -> str:
    """
    curl header fragment for human gates. Prefers the token flow when
    SASE_HUMAN_TOKEN is set; falls back to the legacy X-Acting-As header
    (still valid while SASE_REQUIRE_HUMAN_TOKEN is unset).
    """
    token = os.environ.get("SASE_HUMAN_TOKEN")
    if token:
        return f"-H 'Authorization: Bearer {token}'"
    who = name or os.environ.get("SASE_HUMAN_NAME", "m.barani")
    return f"-H 'X-Acting-As: human:{who}'"


def print_human_auth_hint(base_url: str = "http://localhost:8000") -> None:
    """Printed alongside gate instructions so humans know both paths."""
    print("Human identity options:\n"
          "  a) Token flow (required once SASE_REQUIRE_HUMAN_TOKEN=1):\n"
          f"     curl -X POST {base_url}/auth/login \\\n"
          "       -H 'Content-Type: application/json' \\\n"
          "       -d '{\"username\":\"<you>\",\"password\":\"...\"}'\n"
          "     -> then send: -H 'Authorization: Bearer <token>'\n"
          "  b) Legacy header (works until the flag flips):\n"
          "     -H 'X-Acting-As: human:<name>'")


class EngineClient:
    def __init__(self, base_url: str = "http://localhost:8000",
                 role: RolePolicy | None = None,
                 ci_token: str | None = None,
                 bearer_token: str | None = None,
                 timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.role = role
        self.ci_token = ci_token
        # Phase 2 (M3): optional bearer for HUMAN-gate calls made through
        # an unbound client (scripts/tooling). Role-bound agents ignore it.
        self.bearer_token = bearer_token or os.environ.get("SASE_HUMAN_TOKEN")
        self.timeout = timeout

    # -- policy ---------------------------------------------------------
    def _assert_allowed(self, method: str, path: str) -> None:
        """
        Exact-path match by default; a trailing '*' grants the subtree; a
        mid-path '*' matches exactly one path segment (e.g. the verifier's
        'POST /verification-requests/*/complete'). Wildcards must be explicit
        so 'POST /specs' can never silently cover 'POST /specs/{id}/validate'
        (human-only). This is client-side convenience only — the server
        enforces the real gates regardless.
        """
        if self.role is None:
            return  # unbound client (scripts/tests) — server still enforces
        for m, pattern in self.role.allow:
            if m != method:
                continue
            if pattern.endswith("*"):
                if path.startswith(pattern[:-1]):
                    return
            elif "*" in pattern:
                # mid-path wildcard: one path segment (never the empty string,
                # never '/' — so '/*/complete' cannot match '/complete').
                rx = re.compile(
                    "^" + re.escape(pattern).replace(r"\*", r"[^/]+") + "$")
                if rx.match(path):
                    return
            elif path == pattern:
                return
        raise PolicyViolation(
            f"{self.role.identity} is not allowed to {method} {path}. "
            f"Allowed: {[f'{m} {p}' for m, p in self.role.allow]}"
        )

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Content-Type": "application/json"}
        if self.role is not None:
            h["X-Acting-As"] = self.role.identity
        if self.ci_token:
            h["X-CI-Token"] = self.ci_token
        if self.bearer_token:
            h["Authorization"] = f"Bearer {self.bearer_token}"
        if extra:
            h.update(extra)
        return h

    # -- transport ------------------------------------------------------
    def request(self, method: str, path: str, payload: dict | None = None,
                ok: tuple[int, ...] = (200, 201),
                extra: dict | None = None) -> dict:

        method = method.upper()
        self._assert_allowed(method, path)
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data,
            headers=self._headers(extra), method=method)
        actor = self.role.identity if self.role else "unbound"
        if _ENGINE_TRACE:
            print(f"[comms] {actor} -> {method} {path}"
                  + (f"  payload={_compact(payload)}" if payload is not None else ""),
                  flush=True)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode()
                result = json.loads(body) if body else {}
                if _ENGINE_TRACE:
                    print(f"[comms] {actor} <- HTTP {resp.status} "
                          f"{_compact(result)}", flush=True)
                return result
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:500]
            if _ENGINE_TRACE:
                print(f"[comms] {actor} <- HTTP {e.code} {detail[:200]}",
                      flush=True)
            raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {detail}") from e

    # -- sugar ----------------------------------------------------------
    def get(self, path: str) -> dict:
        return self.request("GET", path)

    def post(self, path: str, payload: dict) -> dict:
        return self.request("POST", path, payload)

    def patch(self, path: str, payload: dict, extra: dict | None = None) -> dict:
        return self.request("PATCH", path, payload, extra=extra)

# -- will be done if we needed any updatable option

    # def option(self, path: str, payload: dict,
    #            extra: dict | None = None) -> dict:
    #     return self.request("OPTION", path, payload, extra=extra)
