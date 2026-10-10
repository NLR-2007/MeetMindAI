"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  type Commitment,
  type Finding,
  type Meeting,
  type ProjectSummary,
  type TimelineEvent,
  api,
  progressApi,
  projectApi,
  promiseApi,
} from "@/lib/api";
import { Card, EmptyState, ErrorBanner, Spinner } from "@/components/ui";

const SEVERITY: Record<string, string> = {
  high: "border-red-500/30 bg-red-500/10 text-red-600",
  medium: "border-amber-500/30 bg-amber-500/10 text-amber-700",
  low: "border-[var(--border)] bg-[var(--background)] text-[var(--muted)]",
};

const KIND_LABEL: Record<string, string> = {
  overdue: "Overdue",
  approaching: "Due soon",
  conflicting: "Clashing dates",
  unowned: "No owner",
  undated: "No date",
  changed: "Changed",
  silent_change: "Changed without agreement",
  handed_over: "Handed over",
  released: "Dropped, nobody took it",
};

export default function PromisesPage() {
  const [tab, setTab] = useState<"findings" | "commitments" | "timeline">("findings");
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState<string>("");
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [meetingId, setMeetingId] = useState<string>("");
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [byKind, setByKind] = useState<Record<string, number>>({});
  const [commitments, setCommitments] = useState<Commitment[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  // Clicking a count narrows the list. 40 findings in one flat column is a
  // wall of text; the counts were already there, so make them do something.
  const [kindFilter, setKindFilter] = useState<string | null>(null);

  useEffect(() => {
    projectApi.list().then(setProjects).catch(() => setProjects([]));
    api.listMeetings().then(setMeetings).catch(() => setMeetings([]));
  }, []);

  // `keep` lets the caller discard a response it no longer wants. Changing the
  // project or meeting filter twice quickly can otherwise land the first reply
  // after the second and show the wrong scope.
  const load = useCallback(
    async (keep: () => boolean = () => true) => {
      const pid = projectId || undefined;
      const mid = meetingId || undefined;
      try {
        const [f, c, t] = await Promise.all([
          promiseApi.findings(pid, mid),
          promiseApi.commitments(pid, mid),
          promiseApi.timeline(pid, mid),
        ]);
        if (!keep()) return;
        setFindings(f.findings);
        setByKind(f.by_kind);
        setCommitments(c);
        setTimeline(t);
      } catch (err) {
        if (!keep()) return;
        setError(err instanceof ApiError ? err.message : "Failed to load commitments.");
        setFindings([]);
      }
    },
    [projectId, meetingId],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      await load(() => !cancelled);
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  const shown = useMemo(
    () => (findings ?? []).filter((f) => !kindFilter || f.kind === kindFilter),
    [findings, kindFilter],
  );

  // Findings belong to a project first: "what is wrong on Paddy" is the
  // question being asked. Severity still decides the order inside each
  // project, so the urgent item is always the first thing in its group - and
  // the project with the most urgent work sorts to the top.
  const groups = useMemo(() => {
    const rank = { high: 0, medium: 1, low: 2 } as Record<string, number>;
    const byProject = new Map<
      string,
      { id: string; name: string; items: Finding[]; high: number }
    >();
    for (const f of shown) {
      const id = f.project_id ?? "__none__";
      if (!byProject.has(id)) {
        byProject.set(id, {
          id,
          name: f.project_name ?? "No project",
          items: [],
          high: 0,
        });
      }
      const g = byProject.get(id)!;
      g.items.push(f);
      if (f.severity === "high") g.high += 1;
    }
    for (const g of byProject.values()) {
      g.items.sort(
        (a, b) =>
          (rank[a.severity] ?? 3) - (rank[b.severity] ?? 3) ||
          (a.due_at ?? "9999").localeCompare(b.due_at ?? "9999"),
      );
    }
    return [...byProject.values()].sort(
      (a, b) =>
        b.high - a.high ||
        (a.id === "__none__" ? 1 : b.id === "__none__" ? -1 : 0) ||
        a.name.localeCompare(b.name),
    );
  }, [shown]);

  // Choosing a project narrows the meeting list to that project's meetings;
  // offering every meeting invites picking one from another workstream and
  // getting an empty result.
  const projectMeetings = useMemo(
    () => (projectId ? meetings.filter((m) => m.project_id === projectId) : meetings),
    [meetings, projectId],
  );

  // Promises belong to a project: "everything I committed to on Paddy" is the
  // question people actually ask, and a flat list cannot answer it.
  const commitmentsByProject = useMemo(() => {
    const names = new Map(projects.map((p) => [p.id, p.name]));
    const groups = new Map<
      string,
      { id: string; name: string; items: Commitment[]; done: number }
    >();
    for (const c of commitments) {
      const id = c.project_id ?? "__none__";
      if (!groups.has(id)) {
        groups.set(id, {
          id,
          name: c.project_id
            ? (names.get(c.project_id) ?? "Unknown project")
            : "No project",
          items: [],
          done: 0,
        });
      }
      const g = groups.get(id)!;
      g.items.push(c);
      if (c.status === "completed") g.done += 1;
    }
    // Named projects first, "No project" last: it is a catch-all, not a peer.
    return [...groups.values()].sort((a, b) =>
      a.id === "__none__" ? 1 : b.id === "__none__" ? -1 : a.name.localeCompare(b.name),
    );
  }, [commitments, projects]);

  const counts = useMemo(() => {
    const all = findings ?? [];
    return {
      high: all.filter((f) => f.severity === "high").length,
      medium: all.filter((f) => f.severity === "medium").length,
      low: all.filter((f) => f.severity === "low").length,
    };
  }, [findings]);

  async function resync() {
    setSyncing(true);
    setError(null);
    try {
      const data = await progressApi.get();
      await Promise.all(
        data.recent_meetings.map((m) => promiseApi.sync(m.id).catch(() => null)),
      );
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Re-scan failed.");
    } finally {
      setSyncing(false);
    }
  }

  async function resolveChange(id: string, keep: "original" | "new") {
    setBusyId(id);
    try {
      await promiseApi.resolveChange(id, keep);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not resolve the date.");
    } finally {
      setBusyId(null);
    }
  }

  async function setStatus(id: string, status: string) {
    setBusyId(id);
    try {
      await promiseApi.setStatus(id, status);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update.");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <Link href="/dashboard" className="text-sm text-[var(--accent)] hover:underline">
        ← Dashboard
      </Link>

      <header className="mt-4 mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Your Promises</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            PromiseMirror tracks every commitment you made, when it changed, and
            what is still open. Each finding cites the meeting it came from.
          </p>
        </div>
        <button
          onClick={resync}
          disabled={syncing}
          className="inline-flex items-center gap-2 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium transition hover:bg-[var(--surface)] disabled:opacity-50"
        >
          {syncing && <Spinner />} Re-scan meetings
        </button>
      </header>

      {error && (
        <div className="mb-5">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <select
          value={projectId}
          onChange={(e) => {
            setProjectId(e.target.value);
            // The meeting filter is scoped to the project, so a selection
            // from the previous one would silently show nothing.
            setMeetingId("");
          }}
          className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
        >
          <option value="">All projects</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>

        <select
          value={meetingId}
          onChange={(e) => setMeetingId(e.target.value)}
          className="max-w-[260px] rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm"
        >
          <option value="">
            {projectId && projectMeetings.length === 0
              ? "No meetings in this project"
              : "All meetings"}
          </option>
          {projectMeetings.map((m) => (
            <option key={m.id} value={m.id}>
              {m.title || m.meeting_url}
            </option>
          ))}
        </select>

        {(projectId || meetingId) && (
          <button
            onClick={() => {
              setProjectId("");
              setMeetingId("");
            }}
            className="text-xs text-[var(--accent)] hover:underline"
          >
            Clear filters
          </button>
        )}

        <div className="flex gap-1 rounded-lg border border-[var(--border)] p-1">
          {(["findings", "commitments", "timeline"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`rounded-md px-3 py-1.5 text-xs font-medium capitalize transition ${
                tab === t
                  ? "bg-[var(--accent)] text-[var(--accent-fg)]"
                  : "hover:bg-[var(--background)]"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {tab === "findings" && (
        <>
          {findings !== null && findings.length > 0 && (
            <>
              <div className="mb-4 grid grid-cols-3 gap-3">
                {(
                  [
                    ["high", "Needs attention", "var(--chart-overdue)"],
                    ["medium", "Worth a look", "var(--chart-upcoming)"],
                    ["low", "For information", "var(--muted)"],
                  ] as const
                ).map(([key, label, color]) => (
                  <Card key={key} className="p-4">
                    <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
                      {label}
                    </p>
                    <p
                      className="mt-1 text-2xl font-bold tabular-nums"
                      style={{ color: counts[key] > 0 ? color : "var(--muted)" }}
                    >
                      {counts[key]}
                    </p>
                  </Card>
                ))}
              </div>

              <div className="mb-4 flex flex-wrap gap-2">
                <button
                  onClick={() => setKindFilter(null)}
                  className={`rounded-full border px-3 py-1 text-xs transition ${
                    kindFilter === null
                      ? "border-[var(--accent)] bg-[var(--accent)] text-[var(--accent-fg)]"
                      : "border-[var(--border)] hover:bg-[var(--surface-2)]"
                  }`}
                >
                  All <strong>{findings.length}</strong>
                </button>
                {Object.entries(byKind).map(([kind, n]) => (
                  <button
                    key={kind}
                    onClick={() => setKindFilter(kindFilter === kind ? null : kind)}
                    aria-pressed={kindFilter === kind}
                    className={`rounded-full border px-3 py-1 text-xs transition ${
                      kindFilter === kind
                        ? "border-[var(--accent)] bg-[var(--accent)] text-[var(--accent-fg)]"
                        : "border-[var(--border)] hover:bg-[var(--surface-2)]"
                    }`}
                  >
                    {KIND_LABEL[kind] ?? kind}: <strong>{n}</strong>
                  </button>
                ))}
              </div>
            </>
          )}

          {findings === null ? (
            <Card className="flex items-center gap-2 px-5 py-10 text-sm text-[var(--muted)]">
              <Spinner /> Analysing your commitments…
            </Card>
          ) : findings.length === 0 ? (
            <Card>
              <EmptyState
                title="Nothing outstanding"
                hint="Record a meeting where commitments are made, then re-scan."
              />
            </Card>
          ) : shown.length === 0 ? (
            <Card>
              <EmptyState
                title="Nothing matches that filter"
                hint="Clear it to see every finding again."
              />
            </Card>
          ) : (
            groups.map((group) => (
            <section key={group.id} className="mb-6 last:mb-0">
              <div className="mb-2.5 flex flex-wrap items-baseline gap-2">
                <h2 className="text-sm font-bold">{group.name}</h2>
                <span className="text-xs tabular-nums text-[var(--muted)]">
                  {group.items.length}
                </span>
                {group.high > 0 && (
                  <span
                    className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                    style={{
                      background: "color-mix(in oklab, var(--chart-overdue) 12%, transparent)",
                      color: "var(--chart-overdue)",
                    }}
                  >
                    {group.high} needing attention
                  </span>
                )}
              </div>
            <ul className="space-y-3">
              {group.items.map((f, i) => (
                <li key={`${f.kind}-${i}`}>
                  <Card
                    className={
                      f.kind === "silent_change" || f.kind === "released"
                        ? "border-red-500/40 p-4 ring-2 ring-red-500/25"
                        : "p-4"
                    }
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <span className="mb-1.5 flex flex-wrap items-center gap-1.5">
                          <span
                            className={`inline-block rounded-full border px-2 py-0.5 text-[11px] font-medium ${SEVERITY[f.severity]}`}
                          >
                            {KIND_LABEL[f.kind] ?? f.kind}
                          </span>
                          {/* Repeated from the section heading on purpose: a
                              card scrolled away from its heading, or shared on
                              its own, still has to say which project it is. */}
                          <span
                            className="inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold"
                            style={{
                              background: f.project_name
                                ? "var(--accent-soft)"
                                : "var(--surface-2)",
                              color: f.project_name
                                ? "var(--accent)"
                                : "var(--muted)",
                            }}
                          >
                            {f.project_name ?? "No project"}
                          </span>
                        </span>
                        <p className="text-sm font-medium">{f.title}</p>
                        <p className="mt-0.5 text-sm text-[var(--muted)]">{f.detail}</p>
                      </div>
                      {f.due_at && (
                        <span className="shrink-0 text-xs text-[var(--muted)]">
                          {new Date(f.due_at).toLocaleDateString()}
                        </span>
                      )}
                    </div>

                    {f.evidence && (
                      <blockquote className="mt-3 border-l-2 border-[var(--accent)] bg-[var(--background)] px-3 py-2 text-xs italic text-[var(--muted)]">
                        “{f.evidence}”
                      </blockquote>
                    )}

                    {f.related.length > 0 && (
                      <div className="mt-2 space-y-1">
                        {f.related.map((r, j) => (
                          <p key={j} className="text-xs text-[var(--muted)]">
                            <span className="font-medium">{r.role}:</span>{" "}
                            {r.text ?? r.meeting_title ?? r.commitment_id}
                            {r.due_at && ` (${new Date(r.due_at).toLocaleDateString()})`}
                          </p>
                        ))}
                      </div>
                    )}

                    {f.kind === "silent_change" && f.commitment_id && (
                      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-3">
                        <span className="text-xs text-[var(--muted)]">
                          Which date stands?
                        </span>
                        <button
                          type="button"
                          onClick={() => resolveChange(f.commitment_id!, "original")}
                          disabled={busyId === f.commitment_id}
                          className="rounded-full bg-[var(--navy)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-60"
                        >
                          {busyId === f.commitment_id ? <Spinner /> : "Keep the agreed date"}
                        </button>
                        <button
                          type="button"
                          onClick={() => resolveChange(f.commitment_id!, "new")}
                          disabled={busyId === f.commitment_id}
                          className="rounded-full border border-[var(--border)] px-3 py-1.5 text-xs font-semibold disabled:opacity-60"
                        >
                          Accept the new date
                        </button>
                      </div>
                    )}

                    {f.meeting_id && (
                      <Link
                        href={`/meetings/${f.meeting_id}`}
                        className="mt-2 inline-block text-xs text-[var(--accent)] hover:underline"
                      >
                        From “{f.meeting_title ?? "meeting"}” →
                      </Link>
                    )}
                  </Card>
                </li>
              ))}
            </ul>
            </section>
            ))
          )}
        </>
      )}

      {tab === "commitments" && (
        commitments.length === 0 ? (
          <Card>
            <EmptyState title="No commitments recorded yet" />
          </Card>
        ) : (
          commitmentsByProject.map((group) => (
        <Card key={group.id} className="mb-4 last:mb-0">
          <h2 className="flex items-baseline justify-between gap-3 border-b border-[var(--border)] px-5 py-3">
            <span className="truncate text-sm font-bold">{group.name}</span>
            <span className="shrink-0 text-xs tabular-nums text-[var(--muted)]">
              {group.done}/{group.items.length} done
            </span>
          </h2>
          {(
            <ul className="divide-y divide-[var(--border)]">
              {group.items.map((c) => (
                <li key={c.id} className="flex items-start justify-between gap-4 px-5 py-3">
                  <div className="min-w-0">
                    <p
                      className={`text-sm ${c.status === "completed" ? "line-through opacity-60" : ""}`}
                    >
                      {c.text}
                    </p>
                    <p className="mt-0.5 text-xs text-[var(--muted)]">
                      {c.owner_name ?? "unassigned"}
                      {c.due_at && ` · due ${new Date(c.due_at).toLocaleDateString()}`}
                      {c.status === "superseded" && " · superseded"}
                      {c.meeting_title && ` · from “${c.meeting_title}”`}
                    </p>
                  </div>
                  {c.status !== "superseded" && (
                    <button
                      onClick={() =>
                        setStatus(c.id, c.status === "completed" ? "pending" : "completed")
                      }
                      disabled={busyId === c.id}
                      className="shrink-0 rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs transition hover:bg-[var(--background)] disabled:opacity-50"
                    >
                      {busyId === c.id ? <Spinner /> : c.status === "completed" ? "Reopen" : "Mark done"}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
          ))
        )
      )}

      {tab === "timeline" && (
        <Card className="p-5">
          {timeline.length === 0 ? (
            <EmptyState title="No commitment history yet" />
          ) : (
            <ol className="relative space-y-4 border-l border-[var(--border)] pl-5">
              {timeline.map((e, i) => (
                <li key={`${e.commitment_id}-${i}`} className="relative">
                  <span
                    className={`absolute -left-[26px] top-1.5 h-2.5 w-2.5 rounded-full ${
                      e.event === "completed"
                        ? "bg-emerald-500"
                        : e.supersedes_id
                          ? "bg-amber-500"
                          : "bg-[var(--accent)]"
                    }`}
                  />
                  <p className="text-xs text-[var(--muted)]">
                    {new Date(e.at).toLocaleString()} ·{" "}
                    {e.supersedes_id ? "updated" : e.event}
                  </p>
                  <p className="text-sm">{e.text}</p>
                  {e.due_at && (
                    <p className="text-xs text-[var(--muted)]">
                      due {new Date(e.due_at).toLocaleDateString()}
                    </p>
                  )}
                </li>
              ))}
            </ol>
          )}
        </Card>
      )}
    </main>
  );
}
