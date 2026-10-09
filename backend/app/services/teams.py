"""Team membership, invites, and what a team actually grants.

A team exists so one bot can cover a meeting that several colleagues attend,
instead of each of them sending their own. That is the whole purpose, and the
visibility rules follow from it:

* A team meeting is readable by every member, because everyone in the room
  already heard the conversation.
* A member only sees meetings recorded **after** they joined. Joining a team
  must never hand over conversations they were not part of.
* Promises, coaching and progress stay personal. Membership is not a
  reporting line, and deliberately does not reinstate the manager rollup that
  was removed.
"""
from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Meeting, Team, TeamInvite, TeamMembership, User

logger = logging.getLogger(__name__)

# Long enough that guessing is hopeless, short enough to paste in chat.
TOKEN_BYTES = 24
DEFAULT_INVITE_DAYS = 7
DEFAULT_MAX_USES = 25


def create_team(db: Session, *, name: str, owner: User) -> Team:
    """Create a team with its creator as the first member and owner."""
    team = Team(name=name.strip(), owner_id=owner.id)
    db.add(team)
    db.flush()
    db.add(
        TeamMembership(
            team_id=team.id,
            user_id=owner.id,
            role="owner",
            # Backdated so the creator can see meetings they record straight
            # away, rather than racing their own join timestamp.
            joined_at=datetime.now(UTC) - timedelta(seconds=1),
        )
    )
    db.flush()
    db.refresh(team)
    return team


def memberships_of(db: Session, user: User) -> list[TeamMembership]:
    return list(
        db.scalars(select(TeamMembership).where(TeamMembership.user_id == user.id))
    )


def team_ids_for(db: Session, user: User) -> list[str]:
    return [m.team_id for m in memberships_of(db, user)]


def membership(db: Session, team_id: str, user: User) -> TeamMembership | None:
    return db.scalars(
        select(TeamMembership).where(
            TeamMembership.team_id == team_id, TeamMembership.user_id == user.id
        )
    ).first()


def is_member(db: Session, team_id: str | None, user: User) -> bool:
    return bool(team_id) and membership(db, team_id, user) is not None


def members_of(db: Session, team_id: str) -> list[User]:
    rows = db.scalars(
        select(TeamMembership).where(TeamMembership.team_id == team_id)
    ).all()
    return [m.user for m in rows if m.user is not None]


def can_read_meeting(db: Session, meeting: Meeting, user: User) -> bool:
    """May this person read this meeting at all?

    Either they dispatched the bot, or they were already in the team when it
    was recorded. The join cut-off is the important half: without it, being
    added to a team would retroactively expose its entire history.
    """
    if meeting.owner_id == user.id:
        return True
    if not meeting.team_id:
        return False
    member = membership(db, meeting.team_id, user)
    if member is None:
        return False
    recorded = meeting.created_at
    if recorded is None:
        return True
    if recorded.tzinfo is None:
        recorded = recorded.replace(tzinfo=UTC)
    joined = member.joined_at
    if joined.tzinfo is None:
        joined = joined.replace(tzinfo=UTC)
    return recorded >= joined


def visible_meetings_filter(db: Session, user: User):
    """SQL filter for every meeting this person may read.

    Their own, plus team meetings recorded after they joined that team.
    """
    clauses = [Meeting.owner_id == user.id]
    for member in memberships_of(db, user):
        joined = member.joined_at
        if joined.tzinfo is not None:
            joined = joined.replace(tzinfo=None)
        clauses.append(
            (Meeting.team_id == member.team_id) & (Meeting.created_at >= joined)
        )
    return or_(*clauses)


# --- invites --------------------------------------------------------------


def create_invite(
    db: Session,
    *,
    team: Team,
    created_by: User,
    days: int = DEFAULT_INVITE_DAYS,
    max_uses: int = DEFAULT_MAX_USES,
) -> TeamInvite:
    invite = TeamInvite(
        team_id=team.id,
        token=secrets.token_urlsafe(TOKEN_BYTES),
        created_by=created_by.id,
        expires_at=datetime.now(UTC) + timedelta(days=days),
        max_uses=max_uses,
    )
    db.add(invite)
    db.flush()
    return invite


def invite_problem(invite: TeamInvite | None) -> str | None:
    """Why this invite cannot be used, or None if it can.

    One function so the join endpoint and any preview agree on the rules.
    """
    if invite is None:
        return "This invite link is not valid."
    if invite.revoked_at is not None:
        return "This invite link has been revoked."
    expires = invite.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < datetime.now(UTC):
        return "This invite link has expired."
    if invite.uses >= invite.max_uses:
        return "This invite link has already been used the maximum number of times."
    return None


def accept_invite(db: Session, *, token: str, user: User) -> tuple[Team | None, str | None]:
    """Join a team by invite token. Returns (team, error)."""
    invite = db.scalars(select(TeamInvite).where(TeamInvite.token == token)).first()
    problem = invite_problem(invite)
    if problem or invite is None:
        return None, problem or "This invite link is not valid."

    team = db.get(Team, invite.team_id)
    if team is None:
        return None, "That team no longer exists."

    existing = membership(db, team.id, user)
    if existing is not None:
        # Already in: not an error, and the invite is not spent on a no-op.
        return team, None

    db.add(
        TeamMembership(team_id=team.id, user_id=user.id, role="member")
    )
    invite.uses += 1
    db.flush()
    logger.info("User %s joined team %s", user.id, team.id)
    return team, None
