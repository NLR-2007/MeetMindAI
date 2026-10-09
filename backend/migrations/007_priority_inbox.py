"""Priority inbox: the senders that matter, and what their mail contained.

Commitments do not only happen in meetings. "I'll send the revised scope by
Friday" in an email is the same object PromiseMirror already tracks, so mail
from named senders feeds the same ledger.

Creates `priority_senders` and `inbound_emails`. Message bodies are
deliberately not stored - only the summary, highlights and any commitments.

Idempotent: safe to run more than once.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect

from app.db import Base, engine, init_db

NEW_TABLES = ("priority_senders", "inbound_emails")


def main() -> None:
    init_db()
    import app.models  # noqa: F401  (register mappers)

    Base.metadata.create_all(
        engine,
        tables=[Base.metadata.tables[name] for name in NEW_TABLES],
        checkfirst=True,
    )
    present = set(inspect(engine).get_table_names())
    for name in NEW_TABLES:
        print(f"  {'=' if name in present else '!'} {name}")

    print(
        "\nGmail access also needs, in Google Cloud Console:\n"
        "  1. APIs & Services > Library > Gmail API > Enable\n"
        "  2. OAuth consent screen > Data access > add the scope\n"
        "     https://www.googleapis.com/auth/gmail.readonly\n"
        "  3. Reconnect Google Calendar in MeetMind so the new permission is\n"
        "     actually granted - an existing connection does not have it."
    )
    print("Migration 007 complete.")


if __name__ == "__main__":
    main()
