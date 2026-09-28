"use client";

import { useState } from "react";
import { api, ApiError, type Meeting } from "@/lib/api";
import { ErrorBanner, Spinner } from "./ui";

/**
 * Recording consent is enforced twice: this checkbox, and a hard validator on
 * the backend. The UI gate is a courtesy; the backend gate is the guarantee.
 */
export function JoinMeetingForm({ onJoined }: { onJoined: (m: Meeting) => void }) {
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const canSubmit = url.trim().length > 0 && consent && !busy;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      const meeting = await api.joinMeeting({
        meeting_url: url.trim(),
        title: title.trim() || undefined,
        consent_acknowledged: true,
      });
      setUrl("");
      setTitle("");
      setConsent(false);
      onJoined(meeting);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Something went wrong joining the meeting.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <label
          htmlFor="meeting-url"
          className="mb-1.5 block text-sm font-medium"
        >
          Meeting link
        </label>
        <input
          id="meeting-url"
          type="url"
          required
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://meet.google.com/abc-defg-hij"
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3.5 py-2.5 text-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20"
        />
        <p className="mt-1.5 text-xs text-[var(--muted)]">
          Google Meet, Zoom or Microsoft Teams.
        </p>
      </div>

      <div>
        <label htmlFor="meeting-title" className="mb-1.5 block text-sm font-medium">
          Title <span className="font-normal text-[var(--muted)]">(optional)</span>
        </label>
        <input
          id="meeting-title"
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Weekly project sync"
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3.5 py-2.5 text-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20"
        />
      </div>

      <div className="rounded-xl border border-amber-500/25 bg-[var(--warning-soft)] p-4">
        <p className="text-sm font-semibold text-amber-900">
          This bot records and transcribes the meeting
        </p>
        <p className="mt-1 text-sm leading-6 text-amber-900/75">
          <strong>MeetMind AI Notetaker</strong> joins as a visible participant and
          captures audio, a transcript and speaker names. Tell everyone before you
          join, respect your meeting platform&apos;s rules, and follow the recording
          consent laws that apply to you.
        </p>
        <label className="mt-3 flex cursor-pointer items-start gap-2.5 rounded-lg bg-white/55 p-2.5 text-sm text-amber-900">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            className="mt-0.5 h-4 w-4 shrink-0 accent-amber-600"
          />
          <span>
            I confirm all participants are informed that this meeting will be
            recorded and transcribed.
          </span>
        </label>
      </div>

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      <button
        type="submit"
        disabled={!canSubmit}
        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-3 text-sm font-bold text-[var(--accent-fg)] shadow-[0_14px_28px_-16px_rgb(99_91_255/.8)] transition hover:-translate-y-0.5 hover:bg-[var(--accent-hover)] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:translate-y-0"
      >
        {busy && <Spinner />}
        {busy ? "Sending bot…" : "Join meeting"}
      </button>
      {!consent && (
        <p className="text-center text-xs text-[var(--muted)]">
          Confirm consent above to enable this button.
        </p>
      )}
    </form>
  );
}
