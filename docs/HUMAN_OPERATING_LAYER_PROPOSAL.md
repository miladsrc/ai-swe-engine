# Platform UI / Human Operations Layer — Architectural Preparation

> **Status:** DEFERRED by owner decision (2026-08-26). Placed on the roadmap as
> **Phase 9 — Platform UI / Human Operations Layer** (see MASTER_PLAN.md §3).
> NOT approved for implementation now. No migrations, tables, endpoints, or UI
> may be built from this document until Phase 9 begins.
> **Reason:** priority is core engine capability, governance model, and the
> autonomous engineering workflow; a full frontend product effort must not be
> mixed into backend governance milestones.
> **Owner:** m.barani · **Created:** 2026-08-26 · **Last update:** 2026-08-26

This document preserves the architectural preparation so the eventual frontend
phase starts from recorded decisions instead of archaeology.

## 1. Required concepts (must be honored by any future implementation)

| Concept | Recorded design direction |
|---|---|
| **Users** | Existing `users` table (migration 003) stays the identity source; no second identity system |
| **Roles** | `users.role` enum proposed: admin, product_owner, reviewer, engineer, observer; enforced via a `require_role(...)` dependency wrapping `require_human_actor` |
| **Assignments** | `artifact_assignments` table routing artifacts to users by purpose (`validate_spec`, `review_mrp`, `resolve_crp`) with open/done/superseded lifecycle |
| **Approvals** | Decisions continue through EXISTING gated endpoints only (spec validate, MRP human-decision, VCR); self-approval guard: approver ≠ creator of the originating run |
| **Notifications** | Derived from `audit_log` + `assignments` queries — never a separate notification store (audit remains single source of truth) |
| **Artifact ownership** | PRD `created_by`, spec `human_validated_by`, MRP `human_reviewer` become forward-looking via assignments; historical labels unchanged |
| **Review workflows** | CRP.required_role must be validated against real users' roles at decision time |
| **Evidence visualization** | `/traceability/chain` + `/evidence/run` are the data sources for timeline views; evidence context JSONB carries diffs/test output |

## 2. Scope of the future phase (from owner directive)

Complete management dashboard · per-user workspace · approval center ·
MRP/CRP/VCR review screens · evidence timeline visualization · agent status
monitoring · project workspace · requirement creation wizard · team management ·
notifications · role and permission management.

## 3. Known constraints carried forward

- Pipeline-start API was deliberately deferred until Master-Plan Phase 2
  (Separation of Duties) makes execution orchestrator-owned — spawning agents
  from a UI earlier would reintroduce self-attestation.
- The interim dashboard (`static/ui/`) remains the operating surface until this
  phase; it is a pure client layer and sets no precedent that constrains the
  future application.
- Strict token mode (`SASE_REQUIRE_HUMAN_TOKEN`) should ideally be enabled
  before multi-user features are layered on top.

## 4. Prerequisites before starting Phase 9

1. Phases 1–4 stable (governance integrity proven, execution orchestrator-owned).
2. Role model agreed and migration designed against real team shape.
3. Evidence completeness: file contents/diffs persisted where the UI must show them.
