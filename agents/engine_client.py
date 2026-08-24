"""
HTTP client for the traceability backbone, identity- and policy-aware.

Every call carries X-Acting-As from the role's identity. The allowlist is
checked BEFORE the request is sent, so a misbehaving agent cannot even
attempt an out-of-mandate call — the violation is raised locally and (in
future work) becomes a CRP/audit event rather than a silent bypass.
"""

import json
import urllib.error
import urllib.request

from agents.config import RolePolicy


class PolicyViolation(PermissionError):
    """A role tried to use an endpoint outside its mandate."""


class EngineClient:
    def __init__(self, base_url: str = "http://localhost:8000",
                 role: RolePolicy | None = None,
                 ci_token: str | None = None,
                 timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.role = role
        self.ci_token = ci_token
        self.timeout = timeout

    # -- policy ---------------------------------------------------------
    def _assert_allowed(self, method: str, path: str) -> None:
        """
        Exact-path match by default; a trailing '*' grants the subtree.
        Wildcards must be explicit so 'POST /specs' can never silently
        cover 'POST /specs/{id}/validate' (human-only). This is client-side
        convenience only — the server enforces the real gates regardless.
        """
        if self.role is None:
            return  # unbound client (scripts/tests) — server still enforces
        for m, pattern in self.role.allow:
            if m != method:
                continue
            if pattern.endswith("*"):
                if path.startswith(pattern[:-1]):
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
        if extra:
            h.update(extra)
        return h

    # -- transport ------------------------------------------------------
    def request(self, method: str, path: str, payload: dict | None = None,
                ok: tuple[int, ...] = (200, 201)) -> dict:
        method = method.upper()
        self._assert_allowed(method, path)
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data,
            headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:500]
            raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {detail}") from e

    # -- sugar ----------------------------------------------------------
    def get(self, path: str) -> dict:
        return self.request("GET", path)

    def post(self, path: str, payload: dict) -> dict:
        return self.request("POST", path, payload)

    def patch(self, path: str, payload: dict) -> dict:
        return self.request("PATCH", path, payload)
