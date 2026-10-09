"""Commitments record who held them before they changed hands.

A promise can move during a meeting: someone takes it, then says they cannot
do it after all. Until now only the final owner survived, so a handoff looked
identical to a promise that was always someone else's, and a promise dropped
with nobody picking it up quietly disappeared from its original owner.

`reassigned_from` carries the previous holder:

    owner_name set,  reassigned_from null -> ordinary ownership
    owner_name set,  reassigned_from set  -> handed from one person to another
    owner_name null, reassigned_from set  -> given up, nobody took it

Idempotent: safe to run more than once.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from app.db import engine, init_db

TABLES = {
    "action_items": [("reassigned_from", "VARCHAR(255) NULL")],
    "commitments": [("reassigned_from", "VARCHAR(255) NULL")],
}


def main() -> None:
    init_db()
    insp = inspect(engine)

    with engine.begin() as conn:
        for table, columns in TABLES.items():
            if table not in insp.get_table_names():
                print(f"  ! {table} does not exist yet; skipping")
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

    # Existing rows keep reassigned_from NULL, which reads as "never changed
    # hands". That is the truthful default: nothing in the old data recorded
    # a handoff, so none is claimed.
    print("Migration 005 complete.")


if __name__ == "__main__":
    main()
