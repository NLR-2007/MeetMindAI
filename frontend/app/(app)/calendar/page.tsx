"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";
import {
  API_BASE,
  ApiError,
  type CalendarConnection,
  type CalendarEvent,
  type DeadlineEntry,
  type Meeting,
  api,
  calendarApi,
  projectApi,
  type ProjectSummary,
} from "@/lib/api";
import { Card, EmptyState, ErrorBanner, Spinner } from "@/components/ui";
import { MonthCalendar, type CalendarItem } from "@/components/MonthCalendar";

// The deadline list is a staging area, not an archive; the rest expand in place.
const DEADLINES_PREVIEW = 5;

const CONSENT_KEY = "meetmind.calendar.consent";

/**
 * The scheduling-consent tick, kept in localStorage.
 *
 * Browser storage can throw (private mode, blocked site data), so every access
 * is guarded and failure simply means "not remembered" rather than an error.
 */
const consentStore = {
  listeners: new Set<() => void>(),
  subscribe(onChange: () => void) {
    consentStore.listeners.add(onChange);
    return () => {
      consentStore.listeners.delete(onChange);
    };
  },
  get(): boolean {
    try {
      return window.localStorage.getItem(CONSENT_KEY) === "yes";
    } catch {
      return false;
    }
  },
  set(next: boolean) {
    try {
      if (next) window.localStorage.setItem(CONSENT_KEY, "yes");
      else window.localStorage.removeItem(CONSENT_KEY);
    } catch {
      /* not being able to remember it is not worth surfacing */
    }
    consentStore.listeners.forEach((l) => l());
  },
};

export default function CalendarPage() {
  // The OAuth outcome arrives as a query string, and useSearchParams needs a
  // boundary so this page can still be prerendered.
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
          <p className="flex items-center gap-2 text-sm text-[var(--muted)]">
            <Spinner /> Loading calendar...
          </p>
        </main>
      }
    >
      <CalendarView />
    </Suspense>
  );
}

function CalendarView() {
  const searchParams = useSearchParams();
  const [calendars, setCalendars] = useState<CalendarConnection[] | null>(null);
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [outcomeDismissed, setOutcomeDismissed] = useState(false);
  const [busyEvent, setBusyEvent] = useState<string | null>(null);
  const [deadlines, setDeadlines] = useState<DeadlineEntry[]>([]);
  // Remembered per browser so it survives a reload: re-ticking the same box
  // every visit is friction, not a safeguard. useSyncExternalStore rather than
  // an effect, so the server snapshot is a definite false and hydration cannot
  // mismatch. It is only a UI convenience - the backend re-checks consent on
  // every schedule request, so a remembered tick schedules nothing by itself.
  const consent = useSyncExternalStore(
    consentStore.subscribe,
    consentStore.get,
    () => false,
  );
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [showAllDeadlines, setShowAllDeadlines] = useState(false);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  // Narrows the grid and the deadline list to one workstream. With a dozen
  // meetings a month the grid is unreadable otherwise.
  const [projectFilter, setProjectFilter] = useState("");

  // Read the redirect outcome straight from the URL instead of copying it into
  // state on mount: one source of truth, and no render cascade.
  const connectErrorParam = searchParams.get("error");
  const notice =
    outcomeDismissed || !searchParams.get("connected") ? null : "Calendar connected.";
  const oauthError =
    outcomeDismissed || !connectErrorParam
      ? null
      : connectErrorParam === "access_denied"
        ? // Google sends access_denied both when the user cancels and when the
          // account is not on the OAuth consent screen's test-user list. The
          // second is far more confusing, so name it explicitly: the raw
          // "access denied" sends people hunting for a bug in this app.
          "Google refused the connection (access_denied). Either you cancelled " +
          "on Google's screen, or this Google account is not an approved " +
          "tester. While the MeetMind AI OAuth app is in Testing mode, only " +
          "accounts listed under Google Cloud Console → APIs & Services → " +
          "OAuth consent screen → Test users can connect. Add the account " +
          "there, then try again."
        : `Could not connect the calendar: ${connectErrorParam.replace(/_/g, " ")}`;

  const loadDeadlines = useCallback(async () => {
    try {
      setDeadlines(await calendarApi.deadlines());
    } catch {
      /* non-fatal: the rest of the page still works */
    }
  }, []);

  const loadMeetings = useCallback(async () => {
    try {
      setMeetings(await api.listMeetings());
    } catch {
      /* non-fatal: the grid simply shows fewer items */
    }
  }, []);

  const loadEvents = useCallback(async (calendarId: string) => {
    try {
      setEvents(await calendarApi.events(calendarId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load events.");
    }
  }, []);

  // One first load for the three independent lists, applied in a single pass so
  // mounting does not trigger three extra renders. Nothing is written after
  // unmount, which matters because OAuth navigates away mid-flight.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [cals, dues, mtgs, projectRows] = await Promise.all([
        calendarApi.list().catch(() => null),
        calendarApi.deadlines().catch(() => [] as DeadlineEntry[]),
        api.listMeetings(200).catch(() => [] as Meeting[]),
        projectApi.list().catch(() => [] as ProjectSummary[]),
      ]);
      if (cancelled) return;
      setProjects(projectRows);
      if (cals === null) {
        setError("Failed to load calendars.");
        setCalendars([]);
      } else {
        setCalendars(cals);
        // Default to the first calendar, but never clobber a chosen one.
        if (cals.length) setSelected((prev) => prev ?? cals[0].id);
      }
      setDeadlines(dues);
      setMeetings(mtgs);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Events belong to whichever calendar is selected.
  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    (async () => {
      const rows = await calendarApi.events(selected).catch(() => null);
      if (cancelled) return;
      if (rows === null) setError("Failed to load events.");
      else setEvents(rows);
    })();
    return () => {
      cancelled = true;
    };
  }, [selected]);

  // A deadline has no project of its own: it inherits the project of the
  // meeting it was extracted from.
  const projectOfMeeting = useMemo(
    () => new Map(meetings.map((m) => [m.id, m.project_id])),
    [meetings],
  );
  const visibleMeetings = useMemo(
    () =>
      projectFilter
        ? meetings.filter((m) => m.project_id === projectFilter)
        : meetings,
    [meetings, projectFilter],
  );
  const visibleDeadlines = useMemo(
    () =>
      projectFilter
        ? deadlines.filter(
            (d) => projectOfMeeting.get(d.meeting_id) === projectFilter,
          )
        : deadlines,
    [deadlines, projectFilter, projectOfMeeting],
  );

  // Everything that has a date, in one shape the month grid understands.
  const calendarItems: CalendarItem[] = useMemo(() => [
    ...visibleMeetings.map((m) => ({
      id: `m-${m.id}`,
      date: m.created_at,
      title: m.title || m.meeting_url,
      kind: "meeting" as const,
      detail: m.status,
      href: `/meetings/${m.id}`,
    })),
    ...visibleDeadlines
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
    ],
    [visibleMeetings, visibleDeadlines, events],
  );

  const isConnected = (calendars ?? []).some((c) => c.status === "connected");
  const connectedAccounts = (calendars ?? [])
    .filter((c) => c.status === "connected" && c.email)
    .map((c) => c.email as string);

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
        <p className="mb-5 flex items-start justify-between gap-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-sm text-emerald-700">
          <span>{notice}</span>
          <button
            onClick={() => setOutcomeDismissed(true)}
            className="shrink-0 text-xs font-semibold hover:underline"
          >
            Dismiss
          </button>
        </p>
      )}
      {oauthError && (
        <div className="mb-5">
          <ErrorBanner message={oauthError} onDismiss={() => setOutcomeDismissed(true)} />
        </div>
      )}
      {error && (
        <div className="mb-5">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}

      {/* Once a calendar is connected this is settled business, so it reads as
          one quiet line rather than a panel. Only the unconnected state needs
          to explain itself and ask for something. */}
      {isConnected ? (
        <div className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs">
          <span
            className="inline-flex items-center gap-1.5 font-semibold"
            style={{ color: "var(--success)" }}
          >
            <span
              aria-hidden
              className="grid h-3.5 w-3.5 place-items-center rounded-full text-[9px] text-white"
              style={{ background: "var(--success)" }}
            >
              ✓
            </span>
            Google Calendar connected
          </span>
          {connectedAccounts.length > 0 && (
            <span className="truncate text-[var(--muted)]">
              {connectedAccounts.join(", ")}
            </span>
          )}
          {calendars !== null && calendars.length > 1 && (
            <select
              value={selected ?? ""}
              onChange={(e) => setSelected(e.target.value)}
              aria-label="Which calendar to show"
              className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-xs"
            >
              {calendars.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.email ?? c.recall_calendar_id}
                </option>
              ))}
            </select>
          )}
          <button
            onClick={connect}
            title="Reconnect to refresh permissions or add another account"
            className="font-semibold text-[var(--accent)] hover:underline"
          >
            Reconnect
          </button>
        </div>
      ) : (
        <Card className="mb-6 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">Connect Google Calendar</h2>
              <p className="mt-0.5 text-xs text-[var(--muted)]">
                MeetMind reads your events and adds meeting deadlines back to
                your calendar.
              </p>
            </div>
            <button
              onClick={connect}
              className="rounded-lg bg-[var(--accent)] px-3.5 py-2 text-sm font-semibold text-[var(--accent-fg)] transition hover:opacity-90"
            >
              Connect Google Calendar
            </button>
          </div>
          {calendars === null && (
            <p className="mt-4 flex items-center gap-2 text-sm text-[var(--muted)]">
              <Spinner /> Loading…
            </p>
          )}
        </Card>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <label htmlFor="calendar-project" className="text-xs text-[var(--muted)]">
          Show
        </label>
        <select
          id="calendar-project"
          value={projectFilter}
          onChange={(e) => setProjectFilter(e.target.value)}
          className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2.5 py-1.5 text-xs"
        >
          <option value="">All projects</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        {projectFilter && (
          <span className="text-xs text-[var(--muted)]">
            {visibleMeetings.length} meeting
            {visibleMeetings.length === 1 ? "" : "s"} · {visibleDeadlines.length}{" "}
            deadline{visibleDeadlines.length === 1 ? "" : "s"}
          </span>
        )}
      </div>

      <div className="mb-6">
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
              onChange={(e) => consentStore.set(e.target.checked)}
              className="mt-0.5 h-4 w-4 shrink-0 accent-amber-600"
            />
            <span className="text-amber-900">
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
        {visibleDeadlines.length === 0 ? (
          <EmptyState
            title="No deadlines yet"
            hint="Record a meeting where a date is mentioned."
          />
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {(showAllDeadlines
              ? visibleDeadlines
              : visibleDeadlines.slice(0, DEADLINES_PREVIEW)
            ).map((d) => (
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
                    className="shrink-0 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-xs font-medium text-emerald-600 hover:underline"
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
        {visibleDeadlines.length > DEADLINES_PREVIEW && (
          // Expanded in place rather than on its own page: the action here is
          // pushing a deadline to Google Calendar, and that belongs beside the
          // calendar it is being pushed to.
          <div className="flex items-center justify-between gap-3 border-t border-[var(--border)] px-5 py-3">
            <span className="text-xs text-[var(--muted)]">
              {showAllDeadlines
                ? `Showing all ${visibleDeadlines.length}.`
                : `Showing the ${DEADLINES_PREVIEW} soonest of ${visibleDeadlines.length}.`}
            </span>
            <button
              onClick={() => setShowAllDeadlines((v) => !v)}
              className="shrink-0 text-xs font-semibold text-[var(--accent)] hover:underline"
            >
              {showAllDeadlines ? "Show fewer" : `Show all ${visibleDeadlines.length}`}
            </button>
          </div>
        )}
      </Card>

      <p className="mt-6 text-xs text-[var(--muted)]">
        Backend: {API_BASE}
      </p>
    </main>
  );
}
