"""Team visibility and commitment-to-person mapping.

Two rules govern everything here:

* **An employee sees only their own work.** A manager additionally sees their
  direct reports'. Nobody ever sees another team.
* **A transcript name is only ever matched to someone on the same team.**
  "Bunny" in your meeting can never resolve to a Bunny in another company's
  workspace, because candidates are drawn from the team scope, not the whole
  user table.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import Commitment, User

logger = logging.getLogger(__name__)

MANAGER = "manager"
EMPLOYEE = "employee"


def team_user_ids(db: Session, user: User) -> list[str]:
    """User ids this person is allowed to see.

    Employees: just themselves. Managers: themselves plus direct reports.
    """
    if user.role != MANAGER:
        return [user.id]

    reports = db.scalars(select(User.id).where(User.manager_id == user.id))
    return [user.id, *reports]


def teammates(db: Session, user: User) -> list[User]:
    """Everyone whose names may be matched against this user's transcripts.

    For an employee that is their manager and their manager's other reports;
    for a manager it is themselves and their reports. Restricting the candidate
    pool is what prevents cross-team mapping.
    """
    if user.role == MANAGER:
        rows = db.scalars(
            select(User).where(or_(User.id == user.id, User.manager_id == user.id))
        )
        return list(rows)

    if user.manager_id:
        rows = db.scalars(
            select(User).where(
                or_(
                    User.id == user.id,
                    User.id == user.manager_id,
                    User.manager_id == user.manager_id,
                )
            )
        )
        return list(rows)

    return [user]


def _aliases(u: User) -> list[str]:
    names = list(u.display_names or [])
    if u.name:
        names.append(u.name)
        names.extend(u.name.split())
    if u.email:
        names.append(u.email.split("@")[0])
    # Longest first so "Bunny Reddy" wins over "Bunny".
    seen: dict[str, None] = {}
    for n in names:
        n = (n or "").strip().lower()
        if len(n) >= 3:
            seen.setdefault(n, None)
    return sorted(seen, key=len, reverse=True)


def resolve_person(owner_name: str | None, candidates: Iterable[User]) -> User | None:
    """Map a name spoken in a meeting to a real user, or None.

    Returns None rather than guessing when the name is absent, too short, or
    matches more than one person: a commitment on the wrong person's dashboard
    is worse than one that is merely unassigned.
    """
    if not owner_name:
        return None

    needle = re.sub(r"[^a-z\s]", "", owner_name.lower()).strip()
    if len(needle) < 3:
        return None

    matches: list[User] = []
    for user in candidates:
        for alias in _aliases(user):
            if alias == needle or alias in needle or needle in alias:
                matches.append(user)
                break

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        logger.info(
            "Ambiguous owner %r matched %d people; leaving unassigned",
            owner_name,
            len(matches),
        )
    return None


def assign_commitments(db: Session, owner: User) -> dict[str, int]:
    """Resolve owner_name to a real user for this owner's commitments."""
    candidates = teammates(db, owner)
    rows = db.scalars(
        select(Commitment).where(
            Commitment.owner_user_id == owner.id,
            Commitment.assigned_user_id.is_(None),
        )
    )

    assigned = unresolved = 0
    for c in rows:
        person = resolve_person(c.owner_name, candidates)
        if person is not None:
            c.assigned_user_id = person.id
            assigned += 1
        else:
            unresolved += 1
    db.flush()
    return {"assigned": assigned, "unresolved": unresolved}


def own_commitments_filter(user: User):
    """Commitments that are this person's own work.

    Recording a meeting does not make its promises yours. A manager who ran
    the standup owns those rows, but the work belongs to whoever was named.
    So "mine" means: assigned to me, or recorded by me and assigned to nobody.
    """
    return or_(
        Commitment.assigned_user_id == user.id,
        and_(
            Commitment.owner_user_id == user.id,
            Commitment.assigned_user_id.is_(None),
        ),
    )


def visible_commitments_filter(db: Session, user: User):
    """Commitments the user may READ, including a manager's reports'.

    Read-only by design: the team section never offers write actions, because
    marking someone else's promise complete is their call, not their manager's.
    """
    ids = team_user_ids(db, user)
    return or_(
        Commitment.owner_user_id.in_(ids),
        Commitment.assigned_user_id.in_(ids),
    )


def can_modify(user: User, commitment: Commitment) -> bool:
    """Whether this user may change a commitment's status.

    Once a commitment is assigned, only the assignee may close it — not even
    the manager who recorded the meeting. Completion is a statement about your
    own work, so it is not someone else's to make.
    """
    if commitment.assigned_user_id:
        return commitment.assigned_user_id == user.id
    return commitment.owner_user_id == user.id
