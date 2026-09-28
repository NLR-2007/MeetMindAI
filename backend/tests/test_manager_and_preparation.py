"""Manager rollups and private, history-aware meeting preparation."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import respx
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.models import (
    CoachingNote,
    Commitment,
    Meeting,
    PracticeSession,
    PrepPlan,
    Project,
    Transcript,
    User,
)
from app.services.security import create_access_token, hash_password

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _meeting(db, user_id: str) -> Meeting:
    meeting = Meeting(
        owner_id=user_id,
        bot_id="bot_prep_history",
        meeting_url="https://meet.google.com/abc-defg-hij",
        platform="google_meet",
        bot_name="MeetMind AI Notetaker",
        title="Earlier client review",
        status="done",
    )
    db.add(meeting)
    db.flush()
    return meeting


@respx.mock
def test_new_meeting_preparation_uses_private_coaching(client, db, user) -> None:
    meeting = _meeting(db, user.id)
    db.add(
        CoachingNote(
            owner_user_id=user.id,
            meeting_id=meeting.id,
            category="clarity",
            suggestion="Lead with the recommendation before implementation detail.",
            evidence="We could maybe do one of two approaches.",
            rejected=False,
        )
    )
    db.commit()

    route = respx.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": json.dumps({
                        "briefing": "Align the group on launch scope.",
                        "role_guidance": "Own the technical recommendation.",
                        "opening_script": "I recommend we start with the smallest safe scope.",
                        "speaking_strategy": ["State the recommendation first."],
                        "past_improvements": ["Lead with your conclusion."],
                        "talking_points": ["Explain the API boundary."],
                        "questions_to_ask": ["Who approves scope changes?"],
                        "risks": ["The timeline is not confirmed."],
                    })},
                }],
                "usage": {"total_tokens": 50},
            },
        )
    )

    response = client.post(
        "/markup/prepare/new",
        json={
            "purpose": "Alpha kickoff",
            "project_description": "A new internal API.",
            "participants": "Product manager and client",
            "my_responsibilities": "Backend lead",
            "desired_outcomes": "Approve the technical direction",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["role_guidance"] == "Own the technical recommendation."
    assert body["past_improvements"] == ["Lead with your conclusion."]
    assert body["past_coaching_count"] == 1

    sent = json.loads(route.calls.last.request.content)
    prompt = " ".join(message["content"] for message in sent["messages"])
    assert "Lead with the recommendation" in prompt


def test_personal_progress_excludes_reports_and_team_section_includes_them(db) -> None:
    """A manager's personal dashboard stays personal; the team has its own view."""
    manager = User(
        email="manager@example.com",
        name="Manager",
        role="manager",
        password_hash=hash_password("managerpass123"),
    )
    db.add(manager)
    db.flush()
    employee = User(
        email="employee@example.com",
        name="Employee",
        role="employee",
        manager_id=manager.id,
        password_hash=hash_password("employeepass123"),
    )
    db.add(employee)
    db.flush()
    project = Project(name="Employee Project", owner_id=employee.id)
    db.add(project)
    db.flush()
    commitment = Commitment(
        owner_user_id=employee.id,
        assigned_user_id=employee.id,
        project_id=project.id,
        text="Send the final launch checklist",
        owner_name="Employee",
        status="pending",
        due_at=datetime.now(timezone.utc) + timedelta(days=2),
    )
    db.add(commitment)
    db.commit()

    client = TestClient(app)
    token = create_access_token(get_settings(), manager.id, manager.email)
    client.headers.update({"Authorization": f"Bearer {token}"})

    # Personal view: the report's work must not appear here.
    personal = client.get("/progress")
    assert personal.status_code == 200
    assert personal.json()["totals"]["pending"] == 0

    # Team view: it must.
    overview = client.get("/team/overview").json()
    employee_row = next(m for m in overview["members"] if m["user_id"] == employee.id)
    assert employee_row["pending"] == 1
    assert overview["totals"]["pending"] == 1

    deadlines = client.get("/team/deadlines").json()
    assert any(d["text"] == "Send the final launch checklist" for d in deadlines["upcoming"])

    projects = client.get("/team/projects").json()
    assert any(p["project_name"] == "Employee Project" for p in projects)


def test_manager_cannot_close_a_reports_commitment(db) -> None:
    """Reading a report's work is fine; completing it for them is not."""
    manager = User(
        email="boss@example.com",
        name="Boss",
        role="manager",
        password_hash=hash_password("bosspass12345"),
    )
    db.add(manager)
    db.flush()
    employee = User(
        email="report@example.com",
        name="Report",
        role="employee",
        manager_id=manager.id,
        password_hash=hash_password("reportpass123"),
    )
    db.add(employee)
    db.flush()
    commitment = Commitment(
        owner_user_id=employee.id,
        assigned_user_id=employee.id,
        text="Write the spec",
        status="pending",
    )
    db.add(commitment)
    db.commit()

    client = TestClient(app)
    client.headers.update(
        {"Authorization": f"Bearer {create_access_token(get_settings(), manager.id, manager.email)}"}
    )
    resp = client.post(
        f"/promisemirror/commitments/{commitment.id}/status",
        json={"status": "completed", "confirmed": True},
    )
    assert resp.status_code == 403
    assert "owns this commitment" in resp.json()["detail"]

    # The owner still can.
    client.headers.update(
        {"Authorization": f"Bearer {create_access_token(get_settings(), employee.id, employee.email)}"}
    )
    assert (
        client.post(
            f"/promisemirror/commitments/{commitment.id}/status",
            json={"status": "completed", "confirmed": True},
        ).status_code
        == 200
    )


def test_employee_cannot_reach_team_endpoints(db) -> None:
    solo = User(
        email="solo@example.com",
        name="Solo",
        role="employee",
        password_hash=hash_password("solopass12345"),
    )
    db.add(solo)
    db.commit()

    client = TestClient(app)
    client.headers.update(
        {"Authorization": f"Bearer {create_access_token(get_settings(), solo.id, solo.email)}"}
    )
    for path in ["/team/overview", "/team/commitments", "/team/deadlines", "/team/projects"]:
        assert client.get(path).status_code == 403, path


@respx.mock
def test_private_coach_answers_with_meeting_feedback(client, db, user) -> None:
    meeting = _meeting(db, user.id)
    db.add(
        Transcript(
            meeting_id=meeting.id,
            plain_text="I think maybe we can ship Friday.",
            word_count=7,
        )
    )
    db.add(
        CoachingNote(
            owner_user_id=user.id,
            meeting_id=meeting.id,
            category="clarity",
            suggestion="State the recommendation before the uncertainty.",
            evidence="I think maybe we can ship Friday.",
            rejected=False,
        )
    )
    db.commit()

    route = respx.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": "Try: I recommend Friday, provided QA passes Thursday."
                        },
                    }
                ],
                "usage": {"total_tokens": 20},
            },
        )
    )

    response = client.post(
        f"/coach/{meeting.id}/ask",
        json={"message": "How should I say this next time?", "history": []},
    )

    assert response.status_code == 200
    assert "I recommend Friday" in response.json()["answer"]
    sent = json.loads(route.calls.last.request.content)
    context = " ".join(message["content"] for message in sent["messages"])
    assert "State the recommendation" in context
    assert "I think maybe we can ship Friday" in context


@respx.mock
def test_live_answer_uses_preparation_and_practice(client, db, user) -> None:
    plan = PrepPlan(
        owner_user_id=user.id,
        title="Paddy detection model review",
        context={"project_description": "Detect paddy fields using a CNN."},
        briefing="Recommend a CNN and explain the data requirements.",
        talking_points=["Satellite imagery resolution must be validated."],
        questions_to_ask=["How often can imagery be collected?"],
        open_commitments=[],
    )
    db.add(plan)
    db.flush()
    db.add(
        PracticeSession(
            prep_plan_id=plan.id,
            owner_user_id=user.id,
            persona="client",
            transcript=[
                {"role": "assistant", "content": "What data do we need?"},
                {"role": "user", "content": "We need labelled satellite images."},
            ],
        )
    )
    db.commit()

    route = respx.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": "We need labelled satellite imagery; I would validate resolution and collection frequency before fixing the training target."},
                }],
                "usage": {"total_tokens": 24},
            },
        )
    )
    response = client.post(
        f"/markup/plans/{plan.id}/live-answer",
        json={"question": "What data should we collect?"},
    )

    assert response.status_code == 200
    assert "labelled satellite imagery" in response.json()["answer"]
    sent = json.loads(route.calls.last.request.content)
    prompt = " ".join(message["content"] for message in sent["messages"])
    assert "Satellite imagery resolution" in prompt
    assert "We need labelled satellite images" in prompt


@respx.mock
def test_private_live_assist_answers_after_two_seconds(client, db, user) -> None:
    meeting = _meeting(db, user.id)
    db.add(
        Transcript(
            meeting_id=meeting.id,
            plain_text="Client: What data should we collect?",
            word_count=6,
            utterances=[{
                "participant_id": "client-1",
                "participant_name": "Client",
                "participant_email": None,
                "text": "What data should we collect?",
                "end": 18.2,
                "received_at": (datetime.now(timezone.utc) - timedelta(seconds=3)).isoformat(),
            }],
        )
    )
    plan = PrepPlan(
        owner_user_id=user.id,
        title="Paddy model review",
        context={"project_description": "CNN using labelled satellite imagery."},
        briefing="Explain the training data requirements.",
        talking_points=["Validate resolution and collection frequency."],
        questions_to_ask=[],
        open_commitments=[],
    )
    db.add(plan)
    db.commit()

    configured = client.post(
        f"/markup/plans/{plan.id}/live-assist",
        json={"meeting_id": meeting.id, "enabled": True},
    )
    assert configured.status_code == 200
    respx.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": "We should collect labelled satellite imagery and validate its resolution and capture frequency first."}}],
                "usage": {"total_tokens": 20},
            },
        )
    )

    status_response = client.get(f"/markup/plans/{plan.id}/live-assist")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["state"] == "ready"
    assert status_body["question"] == "What data should we collect?"
    assert "labelled satellite imagery" in status_body["answer"]

