"""Create the Mark Up, PromiseMirror and coaching tables."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect  # noqa: E402

from app.db import engine, init_db  # noqa: E402

NEW = ["commitments", "prep_plans", "practice_sessions", "coaching_notes"]


def main() -> None:
    before = set(inspect(engine).get_table_names())
    init_db()  # create_all is additive; it never drops or alters
    after = set(inspect(engine).get_table_names())
    for t in NEW:
        print(("  + created " if t in after - before else "  = exists  ") + t)
    missing = [t for t in NEW if t not in after]
    if missing:
        raise SystemExit(f"FAILED to create: {missing}")


if __name__ == "__main__":
    print("Running migration 002_markup_promisemirror")
    main()
    print("Done.")
