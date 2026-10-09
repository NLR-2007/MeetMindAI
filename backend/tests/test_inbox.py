"""Priority inbox: only named senders, and their promises join one ledger.

The risk this feature carries is reading more mail than the user asked for,
so most of these tests are about what is NOT fetched or stored.
"""
from __future__ import annotations

import base64

import httpx
import respx

from app.models import Calendar, Commitment, InboundEmail, PrioritySender
from app.services import mailbox

GMAIL_LIST = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


# --- matching rules -------------------------------------------------------


def test_a_domain_matches_any_address_at_it() -> None:
    assert mailbox.matches("Ravi <ravi@acme.com>", ["acme.com"]) == "acme.com"
    assert mailbox.matches("billing@acme.com", ["acme.com"]) == "acme.com"
    # Subdomains count: mail.acme.com is still Acme.
    assert mailbox.matches("x@mail.acme.com", ["acme.com"]) == "acme.com"


def test_a_full_address_matches_only_itself() -> None:
    assert mailbox.matches("ravi@acme.com", ["ravi@acme.com"]) == "ravi@acme.com"
    assert mailbox.matches("someone@acme.com", ["ravi@acme.com"]) is None


def test_lookalike_domains_do_not_match() -> None:
    """The obvious way to leak: suffix matching that ignores the boundary."""
    assert mailbox.matches("spam@notacme.com", ["acme.com"]) is None
    assert mailbox.matches("spam@acme.com.evil.net", ["acme.com"]) is None


def test_unmatched_senders_are_ignored() -> None:
    assert mailbox.matches("newsletter@substack.com", ["acme.com"]) is None
    assert mailbox.matches("", ["acme.com"]) is None
    assert mailbox.matches("not-an-address", ["acme.com"]) is None


def test_the_gmail_query_only_asks_for_named_senders() -> None:
    """Server-side filtering is the difference between this and reading
    someone's whole mailbox."""
    q = mailbox._gmail_query(["acme.com", "ravi@beta.io"], 14)
    assert "from:acme.com" in q
    assert "from:ravi@beta.io" in q
    assert "newer_than:14d" in q


def test_plain_text_is_preferred_over_html() -> None:
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("the real text")}},
            {"mimeType": "text/html", "body": {"data": _b64("<p>markup</p>")}},
        ],
    }
    assert mailbox.extract_body(payload) == "the real text"


def test_html_is_stripped_when_there_is_no_plain_part() -> None:
    payload = {
        "mimeType": "text/html",
        "body": {"data": _b64("<p>Hello <b>there</b></p>")},
    }
    body = mailbox.extract_body(payload)
    assert "<" not in body
    assert "Hello" in body and "there" in body


# --- endpoints ------------------------------------------------------------


def test_senders_can_be_added_and_removed(client, db, user) -> None:
    created = client.post("/inbox/senders", json={"pattern": "Acme.com", "label": "Acme"})
    assert created.status_code == 201, created.text
    # Normalised to lowercase, no stray @.
    assert created.json()["pattern"] == "acme.com"

    assert len(client.get("/inbox/senders").json()) == 1
    # Adding the same one twice is a no-op, not an error.
    assert client.post("/inbox/senders", json={"pattern": "@acme.com"}).status_code == 201
    assert len(client.get("/inbox/senders").json()) == 1

    sid = created.json()["id"]
    assert client.delete(f"/inbox/senders/{sid}").status_code == 200
    assert client.get("/inbox/senders").json() == []


def test_rubbish_patterns_are_rejected(client, db, user) -> None:
    for bad in ["notadomain", "two words", "a b.com"]:
        assert client.post("/inbox/senders", json={"pattern": bad}).status_code == 422


def test_senders_are_private_to_their_owner(client, db, user, other_client) -> None:
    sid = client.post("/inbox/senders", json={"pattern": "acme.com"}).json()["id"]
    assert other_client.get("/inbox/senders").json() == []
    assert other_client.delete(f"/inbox/senders/{sid}").status_code == 404


def test_sync_without_senders_reads_nothing(client, db, user) -> None:
    """No senders means no mail is requested at all."""
    body = client.post("/inbox/sync").json()
    assert body["synced"] == 0
    assert "Add a priority sender" in body["message"]


def test_sync_requires_a_google_connection(client, db, user) -> None:
    client.post("/inbox/senders", json={"pattern": "acme.com"})
    resp = client.post("/inbox/sync")
    assert resp.status_code == 409
    assert "Connect Google Calendar" in resp.json()["detail"]


@respx.mock
def test_sync_stores_the_summary_and_files_the_promise(client, db, user) -> None:
    db.add(
        Calendar(
            recall_calendar_id="cal_inbox",
            owner_id=user.id,
            email="me@example.com",
            status="connected",
            google_refresh_token="refresh-token-value",
        )
    )
    db.add(PrioritySender(owner_id=user.id, pattern="acme.com"))
    db.commit()

    respx.post(GOOGLE_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
    )
    respx.get(GMAIL_LIST).mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "m1"}]})
    )
    respx.get(f"{GMAIL_LIST}/m1").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "m1",
                "threadId": "t1",
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": "Ravi <ravi@acme.com>"},
                        {"name": "Subject", "value": "Revised scope"},
                        {"name": "Date", "value": "Tue, 6 Oct 2026 09:00:00 +0000"},
                    ],
                    "body": {
                        "data": _b64("I will send the revised scope by Friday.")
                    },
                },
            },
        )
    )
    respx.post(GROQ_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": (
                                '{"summary":"Ravi will send a revised scope.",'
                                '"highlights":["Revised scope due Friday"],'
                                '"urgent":true,"urgency_reason":"You are blocked on it",'
                                '"commitments":[{"text":"Send the revised scope",'
                                '"owner":"Ravi","due":"Friday","due_date":"2026-10-09"}]}'
                            )
                        },
                    }
                ]
            },
        )
    )

    body = client.post("/inbox/sync").json()
    assert body["new"] == 1
    assert body["commitments"] == 1

    mail = client.get("/inbox").json()
    assert len(mail) == 1
    assert mail[0]["urgent"] is True
    assert mail[0]["matched_pattern"] == "acme.com"
    assert "revised scope" in mail[0]["summary"].lower()

    # The promise joined the same ledger meetings feed.
    promises = client.get("/promisemirror/commitments").json()
    assert any("revised scope" in c["text"].lower() for c in promises)

    # The message body itself is never stored.
    stored = db.query(InboundEmail).one()
    assert not hasattr(stored, "body")
    assert "I will send the revised scope" not in (stored.summary or "")


@respx.mock
def test_mail_from_an_unlisted_sender_is_discarded(client, db, user) -> None:
    """Gmail's from: is fuzzier than our rules, so ours decide."""
    db.add(
        Calendar(
            recall_calendar_id="cal_inbox2",
            owner_id=user.id,
            status="connected",
            google_refresh_token="refresh-token-value",
        )
    )
    db.add(PrioritySender(owner_id=user.id, pattern="acme.com"))
    db.commit()

    respx.post(GOOGLE_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
    )
    respx.get(GMAIL_LIST).mock(
        return_value=httpx.Response(200, json={"messages": [{"id": "spam"}]})
    )
    respx.get(f"{GMAIL_LIST}/spam").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "spam",
                "payload": {
                    "mimeType": "text/plain",
                    "headers": [
                        {"name": "From", "value": "deals@notacme.com"},
                        {"name": "Subject", "value": "50% off"},
                    ],
                    "body": {"data": _b64("Buy now")},
                },
            },
        )
    )
    groq = respx.post(GROQ_URL).mock(return_value=httpx.Response(200, json={}))

    body = client.post("/inbox/sync").json()
    assert body["new"] == 0
    assert db.query(InboundEmail).count() == 0
    assert not groq.called, "an unlisted sender's mail was sent to the model"


@respx.mock
def test_a_missing_gmail_scope_is_explained(client, db, user) -> None:
    db.add(
        Calendar(
            recall_calendar_id="cal_inbox3",
            owner_id=user.id,
            status="connected",
            google_refresh_token="refresh-token-value",
        )
    )
    db.add(PrioritySender(owner_id=user.id, pattern="acme.com"))
    db.commit()

    respx.post(GOOGLE_TOKEN).mock(
        return_value=httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
    )
    respx.get(GMAIL_LIST).mock(return_value=httpx.Response(403, json={"error": "nope"}))

    resp = client.post("/inbox/sync")
    assert resp.status_code == 502
    # The error has to name the cure, or it sends people hunting for a bug.
    assert "gmail.readonly" in resp.json()["detail"]


def test_mail_is_private_to_its_owner(client, db, user, other_client) -> None:
    email = InboundEmail(
        owner_id=user.id,
        gmail_id="private-1",
        sender="ravi@acme.com",
        subject="Private",
        summary="Not yours",
    )
    db.add(email)
    db.commit()

    assert other_client.get("/inbox").json() == []
    assert other_client.post(f"/inbox/{email.id}/read").status_code == 404
    assert len(client.get("/inbox").json()) == 1


def test_urgent_mail_sorts_first(client, db, user) -> None:
    from datetime import datetime

    db.add(
        InboundEmail(
            owner_id=user.id,
            gmail_id="old-urgent",
            sender="a@acme.com",
            urgent=True,
            received_at=datetime(2026, 1, 1),
        )
    )
    db.add(
        InboundEmail(
            owner_id=user.id,
            gmail_id="new-calm",
            sender="b@acme.com",
            urgent=False,
            received_at=datetime(2026, 10, 1),
        )
    )
    db.commit()

    rows = client.get("/inbox").json()
    # Newer, but not urgent, so it comes second.
    assert rows[0]["sender"] == "a@acme.com"


def test_marking_read_sticks(client, db, user) -> None:
    email = InboundEmail(owner_id=user.id, gmail_id="r1", sender="a@acme.com")
    db.add(email)
    db.commit()

    assert client.post(f"/inbox/{email.id}/read").json()["read"] is True
    assert client.get("/inbox?unread_only=true").json() == []
    assert client.post(f"/inbox/{email.id}/read?read=false").json()["read"] is False
    assert len(client.get("/inbox?unread_only=true").json()) == 1


def test_email_commitments_are_scoped_to_their_owner(client, db, user, other_client) -> None:
    db.add(
        Commitment(
            owner_user_id=user.id,
            assigned_user_id=user.id,
            text="Send the revised scope",
            status="pending",
            evidence="Email from ravi@acme.com",
        )
    )
    db.commit()
    assert other_client.get("/promisemirror/commitments").json() == []
