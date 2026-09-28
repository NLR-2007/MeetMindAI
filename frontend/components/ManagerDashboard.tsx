"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowUpRight, CalendarDays, CheckCircle2, Clock3, Users } from "lucide-react";
import { authApi, progressApi, type Commitment, type ProgressData, type TeamMember } from "@/lib/api";
import { Card, EmptyState, ErrorBanner, Spinner } from "./ui";

interface MemberProgress {
  member: TeamMember;
  progress: ProgressData;
}

function dueLabel(date: string | null) {
  if (!date) return "No date";
  return new Date(date).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function initials(member: TeamMember) {
  return (member.name || member.email).split(/[\s@._-]+/).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
}

export function ManagerDashboard() {
  const [rows, setRows] = useState<MemberProgress[] | null>(null);
  const [selectedMember, setSelectedMember] = useState("all");
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const team = await authApi.team();
      const employees = team.filter((member) => member.role !== "manager");
      setRows(await Promise.all(employees.map(async (member) => ({ member, progress: await progressApi.get(undefined, member.id) }))));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load team progress.");
      setRows([]);
    }
  }

  useEffect(() => {
    authApi.team()
      .then(async (team) => Promise.all(team.filter((member) => member.role !== "manager").map(async (member) => ({ member, progress: await progressApi.get(undefined, member.id) }))))
      .then(setRows)
      .catch((reason) => {
        setError(reason instanceof Error ? reason.message : "Could not load team progress.");
        setRows([]);
      });
  }, []);

  const visibleRows = useMemo(
    () => (rows ?? []).filter((row) => selectedMember === "all" || row.member.id === selectedMember),
    [rows, selectedMember],
  );

  const totals = useMemo(
    () => visibleRows.reduce(
      (sum, row) => ({
        total: sum.total + row.progress.totals.pending + row.progress.totals.completed,
        completed: sum.completed + row.progress.totals.completed,
        pending: sum.pending + row.progress.totals.pending,
        overdue: sum.overdue + row.progress.totals.overdue,
      }),
      { total: 0, completed: 0, pending: 0, overdue: 0 },
    ),
    [visibleRows],
  );

  const commitments = useMemo(
    () => visibleRows.flatMap((row) => {
      const projects = new Map(row.progress.by_project.map((project) => [project.project_id, project.project_name]));
      const overdueIds = new Set(row.progress.overdue.map((commitment) => commitment.id));
      return row.progress.pending.map((commitment) => ({ commitment, member: row.member, projectName: projects.get(commitment.project_id) ?? "Unassigned", overdue: overdueIds.has(commitment.id) }));
    }).sort((a, b) => {
      if (!a.commitment.due_at) return 1;
      if (!b.commitment.due_at) return -1;
      return new Date(a.commitment.due_at).getTime() - new Date(b.commitment.due_at).getTime();
    }),
    [visibleRows],
  );

  if (rows === null) {
    return <main className="mx-auto flex max-w-6xl items-center gap-2 px-4 py-16 text-sm text-[var(--muted)]"><Spinner /> Loading your team dashboard…</main>;
  }

  return (
    <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 sm:py-10">
      <header className="mb-7 overflow-hidden rounded-[1.75rem] bg-[var(--navy)] px-5 py-7 text-white shadow-[0_24px_60px_-34px_rgb(21_27_46/.65)] sm:px-8 sm:py-9">
        <div className="flex flex-col justify-between gap-6 sm:flex-row sm:items-end">
          <div>
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[0.15em] text-white/55"><Users className="h-3.5 w-3.5" /> Manager workspace</div>
            <h1 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">Team overview</h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-white/60">See every employee&apos;s commitments, approaching deadlines, overdue work, and overall follow-through in one place.</p>
          </div>
          <select value={selectedMember} onChange={(event) => setSelectedMember(event.target.value)} className="rounded-xl border border-white/15 bg-white/10 px-3.5 py-2.5 text-sm font-semibold text-white outline-none backdrop-blur [&>option]:text-[var(--foreground)]">
            <option value="all">All employees</option>
            {rows.map(({ member }) => <option key={member.id} value={member.id}>{member.name || member.email}</option>)}
          </select>
        </div>
      </header>

      {error && <div className="mb-5"><ErrorBanner message={error} onDismiss={() => setError(null)} /></div>}

      <section aria-label="Team metrics" className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          { label: "Total commitments", value: totals.total, icon: Clock3, tone: "var(--accent)", soft: "var(--accent-soft)" },
          { label: "Completed", value: totals.completed, icon: CheckCircle2, tone: "var(--success)", soft: "var(--success-soft)" },
          { label: "In progress", value: totals.pending, icon: ArrowUpRight, tone: "var(--info)", soft: "var(--info-soft)" },
          { label: "Overdue", value: totals.overdue, icon: AlertTriangle, tone: "var(--danger)", soft: "var(--danger-soft)" },
        ].map((metric) => (
          <Card key={metric.label} className="p-4 sm:p-5">
            <div className="flex items-start justify-between gap-3">
              <div><p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--muted)]">{metric.label}</p><p className="mt-2 text-3xl font-bold tracking-[-0.04em]" style={{ color: metric.tone }}>{metric.value}</p></div>
              <span className="grid h-9 w-9 place-items-center rounded-xl" style={{ color: metric.tone, background: metric.soft }}><metric.icon className="h-4 w-4" /></span>
            </div>
          </Card>
        ))}
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,.9fr)]">
        <Card className="overflow-hidden">
          <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
            <div><h2 className="text-sm font-bold">Employee progress</h2><p className="mt-0.5 text-xs text-[var(--muted)]">Completion and deadline health by team member</p></div>
            <button onClick={load} className="text-xs font-bold text-[var(--accent)] hover:underline">Refresh</button>
          </div>
          {visibleRows.length === 0 ? <EmptyState title="No employees connected" hint="Employees appear after joining with your manager email." /> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[620px] text-left">
                <thead className="bg-[var(--background)] text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--muted)]"><tr><th className="px-5 py-3">Employee</th><th className="px-4 py-3">Progress</th><th className="px-4 py-3">Open</th><th className="px-4 py-3">Overdue</th><th className="px-5 py-3 text-right">Next deadline</th></tr></thead>
                <tbody className="divide-y divide-[var(--border)]">
                  {visibleRows.map(({ member, progress }) => {
                    const total = progress.totals.pending + progress.totals.completed;
                    const percent = total ? Math.round((progress.totals.completed / total) * 100) : 0;
                    const next = [...progress.pending].filter((item) => item.due_at).sort((a, b) => new Date(a.due_at!).getTime() - new Date(b.due_at!).getTime())[0];
                    return (
                      <tr key={member.id} className="transition hover:bg-[var(--background)]/70">
                        <td className="px-5 py-4"><div className="flex items-center gap-3"><span className="grid h-9 w-9 place-items-center rounded-xl bg-[var(--accent-soft)] text-[10px] font-bold text-[var(--accent)]">{initials(member)}</span><div><p className="text-sm font-bold">{member.name || "Unnamed employee"}</p><p className="text-[10px] text-[var(--muted)]">{member.email}</p></div></div></td>
                        <td className="px-4 py-4"><div className="flex items-center gap-2"><div className="h-2 w-24 overflow-hidden rounded-full bg-[var(--surface-strong)]"><div className="h-full rounded-full bg-[var(--accent)]" style={{ width: `${percent}%` }} /></div><span className="text-xs font-bold">{percent}%</span></div></td>
                        <td className="px-4 py-4 text-sm font-semibold">{progress.totals.pending}</td>
                        <td className="px-4 py-4"><span className={progress.totals.overdue ? "font-bold text-[var(--danger)]" : "text-[var(--muted)]"}>{progress.totals.overdue}</span></td>
                        <td className="px-5 py-4 text-right text-xs text-[var(--muted)]">{next ? dueLabel(next.due_at) : "Nothing scheduled"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card className="overflow-hidden">
          <div className="border-b border-[var(--border)] px-5 py-4"><h2 className="text-sm font-bold">Project health</h2><p className="mt-0.5 text-xs text-[var(--muted)]">Progress across employee projects</p></div>
          {visibleRows.flatMap((row) => row.progress.by_project).length === 0 ? <EmptyState title="No project activity yet" /> : (
            <div className="max-h-[420px] space-y-4 overflow-y-auto p-5">
              {visibleRows.flatMap(({ member, progress }) => progress.by_project.map((project) => ({ member, project }))).map(({ member, project }, index) => (
                <div key={`${member.id}-${project.project_id ?? "none"}-${index}`}>
                  <div className="mb-1.5 flex items-end justify-between gap-3"><div><p className="text-sm font-bold">{project.project_name}</p><p className="text-[10px] text-[var(--muted)]">{member.name || member.email}</p></div><span className="text-xs font-bold">{project.percent}%</span></div>
                  <div className="h-2 overflow-hidden rounded-full bg-[var(--surface-strong)]"><div className="h-full rounded-full bg-gradient-to-r from-[var(--accent)] to-[#8b7eff]" style={{ width: `${project.percent}%` }} /></div>
                  <div className="mt-1.5 flex gap-3 text-[10px] text-[var(--muted)]"><span>{project.completed} done</span><span>{project.pending} open</span>{project.overdue > 0 && <span className="font-bold text-[var(--danger)]">{project.overdue} overdue</span>}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card className="mt-6 overflow-hidden">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-4">
          <div><h2 className="flex items-center gap-2 text-sm font-bold"><CalendarDays className="h-4 w-4 text-[var(--accent)]" /> All employee commitments</h2><p className="mt-0.5 text-xs text-[var(--muted)]">Every open task and deadline, ordered by urgency</p></div>
          <Link href="/promises" className="text-xs font-bold text-[var(--accent)] hover:underline">Open PromiseMirror →</Link>
        </div>
        {commitments.length === 0 ? <EmptyState title="No open commitments" hint="Your team is all caught up." /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left">
              <thead className="bg-[var(--background)] text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--muted)]"><tr><th className="px-5 py-3">Employee</th><th className="px-4 py-3">Commitment</th><th className="px-4 py-3">Project</th><th className="px-4 py-3">Deadline</th><th className="px-5 py-3 text-right">Status</th></tr></thead>
              <tbody className="divide-y divide-[var(--border)]">{commitments.map(({ commitment, member, projectName, overdue }) => <CommitmentRow key={`${member.id}-${commitment.id}`} member={member} commitment={commitment} projectName={projectName} overdue={overdue} />)}</tbody>
            </table>
          </div>
        )}
      </Card>
    </main>
  );
}

function CommitmentRow({ member, commitment, projectName, overdue }: { member: TeamMember; commitment: Commitment; projectName: string; overdue: boolean }) {
  return (
    <tr className="transition hover:bg-[var(--background)]/70">
      <td className="px-5 py-4"><div className="flex items-center gap-2"><span className="grid h-7 w-7 place-items-center rounded-lg bg-[var(--accent-soft)] text-[9px] font-bold text-[var(--accent)]">{initials(member)}</span><span className="text-xs font-semibold">{member.name || member.email}</span></div></td>
      <td className="max-w-md px-4 py-4 text-sm font-medium">{commitment.text}</td>
      <td className="px-4 py-4 text-xs text-[var(--muted)]">{projectName}</td>
      <td className={`px-4 py-4 text-xs font-semibold ${overdue ? "text-[var(--danger)]" : "text-[var(--muted-strong)]"}`}>{dueLabel(commitment.due_at)}</td>
      <td className="px-5 py-4 text-right"><span className={`rounded-full px-2.5 py-1 text-[10px] font-bold ${overdue ? "bg-[var(--danger-soft)] text-[var(--danger)]" : "bg-[var(--warning-soft)] text-[var(--warning)]"}`}>{overdue ? "Overdue" : commitment.due_at ? "Upcoming" : "Needs date"}</span></td>
    </tr>
  );
}
