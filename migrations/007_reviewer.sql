-- Migration 007: independent Reviewer review record (Phase 2 I3, gate G8).
--
-- G8 (ADR-002 Separation of Duties, Reviewer / I3) adds a genuinely separate
-- agent:reviewer authority. It is ADVISORY-ONLY: it may write only its own
-- review fields (ai_review_status, ai_review_notes, ai_review_findings)
-- through the dedicated PATCH /mrps/{id}/review endpoint, and it NEVER
-- approves merges, writes verification evidence, touches code, or mutates
-- agent runs.
--
-- ai_review_findings complements the previously-added ai_review_status /
-- ai_review_notes columns with STRUCTURED review findings (severity, file,
-- line, message) so reflection/review is analyzable rather than a note blob.
--
-- APPLY MANUALLY on existing volumes:
--   docker exec -i ai-swe-engine-postgres-1 psql -U sase -d sase < migrations/007_reviewer.sql

ALTER TABLE mrps ADD COLUMN IF NOT EXISTS ai_review_findings jsonb;
