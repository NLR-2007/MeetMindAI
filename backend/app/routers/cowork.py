"""MeetMind Co-Work endpoints: spaces, admission, and a shared task board."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.deps import current_user
from app.models import (
    CoWorkDeadlineChangeRequest,
    CoWorkJoinRequest,
    CoWorkspace,
    CoWorkTask,
    Meeting,
    User,
)
from app.services import cowork
from app.services import teams as team_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cowork", tags=["cowork"])


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    purpose: str | None = Field(default=None, max_length=2000)
    team_id: str | None = None


class MemberOut(BaseModel):
    user_id: str
    name: str | None
    email: str
    role: str
    is_you: bool
    # Everyone's standing is visible here; that is the point of the space.
    total: int
    done: int
    percent: int


class TaskOut(BaseModel):
    id: str
    title: str
    detail: str | None
    status: str
    assignee_id: str | None
    assignee_name: str | None
    due_at: str | None
    completed_at: str | None
    # Whether the caller may change this task at all, so the UI never offers
    # a control the backend will refuse.
    can_update: bool
    # Nobody holds it, so anyone in the room may take it on.
    can_claim: bool
    # Set when the task came out of a meeting rather than being typed in.
    source_meeting_id: str | None
    spoken_owner: str | None
    overdue: bool
    pending_deadline_request_id: str | None


class RequestOut(BaseModel):
    id: str
    user_id: str
    name: str | None
    email: str
    status: str
    note: str | None
    created_at: str


class DeadlineRequestOut(BaseModel):
    id: str
    task_id: str
    task_title: str
    requester_id: str | None
    requester_name: str | None
    requester_email: str | None
    current_due_at: str | None
    requested_due_at: str
    reason: str | None
    status: str
    created_at: str


class WorkspaceOut(BaseModel):
    id: str
    name: str
    purpose: str | None
    team_id: str | None
    meeting_id: str | None
    meeting_title: str | None
    is_lead: bool
    join_url: str | None
    member_count: int
    pending_requests: int
    progress: dict[str, int]


def _space_or_404(db: Session, workspace_id: str, user: User) -> CoWorkspace:
    space = db.get(CoWorkspace, workspace_id)
    if space is None or not cowork.is_member(db, space.id, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown Co-Work space {workspace_id}",
        )
    return space


def _space_out(
    db: Session, space: CoWorkspace, user: User, settings: Settings
) -> WorkspaceOut:
    lead = cowork.is_lead(db, space.id, user)
    frontend = settings.cors_origin_list[0] if settings.cors_origin_list else ""
    pending = sum(1 for r in space.requests if r.status == "pending")
    return WorkspaceOut(
        id=space.id,
        name=space.name,
        purpose=space.purpose,
        team_id=space.team_id,
        meeting_id=space.meeting_id,
        meeting_title=(
            (space.meeting.title or space.meeting.meeting_url)
            if space.meeting
            else None
        ),
        is_lead=lead,
        # Only a Lead can hand out admission, so only a Lead sees the link.
        join_url=(
            f"{frontend}/cowork/join?token={space.join_token}" if lead else None
        ),
        member_count=len(space.memberships),
        pending_requests=pending if lead else 0,
        progress=cowork.progress_for(list(space.tasks)),
    )


def _is_overdue(task: CoWorkTask) -> bool:
    """Past its date and still open. Finished work is never overdue."""
    if task.due_at is None or task.status == "done":
        return False
    due = task.due_at if task.due_at.tzinfo else task.due_at.replace(tzinfo=UTC)
    return due < datetime.now(UTC)


def _task_out(task: CoWorkTask, user: User) -> TaskOut:
    pending = next(
        (r for r in task.deadline_requests if r.status == "pending"),
        None,
    )
    return TaskOut(
        id=task.id,
        title=task.title,
        detail=task.detail,
        status=task.status,
        assignee_id=task.assignee_id,
        assignee_name=(
            (task.assignee.name or task.assignee.email) if task.assignee else None
        ),
        due_at=task.due_at.isoformat() if task.due_at else None,
        completed_at=task.completed_at.isoformat() if task.completed_at else None,
        can_update=cowork.owns_task(task, user),
        can_claim=cowork.may_claim(task),
        source_meeting_id=task.source_meeting_id,
        spoken_owner=task.spoken_owner,
        overdue=_is_overdue(task),
        pending_deadline_request_id=pending.id if pending else None,
    )


def _parse_due_at(value: str) -> datetime:
    try:
        due = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="due_at must be an ISO date.") from exc
    if due.tzinfo is not None:
        due = due.replace(tzinfo=None)
    return due


def _deadline_request_out(req: CoWorkDeadlineChangeRequest) -> DeadlineRequestOut:
    requester = req.requester
    return DeadlineRequestOut(
        id=req.id,
        task_id=req.task_id,
        task_title=req.task.title if req.task else "",
        requester_id=req.requester_id,
        requester_name=(requester.name if requester else None),
        requester_email=(requester.email if requester else None),
        current_due_at=req.current_due_at.isoformat() if req.current_due_at else None,
        requested_due_at=req.requested_due_at.isoformat(),
        reason=req.reason,
        status=req.status,
        created_at=req.created_at.isoformat() if req.created_at else "",
    )


# --- spaces ---------------------------------------------------------------


@router.get("", response_model=list[WorkspaceOut])
def list_spaces(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
) -> list[WorkspaceOut]:
    return [
        _space_out(db, s, user, settings) for s in cowork.workspaces_for(db, user)
    ]


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_space(
    payload: WorkspaceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    settings: Settings = Depends(get_settings),
) -> WorkspaceOut:
    if payload.team_id is not None and not team_service.is_member(
        db, payload.team_id, user
    ):
        raise HTTPException(status_code=404, detail=f"Unknown team {payload.team_id}")
    space = cowork.create_workspace(
        db,
        name=payload.name,
        purpose=payload.purpose,
        team_id=payload.team_id,
        owner=user,
    )
    return _space_out(db, space, user, settings)


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
def list_members(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[MemberOut]:
    """Everyone in the space, with how their own work stands."""
    space = _space_or_404(db, workspace_id, user)
    tasks = list(space.tasks)
    out: list[MemberOut] = []
    for m in space.memberships:
        if m.user is None:
            continue
        mine = [t for t in tasks if t.assignee_id == m.user_id]
        done = sum(1 for t in mine if t.status == "done")
        out.append(
            MemberOut(
                user_id=m.user.id,
                name=m.user.name,
                email=m.user.email,
                role=m.role,
                is_you=m.user.id == user.id,
                total=len(mine),
                done=done,
                percent=round(100 * done / len(mine)) if mine else 0,
            )
        )
    return sorted(out, key=lambda m: (m.role != "owner", (m.name or m.email).lower()))


@router.post("/{workspace_id}/leave", status_code=200)
def leave_space(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    space = _space_or_404(db, workspace_id, user)
    member = cowork.membership(db, space.id, user)
    leads = [m for m in space.memberships if m.role == "lead"]
    if member is not None and member.role == "lead" and len(leads) == 1 and len(space.memberships) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You are the only Lead. Hand the space over before leaving.",
        )
    released = cowork.release_tasks_of(
        db, workspace_id=space.id, user_id=user.id
    )
    db.delete(member)
    db.flush()
    return {"left": True, "tasks_released": released}


# --- admission ------------------------------------------------------------


class JoinRequest(BaseModel):
    token: str = Field(min_length=8, max_length=128)
    note: str | None = Field(default=None, max_length=500)


@router.post("/join")
def ask_to_join(
    payload: JoinRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Following the link asks to join; it does not join you.

    Admission makes your progress visible to the room, so somebody has to
    decide it.
    """
    space, error, outcome = cowork.request_to_join(
        db, token=payload.token, user=user, note=payload.note
    )
    if error or space is None:
        raise HTTPException(status_code=400, detail=error or "Invalid link.")
    messages = {
        "member": f"You are already in “{space.name}”.",
        "pending": f"Asked to join “{space.name}”. Waiting for the owner to accept.",
    }
    return {
        "workspace_id": space.id if outcome == "member" else None,
        "name": space.name,
        "status": outcome,
        "message": messages.get(outcome, "Request sent."),
    }


@router.get("/{workspace_id}/requests", response_model=list[RequestOut])
def list_requests(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[RequestOut]:
    space = _space_or_404(db, workspace_id, user)
    if not cowork.is_lead(db, space.id, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the Lead can see join requests.",
        )
    return [
        RequestOut(
            id=r.id,
            user_id=r.user_id,
            name=r.user.name if r.user else None,
            email=r.user.email if r.user else "",
            status=r.status,
            note=r.note,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in space.requests
        if r.status == "pending"
    ]


class Decision(BaseModel):
    approve: bool


@router.post("/requests/{request_id}/decide", status_code=200)
def decide(
    request_id: str,
    payload: Decision,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    req = db.get(CoWorkJoinRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Unknown request")
    if not cowork.is_lead(db, req.workspace_id, user):
        # 404 for anyone who is not the Lead: a non-member should not learn
        # that this request exists.
        raise HTTPException(status_code=404, detail="Unknown request")
    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"That request was already {req.status}.",
        )
    cowork.decide_request(db, request=req, approve=payload.approve, decider=user)
    return {"status": req.status}


# --- the board ------------------------------------------------------------


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    detail: str | None = Field(default=None, max_length=4000)
    assignee_id: str | None = None
    due_at: str | None = None


class TaskPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^(todo|in_progress|done)$")
    assignee_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=512)
    detail: str | None = Field(default=None, max_length=4000)


@router.get("/{workspace_id}/tasks", response_model=list[TaskOut])
def list_tasks(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[TaskOut]:
    space = _space_or_404(db, workspace_id, user)
    order = {"in_progress": 0, "todo": 1, "done": 2}
    tasks = sorted(
        space.tasks,
        key=lambda t: (
            not _is_overdue(t),
            order.get(t.status, 3),
            t.created_at or datetime.now(UTC),
        ),
    )
    return [_task_out(t, user) for t in tasks]


@router.post("/{workspace_id}/tasks", response_model=TaskOut, status_code=201)
def create_task(
    workspace_id: str,
    payload: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> TaskOut:
    """Anyone in the space can add work, for themselves or for someone else.

    Once it has a holder, only that person can change it — including the
    person who wrote it down. Adding a line to the board is not authority
    over it.
    """
    space = _space_or_404(db, workspace_id, user)
    if payload.assignee_id is not None:
        assignee = db.get(User, payload.assignee_id)
        if assignee is None or not cowork.is_member(db, space.id, assignee):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="That person is not in this Co-Work space.",
            )
    due = None
    if payload.due_at:
        due = _parse_due_at(payload.due_at)

    task = CoWorkTask(
        workspace_id=space.id,
        title=payload.title.strip(),
        detail=(payload.detail or "").strip() or None,
        assignee_id=payload.assignee_id,
        created_by=user.id,
        due_at=due,
    )
    db.add(task)
    db.flush()
    db.refresh(task)
    return _task_out(task, user)


class MeetingBriefOut(BaseModel):
    meeting_id: str
    title: str
    summary: str | None
    decisions: list[str]
    deadlines: list[dict[str, Any]]
    # PromiseMirror's read of this meeting: silent date changes, handoffs,
    # overdue work. The same alerts the rest of the product raises - a team
    # space must not be a quieter place for a deadline to move.
    alerts: list[dict[str, Any]]


@router.get("/{workspace_id}/meetings", response_model=list[MeetingBriefOut])
def meeting_briefs(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[MeetingBriefOut]:
    """Everything the meetings behind this board produced.

    Co-Work is where work handed out in a conversation gets done, so the
    conversation's own output belongs here too: what was decided, what is
    due, and anything PromiseMirror flagged — including a deadline that moved
    without being agreed. Sharing a board must not mean losing the alarm.
    """
    from app.services import promisemirror

    space = _space_or_404(db, workspace_id, user)

    ids: list[str] = []
    for candidate in [space.meeting_id, *(t.source_meeting_id for t in space.tasks)]:
        if candidate and candidate not in ids:
            ids.append(candidate)

    out: list[MeetingBriefOut] = []
    for meeting_id in ids:
        meeting = db.get(Meeting, meeting_id)
        if meeting is None:
            continue
        findings = promisemirror.analyse(
            db, owner_user_id=meeting.owner_id or user.id, meeting_id=meeting.id
        )
        out.append(
            MeetingBriefOut(
                meeting_id=meeting.id,
                title=meeting.title or meeting.meeting_url,
                summary=meeting.summary.summary_text if meeting.summary else None,
                decisions=list(
                    (meeting.summary.decisions if meeting.summary else None) or []
                ),
                deadlines=[
                    {
                        "what": d.what,
                        "due_at": d.due_at.isoformat() if d.due_at else None,
                        "when_text": d.when_text,
                        "on_calendar": bool(d.google_event_id),
                    }
                    for d in meeting.deadlines
                ],
                alerts=[
                    {
                        "kind": f.kind,
                        "severity": f.severity,
                        "title": f.title,
                        "detail": f.detail,
                    }
                    for f in findings
                ],
            )
        )
    return out


class AttachMeeting(BaseModel):
    meeting_id: str


@router.post("/{workspace_id}/import", status_code=200)
def import_from_meeting(
    workspace_id: str,
    payload: AttachMeeting,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Pull a meeting's action items onto the board.

    This is the point of Co-Work sitting next to the meeting record: work
    handed out in a conversation should not have to be retyped, and the
    spoken name should land on the right person. Names are resolved against
    the people actually in this space, and anything ambiguous is left
    unclaimed rather than guessed onto the wrong person - a task on the wrong
    board is worse than one nobody has picked up yet.

    Re-importing is safe: an action item already on the board is skipped.
    """
    from app.services import teams as team_rooms
    from app.services.meeting_service import resolve_due_date
    from app.services.team import resolve_person

    space = _space_or_404(db, workspace_id, user)
    meeting = db.get(Meeting, payload.meeting_id)
    if meeting is None or not team_rooms.can_read_meeting(db, meeting, user):
        raise HTTPException(
            status_code=404, detail=f"Unknown meeting {payload.meeting_id}"
        )

    members = [m.user for m in space.memberships if m.user is not None]
    already = {(t.title or "").strip().lower() for t in space.tasks}

    # A deadline agreed in the meeting is the same deadline on the board, so
    # the date comes across rather than being retyped. Resolved against the
    # meeting's own date, exactly as the meeting pipeline does it.
    anchor = meeting.created_at or datetime.now(UTC)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    deadline_for = {
        (d.what or "").strip().lower(): d.due_at
        for d in meeting.deadlines
        if d.due_at is not None
    }

    created = 0
    assigned = 0
    dated = 0
    for item in meeting.action_items:
        title = (item.task or "").strip()
        if not title or title.lower() in already:
            continue
        who = resolve_person(item.owner_name, members)
        due = deadline_for.get(title.lower()) or resolve_due_date(
            None, item.due_text, anchor
        )
        if due is not None and due.tzinfo is not None:
            due = due.replace(tzinfo=None)
        db.add(
            CoWorkTask(
                workspace_id=space.id,
                title=title,
                assignee_id=who.id if who else None,
                created_by=user.id,
                source_meeting_id=meeting.id,
                spoken_owner=item.owner_name,
                due_at=due,
            )
        )
        already.add(title.lower())
        created += 1
        if who is not None:
            assigned += 1
        if due is not None:
            dated += 1

    if space.meeting_id is None:
        space.meeting_id = meeting.id
    db.flush()
    logger.info(
        "Imported %d task(s) from meeting %s into co-work %s",
        created,
        meeting.id,
        space.id,
    )
    return {
        "imported": created,
        "assigned": assigned,
        "unassigned": created - assigned,
        "with_dates": dated,
        "meeting_title": meeting.title or meeting.meeting_url,
    }


class DeadlineRequestCreate(BaseModel):
    requested_due_at: str
    reason: str | None = Field(default=None, max_length=1000)


class DeadlineDecision(BaseModel):
    approve: bool


@router.get(
    "/{workspace_id}/deadline-requests", response_model=list[DeadlineRequestOut]
)
def list_deadline_requests(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[DeadlineRequestOut]:
    space = _space_or_404(db, workspace_id, user)
    is_lead = cowork.is_lead(db, space.id, user)
    out: list[CoWorkDeadlineChangeRequest] = []
    for req in space.deadline_requests:
        if req.status != "pending":
            continue
        if is_lead or req.requester_id == user.id:
            out.append(req)
    return [_deadline_request_out(r) for r in sorted(out, key=lambda r: r.created_at)]


@router.post(
    "/tasks/{task_id}/deadline-requests",
    response_model=DeadlineRequestOut,
    status_code=201,
)
def request_deadline_change(
    task_id: str,
    payload: DeadlineRequestCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DeadlineRequestOut:
    task = db.get(CoWorkTask, task_id)
    if task is None or not cowork.is_member(db, task.workspace_id, user):
        raise HTTPException(status_code=404, detail=f"Unknown task {task_id}")
    if cowork.is_lead(db, task.workspace_id, user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The Lead can approve requests; members request deadline changes.",
        )
    existing = cowork.pending_deadline_request(db, task_id=task.id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This task already has a deadline change waiting for Lead approval.",
        )
    requested = _parse_due_at(payload.requested_due_at)
    req = cowork.create_deadline_request(
        db,
        task=task,
        requester=user,
        requested_due_at=requested,
        reason=payload.reason,
    )
    db.refresh(req)
    return _deadline_request_out(req)


@router.post("/deadline-requests/{request_id}/decide", status_code=200)
def decide_deadline_request(
    request_id: str,
    payload: DeadlineDecision,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    req = db.get(CoWorkDeadlineChangeRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Unknown deadline request")
    if not cowork.is_lead(db, req.workspace_id, user):
        raise HTTPException(status_code=404, detail="Unknown deadline request")
    if req.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"That deadline request was already {req.status}.",
        )
    cowork.decide_deadline_request(db, request=req, approve=payload.approve, decider=user)
    return {
        "status": req.status,
        "task_id": req.task_id,
        "due_at": req.task.due_at.isoformat() if req.task.due_at else None,
    }


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: str,
    payload: TaskPatch,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> TaskOut:
    """Edit a task. Only the person it belongs to may change anything on it.

    Status, wording and who holds it are all gated the same way, and the Lead
    gets no exception: over someone else's work everyone is read-only. The one
    opening is an unclaimed task, which anybody in the room may take on —
    picking up work nobody holds takes nothing away from anyone.
    """
    task = db.get(CoWorkTask, task_id)
    if task is None or not cowork.is_member(db, task.workspace_id, user):
        raise HTTPException(status_code=404, detail=f"Unknown task {task_id}")

    mine = cowork.owns_task(task, user)
    claiming = (
        cowork.may_claim(task)
        and payload.assignee_id == user.id
        and payload.status is None
        and payload.title is None
        and payload.detail is None
    )
    if not mine and not claiming:
        who = (task.assignee.name or task.assignee.email) if task.assignee else None
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Only {who} can change this task."
                if who
                else "Nobody holds this task yet. Claim it first, then you can "
                "change it."
            ),
        )

    if payload.assignee_id is not None and payload.assignee_id != task.assignee_id:
        assignee = db.get(User, payload.assignee_id)
        if assignee is None or not cowork.is_member(db, task.workspace_id, assignee):
            raise HTTPException(
                status_code=404, detail="That person is not in this Co-Work space."
            )
        # Handing work on is the assignee's own call, the same as finishing it.
        task.assignee_id = payload.assignee_id
    if payload.title is not None:
        task.title = payload.title.strip()
    if payload.detail is not None:
        task.detail = payload.detail.strip() or None
    if payload.status is not None and payload.status != task.status:
        cowork.set_status(db, task=task, status=payload.status)

    db.flush()
    db.refresh(task)
    return _task_out(task, user)


@router.delete("/tasks/{task_id}", status_code=200)
def delete_task(
    task_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict[str, Any]:
    """Remove a task.

    Its holder can remove it. So can the Lead, but only while nobody holds it
    — tidying the board is theirs, deleting somebody's record of outstanding
    work is not. A departed member's tasks become unclaimed on their way out,
    so nothing is ever stuck.
    """
    task = db.get(CoWorkTask, task_id)
    if task is None or not cowork.is_member(db, task.workspace_id, user):
        raise HTTPException(status_code=404, detail=f"Unknown task {task_id}")

    unclaimed_tidy_up = task.assignee_id is None and cowork.is_lead(
        db, task.workspace_id, user
    )
    if not cowork.owns_task(task, user) and not unclaimed_tidy_up:
        who = (task.assignee.name or task.assignee.email) if task.assignee else None
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Only {who} can remove this task."
                if who
                else "Only the Lead can remove an unclaimed task."
            ),
        )
    db.delete(task)
    db.flush()
    return {"deleted": True}
