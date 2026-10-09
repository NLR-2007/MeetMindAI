"use client";

import Link from "next/link";
import { useState } from "react";
import { api, ApiError, type Meeting, type ProjectSummary } from "@/lib/api";
import { EmptyState, Spinner, StatusBadge } from "./ui";

/**
 * The meeting history rows, shared by the dashboard (which shows the most
 * recent few) and the full history page. Deleting lives here so both views
 * behave identically rather than one of them quietly drifting.
 */
export function MeetingList({
  meetings,
  onRemoved,
  onError,
  onNotice,
  emptyHint = "Paste a meeting link to send the notetaker.",
  projects,
  onProjectChanged,
}: {
  meetings: Meeting[] | null;
  onRemoved: (id: string) => void;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
  emptyHint?: string;
  /** Supplying these turns the project pill into an editable picker. */
  projects?: ProjectSummary[];
  onProjectChanged?: (meeting: Meeting) => void;
}) {
  // Deleting is irreversible, so it asks first, inline on the row.
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [filingId, setFilingId] = useState<string | null>(null);
  const editable = Boolean(projects && onProjectChanged);

  async function file(meeting: Meeting, projectId: string) {
    setFilingId(meeting.id);
    try {
      const updated = await api.setMeetingProject(meeting.id, projectId || null);
      onProjectChanged?.(updated);
    } catch (err) {
      onError(
        err instanceof ApiError ? err.message : "Could not change the project.",
      );
    } finally {
      setFilingId(null);
    }
  }

  async function remove(id: string) {
    setDeletingId(id);
    try {
      const result = await api.deleteMeeting(id);
      onRemoved(id);
      onNotice(
        `Deleted “${result.title}”.` +
          (result.commitments_removed
            ? ` ${result.commitments_removed} commitment(s) removed.`
            : "") +
          (result.memory_bank_dropped ? " Memory bank dropped." : "") +
          (result.calendar_events_kept
            ? ` ${result.calendar_events_kept} calendar event(s) left in Google Calendar.`
            : ""),
      );
    } catch (err) {
      onError(
        err instanceof ApiError ? err.message : "Could not delete the meeting.",
      );
    } finally {
      setDeletingId(null);
      setConfirmingId(null);
    }
  }

  if (meetings === null) {
    return (
      <div className="flex items-center justify-center gap-2 px-5 py-12 text-sm text-[var(--muted)]">
        <Spinner /> Loading meetings…
      </div>
    );
  }

  if (meetings.length === 0) {
    return <EmptyState title="No meetings yet" hint={emptyHint} />;
  }

  return (
    <ul className="divide-y divide-[var(--border)]">
      {meetings.map((m) => (
        <li
          key={m.id}
          className="group flex items-center gap-2 px-5 py-4 transition hover:bg-[var(--background)]"
        >
          <Link
            href={`/meetings/${m.id}`}
            className="flex min-w-0 flex-1 items-center gap-4"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {m.title || m.meeting_url}
              </p>
              <p className="mt-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-[var(--muted)]">
                {m.project_name && !editable && (
                  // The project is what ties a series together, so it reads
                  // first and is the only part that is coloured.
                  <span
                    className="rounded-full px-2 py-0.5 text-[11px] font-semibold"
                    style={{
                      background: "var(--accent-soft)",
                      color: "var(--accent)",
                    }}
                  >
                    {m.project_name}
                  </span>
                )}
                <span>
                  {new Date(m.created_at).toLocaleString()} · {m.platform}
                  {m.has_summary && " · summarised"}
                </span>
              </p>
            </div>
            <StatusBadge status={m.status} />
          </Link>

          {editable && (
            // Outside the Link on purpose: picking a project must not
            // navigate to the meeting.
            <select
              value={m.project_id ?? ""}
              disabled={filingId === m.id}
              onChange={(e) => file(m, e.target.value)}
              aria-label={`Project for ${m.title || "this meeting"}`}
              className="max-w-[11rem] shrink-0 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-xs disabled:opacity-50"
            >
              <option value="">No project</option>
              {projects?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          )}

          {confirmingId === m.id ? (
            <span className="flex shrink-0 items-center gap-1.5">
              <button
                onClick={() => remove(m.id)}
                disabled={deletingId === m.id}
                className="rounded-lg px-2.5 py-1.5 text-xs font-bold text-white disabled:opacity-50"
                style={{ background: "var(--danger)" }}
              >
                {deletingId === m.id ? "Deleting…" : "Delete"}
              </button>
              <button
                onClick={() => setConfirmingId(null)}
                className="rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-xs font-semibold"
              >
                Cancel
              </button>
            </span>
          ) : (
            <button
              onClick={() => setConfirmingId(m.id)}
              aria-label={`Delete ${m.title || "meeting"}`}
              title="Delete this meeting and everything derived from it"
              className="shrink-0 rounded-lg border border-transparent px-2 py-1.5 text-xs font-semibold text-[var(--muted-strong)] opacity-0 transition hover:border-[var(--danger)] hover:text-[var(--danger)] focus:opacity-100 group-hover:opacity-100"
            >
              Delete
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

/**
 * "Showing the newest N — see all M" footer. Used wherever a dashboard card
 * deliberately truncates a list so the page stays scannable.
 */
export function SeeAllFooter({
  shown,
  total,
  href,
  label,
}: {
  shown: number;
  total: number;
  href: string;
  label: string;
}) {
  if (total <= shown) return null;
  return (
    <div className="flex items-center justify-between gap-3 border-t border-[var(--border)] px-5 py-3">
      <span className="text-xs text-[var(--muted)]">
        Showing the {shown} most recent of {total}.
      </span>
      <Link
        href={href}
        className="shrink-0 text-xs font-semibold text-[var(--accent)] hover:underline"
      >
        {label} →
      </Link>
    </div>
  );
}
