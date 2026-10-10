"""MeetMind Co-Work: shared progress for people doing one piece of work.

Everywhere else in MeetMind progress is private. Co-Work is the deliberate
exception, which is why it is a separate space with its own door: you ask to
join via its own link, the owner decides, and only then does your progress
become visible to that room. Only the assignee may close their own task.

Creates `coworkspaces`, `cowork_memberships`, `cowork_join_requests` and
`cowork_tasks`. Idempotent: safe to run more than once.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect

from app.db import Base, engine, init_db

NEW_TABLES = (
    "coworkspaces",
    "cowork_memberships",
    "cowork_join_requests",
    "cowork_tasks",
)


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

    print("Migration 008 complete.")


if __name__ == "__main__":
    main()
