"""Co-Work: the Lead runs the door, and work can come from a meeting.

Two changes:

1. The space creator is a "lead" rather than an "owner". The rename is not
   cosmetic — their authority is now only over admission. Over anyone else's
   task a Lead is read-only, exactly like every other member.
2. A space can point at the meeting its work came out of, and a task can
   record the meeting and the spoken name it was lifted from.

Idempotent: safe to run more than once.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from app.db import engine, init_db

COLUMNS = {
    "coworkspaces": [("meeting_id", "VARCHAR(32) NULL")],
    "cowork_tasks": [
        ("source_meeting_id", "VARCHAR(32) NULL"),
        ("spoken_owner", "VARCHAR(255) NULL"),
    ],
}


def main() -> None:
    init_db()
    insp = inspect(engine)
    tables = set(insp.get_table_names())

    with engine.begin() as conn:
        for table, columns in COLUMNS.items():
            if table not in tables:
                print(f"  ! {table} missing; run 008 first")
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in columns:
                if name in existing:
                    print(f"  = {table}.{name}")
                else:
                    conn.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
                    )
                    print(f"  + {table}.{name}")

        if "cowork_memberships" in tables:
            result = conn.execute(
                text(
                    "UPDATE cowork_memberships SET role = 'lead' WHERE role = 'owner'"
                )
            )
            print(f"  ~ {result.rowcount} membership(s) owner -> lead")

    print("Migration 009 complete.")


if __name__ == "__main__":
    main()
