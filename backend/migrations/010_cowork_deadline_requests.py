"""Co-Work deadline changes require Lead approval.

Members can request a new due date, but the task date only moves when the
Lead approves the request.

Idempotent: safe to run more than once.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text

from app.db import engine, init_db


def main() -> None:
    init_db()
    insp = inspect(engine)
    tables = set(insp.get_table_names())

    if "cowork_deadline_requests" in tables:
        print("  = cowork_deadline_requests")
        print("Migration 010 complete.")
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE cowork_deadline_requests (
                    id VARCHAR(32) NOT NULL PRIMARY KEY,
                    workspace_id VARCHAR(32) NOT NULL,
                    task_id VARCHAR(32) NOT NULL,
                    requester_id VARCHAR(32) NULL,
                    current_due_at DATETIME NULL,
                    requested_due_at DATETIME NOT NULL,
                    reason TEXT NULL,
                    status VARCHAR(16) NOT NULL DEFAULT 'pending',
                    decided_by VARCHAR(32) NULL,
                    decided_at DATETIME NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    INDEX ix_cowork_deadline_requests_workspace_id (workspace_id),
                    INDEX ix_cowork_deadline_requests_task_id (task_id),
                    INDEX ix_cowork_deadline_requests_requester_id (requester_id)
                )
                """
            )
        )
        print("  + cowork_deadline_requests")

    print("Migration 010 complete.")


if __name__ == "__main__":
    main()
