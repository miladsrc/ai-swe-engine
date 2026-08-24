"""
SASE agent layer (roadmap step 5, v0).

Each agent is a SEPARATE identity talking to the traceability backbone.
Separation is enforced in code by an endpoint allowlist per role
(agents/config.py): a role literally cannot call an endpoint outside its
mandate, mirroring the paper's rule that e.g. the reviewer is not the
coder and no agent performs human decisions.

Human-only actions (spec validation, VCR, merge) have no agent binding at
all — the server rejects any 'agent:' identity on those endpoints.
"""

from agents.config import ROLES, RolePolicy
from agents.engine_client import EngineClient, PolicyViolation

__all__ = ["ROLES", "RolePolicy", "EngineClient", "PolicyViolation"]
