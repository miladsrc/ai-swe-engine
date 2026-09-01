-- Migration 005: bind each MRP to the immutable git tree hash that the
-- orchestrator actually verified (Phase 2 SoD, gate G7).
--
-- G7 (docs/PHASES/PHASE-2.md §4) requires that an MRP only becomes
-- merge-ready when its evidence is owned by the orchestrator (runner ==
-- "orchestrator" in the audit execution_context) AND that evidence's
-- tree_hash exactly equals the bytes the MRP claims to merge. That
-- comparison needs a real column on mrps, not just JSONB in the audit log.
--
-- verified_tree_hash defaults to NULL so pre-existing / legacy MRPs are
-- unaffected: G7 only engages for MRPs created through the SoD strict
-- flow (SASE_SOD_MODE=strict), which always sets this value.
--
-- APPLY MANUALLY on existing volumes:
--   docker exec -i ai-swe-engine-postgres-1 psql -U sase -d sase < migrations/005_mrps_verified_tree_hash.sql

ALTER TABLE mrps ADD COLUMN IF NOT EXISTS verified_tree_hash text;
