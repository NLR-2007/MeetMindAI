"""Add roles, the manager hierarchy, and commitment assignment.

Idempotent and additive: existing users default to "employee" and keep every
row they already own.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text  # noqa: E402

from app.db import engine, init_db  # noqa: E402

COLUMNS = {
    "users": [
        ("role", "VARCHAR(16) NOT NULL DEFAULT 'employee'"),
        ("manager_id", "VARCHAR(32) NULL"),
        ("display_names", "JSON NULL"),
    ],
    "commitments": [("assigned_user_id", "VARCHAR(32) NULL")],
}

INDEXES = [
    ("users", "ix_users_manager_id", "manager_id"),
    ("commitments", "ix_commitments_assigned_user_id", "assigned_user_id"),
]


def main() -> None:
    init_db()
    insp = inspect(engine)

    with engine.begin() as conn:
        for table, cols in COLUMNS.items():
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name in existing:
                    print(f"  = {table}.{name}")
                else:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    print(f"  + {table}.{name}")

        for table, index, col in INDEXES:
            names = {i["name"] for i in insp.get_indexes(table)}
            if index in names:
                print(f"  = index {index}")
            else:
                conn.execute(text(f"CREATE INDEX {index} ON {table} ({col})"))
                print(f"  + index {index}")

        # Seed each user's own name as a transcript alias so commitment
        # assignment has something to match on from day one.
        rows = conn.execute(
            text("SELECT id, name, email FROM users WHERE display_names IS NULL")
        ).fetchall()
        for uid, name, email in rows:
            aliases = [a for a in [name, (email or "").split("@")[0]] if a]
            conn.execute(
                text("UPDATE users SET display_names = :d WHERE id = :i"),
                {"d": json.dumps(aliases), "i": uid},
            )
        print(f"  ~ seeded display names for {len(rows)} user(s)")


if __name__ == "__main__":
    print("Running migration 003_roles_and_assignment")
    main()
    print("Done.")
