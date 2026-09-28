"""Test fixtures.

Tests run against a throwaway SQLite database, never the real MySQL schema,
and every Recall/Groq call is mocked so no bot minutes or tokens are spent.
"""
from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Config is read at import time, so these must be set before app modules load.
os.environ.setdefault("RECALL_API_KEY", "test_key_0123456789")
os.environ.setdefault("RECALL_REGION", "us-west-2")
os.environ.setdefault("GROQ_API_KEY", "test_groq_key")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

test_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _schema() -> Iterator[None]:
    import app.models  # noqa: F401  (register mappers)

    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db() -> Iterator[Session]:
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _override_db() -> Iterator[None]:
    def _get_test_db() -> Iterator[Session]:
        session = TestSession()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = _get_test_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def anon_client():
    """Unauthenticated client, for testing the auth boundary itself."""
    from fastapi.testclient import TestClient

    # No context manager: lifespan would try to reach the real MySQL.
    return TestClient(app)


@pytest.fixture
def user(db: Session):
    """A registered user owning everything the tests create."""
    from app.models import User
    from app.services.security import hash_password

    u = User(
        email="tester@example.com",
        name="Tester",
        password_hash=hash_password("testpassword123"),
    )
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def client(user):
    """Authenticated client for the fixture user."""
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.services.security import create_access_token

    c = TestClient(app)
    token = create_access_token(get_settings(), user.id, user.email)
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


@pytest.fixture
def other_client(db: Session):
    """A second user, for proving tenant isolation."""
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.models import User
    from app.services.security import create_access_token, hash_password

    other = User(
        email="intruder@example.com",
        name="Intruder",
        password_hash=hash_password("intruderpass123"),
    )
    db.add(other)
    db.commit()

    c = TestClient(app)
    token = create_access_token(get_settings(), other.id, other.email)
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c
