---
id: BP-TEST-FULLSTACK-001
version: v1.0
scope: project:test-taskboard
approved_by: human:offline-runner
change_note: Validation blueprint for the offline blueprint->software lifecycle test
---

# Taskboard — Offline Full-Stack Web Application

A self-contained, fully-offline web application for managing team tasks, with a
browser frontend, a JSON backend API, authentication, a database, role-based
permissions, an automated test suite, and deployment instructions.

**Anything that would normally call the internet must be avoided.** The product
must run with the internet disconnected, using only the Python standard library
(python 3), pytest for tests, and SQLite for persistence. No CDN, no external
package installs, no cloud services.

## Product requirements

- Serve a browser UI (login screen + a task board) over HTTP on a local port.
- Provide a JSON API that the UI calls for authentication and task management.
- Persist users and tasks in a local SQLite database so data survives restarts.
- Two roles: `admin` (full control) and `member` (manages only their own tasks).
- Every sensitive/restricted action must be authorized server-side.

## Architecture

- `app.py` — entrypoint: HTTP server (stdlib `http.server`), request router for
  `/`, `/api/*`, `/static/*`-style static file serving, JSON body parsing, and
  a small session/token store.
- `store.py` — SQLite data-access layer (schema bootstrap, users + tasks
  queries), path configurable via `$STORE_PATH` env so tests can isolate a
  fresh database (`pytest tmp_path`).
- `static/index.html` + `static/app.js` — a clean, small vanilla-JS frontend with
  a login panel and a task board, calling the JSON API. No external assets.

## Database design

- `users(id INTEGER PK, username TEXT UNIQUE, password_hash TEXT, salt TEXT, role TEXT)`
- `tasks(id INTEGER PK, title TEXT, status TEXT, assignee TEXT, created_by TEXT,
   created_at TEXT)`

## API requirements

- `POST /api/login` `{username, password}` -> `200 {token}` or `401`.
- `GET  /api/me` (token) -> current user + role.
- `GET  /api/tasks` (token; member sees own, admin sees all).
- `POST /api/tasks` (token; member may create with themselves as assignee).
- `PATCH /api/tasks/{id}` (token; admin or the owner).
- `DELETE /api/tasks/{id}` (token; admin only).
- `GET  /api/health` -> `{"status":"ok"}`.
- Missing/invalid token -> `401`. Authorization failure -> `403`.
- Passwords never stored in plaintext (use `hashlib.pbkdf2_hmac` with a random
  salt).

## Frontend requirements

- Login form posts to `/api/login`, stores the token, loads the task board.
- Task board: list tasks, add a task, change status, delete (admin).
- Graceful error messages from the API (401 -> back to login).
- No inline secrets, no unsafe `innerHTML` from user input.

## Security requirements

- No `eval`/`exec`/`pickle`/`__import__`/`socket`/`os.system` on user input.
- Server-side authorization on every task mutation (never trust the client).
- Constant-time token comparison where applicable.

## Testing (must pass offline)

- `test_app.py` (pytest) covering:
  1. login success returns a token; wrong password and unknown user both -> 401.
  2. no/invalid token -> 401.
  3. member can create + list their own task, but cannot delete it (403).
  4. admin can delete any task.
  5. empty task title -> 400.
  6. persistence: task written with one `$STORE_PATH` is present on a fresh
     process using the same path.
- Every test uses an isolated temporary `$STORE_PATH` (pytest `tmp_path`).

## Deployment instructions

- `README.md` must document:
  - `python app.py` -> open `http://localhost:8001`.
  - `$PORT` to change the port, `$STORE_PATH` to relocate the DB.
  - `python -m pytest -q` to run the offline test suite.
  - Seeding an `admin` account on first run.
