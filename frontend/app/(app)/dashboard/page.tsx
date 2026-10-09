"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  API_BASE,
  TERMINAL_STATUSES,
  promiseApi,
  type Finding,
  type Meeting,
} from "@/lib/api";
import { JoinMeetingForm } from "@/components/JoinMeetingForm";
import { Card, ErrorBanner } from "@/components/ui";
import { MeetingList, SeeAllFooter } from "@/components/MeetingList";
import { useAuth } from "@/components/AuthGate";

const POLL_MS = 6000;
// The dashboard is a landing pad, not an archive: the rest live on /meetings.
const HISTORY_PREVIEW = 5;

export default function DashboardPage() {
  const { user } = useAuth();
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [backendDown, setBackendDown] = useState(false);
  // The API is up but a dependency it needs is not; /health says which.
  const [degradedHint, setDegradedHint] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // A deadline that moved without anyone saying so is worth interrupting for,
  // so it is surfaced here and not only inside My Promises.
  const [silentChanges, setSilentChanges] = useState<Finding[]>([]);

  const load = useCallback(async () => {
    try {
      const rows = await api.listMeetings();
      setMeetings(rows);
      setBackendDown(false);
      setDegradedHint(null);
      return rows;
    } catch (err) {
      if (err instanceof ApiError && err.status === 0) {
        setBackendDown(true);
      } else {
        // The API answered, so it is running — something it depends on is not.
        // Ask /health which, rather than blaming the API the user just started.
        const health = await api.health().catch(() => null);
        if (health && health.status === "degraded" && health.hint) {
          setDegradedHint(health.hint);
        } else {
          setError(err instanceof Error ? err.message : "Failed to load meetings.");
        }
      }
      setMeetings((prev) => prev ?? []);
      return [] as Meeting[];
    }
  }, []);

  useEffect(() => {
    promiseApi
      .findings()
      .then((r) => setSilentChanges(r.findings.filter((f) => f.kind === "silent_change")))
      .catch(() => setSilentChanges([]));
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

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <header className="mb-8 overflow-hidden rounded-[1.75rem] bg-[var(--navy)] px-5 py-7 text-white shadow-[0_24px_60px_-34px_rgb(21_27_46/.65)] sm:px-8 sm:py-9">
        <div className="flex flex-col justify-between gap-7 sm:flex-row sm:items-end">
          <div>
            <span className="inline-flex rounded-full bg-white/10 px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.14em] text-white/70">Your workspace</span>
            <h1 className="mt-4 text-2xl font-semibold tracking-tight text-white">
              {user?.name ? `Welcome back, ${user.name.split(" ")[0]}` : "Your meeting command center"}
            </h1>
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

      {silentChanges.length > 0 && (
        <div className="mb-6 rounded-2xl border border-red-500/40 bg-red-500/[0.06] px-5 py-4 ring-1 ring-red-500/20">
          <p className="flex items-center gap-2 text-sm font-semibold text-red-600">
            <span aria-hidden>⚠</span>
            {silentChanges.length === 1
              ? "A deadline changed without being agreed"
              : `${silentChanges.length} deadlines changed without being agreed`}
          </p>
          <ul className="mt-2 space-y-1.5">
            {silentChanges.slice(0, 3).map((f, i) => (
              <li key={i} className="text-sm text-[var(--muted-strong)]">
                <span className="font-medium">{f.title.replace(/^Deadline moved without being agreed: /, "")}</span>
                <span className="block text-xs text-[var(--muted)]">{f.detail}</span>
              </li>
            ))}
          </ul>
          <Link
            href="/promises"
            className="mt-3 inline-block text-xs font-semibold text-[var(--accent)] hover:underline"
          >
            Review and confirm which date stands →
          </Link>
        </div>
      )}

      {backendDown && (
        <div className="mb-6">
          <ErrorBanner
            // The port comes from API_BASE rather than being written out here,
            // so this can never tell you to start the backend on a port the
            // frontend is not actually calling.
            message={
              `Cannot reach the backend at ${API_BASE}. Start FastAPI with: ` +
              `cd backend; .\\.venv\\Scripts\\python.exe -m uvicorn app.main:app ` +
              `--reload --port ${new URL(API_BASE).port || "8000"}`
            }
          />
        </div>
      )}
      {degradedHint && (
        <div className="mb-6">
          <ErrorBanner message={degradedHint} />
        </div>
      )}
      {error && (
        <div className="mb-6">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}
      {notice && (
        <div className="mb-6 flex items-start justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm text-[var(--muted-strong)]">
          <span>{notice}</span>
          <button
            onClick={() => setNotice(null)}
            className="shrink-0 text-xs font-semibold text-[var(--accent)] hover:underline"
          >
            Dismiss
          </button>
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

          <MeetingList
            meetings={meetings === null ? null : meetings.slice(0, HISTORY_PREVIEW)}
            onRemoved={(id) =>
              setMeetings((rows) => (rows ?? []).filter((m) => m.id !== id))
            }
            onError={setError}
            onNotice={setNotice}
          />
          {meetings !== null && (
            <SeeAllFooter
              shown={HISTORY_PREVIEW}
              total={meetings.length}
              href="/meetings"
              label="See all meetings"
            />
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
