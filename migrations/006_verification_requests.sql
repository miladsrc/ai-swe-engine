-- Migration 006: remote-verification request record (Step 2B).
--
-- The Orchestrator enqueues an IMMUTABLE verification request (run_id, mrp_id,
-- exact commit, worktree ref) and NEVER receives the verifier credential. A
-- separately-administered Verifier claims it atomically, writes trusted
-- evidence to the MRP as ci:verifier, and records completion here. The
-- Orchestrator only polls non-secret status.
--
-- Security properties enforced at the API layer (api/routers/verification_requests.py):
--   * idempotent by run_id  (UNIQUE constraint below)
--   * atomic claim          (UPDATE ... WHERE status='pending' RETURNING)
--   * TTL/expire fail-closed
--   * only the verifier may claim/complete; the orchestrator may create + read
--
-- DEV/CONTAINMENT ONLY: see docs/ADR/ADR-002. This table models the protocol;
-- it is not itself the credential boundary.
--
-- APPLY MANUALLY on existing volumes:
--   docker exec -i ai-swe-engine-postgres-1 psql -U sase -d sase < migrations/006_verification_requests.sql

CREATE TABLE IF NOT EXISTS verification_requests (
    id                  text PRIMARY KEY,
    run_id              text NOT NULL UNIQUE,          -- one logical request per run
    mrp_id              text NOT NULL,
    commit              text NOT NULL,                 -- EXACT pinned commit
    worktree_ref        text NOT NULL,
    status              text NOT NULL DEFAULT 'pending',  -- pending|running|passed|failed|expired|error
    created_at          timestamptz NOT NULL DEFAULT now(),
    started_at          timestamptz,
    completed_at        timestamptz,
    expires_at          timestamptz,                   -- TTL -> fail closed
    lease_expires_at    timestamptz,                   -- atomic-pickup lease
    lease_holder        text,                          -- ci:verifier that claimed it
    verified_tree_hash  text,                          -- authoritative hash (verifier-set)
    failure_reason      text
);
CREATE INDEX IF NOT EXISTS ix_verification_requests_status ON verification_requests (status);
CREATE INDEX IF NOT EXISTS ix_verification_requests_mrp_id ON verification_requests (mrp_id);
