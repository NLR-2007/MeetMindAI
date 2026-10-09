"""Meetings are filed under a project, and only under one of your own.

Filing a meeting under someone else's project would pull it into their Mark Up
context and their commitment history, which is exactly the cross-mapping the
app exists to prevent.
"""
from __future__ import annotations

import httpx
import respx

from app.models import Meeting, Project, User
from app.services.security import hash_password

BOT_URL = "https://us-west-2.recall.ai/api/v1/bot/"
MEET = "https://meet.google.com/abc-defg-hij"


def _bot_response(bot_id: str = "bot_project_1") -> httpx.Response:
    return httpx.Response(
        201,
        json={
            "id": bot_id,
            "meeting_url": MEET,
            "bot_name": "MeetMind AI Notetaker",
            "status_changes": [{"code": "joining_call"}],
        },
    )


@respx.mock
def test_meeting_joins_under_a_project_and_reports_it(client, db, user) -> None:
    project = Project(name="Paddy rollout", owner_id=user.id)
    db.add(project)
    db.commit()

    respx.post(BOT_URL).mock(return_value=_bot_response())

    resp = client.post(
        "/meetings/join",
        json={
            "meeting_url": MEET,
            "consent_acknowledged": True,
            "project_id": project.id,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["project_id"] == project.id
    assert body["project_name"] == "Paddy rollout"

    # And the listing carries it too, so history can group by workstream.
    listed = client.get("/meetings").json()
    assert listed[0]["project_name"] == "Paddy rollout"


@respx.mock
def test_meeting_without_a_project_is_still_allowed(client, db, user) -> None:
    """A project is optional: a one-off call should not be blocked."""
    respx.post(BOT_URL).mock(return_value=_bot_response("bot_no_project"))

    resp = client.post(
        "/meetings/join",
        json={"meeting_url": MEET, "consent_acknowledged": True},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["project_id"] is None
    assert resp.json()["project_name"] is None


@respx.mock
def test_cannot_file_a_meeting_under_someone_elses_project(client, db, user) -> None:
    stranger = User(
        email="stranger@example.com",
        name="Stranger",
        role="employee",
        password_hash=hash_password("strangerpass123"),
    )
    db.add(stranger)
    db.flush()
    theirs = Project(name="Their private project", owner_id=stranger.id)
    db.add(theirs)
    db.commit()

    route = respx.post(BOT_URL).mock(return_value=_bot_response("bot_should_not_happen"))

    resp = client.post(
        "/meetings/join",
        json={
            "meeting_url": MEET,
            "consent_acknowledged": True,
            "project_id": theirs.id,
        },
    )
    # 404, not 403: an id that is not yours looks like one that does not exist.
    assert resp.status_code == 404
    assert theirs.id in resp.json()["detail"]
    # And no bot was dispatched, so no Recall minutes were spent on the attempt.
    assert not route.called


@respx.mock
def test_unknown_project_id_is_rejected(client, db, user) -> None:
    route = respx.post(BOT_URL).mock(return_value=_bot_response("bot_unknown_project"))

    resp = client.post(
        "/meetings/join",
        json={
            "meeting_url": MEET,
            "consent_acknowledged": True,
            "project_id": "does-not-exist",
        },
    )
    assert resp.status_code == 404
    assert not route.called


@respx.mock
def test_later_meetings_accumulate_under_the_same_project(client, db, user) -> None:
    """The point of the selector: pick the project again and history builds up."""
    project = Project(name="Compliance rollout", owner_id=user.id)
    db.add(project)
    db.commit()

    for n in range(3):
        respx.post(BOT_URL).mock(return_value=_bot_response(f"bot_seq_{n}"))
        resp = client.post(
            "/meetings/join",
            json={
                "meeting_url": MEET,
                "consent_acknowledged": True,
                "title": f"Weekly sync {n}",
                "project_id": project.id,
            },
        )
        assert resp.status_code == 201, resp.text

    listed = client.get("/meetings").json()
    under_project = [m for m in listed if m["project_id"] == project.id]
    assert len(under_project) == 3
    assert {m["project_name"] for m in under_project} == {"Compliance rollout"}


# --- filing an existing meeting into a project ----------------------------


def _commitment(db, meeting_id: str, user_id: str, project_id: str | None):
    from app.models import Commitment

    c = Commitment(
        owner_user_id=user_id,
        project_id=project_id,
        source_meeting_id=meeting_id,
        text="Ship the pilot",
        status="pending",
    )
    db.add(c)
    db.flush()
    return c


@respx.mock
def test_existing_meeting_can_be_filed_under_a_project(client, db, user) -> None:
    """Meetings recorded before the selector existed must still be groupable."""
    respx.post(BOT_URL).mock(return_value=_bot_response("bot_backfill"))
    meeting_id = client.post(
        "/meetings/join",
        json={"meeting_url": MEET, "consent_acknowledged": True},
    ).json()["id"]

    project = Project(name="Paddy Field Detection", owner_id=user.id)
    db.add(project)
    db.flush()
    commitment = _commitment(db, meeting_id, user.id, None)
    db.commit()

    resp = client.patch(
        f"/meetings/{meeting_id}/project", json={"project_id": project.id}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_name"] == "Paddy Field Detection"

    db.expire_all()
    # The promises move with the conversation they came from.
    assert db.get(type(commitment), commitment.id).project_id == project.id


@respx.mock
def test_meeting_can_be_moved_back_to_no_project(client, db, user) -> None:
    project = Project(name="Temporary", owner_id=user.id)
    db.add(project)
    db.flush()
    db.commit()

    respx.post(BOT_URL).mock(return_value=_bot_response("bot_unfile"))
    meeting_id = client.post(
        "/meetings/join",
        json={
            "meeting_url": MEET,
            "consent_acknowledged": True,
            "project_id": project.id,
        },
    ).json()["id"]

    resp = client.patch(f"/meetings/{meeting_id}/project", json={"project_id": None})
    assert resp.status_code == 200, resp.text
    assert resp.json()["project_id"] is None


@respx.mock
def test_cannot_file_a_meeting_into_someone_elses_project(client, db, user) -> None:
    stranger = User(
        email="other@example.com",
        name="Other",
        role="employee",
        password_hash=hash_password("otherpass12345"),
    )
    db.add(stranger)
    db.flush()
    theirs = Project(name="Theirs", owner_id=stranger.id)
    db.add(theirs)
    db.commit()

    respx.post(BOT_URL).mock(return_value=_bot_response("bot_guard"))
    meeting_id = client.post(
        "/meetings/join",
        json={"meeting_url": MEET, "consent_acknowledged": True},
    ).json()["id"]

    resp = client.patch(
        f"/meetings/{meeting_id}/project", json={"project_id": theirs.id}
    )
    assert resp.status_code == 404


def test_cannot_file_someone_elses_meeting(client, db, user, other_client) -> None:
    project = Project(name="Mine", owner_id=user.id)
    db.add(project)
    db.flush()
    meeting = Meeting(
        owner_id=user.id,
        bot_id="bot_not_yours",
        meeting_url=MEET,
        platform="google_meet",
        bot_name="MeetMind AI Notetaker",
        status="done",
    )
    db.add(meeting)
    db.commit()

    resp = other_client.patch(
        f"/meetings/{meeting.id}/project", json={"project_id": project.id}
    )
    assert resp.status_code == 404
