"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  type Finding,
  type TeamCommitment,
  type TeamDeadlineItem,
  type TeamOverview,
  type TeamProjectRollup,
  teamApi,
} from "@/lib/api";
import { useAuth } from "@/components/AuthGate";
import { Card, EmptyState, ErrorBanner, Spinner } from "@/components/ui";

type Tab = "overview" | "deadlines" | "commitments" | "findings";

const KIND_LABEL: Record<string, string> = {
  overdue: "Overdue",
  approaching: "Due soon",
  conflicting: "Clashing dates",
  unowned: "No owner",
  undated: "No date",
  changed: "Changed",
};

export default function TeamPage() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("overview");
  const [member, setMember] = useState("");
  const [overview, setOverview] = useState<TeamOverview | null>(null);
  const [deadlines, setDeadlines] = useState<{
    overdue: TeamDeadlineItem[];
    upcoming: TeamDeadlineItem[];
  }>({ overdue: [], upcoming: [] });
  const [commitments, setCommitments] = useState<TeamCommitment[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [projects, setProjects] = useState<TeamProjectRollup[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [o, d, c, f, p] = await Promise.all([
        teamApi.overview(),
        teamApi.deadlines(),
        teamApi.commitments(member || undefined),
        teamApi.findings(member || undefined),
        teamApi.projects(),
      ]);
      setOverview(o);
      setDeadlines(d);
      setCommitments(c);
      setFindings(f.findings);
      setProjects(p);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load team data.");
    } finally {
      setLoading(false);
    }
  }, [member]);

  useEffect(() => {
    load();
  }, [load]);

  if (user?.role !== "manager") {
    return (
      <main className="mx-auto max-w-3xl px-4 py-16 sm:px-6">
        <Card className="p-8 text-center">
          <h1 className="text-lg font-semibold">Manager access only</h1>
          <p className="mt-2 text-sm text-[var(--muted-strong)]">
            This section shows a team&apos;s commitments and deadlines. Your
            account is an employee account, so it shows only your own work.
          </p>
          <Link
            href="/progress"
            className="mt-4 inline-block text-sm font-medium text-[var(--accent)] hover:underline"
          >
            Go to My Progress →
          </Link>
        </Card>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <header className="mb-6">
        <div className="accent-bar mb-3" />
        <h1 className="text-2xl font-semibold tracking-tight">About My Team</h1>
        <p className="mt-1 text-sm text-[var(--muted-strong)]">
          Everything your reports committed to, across their meetings. This view
          is read-only — only the person who made a promise can mark it done.
        </p>
      </header>

      {error && (
        <div className="mb-5">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}

      {overview && (
        <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ["People", overview.totals.people, "var(--accent)"],
            ["Pending", overview.totals.pending, "var(--c-progress)"],
            ["Completed", overview.totals.completed, "var(--success)"],
            ["Overdue", overview.totals.overdue, "var(--danger)"],
          ].map(([label, value, colour]) => (
            <Card key={String(label)} className="p-4">
              <p className="text-xs uppercase tracking-wide text-[var(--muted-strong)]">
                {label}
              </p>
              <p
                className="mt-1 text-2xl font-semibold tabular-nums"
                style={{ color: colour as string }}
              >
                {value}
              </p>
            </Card>
          ))}
        </div>
      )}

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <select
          value={member}
          onChange={(e) => setMember(e.target.value)}
          className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm"
        >
          <option value="">Everyone</option>
          {overview?.members
            .filter((m) => m.user_id)
            .map((m) => (
              <option key={m.user_id} value={m.user_id ?? ""}>
                {m.name}
                {m.is_you ? " (you)" : ""}
              </option>
            ))}
        </select>

        <div className="flex flex-wrap gap-1 rounded-lg border border-[var(--border)] p-1">
          {(["overview", "deadlines", "commitments", "findings"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold capitalize transition ${
                tab === t
                  ? "bg-[var(--accent)] text-[var(--accent-fg)]"
                  : "hover:bg-[var(--surface-2)]"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <Card className="flex items-center gap-2 px-5 py-10 text-sm text-[var(--muted-strong)]">
          <Spinner /> Loading your team…
        </Card>
      ) : tab === "overview" ? (
        <div className="space-y-6">
          <Card>
            <h2 className="border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted-strong)]">
              People
            </h2>
            {!overview?.members.length ? (
              <EmptyState
                title="No one reports to you yet"
                hint="Share your email — employees enter it when they register."
              />
            ) : (
              <ul className="divide-y divide-[var(--border)]">
                {overview.members.map((m) => (
                  <li key={m.user_id ?? "unassigned"} className="px-5 py-4">
                    <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
                      <span className="text-sm font-medium">
                        {m.name}
                        {m.is_you && (
                          <span className="ml-2 text-[11px] text-[var(--muted-strong)]">
                            you
                          </span>
                        )}
                      </span>
                      <span className="text-xs text-[var(--muted-strong)]">
                        {m.completed}/{m.total} done
                        {m.overdue > 0 && (
                          <span style={{ color: "var(--danger)" }}>
                            {" "}
                            · {m.overdue} overdue
                          </span>
                        )}
                        {m.next_due && (
                          <> · next {new Date(m.next_due).toLocaleDateString()}</>
                        )}
                      </span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--surface-2)]">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${m.percent}%`,
                          background:
                            m.overdue > 0 ? "var(--danger)" : "var(--accent)",
                        }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <h2 className="border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted-strong)]">
              Projects
            </h2>
            {projects.length === 0 ? (
              <EmptyState title="No project activity yet" />
            ) : (
              <ul className="space-y-3 px-5 py-4">
                {projects.map((p) => (
                  <li key={p.project_id ?? "unassigned"}>
                    <div className="mb-1 flex items-baseline justify-between text-sm">
                      <span className="font-medium">{p.project_name}</span>
                      <span className="text-xs text-[var(--muted-strong)]">
                        {p.completed}/{p.total}
                        {p.overdue > 0 && (
                          <span style={{ color: "var(--danger)" }}>
                            {" "}
                            · {p.overdue} overdue
                          </span>
                        )}
                      </span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--surface-2)]">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${p.percent}%`,
                          background: "var(--c-progress)",
                        }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      ) : tab === "deadlines" ? (
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <h2
              className="border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide"
              style={{ color: "var(--danger)" }}
            >
              Overdue
            </h2>
            {deadlines.overdue.length === 0 ? (
              <EmptyState title="Nothing overdue" hint="The team is on track." />
            ) : (
              <ul className="divide-y divide-[var(--border)]">
                {deadlines.overdue.map((d) => (
                  <li key={d.id} className="px-5 py-3">
                    <p className="text-sm">{d.text}</p>
                    <p className="text-xs" style={{ color: "var(--danger)" }}>
                      {d.assigned_to} · was due{" "}
                      {new Date(d.due_at).toLocaleDateString()}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <h2 className="border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted-strong)]">
              Coming up
            </h2>
            {deadlines.upcoming.length === 0 ? (
              <EmptyState title="Nothing due in the next 30 days" />
            ) : (
              <ul className="divide-y divide-[var(--border)]">
                {deadlines.upcoming.map((d) => (
                  <li key={d.id} className="px-5 py-3">
                    <p className="text-sm">{d.text}</p>
                    <p className="text-xs text-[var(--muted-strong)]">
                      {d.assigned_to} · {new Date(d.due_at).toLocaleDateString()}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      ) : tab === "commitments" ? (
        <Card>
          {commitments.length === 0 ? (
            <EmptyState title="No commitments recorded for this selection" />
          ) : (
            <ul className="divide-y divide-[var(--border)]">
              {commitments.map((c) => (
                <li key={c.id} className="px-5 py-3.5">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <p
                      className={`text-sm ${
                        c.status === "completed" ? "line-through opacity-60" : ""
                      }`}
                    >
                      {c.text}
                    </p>
                    <span className="shrink-0 rounded-full border border-[var(--border)] px-2 py-0.5 text-[11px] capitalize text-[var(--muted-strong)]">
                      {c.status}
                    </span>
                  </div>
                  <p className="mt-0.5 text-xs text-[var(--muted-strong)]">
                    {c.assigned_to ?? `“${c.spoken_owner ?? "unassigned"}” — not matched`}
                    {c.due_at && ` · due ${new Date(c.due_at).toLocaleDateString()}`}
                    {c.meeting_title && ` · from “${c.meeting_title}”`}
                  </p>
                  {c.evidence && (
                    <blockquote className="mt-2 border-l-2 border-[var(--accent)] bg-[var(--surface-2)] px-3 py-1.5 text-xs italic text-[var(--muted-strong)]">
                      “{c.evidence}”
                    </blockquote>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : (
        <div className="space-y-3">
          {findings.length === 0 ? (
            <Card>
              <EmptyState title="No outstanding issues across the team" />
            </Card>
          ) : (
            findings.map((f, i) => (
              <Card key={`${f.kind}-${i}`} className="p-4">
                <span className="mb-1.5 inline-block rounded-full border border-[var(--border)] px-2 py-0.5 text-[11px] font-semibold text-[var(--muted-strong)]">
                  {KIND_LABEL[f.kind] ?? f.kind}
                </span>
                <p className="text-sm font-medium">{f.title}</p>
                <p className="mt-0.5 text-sm text-[var(--muted-strong)]">{f.detail}</p>
                {f.evidence && (
                  <blockquote className="mt-2 border-l-2 border-[var(--accent)] bg-[var(--surface-2)] px-3 py-1.5 text-xs italic text-[var(--muted-strong)]">
                    “{f.evidence}”
                  </blockquote>
                )}
                {f.meeting_id && (
                  <Link
                    href={`/meetings/${f.meeting_id}`}
                    className="mt-2 inline-block text-xs text-[var(--accent)] hover:underline"
                  >
                    From “{f.meeting_title ?? "meeting"}” →
                  </Link>
                )}
              </Card>
            ))
          )}
        </div>
      )}
    </main>
  );
}
