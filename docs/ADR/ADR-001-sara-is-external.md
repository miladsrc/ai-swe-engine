# ADR-001: Sara is External to the Engine

## Date
2026-08-25

## Context

The ai-swe-engine needs a clear architectural boundary between development-time assistance (Sara) and run-time operation. Without this boundary, there is a risk of coupling the engine to an external AI assistant, violating the air-gap requirement.

## Decision

Sara is an external, advisory-only entity with zero execution rights in the engine. The engine must function completely independently of Sara at runtime.

## Alternatives Considered

1. Sara as a runtime component (rejected - violates air-gap, creates dependency)
2. Sara as an optional plugin (rejected - still creates coupling risk)
3. Sara as external advisor only (accepted - clean separation)

## Consequences

- The engine can be deployed and operated without Sara
- Sara can only influence the engine through code changes (development-time)
- No runtime interface exists between Sara and the engine
- The engine must be self-documenting (Sara cannot be relied upon for runtime knowledge)

## Approval Status

APPROVED - by m.barani (2026-08-25)