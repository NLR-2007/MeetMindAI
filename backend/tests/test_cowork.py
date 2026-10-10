"""Co-Work: shared progress, with ownership that cannot be faked.

This space deliberately inverts the product's privacy default, so the tests
concentrate on the two rules that keep it honest: you cannot get in without
somebody deciding, and you cannot close work that is not yours.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.models import User
from app.services.security import create_access_token, hash_password


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


def _space(client, name: str = "Hackathon push") -> dict:
    return client.post("/cowork", json={"name": name}).json()


def _admit(owner_client, space, newcomer) -> TestClient:
    """Run the full ask-then-approve flow and return the newcomer's client."""
    mate = _client_for(newcomer)
    mate.post("/cowork/join", json={"token": _token(owner_client, space)})
    req = owner_client.get(f"/cowork/{space['id']}/requests").json()[0]
    owner_client.post(f"/cowork/requests/{req['id']}/decide", json={"approve": True})
    return mate


def _token(owner_client, space) -> str:
    url = owner_client.get("/cowork").json()
    live = next(s for s in url if s["id"] == space["id"])
    return live["join_url"].split("token=")[1]


# --- the door -------------------------------------------------------------


def test_the_link_asks_rather_than_admits(client, db, user) -> None:
    """Admission makes your progress visible, so it is somebody's decision."""
    newcomer = _user(db, "yash@example.com", "Yash")
    db.commit()
    space = _space(client)

    mate = _client_for(newcomer)
    resp = mate.post("/cowork/join", json={"token": _token(client, space)})
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"
    # Asking is not joining: nothing is visible yet.
    assert mate.get("/cowork").json() == []
    assert mate.get(f"/cowork/{space['id']}/members").status_code == 404

    pending = client.get(f"/cowork/{space['id']}/requests").json()
    assert len(pending) == 1
    assert pending[0]["email"] == "yash@example.com"


def test_approval_lets_them_in(client, db, user) -> None:
    newcomer = _user(db, "yash2@example.com", "Yash")
    db.commit()
    space = _space(client)
    mate = _admit(client, space, newcomer)

    assert [s["id"] for s in mate.get("/cowork").json()] == [space["id"]]
    assert len(mate.get(f"/cowork/{space['id']}/members").json()) == 2


def test_rejection_keeps_them_out(client, db, user) -> None:
    newcomer = _user(db, "nope@example.com", "Nope")
    db.commit()
    space = _space(client)
    mate = _client_for(newcomer)
    mate.post("/cowork/join", json={"token": _token(client, space)})

    req = client.get(f"/cowork/{space['id']}/requests").json()[0]
    assert (
        client.post(
            f"/cowork/requests/{req['id']}/decide", json={"approve": False}
        ).json()["status"]
        == "rejected"
    )
    assert mate.get("/cowork").json() == []
    assert client.get(f"/cowork/{space['id']}/requests").json() == []


def test_only_the_lead_sees_or_decides_requests(client, db, user) -> None:
    member = _user(db, "member@cowork.test", "Member")
    outsider = _user(db, "outsider@cowork.test", "Outsider")
    db.commit()
    space = _space(client)
    mate = _admit(client, space, member)

    # A plain member cannot see the queue.
    assert mate.get(f"/cowork/{space['id']}/requests").status_code == 403

    out = _client_for(outsider)
    out.post("/cowork/join", json={"token": _token(client, space)})
    req = client.get(f"/cowork/{space['id']}/requests").json()[0]
    # ...nor decide on it. 404, because a member should not even confirm it.
    assert (
        mate.post(
            f"/cowork/requests/{req['id']}/decide", json={"approve": True}
        ).status_code
        == 404
    )


def test_only_the_lead_gets_the_join_link(client, db, user) -> None:
    member = _user(db, "nolink@cowork.test", "NoLink")
    db.commit()
    space = _space(client)
    mate = _admit(client, space, member)

    theirs = next(s for s in mate.get("/cowork").json() if s["id"] == space["id"])
    assert theirs["join_url"] is None, "a member could hand out admission"
    assert theirs["is_lead"] is False


def test_a_bad_link_is_refused(client, db, user) -> None:
    assert client.post("/cowork/join", json={"token": "nonsense-token"}).status_code == 400


def test_deciding_twice_is_refused(client, db, user) -> None:
    newcomer = _user(db, "twice@cowork.test", "Twice")
    db.commit()
    space = _space(client)
    _client_for(newcomer).post("/cowork/join", json={"token": _token(client, space)})
    req = client.get(f"/cowork/{space['id']}/requests").json()[0]

    client.post(f"/cowork/requests/{req['id']}/decide", json={"approve": True})
    again = client.post(f"/cowork/requests/{req['id']}/decide", json={"approve": True})
    assert again.status_code == 409


# --- the rule that makes the board trustworthy ----------------------------


def test_only_the_assignee_can_mark_their_work_done(client, db, user) -> None:
    """Lokesh cannot close Yash's analysis, and Yash cannot close Lokesh's deck."""
    yash = _user(db, "yash3@example.com", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)

    deck = client.post(
        f"/cowork/{space['id']}/tasks",
        json={"title": "Build the deck", "assignee_id": user.id},
    ).json()
    analysis = client.post(
        f"/cowork/{space['id']}/tasks",
        json={"title": "Run the analysis", "assignee_id": yash.id},
    ).json()

    # Yash cannot close Lokesh's deck.
    blocked = yash_client.patch(f"/cowork/tasks/{deck['id']}", json={"status": "done"})
    assert blocked.status_code == 403
    # The refusal names who it belongs to, so it reads as a rule not a bug.
    assert "can change this task" in blocked.json()["detail"]
    assert (user.name or user.email) in blocked.json()["detail"]

    # Lokesh cannot close Yash's analysis either - owner included.
    blocked2 = client.patch(f"/cowork/tasks/{analysis['id']}", json={"status": "done"})
    assert blocked2.status_code == 403
    assert "Yash" in blocked2.json()["detail"]

    # Each closes their own.
    assert (
        client.patch(f"/cowork/tasks/{deck['id']}", json={"status": "done"}).json()[
            "status"
        ]
        == "done"
    )
    assert (
        yash_client.patch(
            f"/cowork/tasks/{analysis['id']}", json={"status": "done"}
        ).json()["status"]
        == "done"
    )


def test_an_unassigned_task_cannot_be_closed_by_anyone(client, db, user) -> None:
    """With nobody answerable, there is nobody to vouch that it is done."""
    space = _space(client)
    task = client.post(
        f"/cowork/{space['id']}/tasks", json={"title": "Someone should do this"}
    ).json()
    assert task["assignee_id"] is None
    assert task["can_update"] is False

    resp = client.patch(f"/cowork/tasks/{task['id']}", json={"status": "done"})
    assert resp.status_code == 403
    assert "Claim it first" in resp.json()["detail"]


def test_can_update_tells_the_ui_the_truth(client, db, user) -> None:
    """The flag must agree with what the backend will actually allow."""
    yash = _user(db, "yash4@example.com", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)

    client.post(
        f"/cowork/{space['id']}/tasks",
        json={"title": "Mine", "assignee_id": user.id},
    )
    mine = client.get(f"/cowork/{space['id']}/tasks").json()[0]
    theirs = yash_client.get(f"/cowork/{space['id']}/tasks").json()[0]

    assert mine["can_update"] is True
    assert theirs["can_update"] is False


def test_reopening_is_guarded_the_same_way(client, db, user) -> None:
    yash = _user(db, "yash5@example.com", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)

    task = client.post(
        f"/cowork/{space['id']}/tasks",
        json={"title": "Mine to finish", "assignee_id": user.id},
    ).json()
    client.patch(f"/cowork/tasks/{task['id']}", json={"status": "done"})

    # Undoing someone's completion is the same claim in reverse.
    assert (
        yash_client.patch(
            f"/cowork/tasks/{task['id']}", json={"status": "todo"}
        ).status_code
        == 403
    )
    assert (
        client.patch(f"/cowork/tasks/{task['id']}", json={"status": "todo"}).json()[
            "completed_at"
        ]
        is None
    )


def test_unclaimed_work_can_be_picked_up_by_anyone(client, db, user) -> None:
    """Taking work nobody holds takes nothing away from anyone."""
    yash = _user(db, "yash6@example.com", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)

    task = client.post(
        f"/cowork/{space['id']}/tasks", json={"title": "Draft the brief"}
    ).json()
    assert task["can_claim"] is True

    claimed = yash_client.patch(
        f"/cowork/tasks/{task['id']}", json={"assignee_id": yash.id}
    )
    assert claimed.status_code == 200
    assert claimed.json()["assignee_name"] == "Yash"
    assert claimed.json()["can_update"] is True
    # And nobody else can touch it now, including whoever wrote it down.
    assert (
        client.patch(
            f"/cowork/tasks/{task['id']}", json={"title": "Reworded"}
        ).status_code
        == 403
    )


def test_claiming_is_only_claiming(client, db, user) -> None:
    """You cannot smuggle an edit in alongside taking a task."""
    yash = _user(db, "yash6b@example.com", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)
    task = client.post(
        f"/cowork/{space['id']}/tasks", json={"title": "Unclaimed"}
    ).json()

    sneaky = yash_client.patch(
        f"/cowork/tasks/{task['id']}",
        json={"assignee_id": yash.id, "status": "done"},
    )
    assert sneaky.status_code == 403


def test_the_lead_cannot_edit_or_delete_someone_elses_task(client, db, user) -> None:
    """The Lead runs the door, not the board. This is the whole rule."""
    yash = _user(db, "yash6c@example.com", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)

    task = yash_client.post(
        f"/cowork/{space['id']}/tasks",
        json={"title": "Yash word doc", "assignee_id": yash.id},
    ).json()

    assert (
        client.patch(
            f"/cowork/tasks/{task['id']}", json={"title": "Renamed by the lead"}
        ).status_code
        == 403
    )
    assert (
        client.patch(f"/cowork/tasks/{task['id']}", json={"status": "done"}).status_code
        == 403
    )
    assert (
        client.patch(
            f"/cowork/tasks/{task['id']}", json={"assignee_id": user.id}
        ).status_code
        == 403
    )
    assert client.delete(f"/cowork/tasks/{task['id']}").status_code == 403

    assert (
        yash_client.patch(
            f"/cowork/tasks/{task['id']}", json={"title": "Word doc v2"}
        ).status_code
        == 200
    )


def test_the_lead_may_tidy_unclaimed_work_only(client, db, user) -> None:
    yash = _user(db, "yash6d@example.com", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)

    loose = client.post(
        f"/cowork/{space['id']}/tasks", json={"title": "Nobodys"}
    ).json()
    held = yash_client.post(
        f"/cowork/{space['id']}/tasks",
        json={"title": "Yashs", "assignee_id": yash.id},
    ).json()

    assert client.delete(f"/cowork/tasks/{loose['id']}").status_code == 200
    assert client.delete(f"/cowork/tasks/{held['id']}").status_code == 403


def test_leaving_releases_your_work_rather_than_freezing_it(client, db, user) -> None:
    """Assignee-only would otherwise make a departed member's tasks immortal."""
    yash = _user(db, "yash6e@example.com", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)
    yash_client.post(
        f"/cowork/{space['id']}/tasks",
        json={"title": "Half-finished", "assignee_id": yash.id},
    )

    left = yash_client.post(f"/cowork/{space['id']}/leave").json()
    assert left["tasks_released"] == 1

    task = client.get(f"/cowork/{space['id']}/tasks").json()[0]
    assert task["assignee_id"] is None
    assert task["can_claim"] is True
    assert client.delete(f"/cowork/tasks/{task['id']}").status_code == 200


def test_work_cannot_be_assigned_to_someone_outside_the_space(client, db, user) -> None:
    outsider = _user(db, "stranger@cowork.test", "Stranger")
    db.commit()
    space = _space(client)
    resp = client.post(
        f"/cowork/{space['id']}/tasks",
        json={"title": "Not yours to give", "assignee_id": outsider.id},
    )
    assert resp.status_code == 404


# --- isolation ------------------------------------------------------------


def test_a_non_member_sees_nothing_of_the_space(client, db, user, other_client) -> None:
    space = _space(client)
    client.post(f"/cowork/{space['id']}/tasks", json={"title": "Private work"})

    assert other_client.get("/cowork").json() == []
    assert other_client.get(f"/cowork/{space['id']}/tasks").status_code == 404
    assert other_client.get(f"/cowork/{space['id']}/members").status_code == 404
    assert other_client.post(f"/cowork/{space['id']}/tasks", json={"title": "x"}).status_code == 404


def test_cowork_does_not_expose_promises_or_progress(client, db, user) -> None:
    """Co-Work shares this board only. The rest of MeetMind stays private."""
    yash = _user(db, "yash7@example.com", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)

    from app.models import Commitment

    db.add(
        Commitment(
            owner_user_id=user.id,
            assigned_user_id=user.id,
            text="A promise from a meeting",
            status="pending",
        )
    )
    db.commit()

    assert yash_client.get("/promisemirror/commitments").json() == []
    assert yash_client.get("/progress").json()["totals"]["pending"] == 0


def test_progress_is_visible_across_the_room(client, db, user) -> None:
    """The one thing Co-Work does share: how everyone is doing."""
    yash = _user(db, "yash8@example.com", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)

    client.post(
        f"/cowork/{space['id']}/tasks",
        json={"title": "Deck", "assignee_id": user.id},
    )
    t2 = client.post(
        f"/cowork/{space['id']}/tasks",
        json={"title": "Analysis", "assignee_id": yash.id},
    ).json()
    yash_client.patch(f"/cowork/tasks/{t2['id']}", json={"status": "done"})

    rows = {m["email"]: m for m in client.get(f"/cowork/{space['id']}/members").json()}
    assert rows["yash8@example.com"]["done"] == 1
    assert rows["yash8@example.com"]["percent"] == 100
    assert rows[user.email]["done"] == 0

    space_now = next(s for s in client.get("/cowork").json() if s["id"] == space["id"])
    assert space_now["progress"] == {
        "total": 2,
        "done": 1,
        "in_progress": 0,
        "todo": 1,
        "percent": 50,
    }


def test_writing_a_task_down_is_not_authority_over_it(client, db, user) -> None:
    """The Lead hands work out; the holder owns it from that moment on."""
    yash = _user(db, "yash9@example.com", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)

    handed = client.post(
        f"/cowork/{space['id']}/tasks",
        json={"title": "Yash: word doc", "assignee_id": yash.id},
    ).json()

    assert client.delete(f"/cowork/tasks/{handed['id']}").status_code == 403
    assert yash_client.delete(f"/cowork/tasks/{handed['id']}").status_code == 200


def test_last_lead_cannot_strand_the_space(client, db, user) -> None:
    yash = _user(db, "yash10@example.com", "Yash")
    db.commit()
    space = _space(client)
    _admit(client, space, yash)
    assert client.post(f"/cowork/{space['id']}/leave").status_code == 409


def test_join_tokens_are_unguessable_and_distinct_from_team_invites(
    client, db, user
) -> None:
    tokens = {_token(client, _space(client, f"Space {i}")) for i in range(4)}
    assert len(tokens) == 4
    assert all(len(t) >= 24 for t in tokens)

    team = client.post("/teams", json={"name": "Separate"}).json()
    team_token = client.post(f"/teams/{team['id']}/invites").json()["token"]
    # A team invite must never admit anyone to a Co-Work space.
    assert client.post("/cowork/join", json={"token": team_token}).status_code == 400


# --- work that came out of a meeting --------------------------------------


def _done_meeting(db, owner_id: str, items: list[tuple[str, str | None]]):
    """A processed meeting with action items, as the analyser would leave it."""
    from app.models import ActionItem, Meeting

    meeting = Meeting(
        owner_id=owner_id,
        bot_id="bot_cowork_import",
        meeting_url="https://meet.google.com/abc-defg-hij",
        platform="google_meet",
        bot_name="MeetMind AI Notetaker",
        title="Hackathon split",
        status="done",
    )
    db.add(meeting)
    db.flush()
    for task, owner_name in items:
        db.add(ActionItem(meeting_id=meeting.id, task=task, owner_name=owner_name))
    db.flush()
    db.refresh(meeting)
    return meeting


def test_meeting_work_lands_on_the_board_with_the_right_names(
    client, db, user
) -> None:
    """The point of Co-Work next to the meeting record: no retyping."""
    yash = _user(db, "yash11@example.com", "Yash")
    db.commit()
    space = _space(client)
    _admit(client, space, yash)

    meeting = _done_meeting(
        db,
        user.id,
        [
            ("Build the PPT", user.name),
            ("Run the analysis", "Yash"),
            ("Book the venue", "Someone from facilities"),
        ],
    )
    db.commit()

    result = client.post(
        f"/cowork/{space['id']}/import", json={"meeting_id": meeting.id}
    ).json()
    assert result["imported"] == 3
    assert result["assigned"] == 2
    # The unknown name is left unclaimed rather than guessed onto somebody.
    assert result["unassigned"] == 1

    tasks = {t["title"]: t for t in client.get(f"/cowork/{space['id']}/tasks").json()}
    assert tasks["Run the analysis"]["assignee_name"] == "Yash"
    assert tasks["Book the venue"]["assignee_id"] is None
    assert tasks["Book the venue"]["spoken_owner"] == "Someone from facilities"
    assert tasks["Run the analysis"]["source_meeting_id"] == meeting.id


def test_importing_twice_does_not_duplicate_the_board(client, db, user) -> None:
    space = _space(client)
    meeting = _done_meeting(db, user.id, [("Build the PPT", user.name)])
    db.commit()

    first = client.post(
        f"/cowork/{space['id']}/import", json={"meeting_id": meeting.id}
    ).json()
    second = client.post(
        f"/cowork/{space['id']}/import", json={"meeting_id": meeting.id}
    ).json()
    assert first["imported"] == 1
    assert second["imported"] == 0
    assert len(client.get(f"/cowork/{space['id']}/tasks").json()) == 1


def test_imported_work_obeys_the_same_ownership_rule(client, db, user) -> None:
    """Coming from a meeting grants the importer no extra authority."""
    yash = _user(db, "yash12@example.com", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)

    meeting = _done_meeting(db, user.id, [("Run the analysis", "Yash")])
    db.commit()
    client.post(f"/cowork/{space['id']}/import", json={"meeting_id": meeting.id})
    task = client.get(f"/cowork/{space['id']}/tasks").json()[0]

    # The Lead imported it, but it is Yash's work.
    assert client.patch(
        f"/cowork/tasks/{task['id']}", json={"status": "done"}
    ).status_code == 403
    assert yash_client.patch(
        f"/cowork/tasks/{task['id']}", json={"status": "done"}
    ).status_code == 200


def test_cannot_import_a_meeting_you_cannot_read(client, db, user, other_client) -> None:
    space = _space(client)
    meeting = _done_meeting(db, user.id, [("Private work", None)])
    db.commit()

    # The other user is not in the space, so the space itself 404s first.
    assert (
        other_client.post(
            f"/cowork/{space['id']}/import", json={"meeting_id": meeting.id}
        ).status_code
        == 404
    )


def test_importing_an_unknown_meeting_is_refused(client, db, user) -> None:
    space = _space(client)
    assert (
        client.post(
            f"/cowork/{space['id']}/import", json={"meeting_id": "nope"}
        ).status_code
        == 404
    )


# --- a Co-Work meeting is still an ordinary meeting ------------------------


def test_imported_work_carries_its_deadline(client, db, user) -> None:
    """A date agreed in the meeting is the same date on the board."""
    from datetime import datetime, timedelta

    from app.models import Deadline

    space = _space(client)
    meeting = _done_meeting(db, user.id, [("Ship the demo video", user.name)])
    soon = datetime.utcnow() + timedelta(days=3)
    db.add(
        Deadline(
            meeting_id=meeting.id,
            what="Ship the demo video",
            due_at=soon,
            when_text="in three days",
        )
    )
    db.commit()

    result = client.post(
        f"/cowork/{space['id']}/import", json={"meeting_id": meeting.id}
    ).json()
    assert result["with_dates"] == 1

    task = client.get(f"/cowork/{space['id']}/tasks").json()[0]
    assert task["due_at"] is not None
    assert task["overdue"] is False


def test_members_request_deadline_changes_and_lead_approves(client, db, user) -> None:
    """A member asking for more time must not move the date by itself."""
    from datetime import datetime

    yash = _user(db, "deadline-yash@cowork.test", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)
    task = client.post(
        f"/cowork/{space['id']}/tasks",
        json={
            "title": "Finish the integration",
            "assignee_id": yash.id,
            "due_at": "2026-11-20T00:00:00",
        },
    ).json()

    requested = "2026-11-25T00:00:00"
    req = yash_client.post(
        f"/cowork/tasks/{task['id']}/deadline-requests",
        json={"requested_due_at": requested, "reason": "The API changed."},
    )
    assert req.status_code == 201
    assert req.json()["status"] == "pending"

    unchanged = client.get(f"/cowork/{space['id']}/tasks").json()[0]
    assert datetime.fromisoformat(unchanged["due_at"]).date().isoformat() == "2026-11-20"
    assert unchanged["pending_deadline_request_id"] == req.json()["id"]

    queue = client.get(f"/cowork/{space['id']}/deadline-requests").json()
    assert len(queue) == 1
    assert queue[0]["task_title"] == "Finish the integration"
    assert queue[0]["requester_name"] == "Yash"

    decided = client.post(
        f"/cowork/deadline-requests/{req.json()['id']}/decide",
        json={"approve": True},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "approved"

    moved = client.get(f"/cowork/{space['id']}/tasks").json()[0]
    assert datetime.fromisoformat(moved["due_at"]).date().isoformat() == "2026-11-25"
    assert moved["pending_deadline_request_id"] is None


def test_non_lead_cannot_approve_deadline_changes(client, db, user) -> None:
    yash = _user(db, "deadline-member@cowork.test", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)
    task = client.post(
        f"/cowork/{space['id']}/tasks",
        json={
            "title": "Draft the report",
            "assignee_id": user.id,
            "due_at": "2026-11-20T00:00:00",
        },
    ).json()

    req = yash_client.post(
        f"/cowork/tasks/{task['id']}/deadline-requests",
        json={"requested_due_at": "2026-11-22T00:00:00"},
    ).json()
    assert (
        yash_client.post(
            f"/cowork/deadline-requests/{req['id']}/decide",
            json={"approve": True},
        ).status_code
        == 404
    )


def test_rejected_deadline_change_leaves_date_alone(client, db, user) -> None:
    yash = _user(db, "deadline-reject@cowork.test", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)
    task = client.post(
        f"/cowork/{space['id']}/tasks",
        json={
            "title": "Send customer notes",
            "assignee_id": yash.id,
            "due_at": "2026-11-20T00:00:00",
        },
    ).json()
    req = yash_client.post(
        f"/cowork/tasks/{task['id']}/deadline-requests",
        json={"requested_due_at": "2026-11-29T00:00:00"},
    ).json()

    client.post(
        f"/cowork/deadline-requests/{req['id']}/decide",
        json={"approve": False},
    )
    task_after = client.get(f"/cowork/{space['id']}/tasks").json()[0]
    assert task_after["due_at"].startswith("2026-11-20")


def test_only_one_deadline_change_can_wait_at_a_time(client, db, user) -> None:
    yash = _user(db, "deadline-once@cowork.test", "Yash")
    db.commit()
    space = _space(client)
    yash_client = _admit(client, space, yash)
    task = client.post(
        f"/cowork/{space['id']}/tasks",
        json={"title": "Prepare screenshots", "assignee_id": yash.id},
    ).json()

    assert (
        yash_client.post(
            f"/cowork/tasks/{task['id']}/deadline-requests",
            json={"requested_due_at": "2026-11-25T00:00:00"},
        ).status_code
        == 201
    )
    assert (
        yash_client.post(
            f"/cowork/tasks/{task['id']}/deadline-requests",
            json={"requested_due_at": "2026-11-26T00:00:00"},
        ).status_code
        == 409
    )


def test_an_overdue_task_is_flagged_and_sorts_first(client, db, user) -> None:
    from datetime import datetime, timedelta

    from app.models import Deadline

    space = _space(client)
    client.post(f"/cowork/{space['id']}/tasks", json={"title": "Something later"})

    meeting = _done_meeting(db, user.id, [("Overdue thing", user.name)])
    db.add(
        Deadline(
            meeting_id=meeting.id,
            what="Overdue thing",
            due_at=datetime.utcnow() - timedelta(days=5),
            when_text="last week",
        )
    )
    db.commit()
    client.post(f"/cowork/{space['id']}/import", json={"meeting_id": meeting.id})

    tasks = client.get(f"/cowork/{space['id']}/tasks").json()
    assert tasks[0]["title"] == "Overdue thing"
    assert tasks[0]["overdue"] is True
    # Closing it stops it being overdue; finished work never is.
    client.patch(f"/cowork/tasks/{tasks[0]['id']}", json={"status": "done"})
    closed = next(
        t
        for t in client.get(f"/cowork/{space['id']}/tasks").json()
        if t["title"] == "Overdue thing"
    )
    assert closed["overdue"] is False


def test_the_space_shows_what_the_meeting_decided(client, db, user) -> None:
    from app.models import Deadline, Summary

    space = _space(client)
    meeting = _done_meeting(db, user.id, [("Build the PPT", user.name)])
    db.add(
        Summary(
            meeting_id=meeting.id,
            summary_text="Split the hackathon work three ways.",
            decisions=["Submit on the 20th", "Lokesh owns the deck"],
        )
    )
    db.add(
        Deadline(meeting_id=meeting.id, what="Submission", when_text="the 20th")
    )
    db.commit()
    client.post(f"/cowork/{space['id']}/import", json={"meeting_id": meeting.id})

    briefs = client.get(f"/cowork/{space['id']}/meetings").json()
    assert len(briefs) == 1
    assert "three ways" in briefs[0]["summary"]
    assert "Submit on the 20th" in briefs[0]["decisions"]
    assert briefs[0]["deadlines"][0]["what"] == "Submission"


def test_a_silent_deadline_change_still_raises_its_alarm_in_cowork(
    client, db, user
) -> None:
    """Sharing a board must not be a quieter place for a date to move."""
    from datetime import datetime

    from app.models import Deadline, Project, Transcript
    from app.services import promisemirror

    project = Project(owner_id=user.id, name="Co-Work project")
    db.add(project)
    db.flush()

    def _meeting_with(title: str, day: int, said: str):
        from app.models import Meeting

        m = Meeting(
            owner_id=user.id,
            project_id=project.id,
            bot_id=f"bot_{title}",
            meeting_url="https://meet.google.com/abc-defg-hij",
            platform="google_meet",
            bot_name="MeetMind AI Notetaker",
            title=title,
            status="done",
        )
        db.add(m)
        db.flush()
        db.add(Transcript(meeting_id=m.id, plain_text=said, word_count=len(said.split())))
        db.add(
            Deadline(
                meeting_id=m.id,
                what="Submit the compliance report",
                due_at=datetime(2026, 11, day),
                when_text=f"{day} November",
            )
        )
        db.flush()
        db.refresh(m)
        return m

    first = _meeting_with("Kickoff", 20, "We submit the compliance report on the twentieth.")
    promisemirror.sync_meeting_commitments(db, first)
    second = _meeting_with("Standup", 19, "Compliance report on the nineteenth.")
    assert promisemirror.sync_meeting_commitments(db, second)["silent_changes"] == 1
    db.commit()

    space = _space(client)
    client.post(f"/cowork/{space['id']}/import", json={"meeting_id": second.id})

    briefs = client.get(f"/cowork/{space['id']}/meetings").json()
    kinds = [a["kind"] for b in briefs for a in b["alerts"]]
    assert "silent_change" in kinds, "the silent change was invisible inside Co-Work"


def test_meeting_briefs_need_membership(client, db, user, other_client) -> None:
    space = _space(client)
    assert other_client.get(f"/cowork/{space['id']}/meetings").status_code == 404
