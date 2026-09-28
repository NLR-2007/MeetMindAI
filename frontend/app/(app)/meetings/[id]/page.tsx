"use client";

import Link from "next/link";
import { use, useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  ApiError,
  TERMINAL_STATUSES,
  calendarApi,
  type ChatMessage,
  type Deadline,
  type MeetingDetail,
} from "@/lib/api";
import { Card, ErrorBanner, Spinner, StatusBadge } from "@/components/ui";
import { ChatText } from "@/components/ChatText";
import LoadingState from "@/components/ui/loading-state";

const POLL_MS = 6000;
// While the bot is recording, transcript lines arrive continuously, so poll
// harder. Outside a live call the slower cadence is plenty.
const LIVE_POLL_MS = 2500;

export default function MeetingPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const [meeting, setMeeting] = useState<MeetingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [processing, setProcessing] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const transcriptRef = useRef<HTMLPreElement | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.getMeeting(id, true);
      setMeeting(data);
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load meeting.");
      return null;
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      const data = await load();
      if (cancelled || !data) return;
      if (!TERMINAL_STATUSES.has(data.status ?? "")) {
        await api.getStatus(id).catch(() => null);
        const live = data.status === "in_call_recording";
        timer.current = setTimeout(tick, live ? LIVE_POLL_MS : POLL_MS);
      }
    }
    tick();
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [id, load]);

  async function runProcess() {
    setProcessing(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.processMeeting(id);
      setNotice(
        result.skipped_reason
          ? `Nothing to do: ${result.skipped_reason}`
          : `Saved transcript (${result.word_count} words) and analysis.`,
      );
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Processing failed.");
    } finally {
      setProcessing(false);
    }
  }

  async function runLeave() {
    setLeaving(true);
    setError(null);
    try {
      await api.leaveMeeting(id);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not remove the bot.");
    } finally {
      setLeaving(false);
    }
  }

  useEffect(() => {
    // Only follow the tail during a live call; afterwards the reader scrolls.
    if (meeting?.status !== "in_call_recording") return;
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [meeting?.transcript_text, meeting?.status]);

  if (loading) {
    return (
      <main className="mx-auto flex max-w-5xl items-center gap-2 px-4 py-16 text-sm text-[var(--muted)]">
        <Spinner /> Loading meeting…
      </main>
    );
  }

  if (!meeting) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-16">
        <ErrorBanner message={error ?? "Meeting not found."} />
        <Link href="/" className="mt-4 inline-block text-sm text-[var(--accent)] hover:underline">
          ← Back to dashboard
        </Link>
      </main>
    );
  }

  const inCall = !TERMINAL_STATUSES.has(meeting.status ?? "");
  const isRecording = meeting.status === "in_call_recording";

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <Link href="/dashboard" className="text-sm text-[var(--accent)] hover:underline">
        ← Dashboard
      </Link>

      <header className="mt-4 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight">
            {meeting.title || "Untitled meeting"}
          </h1>
          <p className="mt-1 truncate text-sm text-[var(--muted)]">
            {meeting.meeting_url}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={meeting.status} />
          {inCall && (
            <button
              onClick={runLeave}
              disabled={leaving}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-medium transition hover:bg-[var(--surface)] disabled:opacity-50"
            >
              {leaving && <Spinner />} Remove bot
            </button>
          )}
          {!inCall && (
            <button
              onClick={runProcess}
              disabled={processing}
              className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-[var(--accent-fg)] transition hover:opacity-90 disabled:opacity-50"
            >
              {processing && <Spinner />}
              {meeting.has_summary ? "Re-analyse" : "Get transcript & summary"}
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="mt-5">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}
      {notice && (
        <p className="mt-5 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-2.5 text-sm text-[var(--muted)]">
          {notice}
        </p>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          <Section title="Summary">
            {meeting.summary?.summary_text ? (
              <p className="text-sm leading-relaxed">{meeting.summary.summary_text}</p>
            ) : (
              <Muted>
                No summary yet. Run “Get transcript &amp; summary” once the meeting ends.
              </Muted>
            )}
          </Section>

          <Section title="Decisions">
            {meeting.summary?.decisions?.length ? (
              <ul className="list-disc space-y-1.5 pl-5 text-sm">
                {meeting.summary.decisions.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            ) : (
              <Muted>No decisions were recorded in this meeting.</Muted>
            )}
          </Section>

          <Section title="Action items">
            {meeting.action_items.length ? (
              <ul className="space-y-2 text-sm">
                {meeting.action_items.map((a) => (
                  <li
                    key={a.id}
                    className="rounded-lg border border-[var(--border)] px-3 py-2"
                  >
                    <p>{a.task}</p>
                    <p className="mt-0.5 text-xs text-[var(--muted)]">
                      Owner: {a.owner_name ?? "unassigned"} · Due: {a.due_text ?? "n/a"}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <Muted>No action items.</Muted>
            )}
          </Section>

          <Section title="Deadlines">
            {meeting.deadlines.length ? (
              <ul className="space-y-2 text-sm">
                {meeting.deadlines.map((d) => (
                  <DeadlineRow key={d.id} deadline={d} onChanged={load} />
                ))}
              </ul>
            ) : (
              <Muted>No deadlines.</Muted>
            )}
          </Section>

          <Section
            title={`Transcript${
              meeting.transcript_word_count
                ? ` · ${meeting.transcript_word_count} words`
                : ""
            }`}
            badge={
              isRecording ? (
                <span
                  className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white"
                  style={{ background: "var(--recording)" }}
                >
                  <span className="recording-dot h-1.5 w-1.5 rounded-full bg-white" />
                  Live
                </span>
              ) : null
            }
          >
            {meeting.transcript_text ? (
              <pre
                ref={transcriptRef}
                className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-[var(--background)] p-3 text-xs leading-relaxed"
              >
                {meeting.transcript_text}
              </pre>
            ) : isRecording ? (
              <p className="flex items-center gap-2 text-sm text-[var(--muted-strong)]">
                <Spinner /> Listening… words appear here as people speak.
              </p>
            ) : (
              <Muted>No transcript stored yet.</Muted>
            )}
          </Section>
        </div>

        <div className="space-y-6">
          <Section title="Participants">
            {meeting.participants.length ? (
              <ul className="space-y-1.5 text-sm">
                {meeting.participants.map((p) => (
                  <li key={p.id} className="flex items-center gap-2">
                    <span>{p.name ?? "Unknown"}</span>
                    {p.is_host && (
                      <span className="rounded bg-[var(--background)] px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-[var(--muted)]">
                        host
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <Muted>No participants identified.</Muted>
            )}
          </Section>

          <MeetingChat meetingId={id} enabled={meeting.has_transcript || meeting.has_summary} />
        </div>
      </div>
    </main>
  );
}

function Section({
  title,
  children,
  badge,
}: {
  title: string;
  children: React.ReactNode;
  badge?: React.ReactNode;
}) {
  return (
    <Card className="p-5">
      <h2 className="mb-3 flex items-center justify-between gap-2 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
        <span>{title}</span>
        {badge}
      </h2>
      {children}
    </Card>
  );
}

function Muted({ children }: { children: React.ReactNode }) {
  return <p className="text-sm text-[var(--muted)]">{children}</p>;
}

function DeadlineRow({
  deadline,
  onChanged,
}: {
  deadline: Deadline;
  onChanged: () => Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      if (deadline.google_event_id) {
        await calendarApi.removeDeadline(deadline.id);
      } else {
        await calendarApi.pushDeadline(deadline.id);
      }
      await onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Calendar update failed.");
    } finally {
      setBusy(false);
    }
  }

  const onCalendar = Boolean(deadline.google_event_id);

  return (
    <li className="rounded-lg border border-[var(--border)] px-3 py-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p>{deadline.what}</p>
          <p className="mt-0.5 text-xs text-[var(--muted)]">
            {deadline.when_text ?? "no date given"}
            {deadline.due_at &&
              ` · ${new Date(deadline.due_at).toLocaleDateString()}`}
          </p>
        </div>
        <button
          onClick={toggle}
          disabled={busy || (!deadline.due_at && !onCalendar)}
          title={
            !deadline.due_at && !onCalendar
              ? "No resolvable date, so this cannot be added to a calendar"
              : undefined
          }
          className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${
            onCalendar
              ? "border border-[var(--border)] hover:bg-[var(--background)]"
              : "bg-[var(--accent)] text-[var(--accent-fg)] hover:opacity-90"
          }`}
        >
          {busy && <Spinner />}
          {onCalendar ? "Remove from calendar" : "Add to calendar"}
        </button>
      </div>
      {deadline.google_event_link && (
        <a
          href={deadline.google_event_link}
          target="_blank"
          rel="noreferrer"
          className="mt-1 inline-block text-xs text-[var(--accent)] hover:underline"
        >
          View in Google Calendar →
        </a>
      )}
      {error && <p className="mt-1 text-xs text-red-500">{error}</p>}
    </li>
  );
}

function MeetingChat({ meetingId, enabled }: { meetingId: string; enabled: boolean }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingSwitch, setPendingSwitch] = useState<string | null>(null);

  useEffect(() => {
    api.chatHistory(meetingId).then(setMessages).catch(() => null);
  }, [meetingId]);

  async function send(confirmSwitch = false) {
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);

    const optimistic: ChatMessage = {
      id: `tmp-${Date.now()}`,
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimistic]);
    setInput("");

    try {
      const res = await api.chat(meetingId, text, confirmSwitch);
      setMessages((prev) => [
        ...prev,
        {
          id: `tmp-a-${Date.now()}`,
          role: "assistant",
          content: res.answer,
          created_at: new Date().toISOString(),
        },
      ]);
      setPendingSwitch(res.context_switch_required ? text : null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Chat failed.");
      setMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="flex h-[520px] flex-col p-5">
      <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
        Ask about this meeting
      </h2>
      <p className="mb-3 text-xs text-[var(--muted)]">
        Answers use only this meeting&apos;s records.
      </p>

      <div className="flex-1 space-y-3 overflow-y-auto pr-1">
        {messages.length === 0 && (
          <p className="text-sm text-[var(--muted)]">
            {enabled
              ? "Ask what was decided, who committed to what, or what you missed."
              : "Get the transcript first, then you can ask questions here."}
          </p>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={`max-w-[90%] rounded-lg px-3 py-2 text-sm ${
              m.role === "user"
                ? "ml-auto whitespace-pre-wrap bg-[var(--accent)] text-[var(--accent-fg)]"
                : "bg-[var(--background)]"
            }`}
          >
            {m.role === "user" ? m.content : <ChatText content={m.content} />}
          </div>
        ))}
        {busy && <LoadingState label="Building an answer" variant="Drive" />}
      </div>

      {pendingSwitch && (
        <button
          onClick={() => {
            setInput(pendingSwitch);
            setPendingSwitch(null);
            send(true);
          }}
          className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs font-medium text-amber-800 dark:text-amber-200"
        >
          Confirm switching to the other meeting
        </button>
      )}

      {error && (
        <div className="mt-2">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="mt-3 flex gap-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={!enabled || busy}
          placeholder={enabled ? "Ask a question…" : "Transcript required"}
          className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--accent)] disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!enabled || busy || !input.trim()}
          className="rounded-lg bg-[var(--accent)] px-3.5 py-2 text-sm font-semibold text-[var(--accent-fg)] disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </Card>
  );
}
