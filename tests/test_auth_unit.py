"""
Phase 2 human-identity unit tests — DB-free (pure crypto + fake sessions).

Covers: password hashing/verification, token issue/resolve semantics,
and the require_human_actor decision table including bearer-token
priority and SASE_REQUIRE_HUMAN_TOKEN fail-closed mode.

Run: pytest tests/test_auth_unit.py   (no Postgres needed)
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import models
from api.authn import (
    hash_password,
    issue_token,
    resolve_bearer,
    verify_password,
)
from api.security import require_human_actor


# --------------------------------------------------------- passwords ----

def test_password_hash_roundtrip():
    stored = hash_password("s3cret!")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("s3cret!", stored)
    assert not verify_password("wrong", stored)


def test_password_hash_is_salted():
    assert hash_password("same") != hash_password("same")


@pytest.mark.parametrize("bad", ["", "garbage", "pbkdf2_sha256$x$y",
                                 "plain$200000$ab$cd", None])
def test_verify_password_malformed_stored_value_fails(bad):
    assert not verify_password("pw", bad)


def test_verify_password_never_raises_on_none():
    # None password must not crash — treated as failure.
    assert not verify_password(None, hash_password("x"))


# -------------------------------------------------- fake db for tokens ----

class _FakeDb:
    """Minimal Session stand-in: get(Model, pk) backed by dicts."""

    def __init__(self):
        self.objects = {}
        self.added = []
        self.commits = 0

    def seed(self, *objs):
        self._index(objs)

    def _index(self, objs):
        for o in objs:
            pk = o.username if isinstance(o, models.User) else o.token_hash
            self.objects[(type(o), pk)] = o

    def get(self, model, pk):
        return self.objects.get((model, pk))

    def add(self, obj):
        self.added.append(obj)
        self._index([obj])

    def commit(self):
        self.commits += 1


def _user(name="m.barani", active=True):
    return models.User(username=name, display_name=name,
                       password_hash=hash_password("pw"), is_active=active)


def _token(raw="a" * 64, username="m.barani", revoked=False,
           expires=None):
    import hashlib
    th = hashlib.sha256(raw.encode()).hexdigest()
    return models.ApiToken(token_hash=th, username=username,
                           revoked=revoked, expires_at=expires)


RAW = "b" * 64


def test_issue_token_stores_only_sha256():
    db = _FakeDb()
    raw, exp = issue_token(db, "m.barani", ttl_hours=1)
    assert len(raw) == 64 and exp is not None
    tok = db.added[-1]
    assert tok.token_hash != raw                      # raw never stored
    assert tok.token_hash == __import__("hashlib").sha256(
        raw.encode()).hexdigest()
    assert tok.username == "m.barani"


def test_resolve_bearer_happy_path():
    db = _FakeDb()
    db.seed(_user(), _token(RAW))
    assert resolve_bearer(db, f"Bearer {RAW}") == "m.barani"


@pytest.mark.parametrize("header", [None, "", "Basic abc", "Bearer ",
                                    f"Bearer {'c' * 64}"])
def test_resolve_bearer_rejects_bad_headers(header):
    db = _FakeDb()
    db.seed(_user(), _token(RAW))
    assert resolve_bearer(db, header) is None


def test_resolve_bearer_rejects_revoked_expired_inactive():
    expired = datetime.now(timezone.utc) - timedelta(hours=1)
    for tok in (_token(RAW, revoked=True),
                _token(RAW, expires=expired)):
        db = _FakeDb()
        db.seed(_user(), tok)
        assert resolve_bearer(db, f"Bearer {RAW}") is None
    db = _FakeDb()
    db.seed(_user(active=False), _token(RAW))
    assert resolve_bearer(db, f"Bearer {RAW}") is None


# --------------------------------------- require_human_actor decisions ----

def run_dep(monkeypatch, *, x_acting_as=None, authorization=None,
            require_flag=None, fake_db=None):
    monkeypatch.setenv("SASE_REQUIRE_HUMAN_TOKEN", require_flag or "")
    return require_human_actor(x_acting_as=x_acting_as,
                               authorization=authorization,
                               db=fake_db or _FakeDb())


def test_legacy_header_path_unchanged_without_token(monkeypatch):
    assert run_dep(monkeypatch, x_acting_as="human:m.barani") == "human:m.barani"
    with pytest.raises(HTTPException) as e:
        run_dep(monkeypatch, x_acting_as="agent:coder")
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        run_dep(monkeypatch)
    assert e.value.status_code == 401


def test_valid_bearer_yields_authoritative_identity(monkeypatch):
    db = _FakeDb()
    db.seed(_user(), _token(RAW))
    got = run_dep(monkeypatch, x_acting_as="human:someone.else",
                  authorization=f"Bearer {RAW}", fake_db=db)
    # Token identity WINS over a spoofable header value.
    assert got == "human:m.barani"


def test_invalid_bearer_rejected_even_with_valid_header(monkeypatch):
    db = _FakeDb()
    db.seed(_user(), _token(RAW))
    with pytest.raises(HTTPException) as e:
        run_dep(monkeypatch, x_acting_as="human:m.barani",
                authorization=f"Bearer {'d' * 64}", fake_db=db)
    assert e.value.status_code == 401


def test_require_token_mode_closes_header_path(monkeypatch):
    with pytest.raises(HTTPException) as e:
        run_dep(monkeypatch, x_acting_as="human:m.barani",
                require_flag="1")
    assert e.value.status_code == 401
    assert "SASE_REQUIRE_HUMAN_TOKEN" in e.value.detail


def test_require_token_mode_still_accepts_valid_bearer(monkeypatch):
    db = _FakeDb()
    db.seed(_user(), _token(RAW))
    got = run_dep(monkeypatch, authorization=f"Bearer {RAW}",
                  require_flag="1", fake_db=db)
    assert got == "human:m.barani"
