"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  api,
  coworkApi,
  projectApi,
  teamApi,
  type CoWorkMember,
  type CoWorkRequest,
  type CoWorkTask,
  type CoWorkMeetingBrief,
  type CoWorkspace,
  type Meeting,
  type ProjectSummary,
  type TeamSummary,
} from "@/lib/api";
import { Card, EmptyState, ErrorBanner, Spinner } from "@/components/ui";

const STATUS_LABEL: Record<string, string> = {
  todo: "To do",
  in_progress: "In progress",
  done: "Done",
};

const NEXT_STATUS: Record<string, "todo" | "in_progress" | "done"> = {
  todo: "in_progress",
  in_progress: "done",
  done: "todo",
};

/**
 * MeetMind Co-Work.
 *
 * The one place in the product where progress is shared rather than private,
 * which is why it is a separate space with its own door. Two rules are
 * visible in the UI because they are the point:
 *   - the link asks to join; the owner decides;
 *   - only the person a task belongs to can move it, owner included. The
 *     backend returns `can_update` per task, so a button is never offered
 *     that the server would refuse.
 */
export default function CoWorkPage() {
  const [spaces, setSpaces] = useState<CoWorkspace[] | null>(null);
  const [activeId, setActiveId] = useState<string>("");
  const [members, setMembers] = useState<CoWorkMember[]>([]);
  const [tasks, setTasks] = useState<CoWorkTask[]>([]);
  const [requests, setRequests] = useState<CoWorkRequest[]>([]);
  const [teams, setTeams] = useState<TeamSummary[]>([]);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [importId, setImportId] = useState("");
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  // Scoping the meeting list by project: a board for one workstream
  // should not offer meetings from another.
  const [importProject, setImportProject] = useState("");
  const [briefs, setBriefs] = useState<CoWorkMeetingBrief[]>([]);

  const [name, setName] = useState("");
  const [joinToken, setJoinToken] = useState("");
  const [taskTitle, setTaskTitle] = useState("");
  const [taskAssignee, setTaskAssignee] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const active = (spaces ?? []).find((s) => s.id === activeId) ?? null;
  const importMeetings = importProject
    ? meetings.filter((m) => m.project_id === importProject)
    : meetings;

  const loadSpace = useCallback(async (id: string) => {
    const [m, t] = await Promise.all([
      coworkApi.members(id).catch(() => [] as CoWorkMember[]),
      coworkApi.tasks(id).catch(() => [] as CoWorkTask[]),
    ]);
    setMembers(m);
    setTasks(t);
    // Only an owner may read the queue; a 403 here is expected for members.
    setRequests(await coworkApi.requests(id).catch(() => [] as CoWorkRequest[]));
    setBriefs(await coworkApi.meetingBriefs(id).catch(() => [] as CoWorkMeetingBrief[]));
  }, []);

  const reload = useCallback(
    async (preferred?: string) => {
      const rows = await coworkApi.list().catch(() => [] as CoWorkspace[]);
      setSpaces(rows);
      const next = preferred ?? (rows.some((s) => s.id === activeId) ? activeId : rows[0]?.id);
      if (next) {
        setActiveId(next);
        await loadSpace(next);
      } else {
        setActiveId("");
        setMembers([]);
        setTasks([]);
        setRequests([]);
      }
    },
    [activeId, loadSpace],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [rows, teamRows, meetingRows, projectRows] = await Promise.all([
        coworkApi.list().catch(() => [] as CoWorkspace[]),
        teamApi.list().catch(() => [] as TeamSummary[]),
        api.listMeetings(100).catch(() => [] as Meeting[]),
        projectApi.list().catch(() => [] as ProjectSummary[]),
      ]);
      if (cancelled) return;
      setSpaces(rows);
      setTeams(teamRows);
      setProjects(projectRows);
      setMeetings(meetingRows.filter((m) => m.has_summary || m.has_transcript));
      if (rows[0]) {
        setActiveId(rows[0].id);
        await loadSpace(rows[0].id);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadSpace]);

  async function run(fn: () => Promise<void>, fallback: string) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : fallback);
    } finally {
      setBusy(false);
    }
  }

  const field =
    "w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20";

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <Link href="/dashboard" className="text-sm text-[var(--accent)] hover:underline">
        ← Dashboard
      </Link>

      <header className="mt-4 mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">MeetMind Co-Work</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          A shared board for work split between people. Everyone sees how it is
          going; only the person a task belongs to can mark it done.
        </p>
      </header>

      {error && (
        <div className="mb-5">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}
      {notice && (
        <div className="mb-5 flex items-start justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm text-[var(--muted-strong)]">
          <span>{notice}</span>
          <button
            onClick={() => setNotice(null)}
            className="shrink-0 text-xs font-semibold text-[var(--accent)] hover:underline"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="mb-6 grid gap-4 sm:grid-cols-2">
        <Card className="p-4">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (!name.trim()) return;
              void run(async () => {
                const created = await coworkApi.create(
                  name.trim(),
                  undefined,
                  teams[0]?.id,
                );
                setName("");
                await reload(created.id);
                setNotice("Space created. Share its link to invite people.");
              }, "Could not create the space.");
            }}
            className="space-y-2"
          >
            <label htmlFor="space-name" className="block text-sm font-medium">
              Start a Co-Work space
            </label>
            <input
              id="space-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Hackathon submission"
              className={field}
            />
            <button
              type="submit"
              disabled={busy || !name.trim()}
              className="w-full rounded-lg bg-[var(--accent)] px-3 py-2 text-sm font-semibold text-[var(--accent-fg)] transition hover:bg-[var(--accent-hover)] disabled:opacity-40"
            >
              Create space
            </button>
          </form>
        </Card>

        <Card className="p-4">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const raw = joinToken.trim();
              if (!raw) return;
              void run(async () => {
                const token = raw.includes("token=")
                  ? (new URL(raw, window.location.origin).searchParams.get("token") ??
                    raw)
                  : raw;
                const r = await coworkApi.askToJoin(token);
                setJoinToken("");
                setNotice(r.message);
                if (r.status === "member") await reload(r.workspace_id ?? undefined);
              }, "Could not use that link.");
            }}
            className="space-y-2"
          >
            <label htmlFor="space-token" className="block text-sm font-medium">
              Ask to join a space
            </label>
            <input
              id="space-token"
              value={joinToken}
              onChange={(e) => setJoinToken(e.target.value)}
              placeholder="Paste the Co-Work link"
              className={field}
            />
            <button
              type="submit"
              disabled={busy || !joinToken.trim()}
              className="w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-semibold transition hover:bg-[var(--surface-2)] disabled:opacity-40"
            >
              Send request
            </button>
            <p className="text-[11px] text-[var(--muted)]">
              The owner has to accept: joining makes your progress visible to
              the room.
            </p>
          </form>
        </Card>
      </div>

      {spaces === null ? (
        <Card className="flex items-center gap-2 px-5 py-10 text-sm text-[var(--muted)]">
          <Spinner /> Loading spaces…
        </Card>
      ) : spaces.length === 0 ? (
        <Card>
          <EmptyState
            title="No Co-Work spaces yet"
            hint="Create one for work you are splitting with other people."
          />
        </Card>
      ) : (
        <>
          {spaces.length > 1 && (
            <div className="mb-4 flex flex-wrap gap-2">
              {spaces.map((s) => (
                <button
                  key={s.id}
                  onClick={() => {
                    setActiveId(s.id);
                    void loadSpace(s.id);
                  }}
                  className={`rounded-full border px-3 py-1.5 text-xs font-semibold transition ${
                    s.id === activeId
                      ? "border-[var(--accent)] bg-[var(--accent)] text-[var(--accent-fg)]"
                      : "border-[var(--border)] hover:bg-[var(--surface-2)]"
                  }`}
                >
                  {s.name}
                  {s.pending_requests > 0 && ` · ${s.pending_requests} waiting`}
                </button>
              ))}
            </div>
          )}

          {active && (
            <div className="space-y-4">
              <Card className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="text-base font-bold">{active.name}</h2>
                    <p className="mt-0.5 text-xs text-[var(--muted)]">
                      {active.member_count} member
                      {active.member_count === 1 ? "" : "s"} ·{" "}
                      {active.progress.done}/{active.progress.total} done
                    </p>
                  </div>
                  <span className="text-2xl font-bold tabular-nums">
                    {active.progress.percent}%
                  </span>
                </div>
                <div
                  className="mt-3 h-2 w-full overflow-hidden rounded"
                  style={{ background: "var(--chart-track)" }}
                >
                  <div
                    className="h-full rounded transition-[width] duration-300"
                    style={{
                      width: `${active.progress.percent}%`,
                      background: "var(--chart-completed)",
                    }}
                  />
                </div>

                {active.is_lead && active.join_url && (
                  <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-3">
                    <code className="min-w-0 flex-1 truncate rounded border border-[var(--border)] bg-[var(--surface-2)] px-2 py-1.5 text-xs">
                      {active.join_url}
                    </code>
                    <button
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(active.join_url!);
                          setCopied(true);
                          window.setTimeout(() => setCopied(false), 2000);
                        } catch {
                          setError("Could not copy — select the link and copy it.");
                        }
                      }}
                      className="shrink-0 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-semibold"
                    >
                      {copied ? "Copied" : "Copy link"}
                    </button>
                  </div>
                )}
              </Card>

              {requests.length > 0 && (
                <Card className="border-[var(--accent)]/30">
                  <h3 className="border-b border-[var(--border)] px-5 py-3 text-sm font-bold">
                    {requests.length} asking to join
                  </h3>
                  <ul className="divide-y divide-[var(--border)]">
                    {requests.map((r) => (
                      <li
                        key={r.id}
                        className="flex flex-wrap items-center justify-between gap-2 px-5 py-3"
                      >
                        <span className="min-w-0 truncate text-sm">
                          {r.name ?? r.email}
                          <span className="ml-1.5 text-xs text-[var(--muted)]">
                            {r.email}
                          </span>
                        </span>
                        <span className="flex shrink-0 gap-2">
                          <button
                            onClick={() =>
                              void run(async () => {
                                await coworkApi.decide(r.id, true);
                                await reload(active.id);
                                setNotice(`${r.name ?? r.email} is in.`);
                              }, "Could not accept.")
                            }
                            disabled={busy}
                            className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-[var(--accent-fg)] disabled:opacity-40"
                          >
                            Accept
                          </button>
                          <button
                            onClick={() =>
                              void run(async () => {
                                await coworkApi.decide(r.id, false);
                                await reload(active.id);
                              }, "Could not reject.")
                            }
                            disabled={busy}
                            className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-semibold disabled:opacity-40"
                          >
                            Reject
                          </button>
                        </span>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}

              <Card>
                <h3 className="border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
                  Who is doing what
                </h3>
                <ul className="divide-y divide-[var(--border)]">
                  {members.map((m) => (
                    <li key={m.user_id} className="px-5 py-3">
                      <div className="mb-1.5 flex items-baseline justify-between gap-3">
                        <span className="min-w-0 truncate text-sm font-medium">
                          {m.name ?? m.email}
                          {m.role === "lead" && (
                            <span
                              className="ml-1.5 rounded-full px-1.5 py-0.5 text-[10px] font-bold uppercase"
                              style={{
                                background: "var(--accent-soft)",
                                color: "var(--accent)",
                              }}
                            >
                              Lead
                            </span>
                          )}
                          {m.is_you && (
                            <span className="ml-1.5 text-xs text-[var(--muted)]">
                              (you)
                            </span>
                          )}
                        </span>
                        <span className="shrink-0 text-xs tabular-nums text-[var(--muted)]">
                          {m.done}/{m.total} done
                        </span>
                      </div>
                      <div
                        className="h-1.5 w-full overflow-hidden rounded"
                        style={{ background: "var(--chart-track)" }}
                      >
                        <div
                          className="h-full rounded"
                          style={{
                            width: `${m.percent}%`,
                            background: "var(--chart-pending)",
                          }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              </Card>

              <Card>
                <div className="border-b border-[var(--border)] px-5 py-3">
                  <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
                    The board
                  </h3>
                  <p className="mt-0.5 text-xs text-[var(--muted)]">
                    Anyone can add work. Only the person holding a task can
                    change it — the Lead included.
                  </p>
                </div>

                {meetings.length > 0 && (
                  <div className="flex flex-wrap items-center gap-2 border-b border-[var(--border)] bg-[var(--surface-2)] px-5 py-3">
                    <span className="text-xs font-semibold text-[var(--muted-strong)]">
                      Bring in work from a meeting
                    </span>
                    <select
                      value={importProject}
                      onChange={(e) => {
                        setImportProject(e.target.value);
                        // A meeting from the old project would be the wrong
                        // work entirely, so the choice resets with it.
                        setImportId("");
                      }}
                      aria-label="Project"
                      className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1.5 text-xs"
                    >
                      <option value="">All projects</option>
                      {projects.map((pr) => (
                        <option key={pr.id} value={pr.id}>
                          {pr.name}
                        </option>
                      ))}
                    </select>
                    <select
                      value={importId}
                      onChange={(e) => setImportId(e.target.value)}
                      aria-label="Meeting to import from"
                      disabled={importMeetings.length === 0}
                      className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1.5 text-xs disabled:opacity-50"
                    >
                      <option value="">
                        {importMeetings.length === 0
                          ? "No recorded meetings in this project"
                          : "Choose a meeting…"}
                      </option>
                      {importMeetings.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.title || m.meeting_url}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() =>
                        void run(async () => {
                          const r = await coworkApi.importMeeting(
                            active.id,
                            importId,
                          );
                          setImportId("");
                          await reload(active.id);
                          setNotice(
                            r.imported === 0
                              ? "Nothing new — that meeting's work is already on the board."
                              : `Added ${r.imported} task${r.imported === 1 ? "" : "s"} from “${r.meeting_title}” · ` +
                                `${r.assigned} matched to a person, ${r.unassigned} left unclaimed, ` +
                                `${r.with_dates} with a deadline.`,
                          );
                        }, "Could not import from that meeting.")
                      }
                      disabled={busy || !importId}
                      className="shrink-0 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-1.5 text-xs font-semibold disabled:opacity-40"
                    >
                      Import
                    </button>
                  </div>
                )}

                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    if (!taskTitle.trim()) return;
                    void run(async () => {
                      await coworkApi.addTask(active.id, {
                        title: taskTitle.trim(),
                        assignee_id: taskAssignee || null,
                      });
                      setTaskTitle("");
                      await reload(active.id);
                    }, "Could not add the task.");
                  }}
                  className="flex flex-wrap gap-2 border-b border-[var(--border)] px-5 py-3"
                >
                  <input
                    value={taskTitle}
                    onChange={(e) => setTaskTitle(e.target.value)}
                    placeholder="What needs doing?"
                    aria-label="Task title"
                    className={`${field} min-w-0 flex-1`}
                  />
                  <select
                    value={taskAssignee}
                    onChange={(e) => setTaskAssignee(e.target.value)}
                    aria-label="Assign to"
                    className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2.5 py-2 text-sm"
                  >
                    <option value="">Unassigned</option>
                    {members.map((m) => (
                      <option key={m.user_id} value={m.user_id}>
                        {m.name ?? m.email}
                      </option>
                    ))}
                  </select>
                  <button
                    type="submit"
                    disabled={busy || !taskTitle.trim()}
                    className="shrink-0 rounded-lg bg-[var(--accent)] px-3.5 py-2 text-sm font-semibold text-[var(--accent-fg)] disabled:opacity-40"
                  >
                    Add
                  </button>
                </form>

                {tasks.length === 0 ? (
                  <EmptyState title="Nothing on the board yet" />
                ) : (
                  <ul className="divide-y divide-[var(--border)]">
                    {tasks.map((t) => (
                      <li
                        key={t.id}
                        className="flex flex-wrap items-center justify-between gap-3 px-5 py-3"
                      >
                        <div className="min-w-0">
                          <p
                            className={`text-sm ${
                              t.status === "done" ? "line-through opacity-60" : ""
                            }`}
                          >
                            {t.title}
                          </p>
                          <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-[var(--muted)]">
                            <span className="font-medium">
                              {t.assignee_name ?? "unclaimed"}
                            </span>
                            <span>· {STATUS_LABEL[t.status]}</span>
                            {t.due_at && (
                              <span
                                className={
                                  t.overdue ? "font-semibold" : undefined
                                }
                                style={
                                  t.overdue
                                    ? { color: "var(--chart-overdue)" }
                                    : undefined
                                }
                              >
                                · {t.overdue ? "overdue " : "due "}
                                {new Date(t.due_at).toLocaleDateString()}
                              </span>
                            )}
                            {t.source_meeting_id && (
                              <span
                                className="rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
                                style={{
                                  background: "var(--accent-soft)",
                                  color: "var(--accent)",
                                }}
                                title={
                                  t.spoken_owner
                                    ? `Said in the meeting as "${t.spoken_owner}"`
                                    : "Taken from a meeting"
                                }
                              >
                                from a meeting
                              </span>
                            )}
                          </p>
                        </div>

                        <span className="flex shrink-0 items-center gap-2">
                          {t.can_update ? (
                            <>
                              <button
                                onClick={() =>
                                  void run(async () => {
                                    await coworkApi.updateTask(t.id, {
                                      status: NEXT_STATUS[t.status],
                                    });
                                    await reload(active.id);
                                  }, "Could not update the task.")
                                }
                                disabled={busy}
                                className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-semibold transition hover:bg-[var(--surface-2)] disabled:opacity-40"
                              >
                                {t.status === "todo"
                                  ? "Start"
                                  : t.status === "in_progress"
                                    ? "Mark done"
                                    : "Reopen"}
                              </button>
                              <button
                                onClick={() =>
                                  void run(async () => {
                                    await coworkApi.deleteTask(t.id);
                                    await reload(active.id);
                                  }, "Could not remove the task.")
                                }
                                disabled={busy}
                                aria-label={`Remove ${t.title}`}
                                className="rounded-lg border border-transparent px-2 py-1.5 text-xs font-semibold text-[var(--muted-strong)] transition hover:border-[var(--danger)] hover:text-[var(--danger)] disabled:opacity-40"
                              >
                                Remove
                              </button>
                            </>
                          ) : t.can_claim ? (
                            <button
                              onClick={() =>
                                void run(async () => {
                                  const me = members.find((m) => m.is_you);
                                  if (!me) return;
                                  await coworkApi.updateTask(t.id, {
                                    assignee_id: me.user_id,
                                  });
                                  await reload(active.id);
                                }, "Could not claim the task.")
                              }
                              disabled={busy}
                              className="rounded-lg border border-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-[var(--accent)] transition hover:bg-[var(--accent-soft)] disabled:opacity-40"
                            >
                              Claim
                            </button>
                          ) : (
                            // Not offered rather than offered-and-refused: the
                            // backend already told us this is not ours.
                            <span
                              className="text-xs text-[var(--muted)]"
                              title={`Only ${t.assignee_name} can change this`}
                            >
                              {t.assignee_name}&apos;s to mark
                            </span>
                          )}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              {briefs.length > 0 && (
                <Card>
                  <div className="border-b border-[var(--border)] px-5 py-3">
                    <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
                      From the meetings behind this board
                    </h3>
                    <p className="mt-0.5 text-xs text-[var(--muted)]">
                      What was decided, what is due, and anything MeetMind
                      flagged — a shared board is not a quieter place for a
                      deadline to move.
                    </p>
                  </div>
                  <ul className="divide-y divide-[var(--border)]">
                    {briefs.map((b) => (
                      <li key={b.meeting_id} className="px-5 py-3">
                        <Link
                          href={`/meetings/${b.meeting_id}`}
                          className="text-sm font-semibold text-[var(--accent)] hover:underline"
                        >
                          {b.title}
                        </Link>
                        {b.summary && (
                          <p className="mt-1 text-sm text-[var(--muted-strong)]">
                            {b.summary}
                          </p>
                        )}

                        {b.alerts.length > 0 && (
                          <ul className="mt-2 space-y-1.5">
                            {b.alerts.map((a, i) => (
                              <li
                                key={i}
                                className="rounded-lg px-2.5 py-1.5 text-xs"
                                style={{
                                  background:
                                    a.severity === "high"
                                      ? "color-mix(in oklab, var(--chart-overdue) 10%, transparent)"
                                      : "var(--surface-2)",
                                  color:
                                    a.severity === "high"
                                      ? "var(--chart-overdue)"
                                      : "var(--muted-strong)",
                                }}
                              >
                                <span className="font-semibold">{a.title}</span>
                                <span className="block opacity-90">{a.detail}</span>
                              </li>
                            ))}
                          </ul>
                        )}

                        {b.decisions.length > 0 && (
                          <ul className="mt-2 space-y-0.5">
                            {b.decisions.map((d, i) => (
                              <li
                                key={i}
                                className="flex gap-2 text-xs text-[var(--muted-strong)]"
                              >
                                <span aria-hidden className="text-[var(--accent)]">
                                  ✓
                                </span>
                                <span>{d}</span>
                              </li>
                            ))}
                          </ul>
                        )}

                        {b.deadlines.length > 0 && (
                          <p className="mt-2 flex flex-wrap gap-1.5">
                            {b.deadlines.map((d, i) => (
                              <span
                                key={i}
                                className="rounded-full border border-[var(--border)] px-2 py-0.5 text-[11px]"
                              >
                                {d.what}
                                {d.due_at
                                  ? ` · ${new Date(d.due_at).toLocaleDateString()}`
                                  : d.when_text
                                    ? ` · ${d.when_text}`
                                    : ""}
                                {d.on_calendar ? " · on calendar" : ""}
                              </span>
                            ))}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
            </div>
          )}
        </>
      )}
    </main>
  );
}
