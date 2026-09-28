"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  type ProgressData,
  type ProjectSummary,
  progressApi,
  projectApi,
  promiseApi,
} from "@/lib/api";
import { Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from "@/components/ui";

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "neutral" | "good" | "warn" | "bad";
}) {
  const tones = {
    neutral: "text-[var(--foreground)]",
    good: "text-emerald-600 dark:text-emerald-400",
    warn: "text-amber-600 dark:text-amber-400",
    bad: "text-red-600 dark:text-red-400",
  };
  return (
    <Card className="p-4">
      <p className="text-xs uppercase tracking-wide text-[var(--muted)]">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tones[tone]}`}>{value}</p>
    </Card>
  );
}

export default function ProgressPage() {
  const [data, setData] = useState<ProgressData | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    projectApi.list().then(setProjects).catch(() => setProjects([]));
  }, []);

  const load = useCallback(async () => {
    try {
      setData(await progressApi.get(projectId || undefined));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load progress.");
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  async function toggle(id: string, done: boolean) {
    setBusyId(id);
    try {
      await promiseApi.setStatus(id, done ? "completed" : "pending");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Update failed.");
    } finally {
      setBusyId(null);
    }
  }

  if (!data) {
    return (
      <main className="mx-auto flex max-w-5xl items-center gap-2 px-4 py-16 text-sm text-[var(--muted)]">
        <Spinner /> Loading your progress…
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <Link href="/dashboard" className="text-sm text-[var(--accent)] hover:underline">
        ← Dashboard
      </Link>

      <header className="mt-4 mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">My Progress</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Everything you owe, across your projects.
          </p>
        </div>
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
      </header>

      {error && (
        <div className="mb-5">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Pending" value={data.totals.pending} tone="neutral" />
        <Stat label="Completed" value={data.totals.completed} tone="good" />
        <Stat label="Overdue" value={data.totals.overdue} tone="bad" />
        <Stat label="Next 14 days" value={data.totals.upcoming} tone="warn" />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            Overdue
          </h2>
          {data.overdue.length === 0 ? (
            <EmptyState title="Nothing overdue" hint="You are on top of things." />
          ) : (
            <ul className="divide-y divide-[var(--border)]">
              {data.overdue.map((c) => (
                <li key={c.id} className="flex items-center justify-between gap-3 px-5 py-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm">{c.text}</p>
                    <p className="text-xs text-red-500">
                      was due {c.due_at ? new Date(c.due_at).toLocaleDateString() : "—"}
                    </p>
                  </div>
                  <button
                    onClick={() => toggle(c.id, true)}
                    disabled={busyId === c.id}
                    className="shrink-0 rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs hover:bg-[var(--background)] disabled:opacity-50"
                  >
                    {busyId === c.id ? <Spinner /> : "Done"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <h2 className="border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            Upcoming
          </h2>
          {data.upcoming.length === 0 ? (
            <EmptyState title="Nothing due in the next two weeks" />
          ) : (
            <ul className="divide-y divide-[var(--border)]">
              {data.upcoming.map((c) => (
                <li key={c.id} className="flex items-center justify-between gap-3 px-5 py-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm">{c.text}</p>
                    <p className="text-xs text-[var(--muted)]">
                      {c.owner_name ?? "unassigned"} ·{" "}
                      {c.due_at ? new Date(c.due_at).toLocaleDateString() : "no date"}
                    </p>
                  </div>
                  <button
                    onClick={() => toggle(c.id, true)}
                    disabled={busyId === c.id}
                    className="shrink-0 rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs hover:bg-[var(--background)] disabled:opacity-50"
                  >
                    {busyId === c.id ? <Spinner /> : "Done"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <h2 className="border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            Project progress
          </h2>
          {data.by_project.length === 0 ? (
            <EmptyState title="No projects with commitments yet" />
          ) : (
            <ul className="space-y-3 px-5 py-4">
              {data.by_project.map((p) => (
                <li key={p.project_id ?? "unassigned"}>
                  <div className="mb-1 flex items-baseline justify-between text-sm">
                    <span className="font-medium">{p.project_name}</span>
                    <span className="text-xs text-[var(--muted)]">
                      {p.completed}/{p.total}
                      {p.overdue > 0 && (
                        <span className="ml-2 text-red-500">{p.overdue} overdue</span>
                      )}
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--background)]">
                    <div
                      className="h-full rounded-full bg-[var(--accent)] transition-all"
                      style={{ width: `${p.percent}%` }}
                    />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <h2 className="border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            PromiseMirror alerts
          </h2>
          {data.alerts.length === 0 ? (
            <EmptyState title="No alerts" />
          ) : (
            <ul className="divide-y divide-[var(--border)]">
              {data.alerts.map((a, i) => (
                <li key={i} className="px-5 py-3">
                  <p className="text-sm">{a.title}</p>
                  <p className="text-xs text-[var(--muted)]">{a.detail}</p>
                  {a.meeting_id && (
                    <Link
                      href={`/meetings/${a.meeting_id}`}
                      className="text-xs text-[var(--accent)] hover:underline"
                    >
                      view meeting →
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card className="mt-6">
        <h2 className="border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
          Recent meetings
        </h2>
        {data.recent_meetings.length === 0 ? (
          <EmptyState title="No meetings yet" />
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {data.recent_meetings.map((m) => (
              <li key={m.id}>
                <Link
                  href={`/meetings/${m.id}`}
                  className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-[var(--background)]"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm">{m.title}</p>
                    <p className="text-xs text-[var(--muted)]">
                      {new Date(m.created_at).toLocaleString()}
                    </p>
                  </div>
                  <StatusBadge status={m.status} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </main>
  );
}
