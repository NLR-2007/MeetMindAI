"""Coaching notes record what was said and what to say next time.

Also clears coaching notes generated before feedback was scoped to a single
speaker: in a multi-person meeting those could quote another participant, so
they are not safe to keep.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text  # noqa: E402

from app.db import engine, init_db  # noqa: E402

COLUMNS = [
    ("said", "TEXT NULL"),
    ("better", "TEXT NULL"),
]


def main() -> None:
    init_db()
    insp = inspect(engine)

    with engine.begin() as conn:
        existing = {c["name"] for c in insp.get_columns("coaching_notes")}
        for name, ddl in COLUMNS:
            if name in existing:
                print(f"  = coaching_notes.{name}")
            else:
                conn.execute(
                    text(f"ALTER TABLE coaching_notes ADD COLUMN {name} {ddl}")
                )
                print(f"  + coaching_notes.{name}")

        # Old notes were produced from the whole transcript, so their evidence
        # may belong to someone else. Regenerating is cheap; mis-attribution
        # is not.
        stale = conn.execute(
            text("SELECT COUNT(*) FROM coaching_notes WHERE said IS NULL")
        ).scalar()
        if stale:
            conn.execute(text("DELETE FROM coaching_notes WHERE said IS NULL"))
            print(f"  ~ removed {stale} note(s) from before speaker scoping")
        else:
            print("  = no pre-scoping notes to remove")


if __name__ == "__main__":
    print("Running migration 004_speaker_scoped_coaching")
    main()
    print("Done.")
