"""
Role definitions for the SASE agent layer.

Every agent gets:
  identity      — the actor id it presents to the engine (X-Acting-As)
  allow         — the ONLY (method, path-prefix) pairs it may call;
                  anything else raises PolicyViolation client-side
                  *before* a request is ever sent.
  model         — local Ollama model used by this role in v0.

Design notes:
  - No 'human' role exists here on purpose. Human decisions are made by
    humans (X-Acting-As: human:<name>), enforced server-side
    (api/security.py). An agent that wants a human decision must stop
    and ask — there is no code path around it.
  - ci:test-runner is deliberately LLM-free (no model): test evidence is
    recorded by a real pytest process, never judged into existence.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RolePolicy:
    name: str
    identity: str
    model: str | None            # None => this role never calls an LLM
    allow: tuple[tuple[str, str], ...] = field(default_factory=tuple)


def _allow(*pairs: str) -> tuple[tuple[str, str], ...]:
    """('POST', '/prds'), ... -> normalized tuples."""
    out = []
    for pair in pairs:
        method, _, path = pair.partition(" ")
        out.append((method.upper().strip(), path.strip()))
    return tuple(out)


ROLES: dict[str, RolePolicy] = {
    "product": RolePolicy(
        name="Product Agent",
        identity="agent:product",
        model="qwen2.5-coder:7b",
        allow=_allow("GET /projects*", "POST /projects",
                     "POST /prds", "POST /user-stories",
                     "POST /acceptance-criteria"),
    ),
    "spec": RolePolicy(
        name="Specification Agent",
        identity="agent:spec",
        model="qwen2.5-coder:7b",
        # NOTE: POST /specs/{id}/validate is intentionally absent —
        # human-only per §3.5.
        allow=_allow("GET /specs*", "POST /specs"),
    ),
    "coder": RolePolicy(
        name="Coding Agent",
        identity="agent:coder",
        model="qwen2.5-coder:7b",
        allow=_allow("GET /specs*", "POST /agent-runs", "PATCH /agent-runs*",
                     "POST /crps"),
    ),
    "reviewer": RolePolicy(
        name="Reviewer Agent",
        identity="agent:reviewer",
        # v0: same weights as coder but a different identity+prompt and a
        # separate process; upgrade path is a second model family.
        model="qwen2.5-coder:7b",
        allow=_allow("GET /agent-runs*", "GET /mrps*", "PATCH /mrps*"),
    ),
    "reflection": RolePolicy(
        name="Reflection Agent",
        identity="agent:reflection",
        model="qwen2.5-coder:7b",
        allow=_allow("GET /agent-runs*", "PATCH /agent-runs*"),
    ),
    "test_runner": RolePolicy(
        name="Test Runner (CI)",
        identity="ci:test-runner",
        model=None,
        allow=_allow("PATCH /mrps*"),  # evidence only, via X-CI-Token
    ),
}
