"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  type ProgressData,
  type ProjectSummary,
  progressApi,
  projectApi,
  promiseApi,
} from "@/lib/api";
import { Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from "@/components/ui";
import { DonutChart, ProgressBars, TrendBars } from "@/components/charts";
import { SeeAllFooter } from "@/components/MeetingList";

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
    good: "text-emerald-600",
    warn: "text-amber-600",
    bad: "text-red-600",
  };
  return (
    <Card className="p-4">
      <p className="text-xs uppercase tracking-wide text-[var(--muted)]">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tones[tone]}`}>{value}</p>
    </Card>
  );
}

// The rest of the alerts live on the Promises page, grouped and filterable.
const ALERTS_PREVIEW = 5;

export default function ProgressPage() {
  const [data, setData] = useState<ProgressData | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  useEffect(() => {
    projectApi.list().then(setProjects).catch(() => setProjects([]));
  }, []);

  // `keep` lets the caller discard a response it no longer wants. Switching
  // project twice quickly can otherwise land the first reply after the second.
  const load = useCallback(
    async (keep: () => boolean = () => true) => {
      try {
        const next = await progressApi.get(projectId || undefined);
        if (keep()) setData(next);
      } catch (err) {
        if (keep()) {
          setError(err instanceof ApiError ? err.message : "Failed to load progress.");
        }
      }
    },
    [projectId],
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

  // Overdue is carved out of pending rather than added alongside it, so the
  // ring sums to the real number of commitments instead of double-counting.
  const statusSlices = useMemo(() => {
    const t = data?.totals;
    if (!t) return [];
    return [
      {
        label: "Completed",
        value: t.completed,
        color: "var(--chart-completed)",
      },
      {
        label: "Pending",
        value: Math.max(t.pending - t.overdue, 0),
        color: "var(--chart-pending)",
      },
      { label: "Due soon", value: t.upcoming, color: "var(--chart-upcoming)" },
      { label: "Overdue", value: t.overdue, color: "var(--chart-overdue)" },
    ];
  }, [data]);

  const projectRows = useMemo(
    () =>
      (data?.by_project ?? []).map((p) => ({
        label: p.project_name,
        value: p.completed,
        total: p.total,
        overdue: p.overdue,
      })),
    [data],
  );

  // Eight weeks of "made" against "closed". Growing distance between the two
  // is the backlog forming, which no single total shows.
  const weeklyTrend = useMemo(() => {
    if (!data) return [];
    const all = [...data.pending, ...data.completed, ...data.overdue];
    const WEEKS = 8;
    const now = new Date();
    const startOfWeek = (d: Date) => {
      const c = new Date(d);
      c.setHours(0, 0, 0, 0);
      c.setDate(c.getDate() - ((c.getDay() + 6) % 7));
      return c;
    };
    const thisWeek = startOfWeek(now);
    const buckets = Array.from({ length: WEEKS }, (_, i) => {
      const start = new Date(thisWeek);
      start.setDate(start.getDate() - (WEEKS - 1 - i) * 7);
      return {
        start,
        label: start.toLocaleDateString(undefined, { day: "numeric", month: "short" }),
        made: 0,
        closed: 0,
      };
    });
    const indexFor = (iso: string | null | undefined) => {
      if (!iso) return -1;
      const when = startOfWeek(new Date(iso));
      if (Number.isNaN(when.getTime())) return -1;
      return buckets.findIndex((b) => b.start.getTime() === when.getTime());
    };
    for (const c of all) {
      const made = indexFor(c.created_at);
      if (made >= 0) buckets[made].made += 1;
      const closed = indexFor(c.completed_at);
      if (closed >= 0) buckets[closed].closed += 1;
    }
    return buckets.map(({ label, made, closed }) => ({ label, made, closed }));
  }, [data]);

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

      <div className="mb-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            Where your commitments stand
          </h2>
          <div className="px-5 py-5">
            <DonutChart
              slices={statusSlices}
              total={
                data.totals.pending + data.totals.completed + data.totals.overdue
              }
              totalLabel="Commitments"
            />
          </div>
        </Card>

        <Card>
          <h2 className="border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            Made vs closed, by week
          </h2>
          <div className="px-5 py-5">
            <TrendBars buckets={weeklyTrend} />
          </div>
        </Card>
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
          <div className="px-5 py-4">
            <ProgressBars rows={projectRows} />
          </div>
        </Card>

        <Card>
          <h2 className="border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            PromiseMirror alerts
          </h2>
          {data.alerts.length === 0 ? (
            <EmptyState title="No alerts" />
          ) : (
            <>
              <ul className="divide-y divide-[var(--border)]">
                {data.alerts.slice(0, ALERTS_PREVIEW).map((a, i) => (
                  <li key={i} className="px-5 py-3">
                    {/* This list spans every project, so each row names its
                        own — the same pill My Promises uses, so the two
                        views read alike. */}
                    {a.project_name && (
                      <span
                        className="mb-1 inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold"
                        style={{
                          background: "var(--accent-soft)",
                          color: "var(--accent)",
                        }}
                      >
                        {a.project_name}
                      </span>
                    )}
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
              <SeeAllFooter
                shown={ALERTS_PREVIEW}
                total={data.alerts.length}
                href="/promises"
                label="See all alerts"
              />
            </>
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
