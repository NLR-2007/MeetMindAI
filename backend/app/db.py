"""SQLAlchemy engine/session wiring."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()

if not _settings.database_url:
    raise RuntimeError(
        "DATABASE_URL is not set. Copy .env.example to .env and point it at MySQL, "
        "e.g. mysql+pymysql://root:@127.0.0.1:3306/meetmind?charset=utf8mb4"
    )

engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,   # XAMPP drops idle connections; revalidate before use.
    pool_recycle=280,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create tables that do not exist yet."""
    from app import models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=engine)
