"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ApiError, api, type ChatMessage, type Meeting } from "@/lib/api";
import { Card, EmptyState, ErrorBanner, Spinner, StatusBadge } from "@/components/ui";
import { ChatText } from "@/components/ChatText";
import { AiInput } from "@/components/ui/ai-input";
import Avatar from "@/components/ui/components-primitives-avatar";
import LoadingState from "@/components/ui/loading-state";

export default function ChatPage() {
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [selected, setSelected] = useState<Meeting | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{ text: string; meetingId: string } | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    api.listMeetings()
      .then((rows) => {
        const ready = rows.filter((meeting) => meeting.has_transcript || meeting.has_summary);
        setMeetings(ready);
        if (ready.length) setSelected((current) => current ?? ready[0]);
      })
      .catch((reason) => setError(reason instanceof ApiError ? reason.message : "Could not load meetings."));
  }, []);

  useEffect(() => {
    if (!selected) return;
    api.chatHistory(selected.id).then(setMessages).catch(() => setMessages([]));
  }, [selected]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(text: string, confirmSwitch = false, targetMeeting?: Meeting) {
    const activeMeeting = targetMeeting ?? selected;
    if (!activeMeeting || !text.trim() || busy) return;
    setBusy(true);
    setError(null);

    const messageId = `tmp-${messages.length}-${text.length}`;
    const optimistic: ChatMessage = {
      id: messageId,
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimistic]);
    setInput("");

    try {
      const response = await api.chat(activeMeeting.id, text, confirmSwitch);
      setMessages((current) => [
        ...current,
        {
          id: `tmp-a-${current.length}`,
          role: "assistant",
          content: response.answer,
          created_at: new Date().toISOString(),
        },
      ]);
      setPending(
        response.context_switch_required && response.pending_meeting_id
          ? { text, meetingId: response.pending_meeting_id }
          : null,
      );
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Chat failed.");
      setMessages((current) => current.filter((message) => message.id !== messageId));
    } finally {
      setBusy(false);
    }
  }

  async function confirmSwitch() {
    if (!pending || !meetings) return;
    const target = meetings.find((meeting) => meeting.id === pending.meetingId);
    const question = pending.text;
    setPending(null);
    if (target) {
      setSelected(target);
      setMessages([]);
      setTimeout(() => send(question, true, target), 50);
    }
  }

  const suggestions = [
    "What was decided?",
    "What are my action items?",
    "When is the deadline?",
    "Summarise this meeting in three bullets",
  ];

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
      <Link href="/dashboard" className="text-sm font-semibold text-[var(--accent)] hover:underline">← Dashboard</Link>

      <header className="mt-5 mb-6 flex items-start gap-4">
        <Avatar color="indigo" size="md" shape="squircle" />
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">Ask MeetMind</h1>
            <span className="rounded-full bg-[var(--success-soft)] px-2 py-1 text-[10px] font-bold text-[var(--success)]">AI online</span>
          </div>
          <p className="mt-1 text-sm text-[var(--muted)]">Ask about decisions, owners, deadlines, and anything in the selected meeting.</p>
        </div>
      </header>

      {error && <div className="mb-5"><ErrorBanner message={error} onDismiss={() => setError(null)} /></div>}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,270px)_minmax(0,1fr)]">
        <Card className="h-fit overflow-hidden">
          <div className="border-b border-[var(--border)] px-4 py-3.5">
            <h2 className="text-[10px] font-bold uppercase tracking-[0.15em] text-[var(--muted)]">Meeting memory</h2>
          </div>
          {meetings === null ? (
            <p className="flex items-center gap-2 px-4 py-6 text-sm text-[var(--muted)]"><Spinner /> Loading…</p>
          ) : meetings.length === 0 ? (
            <EmptyState title="Nothing to talk about yet" hint="Record a meeting first." />
          ) : (
            <ul className="max-h-[520px] space-y-1 overflow-y-auto p-2">
              {meetings.map((meeting) => (
                <li key={meeting.id}>
                  <button
                    onClick={() => { setSelected(meeting); setPending(null); }}
                    className={`w-full rounded-xl px-3 py-3 text-left transition ${selected?.id === meeting.id ? "bg-[var(--accent-soft)]" : "hover:bg-[var(--background)]"}`}
                  >
                    <p className={`truncate text-sm font-semibold ${selected?.id === meeting.id ? "text-[var(--accent)]" : ""}`}>{meeting.title || meeting.meeting_url}</p>
                    <p className="mt-1 text-[11px] text-[var(--muted)]">{new Date(meeting.created_at).toLocaleDateString()}</p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="flex h-[min(690px,calc(100vh-165px))] min-h-[550px] flex-col overflow-hidden">
          <div className="flex items-center justify-between gap-3 border-b border-[var(--border)] bg-white px-4 py-3.5 sm:px-5">
            <div className="min-w-0">
              <p className="truncate text-sm font-bold">{selected ? selected.title || selected.meeting_url : "No meeting selected"}</p>
              {selected && <Link href={`/meetings/${selected.id}`} className="text-[11px] font-semibold text-[var(--accent)] hover:underline">Open meeting details →</Link>}
            </div>
            {selected && <StatusBadge status={selected.status} />}
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto bg-[linear-gradient(180deg,#fff,var(--background))] px-4 py-5 sm:px-5">
            {!selected ? (
              <p className="text-sm text-[var(--muted)]">Select a meeting to start.</p>
            ) : messages.length === 0 ? (
              <div className="mx-auto flex max-w-md flex-col items-center py-10 text-center">
                <Avatar color="indigo" size="lg" shape="squircle" />
                <h2 className="mt-5 font-[family-name:var(--font-display)] text-xl font-bold tracking-[-0.03em]">What would you like to know?</h2>
                <p className="mt-2 text-sm leading-6 text-[var(--muted)]">I&apos;ll answer using the transcript and summary from this meeting.</p>
                <div className="mt-5 flex flex-wrap justify-center gap-2">
                  {suggestions.map((question) => (
                    <button key={question} onClick={() => send(question)} className="rounded-full border border-[var(--border)] bg-white px-3 py-1.5 text-xs font-medium transition hover:border-[var(--accent)]/30 hover:bg-[var(--accent-soft)] hover:text-[var(--accent)]">{question}</button>
                  ))}
                </div>
              </div>
            ) : (
              messages.map((message) => message.role === "user" ? (
                <div key={message.id} className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-[var(--accent)] px-4 py-3 text-sm leading-6 text-white shadow-sm">{message.content}</div>
              ) : (
                <div key={message.id} className="flex max-w-[92%] items-start gap-2.5">
                  <Avatar color="indigo" size="sm" shape="squircle" />
                  <div className="rounded-2xl rounded-tl-md border border-[var(--border)] bg-white px-4 py-3 text-sm leading-6 shadow-[var(--shadow-sm)]"><ChatText content={message.content} /></div>
                </div>
              ))
            )}
            {busy && <div className="flex items-center gap-2.5 text-sm text-[var(--muted)]"><Avatar color="indigo" size="sm" shape="squircle" /><span className="rounded-full border border-[var(--border)] bg-white px-3 py-2"><LoadingState label="Reviewing the meeting" variant="Orbit" /></span></div>}
            <div ref={endRef} />
          </div>

          {pending && (
            <div className="mx-4 mb-2 rounded-xl border border-amber-500/25 bg-[var(--warning-soft)] px-3 py-2.5 sm:mx-5">
              <p className="text-xs text-amber-900">That question looks like it is about a different meeting.</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <button onClick={confirmSwitch} className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-bold text-white">Switch and ask there</button>
                <button onClick={() => setPending(null)} className="rounded-lg border border-[var(--border)] bg-white px-3 py-1.5 text-xs font-semibold">Stay here</button>
              </div>
            </div>
          )}

          <div className="border-t border-[var(--border)] bg-white">
            <AiInput value={input} onChange={setInput} onSubmit={send} busy={busy} disabled={!selected} placeholder={selected ? "Ask MeetMind about this meeting…" : "Select a meeting first"} />
          </div>
        </Card>
      </div>
    </main>
  );
}
