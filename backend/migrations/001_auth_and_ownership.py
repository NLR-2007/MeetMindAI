"""Add auth columns and attach pre-auth data to a default owner.

Idempotent: safe to run repeatedly. create_all() never ALTERs existing tables,
so column additions are explicit here.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import engine, init_db  # noqa: E402

COLUMNS = {
    "users": [
        ("password_hash", "VARCHAR(255) NULL"),
        ("is_active", "TINYINT(1) NOT NULL DEFAULT 1"),
    ],
}


def main() -> None:
    init_db()  # create any brand-new tables
    insp = inspect(engine)
    settings = get_settings()

    with engine.begin() as conn:
        for table, cols in COLUMNS.items():
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols:
                if name in existing:
                    print(f"  = {table}.{name} already present")
                else:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    print(f"  + added {table}.{name}")

        # A home for data created before authentication existed.
        email = settings.default_user_email
        row = conn.execute(
            text("SELECT id FROM users WHERE email = :e"), {"e": email}
        ).first()
        if row:
            user_id = row[0]
            print(f"  = default user exists ({email})")
        else:
            user_id = __import__("uuid").uuid4().hex
            conn.execute(
                text(
                    "INSERT INTO users (id, email, name, is_active, created_at, updated_at)"
                    " VALUES (:i, :e, :n, 1, UTC_TIMESTAMP(), UTC_TIMESTAMP())"
                ),
                {"i": user_id, "e": email, "n": "Demo User"},
            )
            print(f"  + created default user {email}")

        proj = conn.execute(
            text("SELECT id FROM projects WHERE owner_id = :u LIMIT 1"), {"u": user_id}
        ).first()
        if proj:
            project_id = proj[0]
            print("  = default project exists")
        else:
            project_id = __import__("uuid").uuid4().hex
            conn.execute(
                text(
                    "INSERT INTO projects (id, name, description, owner_id, created_at, updated_at)"
                    " VALUES (:i, 'General', 'Meetings recorded before projects existed',"
                    " :u, UTC_TIMESTAMP(), UTC_TIMESTAMP())"
                ),
                {"i": project_id, "u": user_id},
            )
            print("  + created default project 'General'")

        # Backfill, never overwrite.
        n = conn.execute(
            text("UPDATE meetings SET owner_id = :u WHERE owner_id IS NULL"),
            {"u": user_id},
        ).rowcount
        print(f"  ~ meetings given an owner: {n}")
        n = conn.execute(
            text("UPDATE meetings SET project_id = :p WHERE project_id IS NULL"),
            {"p": project_id},
        ).rowcount
        print(f"  ~ meetings given a project: {n}")
        n = conn.execute(
            text("UPDATE calendars SET owner_id = :u WHERE owner_id IS NULL"),
            {"u": user_id},
        ).rowcount
        print(f"  ~ calendars given an owner: {n}")


if __name__ == "__main__":
    print("Running migration 001_auth_and_ownership")
    main()
    print("Done.")
