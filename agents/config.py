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
        # Phase 2 I3 (G8): coder and reviewer use DIFFERENT model families to
        # reduce correlated review errors (generation vs independent review).
        # Use the qwen2.5-coder:7b family (code-specialized, proven on this
        # CPU-only Ollama); 14b returns empty/hangs on multi-file generation
        # here, so it is NOT a reliable offline coder.
        model="qwen2.5-coder:7b",
        # POST /mrps: the coder opens the Merge Request package for the
        # code it produced (§3.7.8 requires every generated change to be
        # traceable to an agent run; the MRP is how it enters review).
        # Step 2B: the Orchestrator (driving this client) enqueues an
        # immutable verification request and polls non-secret status. It
        # cannot claim/complete — those are verifier-only.
        allow=_allow("GET /specs*", "POST /agent-runs", "PATCH /agent-runs*",
                     "POST /crps", "POST /mrps",
                     "POST /verification-requests",
                     "GET /verification-requests*"),
    ),
    "reviewer": RolePolicy(
        name="Reviewer Agent (independent, advisory)",
        identity="agent:reviewer",
        # G8 (ADR-002 SoD, Reviewer/I3): a DIFFERENT model family from the
        # coder so a correlated error on the coder's model is not repeated in
        # review. Advisory only — it never approves a merge.
        model="deepseek-r1:8b",
        # Strict allowlist (SoD requirement 2):
        #   READ  = specs, agent runs, MRPs, verification requests, evidence,
        #           traceability (all read-only context a reviewer needs).
        #   WRITE = ONLY PATCH /mrps/*/review (its own review fields). The
        #           generic PATCH /mrps* evidence path is NOT granted, so a
        #           reviewer cannot write verification evidence, and PATCH
        #           /agent-runs* is NOT granted, so it cannot mutate runs.
        allow=_allow("GET /specs*", "GET /agent-runs*", "GET /mrps*",
                     "GET /verification-requests*", "GET /evidence*",
                     "GET /traceability*",
                     "PATCH /mrps/*/review"),
    ),
    "critic": RolePolicy(
        name="Reflection / Critic Agent",
        identity="agent:critic",
        # Phase 2 I3 reflection refactor: reflection/review is SEPARATED from
        # generation (boundaries: Generator/Coder, Reflection/Critic,
        # Reviewer, Verifier). The Critic ANALYZES a run's output and produces
        # STRUCTURED feedback — it does not generate code and does not write
        # verification evidence. Its only write is advisory review feedback on
        # the MRP; the orchestrator (controlled orchestration) decides what to
        # feed back to the coder. Same reviewer-family model (advisory).
        model="deepseek-r1:8b",
        allow=_allow("GET /agent-runs*", "GET /mrps*", "GET /specs*",
                     "GET /evidence*", "GET /traceability*",
                     "PATCH /mrps/*/review"),
    ),
    "test_runner": RolePolicy(
        name="Test Runner (CI)",
        identity="ci:test-runner",
        model=None,
        allow=_allow("PATCH /mrps*"),  # evidence only, via X-CI-Token
    ),
    # Phase 2 SoD (Step 2) — the Independent Verifier boundary. Runs as a
    # separate OS subprocess (python -m agents.verifier) with its OWN
    # credential (SASE_VERIFIER_TOKEN, separate from the shared SASE_CI_TOKEN).
    # It is the ONLY authority allowed to write TRUSTED verification evidence
    # in strict mode. LLM-free: it records real test/scan/lint exit codes.
    "verifier": RolePolicy(
        name="Verifier Agent (independent)",
        identity="ci:verifier",
        model=None,
        # Step 2B runner mode: claim + complete pending verification requests.
        allow=_allow("GET /specs*", "GET /agent-runs*",
                     "GET /mrps*", "PATCH /mrps*",
                     "POST /verification-requests/claim-next",
                     "POST /verification-requests/*/complete"),
    ),
    "designer": RolePolicy(
        name="Designer Agent",
        identity="agent:designer",
        model="qwen2.5-coder:7b",
        # Designer generates DESIGN.md and frontend code, references
        # blueprints and specs, records agent runs.
        allow=_allow("GET /specs*", "GET /blueprints*",
                     "POST /agent-runs", "PATCH /agent-runs*",
                     "POST /mrps"),
    ),
}
