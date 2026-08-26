# HUMAN IDENTITY — Interstitial Security Milestone (COMPLETE)

> **Objective:** Give every human gate real, non-forgeable authentication without changing the engine architecture.
> **Current status:** COMPLETE (2026-08-26). Strict enforcement flag available but deliberately OFF.
> **Owner:** m.barani
> **Created date:** 2026-08-26
> **Last update:** 2026-08-26
> **Phase:** Interstitial (approved workstream between Phase 1 and Master-Plan Phase 2 — NOT Master-Plan Phase 2, which is Separation of Duties and remains Planned)
> **Dependencies:** Phase 1 (gates + audit trail)
> **Tests:** tests/test_auth_unit.py (21 DB-free) + live token-flow gate trio in test_traceability_chain.py
> **Evidence:** Commits 3e0d294 (identity), a2ed450/8e08cc1 (migration); live verification on compose stack
> **Completion criteria:** Valid token authenticates all human gates; invalid token rejected; spoofed headers cannot override token identity — all proven live
> **Future improvements:** Enable SASE_REQUIRE_HUMAN_TOKEN; rate limiting; refresh tokens; OIDC/mTLS

---

## 1. Implemented features

### Data model (migration `003_users.sql`, mirrored in `api/models.py`)
| Table | Columns | Notes |
|---|---|---|
| `users` | username (PK), display_name, password_hash, is_active, created_at | Human-only by construction |
| `api_tokens` | token_hash (PK), username FK, created_at, expires_at, revoked, last_used_at | sha256 of raw token; **raw shown once at login, never stored** |

### Password hashing
PBKDF2-HMAC-SHA256 via stdlib `hashlib` — 200,000 iterations (env `SASE_PBKDF2_ITERATIONS`), per-user random salt, constant-time verification (`hmac.compare_digest`). Format: `pbkdf2_sha256$<iter>$<salt_hex>$<hash_hex>`.

### Token storage model
Raw token = `secrets.token_hex(32)` (64 hex chars). Only `sha256(raw)` is persisted — a database leak yields no usable credentials. TTL default 72h (`SASE_TOKEN_TTL_HOURS`, 0 = no expiry); revocation supported.

### `POST /auth/login`
Password check → issues bearer token. Success AND failure are audited (`login_success` / `login_failed`). Unknown-user logins verify against a placeholder hash so response timing does not reveal account existence.

### `GET /auth/me`
Resolves a presented bearer token to `{username, display_name, actor_id: "human:<username>"}`. 401 on missing/invalid token.

### Bearer authentication & human-gate identity resolution
Implemented inside the EXISTING seam (`require_human_actor`, `api/security.py`) — no new auth layer:

1. `Authorization: Bearer <token>` present → resolved against `api_tokens`/`users`; valid → returns **authoritative** `human:<username>`; any `X-Acting-As` header value is IGNORED.
2. Invalid/expired/revoked token or inactive user → **401**.
3. No bearer + `SASE_REQUIRE_HUMAN_TOKEN` set → **401 fail-closed**.
4. No bearer + flag unset → legacy `X-Acting-As: human:` prefix check (default; unchanged behavior).

Agents are structurally unaffected: they act under `agent:`/`ci:` identities on non-human endpoints and cannot obtain tokens (issuance requires a password check).

### Audit trail behavior
Login attempts audited; every human decision made under a token records the authoritative identity (proven live: audit shows `human:m.barani`, never a spoofed header value).

### X-Acting-As legacy status
Still accepted ONLY while `SASE_REQUIRE_HUMAN_TOKEN` is unset. Remaining legitimate usages after full migration: negative rejection tests, credential-less E2E fallback (dead at flip), historical changelog sections.

### `SASE_REQUIRE_HUMAN_TOKEN` status
**OFF by owner decision.** Zero technical blockers remain. Flipping it makes token auth mandatory at every G5 gate with no code change.

## 2. Approved but not implemented
- P6-B enforced plan-before-write approval gate (design only: docs/P6_A_PLAN_BEFORE_WRITE_DESIGN.md)
- P9 evidence-export endpoint lockdown (actor dependency + real caller recording)
- Rate limiting on `/auth/login`

## 3. Future roadmap items (not approved, not scheduled)
- Refresh tokens / session management
- OIDC / mTLS federation (replaces shared-secret and local password model at scale)
- Password reset flow, account admin UI
- Prompt registry (so AgentRun provenance hashes reference governed prompt rows instead of code history)
