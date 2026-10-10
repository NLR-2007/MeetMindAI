"""Google sign-in through Firebase.

The risk here is accepting a token that was never really issued by Google,
or one issued for a different Firebase project. Most of these tests are
about refusing things.
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.models import User
from app.services import firebase_auth
from app.services.security import hash_password


@pytest.fixture(autouse=True)
def _project_configured(monkeypatch):
    monkeypatch.setattr(get_settings(), "firebase_project_id", "sayvia-nlr-ai")


def _claims(email: str = "new@example.com", name: str = "New Person") -> dict:
    return {"email": email, "name": name, "sub": "uid-123"}


def test_first_sign_in_creates_the_account(client, db, monkeypatch) -> None:
    monkeypatch.setattr(
        firebase_auth, "verify_id_token", lambda token, project: _claims()
    )
    import app.routers.auth as auth_router

    monkeypatch.setattr(auth_router, "verify_id_token", lambda t, p: _claims())

    resp = client.post("/auth/google", json={"id_token": "x" * 40})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["email"] == "new@example.com"
    assert body["access_token"]

    created = db.scalar(
        __import__("sqlalchemy").select(User).where(User.email == "new@example.com")
    )
    assert created is not None
    # A Google account has no password at all.
    assert created.password_hash is None
    # Seeded so a name spoken in a meeting can match this person immediately.
    assert "New Person" in (created.display_names or [])


def test_signing_in_again_reuses_the_same_account(client, db, monkeypatch) -> None:
    import app.routers.auth as auth_router

    monkeypatch.setattr(auth_router, "verify_id_token", lambda t, p: _claims())

    first = client.post("/auth/google", json={"id_token": "x" * 40}).json()
    second = client.post("/auth/google", json={"id_token": "x" * 40}).json()
    assert first["user_id"] == second["user_id"]
    rows = db.query(User).filter(User.email == "new@example.com").all()
    assert len(rows) == 1


def test_an_existing_password_account_can_also_use_google(client, db, monkeypatch) -> None:
    """Same email, same person — signing in with Google must not duplicate them."""
    existing = User(
        email="both@example.com",
        name="Both Ways",
        role="employee",
        password_hash=hash_password("a-real-password"),
    )
    db.add(existing)
    db.commit()

    import app.routers.auth as auth_router

    monkeypatch.setattr(
        auth_router, "verify_id_token", lambda t, p: _claims("both@example.com", "Both Ways")
    )
    resp = client.post("/auth/google", json={"id_token": "x" * 40})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == existing.id
    # Their password still works; Google sign-in did not wipe it.
    db.expire_all()
    assert db.get(User, existing.id).password_hash is not None


def test_a_google_only_account_cannot_be_logged_into_with_a_password(
    client, db, monkeypatch
) -> None:
    """No password set must mean no password works — not 'any password works'."""
    import app.routers.auth as auth_router

    monkeypatch.setattr(auth_router, "verify_id_token", lambda t, p: _claims())
    client.post("/auth/google", json={"id_token": "x" * 40})

    for attempt in ["", "password", "anything at all"]:
        resp = client.post(
            "/auth/login", json={"email": "new@example.com", "password": attempt}
        )
        assert resp.status_code in (401, 422), attempt


def test_a_rejected_token_is_a_401(client, db, monkeypatch) -> None:
    import app.routers.auth as auth_router

    def _reject(token, project):
        raise firebase_auth.FirebaseAuthError("Could not verify that Google sign-in.")

    monkeypatch.setattr(auth_router, "verify_id_token", _reject)
    resp = client.post("/auth/google", json={"id_token": "x" * 40})
    assert resp.status_code == 401
    assert "verify" in resp.json()["detail"].lower()


def test_a_disabled_account_is_refused(client, db, monkeypatch) -> None:
    db.add(
        User(
            email="off@example.com",
            name="Disabled",
            role="employee",
            is_active=False,
        )
    )
    db.commit()
    import app.routers.auth as auth_router

    monkeypatch.setattr(
        auth_router, "verify_id_token", lambda t, p: _claims("off@example.com", "Disabled")
    )
    assert client.post("/auth/google", json={"id_token": "x" * 40}).status_code == 403


# --- the verifier itself --------------------------------------------------


def test_verification_is_refused_when_no_project_is_configured() -> None:
    """Without a project id, any Firebase project's token would be accepted."""
    with pytest.raises(firebase_auth.FirebaseAuthError) as exc:
        firebase_auth.verify_id_token("whatever", "")
    assert "FIREBASE_PROJECT_ID" in str(exc.value)


def test_a_forged_token_is_rejected() -> None:
    """An unsigned token with the right shape must not get through.

    This is the attack the whole endpoint exists to stop: anyone can write
    these claims, so the signature is the only thing that matters.
    """
    import jwt as pyjwt

    forged = pyjwt.encode(
        {
            "email": "attacker@example.com",
            "sub": "uid",
            "aud": "sayvia-nlr-ai",
            "iss": "https://securetoken.google.com/sayvia-nlr-ai",
            "exp": 9999999999,
            "iat": 1,
        },
        "not-googles-key",
        algorithm="HS256",
    )
    with pytest.raises(firebase_auth.FirebaseAuthError):
        firebase_auth.verify_id_token(forged, "sayvia-nlr-ai")


def test_a_token_without_an_email_is_rejected(monkeypatch) -> None:
    """MeetMind identifies people by email; a token without one is unusable."""
    monkeypatch.setattr(
        firebase_auth.jwt, "decode", lambda *a, **k: {"sub": "uid", "exp": 1}
    )
    monkeypatch.setattr(
        firebase_auth, "_client", lambda: type("K", (), {"get_signing_key_from_jwt": staticmethod(lambda t: type("S", (), {"key": "k"})())})()
    )
    with pytest.raises(firebase_auth.FirebaseAuthError) as exc:
        firebase_auth.verify_id_token("token", "sayvia-nlr-ai")
    assert "email" in str(exc.value).lower()
