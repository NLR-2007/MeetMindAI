"""Teams: one bot covers a meeting instead of one bot per attendee.

Four people in a call previously meant four bots, four transcripts and four
copies of the same conversation, because a meeting had exactly one owner. A
team lets one meeting be read by everyone who was in it, while promises,
coaching and progress stay personal.

Creates `teams`, `team_memberships`, `team_invites`, and adds
`meetings.team_id`. Idempotent: safe to run more than once.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from app.db import Base, engine, init_db

NEW_TABLES = ("teams", "team_memberships", "team_invites")


def main() -> None:
    # init_db creates anything missing from the metadata, which covers the
    # three new tables on a fresh database.
    init_db()
    import app.models  # noqa: F401  (register mappers)

    Base.metadata.create_all(
        engine,
        tables=[Base.metadata.tables[name] for name in NEW_TABLES],
        checkfirst=True,
    )
    insp = inspect(engine)
    for name in NEW_TABLES:
        print(f"  {'=' if name in insp.get_table_names() else '!'} {name}")

    with engine.begin() as conn:
        columns = {c["name"] for c in insp.get_columns("meetings")}
        if "team_id" in columns:
            print("  = meetings.team_id")
        else:
            conn.execute(
                text("ALTER TABLE meetings ADD COLUMN team_id VARCHAR(32) NULL")
            )
            print("  + meetings.team_id")
            try:
                conn.execute(
                    text("CREATE INDEX ix_meetings_team_id ON meetings (team_id)")
                )
                print("  + ix_meetings_team_id")
            except Exception as exc:  # pragma: no cover - index may exist
                print(f"  ! index not created: {exc}")

    # Existing meetings keep team_id NULL, which means "personal". Nothing is
    # retroactively shared with anyone.
    print("Migration 006 complete.")


if __name__ == "__main__":
    main()
