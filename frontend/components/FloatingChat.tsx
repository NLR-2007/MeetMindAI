"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ExternalLink, X } from "lucide-react";
import { ApiError, api, type ChatMessage, type Meeting } from "@/lib/api";
import { ChatText } from "./ChatText";
import { ErrorBanner } from "./ui";
import { AiInput } from "./ui/ai-input";
import Avatar from "./ui/components-primitives-avatar";
import LoadingState from "./ui/loading-state";

export function FloatingChat() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [meetingId, setMeetingId] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<{ text: string; meetingId: string } | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open || meetings.length) return;
    api.listMeetings()
      .then((rows) => {
        const ready = rows.filter((meeting) => meeting.has_transcript || meeting.has_summary);
        setMeetings(ready);
        if (ready.length && !meetingId) setMeetingId(ready[0].id);
      })
      .catch(() => setMeetings([]));
  }, [open, meetings.length, meetingId]);

  useEffect(() => {
    if (!meetingId) return;
    api.chatHistory(meetingId).then(setMessages).catch(() => setMessages([]));
  }, [meetingId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send(text: string, confirmSwitch = false, targetMeetingId = meetingId) {
    if (!targetMeetingId || !text.trim() || busy) return;
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
      const response = await api.chat(targetMeetingId, text, confirmSwitch);
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

  if (pathname === "/chat" || pathname === "/coach") return null;

  return (
    <>
      <motion.button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-label={open ? "Close Ask MeetMind" : "Open Ask MeetMind"}
        aria-expanded={open}
        whileHover={{ y: -2, scale: 1.04 }}
        whileTap={{ scale: 0.94 }}
        className="fixed bottom-5 right-4 z-50 rounded-[18px] border border-white bg-white p-1.5 shadow-[0_18px_45px_-15px_rgb(42_45_86/.5)] sm:right-5"
      >
        {open ? (
          <span className="grid h-12 w-12 place-items-center rounded-[14px] bg-[var(--navy)] text-white"><X className="h-5 w-5" /></span>
        ) : (
          <Avatar color="indigo" size="md" shape="squircle" />
        )}
        {!open && <span className="absolute -right-1 -top-1 h-3.5 w-3.5 rounded-full border-2 border-white bg-[var(--success)]" />}
      </motion.button>

      <AnimatePresence>
        {open && (
          <motion.section
            role="dialog"
            aria-label="Ask MeetMind"
            initial={{ opacity: 0, y: 18, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 14, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 300, damping: 26 }}
            className="fixed inset-x-3 bottom-24 z-40 flex h-[min(72vh,590px)] flex-col overflow-hidden rounded-[1.5rem] border border-[var(--border)] bg-white shadow-[0_30px_90px_-30px_rgb(24_30_60/.5)] sm:inset-x-auto sm:right-5 sm:w-[390px]"
          >
            <header className="border-b border-[var(--border)] bg-white px-4 py-3.5">
              <div className="flex items-center gap-3">
                <Avatar color="indigo" size="sm" shape="squircle" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <h2 className="text-sm font-bold">Ask MeetMind</h2>
                    <span className="h-1.5 w-1.5 rounded-full bg-[var(--success)]" />
                  </div>
                  <p className="text-[10px] text-[var(--muted)]">Your meeting memory</p>
                </div>
                <Link href="/chat" aria-label="Open full chat" className="grid h-8 w-8 place-items-center rounded-lg bg-[var(--background)] text-[var(--muted)] transition hover:text-[var(--accent)]">
                  <ExternalLink className="h-3.5 w-3.5" />
                </Link>
              </div>
              <select
                value={meetingId}
                onChange={(event) => { setMeetingId(event.target.value); setPending(null); }}
                aria-label="Select meeting"
                className="mt-3 w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-xs font-medium outline-none focus:border-[var(--accent)]"
              >
                {meetings.length === 0 && <option value="">No processed meetings</option>}
                {meetings.map((meeting) => <option key={meeting.id} value={meeting.id}>{meeting.title || meeting.meeting_url}</option>)}
              </select>
            </header>

            <div className="flex-1 space-y-3 overflow-y-auto bg-[linear-gradient(180deg,#fff,var(--background))] px-4 py-4">
              {messages.length === 0 && (
                <div className="flex flex-col items-center px-4 py-8 text-center">
                  <Avatar color="indigo" size="lg" shape="squircle" />
                  <p className="mt-4 text-sm font-bold">How can I help?</p>
                  <p className="mt-1 text-xs leading-5 text-[var(--muted)]">Ask what was decided, who owns what, or when something is due.</p>
                </div>
              )}
              {messages.map((message) => message.role === "user" ? (
                <div key={message.id} className="ml-auto max-w-[86%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-[var(--accent)] px-3.5 py-2.5 text-sm leading-5 text-white">{message.content}</div>
              ) : (
                <div key={message.id} className="flex max-w-[92%] items-start gap-2">
                  <Avatar color="indigo" size="sm" shape="squircle" />
                  <div className="rounded-2xl rounded-tl-md border border-[var(--border)] bg-white px-3.5 py-2.5 text-sm leading-5 shadow-[var(--shadow-sm)]"><ChatText content={message.content} /></div>
                </div>
              ))}
              {busy && <div className="flex items-center gap-2 text-xs text-[var(--muted)]"><Avatar color="indigo" size="sm" shape="squircle" /><span className="rounded-full bg-white px-3 py-2"><LoadingState label="Searching meeting notes" variant="Orbit" /></span></div>}
              <div ref={endRef} />
            </div>

            {pending && (
              <div className="mx-3 mb-1 rounded-xl border border-amber-500/25 bg-[var(--warning-soft)] px-3 py-2">
                <p className="text-[11px] text-amber-900">That looks like another meeting.</p>
                <button
                  onClick={() => {
                    const question = pending.text;
                    const targetMeetingId = pending.meetingId;
                    setMeetingId(targetMeetingId);
                    setPending(null);
                    setMessages([]);
                    setTimeout(() => send(question, true, targetMeetingId), 50);
                  }}
                  className="mt-1.5 rounded-lg bg-[var(--accent)] px-2.5 py-1.5 text-[10px] font-bold text-white"
                >
                  Switch and ask there
                </button>
              </div>
            )}

            {error && <div className="mx-3 mb-1"><ErrorBanner message={error} onDismiss={() => setError(null)} /></div>}

            <div className="border-t border-[var(--border)] bg-white">
              <AiInput value={input} onChange={setInput} onSubmit={send} busy={busy} disabled={!meetingId} compact placeholder={meetingId ? "Ask a question…" : "Select a meeting first"} />
            </div>
          </motion.section>
        )}
      </AnimatePresence>
    </>
  );
}
