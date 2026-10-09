"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  api,
  projectApi,
  type Meeting,
  type ProjectSummary,
} from "@/lib/api";
import { Card, ErrorBanner } from "@/components/ui";
import { MeetingList } from "@/components/MeetingList";

/**
 * The full meeting archive. The dashboard shows only the newest few, so this
 * is where a long history is actually browsable — hence the search box and
 * project filter, which a five-row preview would not need.
 */
export default function AllMeetingsPage() {
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState("");
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [rows, projectRows] = await Promise.all([
        api.listMeetings(200).catch((err) => {
          if (!cancelled) {
            setError(
              err instanceof ApiError ? err.message : "Failed to load meetings.",
            );
          }
          return [] as Meeting[];
        }),
        projectApi.list().catch(() => [] as ProjectSummary[]),
      ]);
      if (cancelled) return;
      setMeetings(rows);
      setProjects(projectRows);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    if (meetings === null) return null;
    const q = query.trim().toLowerCase();
    return meetings.filter((m) => {
      if (projectId === "__none__") {
        if (m.project_id) return false;
      } else if (projectId && m.project_id !== projectId) {
        return false;
      }
      if (!q) return true;
      return (
        (m.title ?? "").toLowerCase().includes(q) ||
        m.meeting_url.toLowerCase().includes(q) ||
        (m.project_name ?? "").toLowerCase().includes(q)
      );
    });
  }, [meetings, projectId, query]);

  const field =
    "rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20";

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <Link href="/dashboard" className="text-sm text-[var(--accent)] hover:underline">
        ← Dashboard
      </Link>

      <header className="mt-4 mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">All meetings</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Every meeting the notetaker has joined, newest first.
        </p>
      </header>

      {error && (
        <div className="mb-5">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}
      {notice && (
        <div className="mb-5 flex items-start justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm text-[var(--muted-strong)]">
          <span>{notice}</span>
          <button
            onClick={() => setNotice(null)}
            className="shrink-0 text-xs font-semibold text-[var(--accent)] hover:underline"
          >
            Dismiss
          </button>
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search title, link or project…"
          aria-label="Search meetings"
          className={`${field} min-w-0 flex-1`}
        />
        <select
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          aria-label="Filter by project"
          className={field}
        >
          <option value="">All projects</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
          <option value="__none__">No project</option>
        </select>
        {(query || projectId) && (
          <button
            onClick={() => {
              setQuery("");
              setProjectId("");
            }}
            className="text-xs font-semibold text-[var(--accent)] hover:underline"
          >
            Clear
          </button>
        )}
      </div>

      <Card>
        <h2 className="flex items-baseline justify-between gap-3 border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
          <span>Meeting history</span>
          {filtered !== null && (
            <span className="text-xs font-medium normal-case tabular-nums">
              {filtered.length}
              {meetings && filtered.length !== meetings.length
                ? ` of ${meetings.length}`
                : ""}
            </span>
          )}
        </h2>
        <MeetingList
          meetings={filtered}
          onRemoved={(id) =>
            setMeetings((rows) => (rows ?? []).filter((m) => m.id !== id))
          }
          onError={setError}
          onNotice={setNotice}
          // The archive is where you tidy up: meetings recorded before the
          // project selector existed can be filed from here.
          projects={projects}
          onProjectChanged={(updated) => {
            setMeetings((rows) =>
              (rows ?? []).map((m) => (m.id === updated.id ? updated : m)),
            );
            setNotice(
              updated.project_name
                ? `Filed under “${updated.project_name}”.`
                : "Removed from its project.",
            );
          }}
          emptyHint={
            query || projectId
              ? "Nothing matches those filters."
              : "Paste a meeting link on the dashboard to send the notetaker."
          }
        />
      </Card>
    </main>
  );
}
