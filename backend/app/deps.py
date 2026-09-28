"""Shared request dependencies: the authenticated user and tenant scoping."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Meeting, Project, User
from app.services.security import decode_access_token

# auto_error=False so a missing header produces our own 401 message.
bearer = HTTPBearer(auto_error=False)

CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated. Sign in and send 'Authorization: Bearer <token>'.",
    headers={"WWW-Authenticate": "Bearer"},
)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if creds is None or not creds.credentials:
        raise CREDENTIALS_ERROR

    payload = decode_access_token(settings, creds.credentials)
    if not payload or not payload.get("sub"):
        raise CREDENTIALS_ERROR

    user = db.get(User, payload["sub"])
    if user is None or not user.is_active:
        raise CREDENTIALS_ERROR
    return user


def owned_meeting(
    meeting_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Meeting:
    """Fetch a meeting the caller owns.

    Returns 404 rather than 403 for someone else's meeting: confirming a
    resource exists is itself a disclosure.
    """
    meeting = db.get(Meeting, meeting_id)
    if meeting is None or meeting.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown meeting_id {meeting_id}",
        )
    return meeting


def owned_project(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Project:
    project = db.get(Project, project_id)
    if project is None or project.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown project_id {project_id}",
        )
    return project


def get_or_create_default_user(db: Session, settings: Settings) -> User:
    """The owner assigned to data created before authentication existed."""
    user = db.scalar(select(User).where(User.email == settings.default_user_email))
    if user is None:
        user = User(email=settings.default_user_email, name="Demo User")
        db.add(user)
        db.flush()
    return user
