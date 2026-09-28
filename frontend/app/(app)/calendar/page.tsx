"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  API_BASE,
  ApiError,
  type CalendarConnection,
  type CalendarEvent,
  type DeadlineEntry,
  type Meeting,
  api,
  calendarApi,
} from "@/lib/api";
import { Card, EmptyState, ErrorBanner, Spinner } from "@/components/ui";
import { MonthCalendar, type CalendarItem } from "@/components/MonthCalendar";

export default function CalendarPage() {
  const [calendars, setCalendars] = useState<CalendarConnection[] | null>(null);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyEvent, setBusyEvent] = useState<string | null>(null);
  const [deadlines, setDeadlines] = useState<DeadlineEntry[]>([]);
  const [consent, setConsent] = useState(false);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  // Surface the OAuth redirect outcome.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("connected")) setNotice("Calendar connected.");
    const err = params.get("error");
    if (err) setError(`Could not connect the calendar: ${err.replace(/_/g, " ")}`);
  }, []);

  const loadCalendars = useCallback(async () => {
    try {
      const rows = await calendarApi.list();
      setCalendars(rows);
      if (rows.length && !selected) setSelected(rows[0].id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load calendars.");
      setCalendars([]);
    }
  }, [selected]);

  useEffect(() => {
    loadCalendars();
  }, [loadCalendars]);

  const loadDeadlines = useCallback(async () => {
    try {
      setDeadlines(await calendarApi.deadlines());
    } catch {
      /* non-fatal: the rest of the page still works */
    }
  }, []);

  useEffect(() => {
    loadDeadlines();
  }, [loadDeadlines]);

  const loadMeetings = useCallback(async () => {
    try {
      setMeetings(await api.listMeetings());
    } catch {
      /* non-fatal: the grid simply shows fewer items */
    }
  }, []);

  useEffect(() => {
    loadMeetings();
  }, [loadMeetings]);

  // Everything that has a date, in one shape the month grid understands.
  const calendarItems: CalendarItem[] = [
    ...meetings.map((m) => ({
      id: `m-${m.id}`,
      date: m.created_at,
      title: m.title || m.meeting_url,
      kind: "meeting" as const,
      detail: m.status,
      href: `/meetings/${m.id}`,
    })),
    ...deadlines
      .filter((d) => d.due_at)
      .map((d) => ({
        id: `d-${d.id}`,
        date: d.due_at as string,
        title: d.what,
        kind: "deadline" as const,
        detail: d.meeting_title,
        href: d.google_event_link,
        confirmed: d.on_calendar,
      })),
    ...events
      .filter((e) => e.start_time)
      .map((e) => ({
        id: `e-${e.id}`,
        date: e.start_time,
        title: e.title ?? "Untitled event",
        kind: (e.bot_scheduled ? "scheduled" : "event") as CalendarItem["kind"],
        detail: e.meeting_url ? e.meeting_platform : "no meeting link",
        confirmed: e.bot_scheduled,
      })),
  ];

  const isConnected = (calendars ?? []).some((c) => c.status === "connected");

  async function refreshAll() {
    setRefreshing(true);
    try {
      await Promise.all([
        loadDeadlines(),
        loadMeetings(),
        selected ? loadEvents(selected) : Promise.resolve(),
      ]);
    } finally {
      setRefreshing(false);
    }
  }

  const loadEvents = useCallback(async (calendarId: string) => {
    try {
      setEvents(await calendarApi.events(calendarId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load events.");
    }
  }, []);

  useEffect(() => {
    if (selected) loadEvents(selected);
  }, [selected, loadEvents]);

  async function connect() {
    setError(null);
    try {
      const { authorization_url } = await calendarApi.startOAuth();
      window.location.href = authorization_url;
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not start Google authorisation.",
      );
    }
  }

  async function toggleSchedule(event: CalendarEvent) {
    setBusyEvent(event.id);
    setError(null);
    try {
      if (event.bot_scheduled) {
        await calendarApi.unschedule(event.id);
      } else {
        await calendarApi.schedule(event.id, true);
      }
      if (selected) await loadEvents(selected);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Scheduling failed.");
    } finally {
      setBusyEvent(null);
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <Link href="/dashboard" className="text-sm text-[var(--accent)] hover:underline">
        ← Dashboard
      </Link>

      <header className="mt-4 mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Calendar scheduling</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Connect Google Calendar and choose which upcoming meetings the notetaker
          should join automatically.
        </p>
      </header>

      {notice && (
        <p className="mb-5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-sm text-emerald-700 dark:text-emerald-300">
          {notice}
        </p>
      )}
      {error && (
        <div className="mb-5">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}

      <Card className="mb-6 p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Connected calendars</h2>
            <p className="mt-0.5 text-xs text-[var(--muted)]">
              MeetMind reads your events and adds meeting deadlines back to your calendar.
            </p>
          </div>
          {isConnected ? (
            <div className="flex items-center gap-2">
              <span
                className="inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold"
                style={{
                  borderColor: "color-mix(in oklab, var(--success) 35%, transparent)",
                  background: "var(--success-soft)",
                  color: "var(--success)",
                }}
              >
                <span
                  aria-hidden
                  className="grid h-3.5 w-3.5 place-items-center rounded-full text-[9px] text-white"
                  style={{ background: "var(--success)" }}
                >
                  ✓
                </span>
                Connected
              </span>
              <button
                onClick={connect}
                title="Reconnect to refresh permissions or switch account"
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-xs font-semibold transition hover:bg-[var(--surface-2)]"
              >
                Reconnect
              </button>
            </div>
          ) : (
            <button
              onClick={connect}
              className="rounded-lg bg-[var(--accent)] px-3.5 py-2 text-sm font-semibold text-[var(--accent-fg)] transition hover:opacity-90"
            >
              Connect Google Calendar
            </button>
          )}
        </div>

        {calendars === null ? (
          <p className="mt-4 flex items-center gap-2 text-sm text-[var(--muted)]">
            <Spinner /> Loading…
          </p>
        ) : calendars.length === 0 ? (
          <p className="mt-4 text-sm text-[var(--muted)]">No calendars connected yet.</p>
        ) : (
          <ul className="mt-4 space-y-2">
            {calendars.map((c) => (
              <li key={c.id}>
                <button
                  onClick={() => setSelected(c.id)}
                  className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition ${
                    selected === c.id
                      ? "border-[var(--accent)] bg-[var(--accent)]/5"
                      : "border-[var(--border)] hover:bg-[var(--background)]"
                  }`}
                >
                  <span className="font-medium">{c.email ?? c.recall_calendar_id}</span>
                  <span className="ml-2 text-xs text-[var(--muted)]">
                    {c.platform} {c.status ? `· ${c.status}` : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="my-6">
        <MonthCalendar
          items={calendarItems}
          onRefresh={refreshAll}
          busy={refreshing}
        />
      </div>

      <Card>
        <div className="border-b border-[var(--border)] px-5 py-3.5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            Upcoming meetings
          </h2>
        </div>

        <div className="border-b border-[var(--border)] bg-amber-500/5 px-5 py-3">
          <label className="flex cursor-pointer items-start gap-2.5 text-sm">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              className="mt-0.5 h-4 w-4 shrink-0 accent-amber-600"
            />
            <span className="text-amber-900 dark:text-amber-200">
              I confirm participants of the meetings I schedule will be told that
              <strong> MeetMind AI Notetaker </strong> records and transcribes.
            </span>
          </label>
        </div>

        {!selected ? (
          <EmptyState title="Connect a calendar to see upcoming meetings" />
        ) : events.length === 0 ? (
          <EmptyState
            title="No upcoming meetings"
            hint="Events with a meeting link appear here."
          />
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {events.map((e) => (
              <li
                key={e.id}
                className="flex items-center justify-between gap-4 px-5 py-4"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {e.title ?? "Untitled event"}
                  </p>
                  <p className="mt-0.5 text-xs text-[var(--muted)]">
                    {new Date(e.start_time).toLocaleString()}
                    {e.meeting_url ? ` · ${e.meeting_platform ?? "meeting"}` : " · no link"}
                  </p>
                </div>
                <button
                  onClick={() => toggleSchedule(e)}
                  disabled={!e.meeting_url || busyEvent === e.id || (!consent && !e.bot_scheduled)}
                  title={
                    !e.meeting_url
                      ? "This event has no meeting link"
                      : !consent && !e.bot_scheduled
                        ? "Confirm consent above first"
                        : undefined
                  }
                  className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${
                    e.bot_scheduled
                      ? "border border-[var(--border)] hover:bg-[var(--background)]"
                      : "bg-[var(--accent)] text-[var(--accent-fg)] hover:opacity-90"
                  }`}
                >
                  {busyEvent === e.id && <Spinner />}
                  {e.bot_scheduled ? "Cancel bot" : "Schedule bot"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="mt-6">
        <div className="border-b border-[var(--border)] px-5 py-3.5">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            Deadlines from your meetings
          </h2>
          <p className="mt-0.5 text-xs text-[var(--muted)]">
            Extracted by MeetMind. Those marked on your calendar exist as all-day
            events in Google Calendar.
          </p>
        </div>
        {deadlines.length === 0 ? (
          <EmptyState
            title="No deadlines yet"
            hint="Record a meeting where a date is mentioned."
          />
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {deadlines.map((d) => (
              <li
                key={d.id}
                className="flex items-center justify-between gap-4 px-5 py-3"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm">{d.what}</p>
                  <p className="mt-0.5 text-xs text-[var(--muted)]">
                    {d.due_at
                      ? new Date(d.due_at).toLocaleDateString(undefined, {
                          weekday: "short",
                          day: "numeric",
                          month: "short",
                          year: "numeric",
                        })
                      : "no resolvable date"}
                    {d.meeting_title ? ` · from “${d.meeting_title}”` : ""}
                  </p>
                </div>
                {d.on_calendar ? (
                  <a
                    href={d.google_event_link ?? "#"}
                    target="_blank"
                    rel="noreferrer"
                    className="shrink-0 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-600 hover:underline dark:text-emerald-400"
                  >
                    On calendar ↗
                  </a>
                ) : (
                  <span className="shrink-0 rounded-full border border-[var(--border)] px-2.5 py-1 text-xs text-[var(--muted)]">
                    Not added
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <p className="mt-6 text-xs text-[var(--muted)]">
        Backend: {API_BASE}
      </p>
    </main>
  );
}
