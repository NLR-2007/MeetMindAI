"""Teams: one bot for the room, and nothing else shared.

The feature exists because four attendees previously meant four bots. What it
must NOT become is a visibility grant - so most of these tests are about what
a team member still cannot see or do.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import respx
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.models import CoachingNote, Commitment, TeamMembership, User
from app.services.security import create_access_token, hash_password

BOT_URL = "https://us-west-2.recall.ai/api/v1/bot/"
MEET = "https://meet.google.com/abc-defg-hij"


def _bot(bot_id: str) -> httpx.Response:
    return httpx.Response(
        201,
        json={
            "id": bot_id,
            "meeting_url": MEET,
            "bot_name": "MeetMind AI Notetaker",
            "status_changes": [{"code": "in_call_recording"}],
        },
    )


def _user(db, email: str, name: str) -> User:
    u = User(
        email=email,
        name=name,
        role="employee",
        password_hash=hash_password("averygoodpassword"),
    )
    db.add(u)
    db.flush()
    return u


def _client_for(u: User) -> TestClient:
    c = TestClient(app)
    c.headers.update(
        {"Authorization": f"Bearer {create_access_token(get_settings(), u.id, u.email)}"}
    )
    return c


# --- the core promise: one bot, many viewers ------------------------------


@respx.mock
def test_one_bot_serves_the_whole_team(client, db, user) -> None:
    colleague = _user(db, "akhil@example.com", "Akhil")
    db.commit()

    team = client.post("/teams", json={"name": "Platform"}).json()
    invite = client.post(f"/teams/{team['id']}/invites").json()

    mate = _client_for(colleague)
    joined = mate.post("/teams/join", json={"token": invite["token"]})
    assert joined.status_code == 200, joined.text
    assert joined.json()["id"] == team["id"]

    route = respx.post(BOT_URL).mock(return_value=_bot("bot_team_1"))
    first = client.post(
        "/meetings/join",
        json={
            "meeting_url": MEET,
            "consent_acknowledged": True,
            "title": "Weekly sync",
            "team_id": team["id"],
        },
    )
    assert first.status_code == 201, first.text
    assert first.json()["team_name"] == "Platform"
    assert route.call_count == 1

    # The colleague asking for the same call joins the existing recording
    # instead of putting a second bot in the room.
    second = mate.post(
        "/meetings/join",
        json={
            "meeting_url": MEET,
            "consent_acknowledged": True,
            "title": "Weekly sync",
            "team_id": team["id"],
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert route.call_count == 1, "a second bot was dispatched to the same call"

    # And both of them can read it.
    assert mate.get(f"/meetings/{first.json()['id']}").status_code == 200
    assert any(m["id"] == first.json()["id"] for m in mate.get("/meetings").json())


# --- what a team does NOT grant -------------------------------------------


@respx.mock
def test_joining_a_team_does_not_reveal_its_past_meetings(client, db, user) -> None:
    """The join cut-off. Without it, an invite hands over the whole history."""
    respx.post(BOT_URL).mock(return_value=_bot("bot_before"))
    team = client.post("/teams", json={"name": "History"}).json()
    before = client.post(
        "/meetings/join",
        json={
            "meeting_url": MEET,
            "consent_acknowledged": True,
            "title": "Before you arrived",
            "team_id": team["id"],
        },
    ).json()

    latecomer = _user(db, "late@example.com", "Late")
    db.commit()
    invite = client.post(f"/teams/{team['id']}/invites").json()
    mate = _client_for(latecomer)
    mate.post("/teams/join", json={"token": invite["token"]})

    assert mate.get(f"/meetings/{before['id']}").status_code == 404
    assert mate.get("/meetings").json() == []


@respx.mock
def test_a_team_member_cannot_delete_someone_elses_meeting(client, db, user) -> None:
    colleague = _user(db, "other@example.com", "Other")
    db.commit()
    team = client.post("/teams", json={"name": "Shared"}).json()
    invite = client.post(f"/teams/{team['id']}/invites").json()
    mate = _client_for(colleague)
    mate.post("/teams/join", json={"token": invite["token"]})

    respx.post(BOT_URL).mock(return_value=_bot("bot_delete"))
    meeting = client.post(
        "/meetings/join",
        json={
            "meeting_url": MEET,
            "consent_acknowledged": True,
            "title": "Mine",
            "team_id": team["id"],
        },
    ).json()

    # Readable, but not destroyable: reading is not owning.
    assert mate.get(f"/meetings/{meeting['id']}").status_code == 200
    assert mate.delete(f"/meetings/{meeting['id']}").status_code == 404


@respx.mock
def test_team_membership_does_not_share_promises_or_coaching(client, db, user) -> None:
    """The line the whole feature rests on: the room is shared, work is not."""
    colleague = _user(db, "mate@example.com", "Mate")
    db.commit()
    team = client.post("/teams", json={"name": "Quiet"}).json()
    invite = client.post(f"/teams/{team['id']}/invites").json()
    mate = _client_for(colleague)
    mate.post("/teams/join", json={"token": invite["token"]})

    respx.post(BOT_URL).mock(return_value=_bot("bot_private"))
    meeting_id = client.post(
        "/meetings/join",
        json={
            "meeting_url": MEET,
            "consent_acknowledged": True,
            "title": "Shared call",
            "team_id": team["id"],
        },
    ).json()["id"]

    db.add(
        Commitment(
            owner_user_id=user.id,
            assigned_user_id=user.id,
            source_meeting_id=meeting_id,
            text="My private promise",
            status="pending",
        )
    )
    db.add(
        CoachingNote(
            owner_user_id=user.id,
            meeting_id=meeting_id,
            category="clarity",
            suggestion="Lead with the recommendation.",
            evidence="I think maybe",
            rejected=False,
        )
    )
    db.commit()

    assert mate.get("/promisemirror/commitments").json() == []
    assert mate.get("/progress").json()["totals"]["pending"] == 0
    assert mate.get("/coach/notes").json()["notes"] == []


def test_non_member_cannot_see_a_team_at_all(client, db, user, other_client) -> None:
    team = client.post("/teams", json={"name": "Secret"}).json()
    # 404, not 403: confirming the team exists is itself a disclosure.
    assert other_client.get(f"/teams/{team['id']}/members").status_code == 404
    assert other_client.post(f"/teams/{team['id']}/invites").status_code == 404
    assert other_client.get("/teams").json() == []


@respx.mock
def test_cannot_record_for_a_team_you_are_not_in(client, db, user, other_client) -> None:
    team = client.post("/teams", json={"name": "Theirs"}).json()
    route = respx.post(BOT_URL).mock(return_value=_bot("bot_nope"))
    resp = other_client.post(
        "/meetings/join",
        json={
            "meeting_url": MEET,
            "consent_acknowledged": True,
            "title": "Gatecrash",
            "team_id": team["id"],
        },
    )
    assert resp.status_code == 404
    assert not route.called, "a bot was dispatched for a team the caller is not in"


# --- invites are credentials ----------------------------------------------


def test_only_an_owner_can_invite_or_revoke(client, db, user) -> None:
    colleague = _user(db, "member@example.com", "Member")
    db.commit()
    team = client.post("/teams", json={"name": "Locked"}).json()
    invite = client.post(f"/teams/{team['id']}/invites").json()
    mate = _client_for(colleague)
    mate.post("/teams/join", json={"token": invite["token"]})

    assert mate.post(f"/teams/{team['id']}/invites").status_code == 403
    assert mate.post(f"/teams/{team['id']}/invites/revoke").status_code == 403


def test_a_revoked_invite_stops_working(client, db, user) -> None:
    outsider = _user(db, "outsider2@example.com", "Outsider")
    db.commit()
    team = client.post("/teams", json={"name": "Revocable"}).json()
    invite = client.post(f"/teams/{team['id']}/invites").json()

    assert client.post(f"/teams/{team['id']}/invites/revoke").json()["revoked"] == 1

    resp = _client_for(outsider).post("/teams/join", json={"token": invite["token"]})
    assert resp.status_code == 400
    assert "revoked" in resp.json()["detail"].lower()


def test_an_expired_invite_stops_working(client, db, user) -> None:
    from app.models import TeamInvite

    outsider = _user(db, "outsider3@example.com", "Outsider3")
    db.commit()
    team = client.post("/teams", json={"name": "Expiring"}).json()
    token = client.post(f"/teams/{team['id']}/invites").json()["token"]

    stored = db.query(TeamInvite).filter(TeamInvite.token == token).one()
    stored.expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
    db.commit()

    resp = _client_for(outsider).post("/teams/join", json={"token": token})
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()


def test_a_bad_token_is_rejected(client, db, user) -> None:
    resp = client.post("/teams/join", json={"token": "not-a-real-token"})
    assert resp.status_code == 400


def test_rejoining_does_not_spend_an_invite_use(client, db, user) -> None:
    from app.models import TeamInvite

    colleague = _user(db, "twice@example.com", "Twice")
    db.commit()
    team = client.post("/teams", json={"name": "Idempotent"}).json()
    token = client.post(f"/teams/{team['id']}/invites").json()["token"]

    mate = _client_for(colleague)
    assert mate.post("/teams/join", json={"token": token}).status_code == 200
    assert mate.post("/teams/join", json={"token": token}).status_code == 200

    db.expire_all()
    stored = db.query(TeamInvite).filter(TeamInvite.token == token).one()
    assert stored.uses == 1
    members = client.get(f"/teams/{team['id']}/members").json()
    assert len(members) == 2


def test_last_owner_cannot_strand_a_team(client, db, user) -> None:
    colleague = _user(db, "stranded@example.com", "Stranded")
    db.commit()
    team = client.post("/teams", json={"name": "Stranded"}).json()
    token = client.post(f"/teams/{team['id']}/invites").json()["token"]
    _client_for(colleague).post("/teams/join", json={"token": token})

    resp = client.post(f"/teams/{team['id']}/leave")
    assert resp.status_code == 409
    assert "only owner" in resp.json()["detail"].lower()


def test_a_member_can_leave(client, db, user) -> None:
    colleague = _user(db, "leaver@example.com", "Leaver")
    db.commit()
    team = client.post("/teams", json={"name": "Leavable"}).json()
    token = client.post(f"/teams/{team['id']}/invites").json()["token"]
    mate = _client_for(colleague)
    mate.post("/teams/join", json={"token": token})

    assert mate.post(f"/teams/{team['id']}/leave").json()["left"] is True
    assert mate.get("/teams").json() == []
    assert len(client.get(f"/teams/{team['id']}/members").json()) == 1


def test_invite_tokens_are_unguessable(client, db, user) -> None:
    team = client.post("/teams", json={"name": "Entropy"}).json()
    tokens = {
        client.post(f"/teams/{team['id']}/invites").json()["token"] for _ in range(5)
    }
    assert len(tokens) == 5, "invite tokens repeated"
    assert all(len(t) >= 24 for t in tokens)


# --- name resolution across a team ----------------------------------------


def test_team_members_are_candidates_for_name_matching(client, db, user) -> None:
    """A spoken name should resolve to the colleague who was in the room."""
    from app.services.team import teammates

    colleague = _user(db, "bunny@teamtest.com", "Bunny Reddy")
    db.commit()
    team = client.post("/teams", json={"name": "Matching"}).json()
    token = client.post(f"/teams/{team['id']}/invites").json()["token"]
    _client_for(colleague).post("/teams/join", json={"token": token})

    db.expire_all()
    me = db.get(User, user.id)
    names = {u.email for u in teammates(db, me)}
    assert colleague.email in names


def test_people_outside_your_teams_are_never_candidates(client, db, user) -> None:
    from app.services.team import teammates

    stranger = _user(db, "stranger@nowhere.com", "Stranger")
    db.commit()
    me = db.get(User, user.id)
    assert stranger.email not in {u.email for u in teammates(db, me)}


def test_membership_rows_are_unique_per_person(client, db, user) -> None:
    team = client.post("/teams", json={"name": "Unique"}).json()
    rows = db.query(TeamMembership).filter(TeamMembership.team_id == team["id"]).all()
    assert len(rows) == 1
    assert rows[0].role == "owner"
