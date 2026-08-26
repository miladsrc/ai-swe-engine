"""
Bootstrap script: create the first human user (or reset a password).

Usage:
    python scripts/create_user.py <username>            # prompts for password
    python scripts/create_user.py <username> "<name>"   # + display name

Runs against DATABASE_URL directly (default: localhost:5433). Applies
nothing to the schema — apply migrations/003_users.sql first (see file
header for the manual-apply command on existing volumes).
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api import models                     # noqa: E402
from api.authn import hash_password        # noqa: E402
from api.database import SessionLocal      # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: python scripts/create_user.py <username> [display name]")
    username = sys.argv[1].strip().lower()
    display_name = sys.argv[2] if len(sys.argv) > 2 else username

    # Non-interactive mode for scripted bootstraps (SASE_USER_PASSWORD).
    # Interactive getpass is preferred; the env var exists because CI and
    # agent shells have no TTY. Never echoed or logged.
    import os
    password = os.environ.get("SASE_USER_PASSWORD")
    if password:
        print(f"[auth] using SASE_USER_PASSWORD from environment")
        confirm = password
    else:
        password = getpass.getpass(f"Password for '{username}': ")
        confirm = getpass.getpass("Confirm password: ")
    if not password or password != confirm:
        sys.exit("Passwords empty or do not match.")

    db = SessionLocal()
    try:
        user = db.get(models.User, username)
        if user is None:
            user = models.User(username=username,
                               display_name=display_name,
                               password_hash=hash_password(password))
            db.add(user)
            action = "created"
        else:
            user.password_hash = hash_password(password)
            user.is_active = True
            action = "password reset for"
        db.commit()
        print(f"[auth] {action} user '{username}'")
    finally:
        db.close()


if __name__ == "__main__":
    main()
