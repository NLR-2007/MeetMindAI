"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
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
  high: "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400",
  medium: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400",
  low: "border-[var(--border)] bg-[var(--background)] text-[var(--muted)]",
};

const KIND_LABEL: Record<string, string> = {
  overdue: "Overdue",
  approaching: "Due soon",
  conflicting: "Clashing dates",
  unowned: "No owner",
  undated: "No date",
  changed: "Changed",
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

  useEffect(() => {
    projectApi.list().then(setProjects).catch(() => setProjects([]));
    api.listMeetings().then(setMeetings).catch(() => setMeetings([]));
  }, []);

  const load = useCallback(async () => {
    const pid = projectId || undefined;
    const mid = meetingId || undefined;
    try {
      const [f, c, t] = await Promise.all([
        promiseApi.findings(pid, mid),
        promiseApi.commitments(pid, mid),
        promiseApi.timeline(pid, mid),
      ]);
      setFindings(f.findings);
      setByKind(f.by_kind);
      setCommitments(c);
      setTimeline(t);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load commitments.");
      setFindings([]);
    }
  }, [projectId, meetingId]);

  useEffect(() => {
    load();
  }, [load]);

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
          onChange={(e) => setProjectId(e.target.value)}
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
          <option value="">All meetings</option>
          {meetings.map((m) => (
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
          {Object.keys(byKind).length > 0 && (
            <div className="mb-4 flex flex-wrap gap-2">
              {Object.entries(byKind).map(([kind, n]) => (
                <span
                  key={kind}
                  className="rounded-full border border-[var(--border)] px-3 py-1 text-xs"
                >
                  {KIND_LABEL[kind] ?? kind}: <strong>{n}</strong>
                </span>
              ))}
            </div>
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
          ) : (
            <ul className="space-y-3">
              {findings.map((f, i) => (
                <li key={`${f.kind}-${i}`}>
                  <Card className="p-4">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <span
                          className={`mb-1.5 inline-block rounded-full border px-2 py-0.5 text-[11px] font-medium ${SEVERITY[f.severity]}`}
                        >
                          {KIND_LABEL[f.kind] ?? f.kind}
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
          )}
        </>
      )}

      {tab === "commitments" && (
        <Card>
          {commitments.length === 0 ? (
            <EmptyState title="No commitments recorded yet" />
          ) : (
            <ul className="divide-y divide-[var(--border)]">
              {commitments.map((c) => (
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
