"""Team endpoints: create, invite, join, leave.

A team's only power is that one bot can cover a meeting several colleagues
attend. It grants read access to those meetings and nothing else — see
`app.services.teams` for the rules.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import current_user
from app.models import Meeting, Team, TeamInvite, User
from app.services import teams as team_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/teams", tags=["teams"])


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class MemberOut(BaseModel):
    user_id: str
    name: str | None
    email: str
    role: str
    is_you: bool


class TeamOut(BaseModel):
    id: str
    name: str
    role: str
    member_count: int
    meeting_count: int
    is_owner: bool


class InviteOut(BaseModel):
    token: str
    expires_at: str
    max_uses: int
    uses: int
    url: str


def _team_or_404(db: Session, team_id: str, user: User) -> Team:
    """Fetch a team the caller belongs to.

    404 rather than 403 for a team you are not in: confirming it exists is
    itself a disclosure.
    """
    team = db.get(Team, team_id)
    if team is None or not team_service.is_member(db, team.id, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown team {team_id}"
        )
    return team


def _out(db: Session, team: Team, user: User) -> TeamOut:
    member = team_service.membership(db, team.id, user)
    return TeamOut(
        id=team.id,
        name=team.name,
        role=member.role if member else "member",
        member_count=len(team.memberships),
        meeting_count=len(
            db.scalars(select(Meeting.id).where(Meeting.team_id == team.id)).all()
        ),
        is_owner=bool(member and member.role == "owner"),
    )


@router.get("", response_model=list[TeamOut])
def list_teams(
    db: Session = Depends(get_db), user: User = Depends(current_user)
) -> list[TeamOut]:
    rows = [m.team for m in team_service.memberships_of(db, user) if m.team]
    return [_out(db, t, user) for t in sorted(rows, key=lambda t: t.name.lower())]


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
def create_team(
    payload: TeamCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> TeamOut:
    team = team_service.create_team(db, name=payload.name, owner=user)
    return _out(db, team, user)


@router.get("/{team_id}/members", response_model=list[MemberOut])
def list_members(
    team_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[MemberOut]:
    team = _team_or_404(db, team_id, user)
    out: list[MemberOut] = []
    for m in team.memberships:
        if m.user is None:
            continue
        out.append(
            MemberOut(
                user_id=m.user.id,
                name=m.user.name,
                email=m.user.email,
                role=m.role,
                is_you=m.user.id == user.id,
            )
        )
    return sorted(out, key=lambda m: (m.role != "owner", (m.name or m.email).lower()))


@router.post("/{team_id}/invites", response_model=InviteOut, status_code=201)
def create_invite(
    team_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
) -> InviteOut:
    """Mint a join link. Only a team owner may hand out access."""
    team = _team_or_404(db, team_id, user)
    member = team_service.membership(db, team.id, user)
    if member is None or member.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a team owner can create invite links.",
        )
    invite = team_service.create_invite(db, team=team, created_by=user)
    frontend = settings.cors_origin_list[0] if settings.cors_origin_list else ""
    return InviteOut(
        token=invite.token,
        expires_at=invite.expires_at.isoformat(),
        max_uses=invite.max_uses,
        uses=invite.uses,
        url=f"{frontend}/teams/join?token={invite.token}",
    )


@router.post("/{team_id}/invites/revoke", status_code=200)
def revoke_invites(
    team_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Kill every outstanding link for this team at once.

    An invite link is a credential; being able to withdraw it in one action
    matters more than being able to withdraw them individually.
    """
    team = _team_or_404(db, team_id, user)
    member = team_service.membership(db, team.id, user)
    if member is None or member.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a team owner can revoke invite links.",
        )
    now = datetime.now(UTC)
    live = [
        i
        for i in db.scalars(
            select(TeamInvite).where(
                TeamInvite.team_id == team.id, TeamInvite.revoked_at.is_(None)
            )
        )
        if True
    ]
    for invite in live:
        invite.revoked_at = now
    db.flush()
    return {"revoked": len(live)}


class JoinRequest(BaseModel):
    token: str = Field(min_length=8, max_length=128)


@router.post("/join", response_model=TeamOut)
def join_team(
    payload: JoinRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> TeamOut:
    team, error = team_service.accept_invite(db, token=payload.token, user=user)
    if error or team is None:
        # 400, not 404: the caller is authenticated and the link is simply bad.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error or "This invite link is not valid.",
        )
    return _out(db, team, user)


@router.post("/{team_id}/leave", status_code=200)
def leave_team(
    team_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Leave a team. Meetings already recorded stay with the team."""
    team = _team_or_404(db, team_id, user)
    member = team_service.membership(db, team.id, user)
    if member is None:
        raise HTTPException(status_code=404, detail="You are not in this team.")
    owners = [m for m in team.memberships if m.role == "owner"]
    if member.role == "owner" and len(owners) == 1 and len(team.memberships) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "You are the only owner. Make someone else an owner before "
                "leaving, or remove the other members first."
            ),
        )
    db.delete(member)
    db.flush()
    return {"left": True, "team_id": team.id}
