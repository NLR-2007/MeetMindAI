"""Registration, sign-in and the caller's own profile."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import current_user
from app.models import Project, User
from app.services.security import create_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    name: str | None = Field(default=None, max_length=255)
    role: str = Field(default="employee", pattern="^(employee|manager)$")
    # Required for employees: it is what puts them on a team and what scopes
    # commitment name-matching. Managers leave it empty.
    manager_email: EmailStr | None = None

    @model_validator(mode="after")
    def _employees_need_a_manager(self) -> "RegisterRequest":
        if self.role == "employee" and not self.manager_email:
            raise ValueError(
                "Employees must give their manager's email so their work is "
                "mapped to the right team."
            )
        if self.role == "manager" and self.manager_email:
            raise ValueError("Managers do not report to a manager in MeetMind.")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    email: str
    name: str | None = None
    role: str = "employee"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str | None = None
    role: str = "employee"
    manager_id: str | None = None
    display_names: list[str] | None = None


class TeamMemberOut(BaseModel):
    id: str
    email: str
    name: str | None = None
    role: str


class AliasUpdate(BaseModel):
    # Names this person is called in meetings, e.g. ["Bunny", "Bunny Reddy"].
    display_names: list[str] = Field(default_factory=list, max_length=10)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        # An unclaimed pre-auth account can be claimed by setting a password.
        if existing.password_hash is None:
            existing.password_hash = hash_password(payload.password)
            existing.name = payload.name or existing.name
            db.flush()
            return _token(settings, existing)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with that email already exists.",
        )

    manager_id = None
    if payload.manager_email:
        manager = db.scalar(select(User).where(User.email == payload.manager_email))
        if manager is None or manager.role != "manager":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "No manager account exists with that email. Ask your manager "
                    "to register first, then use the address they signed up with."
                ),
            )
        manager_id = manager.id

    aliases = [a for a in [payload.name, payload.email.split("@")[0]] if a]
    user = User(
        email=payload.email,
        name=payload.name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        manager_id=manager_id,
        display_names=aliases,
    )
    db.add(user)
    db.flush()

    # Everyone needs somewhere to file meetings.
    db.add(Project(name="General", description="Default project", owner_id=user.id))
    db.flush()

    logger.info("Registered user %s", user.id)
    return _token(settings, user)


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    # Same message either way: do not reveal which emails are registered.
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled.")
    return _token(settings, user)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.put("/me/aliases", response_model=UserOut)
def set_aliases(
    payload: AliasUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> UserOut:
    """Set the names you are called in meetings, so commitments find you."""
    cleaned = [a.strip() for a in payload.display_names if a and a.strip()]
    user.display_names = cleaned or [user.name or user.email.split("@")[0]]
    db.flush()
    return UserOut.model_validate(user)


@router.get("/team", response_model=list[TeamMemberOut])
def team(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[TeamMemberOut]:
    """Who this account can see. Employees see only themselves."""
    from app.services.team import team_user_ids

    ids = team_user_ids(db, user)
    rows = db.scalars(select(User).where(User.id.in_(ids)).order_by(User.name))
    return [
        TeamMemberOut(id=u.id, email=u.email, name=u.name, role=u.role) for u in rows
    ]


def _token(settings: Settings, user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(settings, user.id, user.email),
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
    )
