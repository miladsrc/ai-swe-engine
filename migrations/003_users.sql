-- Migration 003: human identity (Phase 2, additive).
-- Users + API tokens. No existing table is altered.
--
-- APPLY NOTE: migrations in initdb.d only run on an EMPTY volume. For an
-- existing deployment apply manually:
--   docker exec -i ai-swe-engine-postgres-1 psql -U sase -d sase < migrations/003_users.sql

CREATE TABLE IF NOT EXISTS users (
    username      TEXT PRIMARY KEY,          -- canonical, lowercased
    display_name  TEXT,
    password_hash TEXT NOT NULL,             -- pbkdf2_sha256$iter$salt$hash
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS api_tokens (
    token_hash   TEXT PRIMARY KEY,           -- sha256(raw); raw never stored
    username     TEXT NOT NULL REFERENCES users(username),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ,
    revoked      BOOLEAN NOT NULL DEFAULT FALSE,
    last_used_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_api_tokens_username ON api_tokens(username);
