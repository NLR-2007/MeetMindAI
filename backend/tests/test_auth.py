"""Authentication and tenant-isolation tests."""
from __future__ import annotations

from app.models import Meeting

GOOD_URL = "https://meet.google.com/abc-defg-hij"


def _seed(db, owner_id: str, bot_id: str) -> Meeting:
    m = Meeting(
        owner_id=owner_id,
        bot_id=bot_id,
        meeting_url=GOOD_URL,
        platform="google_meet",
        bot_name="MeetMind AI Notetaker",
        title="Private planning",
        status="done",
    )
    db.add(m)
    db.commit()
    return m


# --- the boundary itself ---------------------------------------------------


def test_protected_routes_reject_anonymous(anon_client) -> None:
    for method, path in [
        ("get", "/meetings"),
        ("post", "/meetings/join"),
        ("get", "/calendar"),
        ("get", "/calendar/deadlines"),
        ("get", "/auth/me"),
    ]:
        # GET takes no body; POST needs one to reach the auth dependency.
        resp = (
            anon_client.get(path)
            if method == "get"
            else anon_client.post(path, json={})
        )
        assert resp.status_code == 401, f"{method.upper()} {path} was not protected"


def test_forged_token_rejected(anon_client) -> None:
    anon_client.headers.update({"Authorization": "Bearer not.a.real.token"})
    assert anon_client.get("/meetings").status_code == 401


def test_health_stays_public(anon_client) -> None:
    """Liveness must not need a token, or monitoring cannot see the app."""
    assert anon_client.get("/health").status_code == 200


# --- registration and login ------------------------------------------------


def test_register_then_login(anon_client) -> None:
    reg = anon_client.post(
        "/auth/register",
        json={
            "email": "new@example.com",
            "password": "strongpass123",
            "name": "New",
            "role": "manager",
        },
    )
    assert reg.status_code == 201
    assert reg.json()["access_token"]

    login = anon_client.post(
        "/auth/login", json={"email": "new@example.com", "password": "strongpass123"}
    )
    assert login.status_code == 200


def test_duplicate_email_refused(anon_client) -> None:
    body = {
        "email": "dupe@example.com",
        "password": "strongpass123",
        "role": "manager",
    }
    assert anon_client.post("/auth/register", json=body).status_code == 201
    assert anon_client.post("/auth/register", json=body).status_code == 409


def test_login_does_not_reveal_whether_email_exists(anon_client) -> None:
    anon_client.post(
        "/auth/register",
        json={
            "email": "known@example.com",
            "password": "strongpass123",
            "role": "manager",
        },
    )
    wrong_pw = anon_client.post(
        "/auth/login", json={"email": "known@example.com", "password": "nope12345678"}
    )
    unknown = anon_client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "nope12345678"}
    )
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json()["detail"] == unknown.json()["detail"]


def test_short_password_refused(anon_client) -> None:
    resp = anon_client.post(
        "/auth/register", json={"email": "short@example.com", "password": "abc"}
    )
    assert resp.status_code == 422


def test_password_is_never_stored_in_clear(anon_client, db) -> None:
    from app.models import User

    anon_client.post(
        "/auth/register",
        json={
            "email": "hash@example.com",
            "password": "verysecret123",
            "role": "manager",
        },
    )
    user = db.query(User).filter_by(email="hash@example.com").one()
    assert user.password_hash and "verysecret123" not in user.password_hash


# --- isolation between users ----------------------------------------------


def test_history_shows_only_own_meetings(client, other_client, db, user) -> None:
    _seed(db, user.id, "bot_mine")
    assert len(client.get("/meetings").json()) == 1
    # The other user must not see it.
    assert other_client.get("/meetings").json() == []


def test_cannot_read_another_users_meeting(client, other_client, db, user) -> None:
    mine = _seed(db, user.id, "bot_secret")
    # 404 rather than 403: confirming existence is itself a disclosure.
    assert other_client.get(f"/meetings/{mine.id}").status_code == 404
    assert other_client.get(f"/meetings/{mine.id}/status").status_code == 404
    assert other_client.post(f"/meetings/{mine.id}/process").status_code == 404
    assert other_client.post(f"/meetings/{mine.id}/leave").status_code == 404


def test_cannot_chat_about_another_users_meeting(client, other_client, db, user) -> None:
    mine = _seed(db, user.id, "bot_chat_private")
    resp = other_client.post(
        f"/meetings/{mine.id}/chat", json={"message": "what was decided?"}
    )
    assert resp.status_code == 404
    assert other_client.get(f"/meetings/{mine.id}/chat").status_code == 404


def test_join_stamps_the_caller_as_owner(client, db, user) -> None:
    import httpx
    import respx

    from app.config import get_settings

    with respx.mock:
        respx.post(f"{get_settings().recall_api_base}/api/v1/bot/").mock(
            return_value=httpx.Response(201, json={"id": "bot_owned", "status_changes": []})
        )
        created = client.post(
            "/meetings/join",
            json={"meeting_url": GOOD_URL, "consent_acknowledged": True},
        ).json()

    meeting = db.get(Meeting, created["id"])
    assert meeting.owner_id == user.id


# --- team membership at sign-up -------------------------------------------


def test_employee_must_name_a_manager(anon_client) -> None:
    """An employee with no manager has no team, so nothing can be scoped."""
    resp = anon_client.post(
        "/auth/register",
        json={"email": "orphan@example.com", "password": "strongpass123"},
    )
    assert resp.status_code == 422
    assert "manager" in resp.text.lower()


def test_employee_manager_email_must_exist(anon_client) -> None:
    resp = anon_client.post(
        "/auth/register",
        json={
            "email": "lost@example.com",
            "password": "strongpass123",
            "manager_email": "nobody@example.com",
        },
    )
    assert resp.status_code == 400
    assert "No manager account" in resp.json()["detail"]


def test_employee_joins_the_named_managers_team(anon_client, db) -> None:
    from app.models import User

    anon_client.post(
        "/auth/register",
        json={
            "email": "lead@example.com",
            "password": "leadpass12345",
            "name": "Lead",
            "role": "manager",
        },
    )
    resp = anon_client.post(
        "/auth/register",
        json={
            "email": "member@example.com",
            "password": "memberpass123",
            "name": "Member",
            "manager_email": "lead@example.com",
        },
    )
    assert resp.status_code == 201

    lead = db.query(User).filter_by(email="lead@example.com").one()
    member = db.query(User).filter_by(email="member@example.com").one()
    assert member.manager_id == lead.id


def test_manager_cannot_report_to_a_manager(anon_client) -> None:
    resp = anon_client.post(
        "/auth/register",
        json={
            "email": "boss2@example.com",
            "password": "bosspass12345",
            "role": "manager",
            "manager_email": "someone@example.com",
        },
    )
    assert resp.status_code == 422
