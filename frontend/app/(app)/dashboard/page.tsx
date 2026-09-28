"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, TERMINAL_STATUSES, type Meeting } from "@/lib/api";
import { JoinMeetingForm } from "@/components/JoinMeetingForm";
import { Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from "@/components/ui";
import { useAuth } from "@/components/AuthGate";
import { ManagerDashboard } from "@/components/ManagerDashboard";

const POLL_MS = 6000;

export default function DashboardPage() {
  const { user } = useAuth();
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      const rows = await api.listMeetings();
      setMeetings(rows);
      setBackendDown(false);
      return rows;
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) setBackendDown(true);
      else setError(err instanceof Error ? err.message : "Failed to load meetings.");
      setMeetings((prev) => prev ?? []);
      return [] as Meeting[];
    }
  }, []);

  // Poll only while something is still in flight, then stop.
  useEffect(() => {
    let cancelled = false;

    async function tick() {
      const rows = await load();
      if (cancelled) return;
      const live = rows.some((m) => !TERMINAL_STATUSES.has(m.status ?? ""));
      if (live || backendDown) {
        timer.current = setTimeout(tick, POLL_MS);
      }
    }

    tick();
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load]);

  async function refreshStatuses() {
    const rows = meetings ?? [];
    await Promise.all(
      rows
        .filter((m) => !TERMINAL_STATUSES.has(m.status ?? ""))
        .map((m) => api.getStatus(m.id).catch(() => null)),
    );
    load();
  }

  if (user?.role === "manager") return <ManagerDashboard />;

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <header className="mb-8 overflow-hidden rounded-[1.75rem] bg-[var(--navy)] px-5 py-7 text-white shadow-[0_24px_60px_-34px_rgb(21_27_46/.65)] sm:px-8 sm:py-9">
        <div className="flex flex-col justify-between gap-7 sm:flex-row sm:items-end">
          <div>
            <span className="inline-flex rounded-full bg-white/10 px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.14em] text-white/70">Your workspace</span>
            <h1 className="mt-4 text-2xl font-semibold tracking-tight text-white">Your meeting command center</h1>
            <p className="mt-2 text-sm text-white/60">
              Capture the conversation, surface every commitment, and keep work moving.
            </p>
          </div>
          <div className="flex flex-wrap gap-2 text-[10px] font-semibold text-white/70">
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5">Live transcript</span>
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5">Smart summaries</span>
            <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5">Action tracking</span>
          </div>
        </div>
      </header>

      {backendDown && (
        <div className="mb-6">
          <ErrorBanner
            message="Cannot reach the backend. Start FastAPI with: cd backend; .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"
          />
        </div>
      )}
      {error && (
        <div className="mb-6">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
        <Card className="h-fit p-5">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            New meeting
          </h2>
          <JoinMeetingForm
            onJoined={(m) => setMeetings((prev) => [m, ...(prev ?? [])])}
          />
        </Card>

        <Card>
          <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3.5">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
              Meeting history
            </h2>
            <button
              onClick={refreshStatuses}
              className="text-xs font-medium text-[var(--accent)] hover:underline"
            >
              Refresh
            </button>
          </div>

          {meetings === null ? (
            <div className="flex items-center justify-center gap-2 px-5 py-12 text-sm text-[var(--muted)]">
              <Spinner /> Loading meetings…
            </div>
          ) : meetings.length === 0 ? (
            <EmptyState
              title="No meetings yet"
              hint="Paste a meeting link to send the notetaker."
            />
          ) : (
            <ul className="divide-y divide-[var(--border)]">
              {meetings.map((m) => (
                <li key={m.id}>
                  <Link
                    href={`/meetings/${m.id}`}
                    className="flex items-center justify-between gap-4 px-5 py-4 transition hover:bg-[var(--background)]"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">
                        {m.title || m.meeting_url}
                      </p>
                      <p className="mt-0.5 text-xs text-[var(--muted)]">
                        {new Date(m.created_at).toLocaleString()} · {m.platform}
                        {m.has_summary && " · summarised"}
                      </p>
                    </div>
                    <StatusBadge status={m.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <footer className="mt-10 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border)] pt-5 text-xs text-[var(--muted)]">
        <span>MeetMind keeps your meeting history organized and searchable.</span>
        <Link href="/progress" className="font-semibold text-[var(--accent)] hover:underline">View progress →</Link>
      </footer>
    </main>
  );
}
