"use client";

import { useEffect, useState } from "react";
import {
  api,
  ApiError,
  projectApi,
  teamApi,
  type Meeting,
  type ProjectSummary,
  type TeamSummary,
} from "@/lib/api";
import { ErrorBanner, Spinner } from "./ui";

const field =
  "w-full rounded-lg border border-[var(--border)] bg-[var(--background)] px-3.5 py-2.5 text-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20";

// Sentinel for the "create one instead" row, so it cannot collide with an id.
const NEW_PROJECT = "__new__";

/**
 * Recording consent is enforced twice: this checkbox, and a hard validator on
 * the backend. The UI gate is a courtesy; the backend gate is the guarantee.
 *
 * Choosing a project here is what makes a meeting series accumulate: pick the
 * same project next time and Mark Up, PromiseMirror and memory all read the
 * earlier meetings as context for this one.
 */
export function JoinMeetingForm({ onJoined }: { onJoined: (m: Meeting) => void }) {
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectsLoaded, setProjectsLoaded] = useState(false);
  // "" = no project, NEW_PROJECT = creating one, otherwise a project id.
  const [projectId, setProjectId] = useState("");
  const [newProjectName, setNewProjectName] = useState("");
  const [teams, setTeams] = useState<TeamSummary[]>([]);
  const [teamId, setTeamId] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [rows, teamRows] = await Promise.all([
        projectApi.list().catch(() => [] as ProjectSummary[]),
        teamApi.list().catch(() => [] as TeamSummary[]),
      ]);
      if (cancelled) return;
      setProjects(rows);
      setTeams(teamRows);
      setProjectsLoaded(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const creatingProject = projectId === NEW_PROJECT;
  // Every meeting belongs to a project and carries a title: that is what makes
  // a series accumulate, and what stops history reading as a list of URLs.
  const projectChosen = creatingProject
    ? newProjectName.trim().length > 0
    : projectId.length > 0;
  const canSubmit =
    url.trim().length > 0 && title.trim().length > 0 && projectChosen && consent && !busy;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      // A new project is created first, so the meeting can be filed under it
      // in the same action rather than making the user visit another page.
      let chosen = projectId;
      if (creatingProject) {
        const created = await projectApi.create(newProjectName.trim());
        setProjects((prev) => [...prev, created].sort((a, b) => a.name.localeCompare(b.name)));
        chosen = created.id;
      }

      const meeting = await api.joinMeeting({
        meeting_url: url.trim(),
        title: title.trim(),
        consent_acknowledged: true,
        project_id: chosen,
        team_id: teamId || undefined,
      });

      setUrl("");
      setTitle("");
      setConsent(false);
      setNewProjectName("");
      // Keep the project selected: the next meeting is usually the same one.
      setProjectId(chosen);
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
      {teams.length > 0 && (
        <div>
          <label htmlFor="meeting-team" className="mb-1.5 block text-sm font-medium">
            Record for{" "}
            <span className="font-normal text-[var(--muted)]">(optional)</span>
          </label>
          <select
            id="meeting-team"
            value={teamId}
            onChange={(e) => setTeamId(e.target.value)}
            className={field}
          >
            <option value="">Just me</option>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <p className="mt-1.5 text-xs text-[var(--muted)]">
            {teamId
              ? "One bot covers the whole team. If a colleague has already sent one to this link, you will join their recording instead of adding a second bot."
              : "Recording for a team means one bot for everyone, not one each."}
          </p>
        </div>
      )}

      <div>
        <label htmlFor="meeting-project" className="mb-1.5 block text-sm font-medium">
          Project <span className="text-[var(--danger)]">*</span>
        </label>
        <select
          id="meeting-project"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          className={field}
        >
          <option value="">
            {projectsLoaded && projects.length === 0
              ? "No projects yet — create your first below"
              : "Select a project\u2026"}
          </option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
          <option value={NEW_PROJECT}>+ New project…</option>
        </select>

        {creatingProject ? (
          <input
            type="text"
            autoFocus
            value={newProjectName}
            onChange={(e) => setNewProjectName(e.target.value)}
            placeholder="Project name, e.g. Compliance rollout"
            aria-label="New project name"
            className={`${field} mt-2`}
          />
        ) : (
          <p className="mt-1.5 text-xs text-[var(--muted)]">
            Pick the same project next time and MeetMind reads the earlier
            meetings as context — prep, promises and memory all build up.
          </p>
        )}
      </div>

      <div>
        <label htmlFor="meeting-url" className="mb-1.5 block text-sm font-medium">
          Meeting link
        </label>
        <input
          id="meeting-url"
          type="url"
          required
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://meet.google.com/abc-defg-hij"
          className={field}
        />
        <p className="mt-1.5 text-xs text-[var(--muted)]">
          Google Meet, Zoom, Microsoft Teams, Webex, Slack huddles or GoTo.
        </p>
      </div>

      <div>
        <label htmlFor="meeting-title" className="mb-1.5 block text-sm font-medium">
          Title <span className="text-[var(--danger)]">*</span>
        </label>
        <input
          id="meeting-title"
          type="text"
          required
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Weekly project sync"
          className={field}
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
      {!canSubmit && !busy && (
        <p className="text-center text-xs text-[var(--muted)]">
          {!projectChosen
            ? creatingProject
              ? "Name the new project to continue."
              : "Choose a project to continue."
            : !url.trim()
              ? "Paste the meeting link to continue."
              : !title.trim()
                ? "Give this meeting a title to continue."
                : "Confirm consent above to enable this button."}
        </p>
      )}
    </form>
  );
}
