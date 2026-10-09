"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiError,
  teamApi,
  type TeamInvite,
  type TeamMemberRow,
  type TeamSummary,
} from "@/lib/api";
import { Card, EmptyState, ErrorBanner, Spinner } from "@/components/ui";

/**
 * Teams exist so one bot can cover a meeting several colleagues attend,
 * instead of each of them sending their own. The page says so plainly,
 * because the obvious reading of "team" is shared visibility — and that is
 * exactly what this is not.
 */
export default function TeamsPage() {
  const [teams, setTeams] = useState<TeamSummary[] | null>(null);
  const [members, setMembers] = useState<Record<string, TeamMemberRow[]>>({});
  const [invite, setInvite] = useState<Record<string, TeamInvite>>({});
  const [name, setName] = useState("");
  const [joinToken, setJoinToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  async function refresh() {
    const rows = await teamApi.list().catch((err) => {
      setError(err instanceof ApiError ? err.message : "Could not load teams.");
      return [] as TeamSummary[];
    });
    setTeams(rows);
    const loaded: Record<string, TeamMemberRow[]> = {};
    await Promise.all(
      rows.map(async (t) => {
        loaded[t.id] = await teamApi.members(t.id).catch(() => []);
      }),
    );
    setMembers(loaded);
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const rows = await teamApi.list().catch(() => [] as TeamSummary[]);
      if (cancelled) return;
      setTeams(rows);
      const loaded: Record<string, TeamMemberRow[]> = {};
      await Promise.all(
        rows.map(async (t) => {
          loaded[t.id] = await teamApi.members(t.id).catch(() => []);
        }),
      );
      if (!cancelled) setMembers(loaded);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await teamApi.create(name.trim());
      setName("");
      await refresh();
      setNotice("Team created. Share an invite link to add people.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create the team.");
    } finally {
      setBusy(false);
    }
  }

  async function join(e: React.FormEvent) {
    e.preventDefault();
    const token = joinToken.trim();
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      // Paste either the whole link or just the token.
      const parsed = token.includes("token=")
        ? (new URL(token, window.location.origin).searchParams.get("token") ?? token)
        : token;
      const team = await teamApi.join(parsed);
      setJoinToken("");
      await refresh();
      setNotice(`Joined “${team.name}”.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not join that team.");
    } finally {
      setBusy(false);
    }
  }

  async function makeInvite(id: string) {
    setBusy(true);
    setError(null);
    try {
      const created = await teamApi.createInvite(id);
      setInvite((prev) => ({ ...prev, [id]: created }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create an invite.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: string) {
    setBusy(true);
    try {
      const { revoked } = await teamApi.revokeInvites(id);
      setInvite((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      setNotice(
        revoked === 0
          ? "No live invite links to revoke."
          : `Revoked ${revoked} invite link${revoked === 1 ? "" : "s"}.`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not revoke invites.");
    } finally {
      setBusy(false);
    }
  }

  async function leave(team: TeamSummary) {
    setBusy(true);
    setError(null);
    try {
      await teamApi.leave(team.id);
      await refresh();
      setNotice(`Left “${team.name}”.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not leave the team.");
    } finally {
      setBusy(false);
    }
  }

  const field =
    "w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20";
  const list = teams ?? [];

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <Link href="/dashboard" className="text-sm text-[var(--accent)] hover:underline">
        ← Dashboard
      </Link>

      <header className="mt-4 mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Teams</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          One bot covers a meeting your team attends, instead of everyone
          sending their own.
        </p>
      </header>

      <Card className="mb-6 border-[var(--accent)]/25 p-4">
        <p className="text-sm font-semibold">What a team does and does not do</p>
        <ul className="mt-1.5 space-y-1 text-sm text-[var(--muted-strong)]">
          <li>
            ✓ One recording for the whole room, readable by everyone who was in
            the team when it happened.
          </li>
          <li>
            ✓ Spoken names resolve to the right teammate, so promises land on
            the right person.
          </li>
          <li>
            ✗ Your promises, coaching and progress stay <strong>private</strong>.
            Joining a team shows nobody your work.
          </li>
          <li>✗ Meetings recorded before you joined stay invisible to you.</li>
        </ul>
      </Card>

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

      <div className="mb-6 grid gap-4 sm:grid-cols-2">
        <Card className="p-4">
          <form onSubmit={create} className="space-y-2">
            <label htmlFor="team-name" className="block text-sm font-medium">
              Create a team
            </label>
            <input
              id="team-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Paddy field crew"
              className={field}
            />
            <button
              type="submit"
              disabled={busy || !name.trim()}
              className="w-full rounded-lg bg-[var(--accent)] px-3 py-2 text-sm font-semibold text-[var(--accent-fg)] transition hover:bg-[var(--accent-hover)] disabled:opacity-40"
            >
              Create team
            </button>
          </form>
        </Card>

        <Card className="p-4">
          <form onSubmit={join} className="space-y-2">
            <label htmlFor="join-token" className="block text-sm font-medium">
              Join with an invite link
            </label>
            <input
              id="join-token"
              value={joinToken}
              onChange={(e) => setJoinToken(e.target.value)}
              placeholder="Paste the link or token"
              className={field}
            />
            <button
              type="submit"
              disabled={busy || !joinToken.trim()}
              className="w-full rounded-lg border border-[var(--border)] px-3 py-2 text-sm font-semibold transition hover:bg-[var(--surface-2)] disabled:opacity-40"
            >
              Join team
            </button>
          </form>
        </Card>
      </div>

      {teams === null ? (
        <Card className="flex items-center gap-2 px-5 py-10 text-sm text-[var(--muted)]">
          <Spinner /> Loading teams…
        </Card>
      ) : list.length === 0 ? (
        <Card>
          <EmptyState
            title="You are not in a team yet"
            hint="Create one above, or paste an invite link a colleague sent you."
          />
        </Card>
      ) : (
        <div className="space-y-4">
          {list.map((team) => (
            <Card key={team.id}>
              <div className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--border)] px-5 py-3">
                <div className="min-w-0">
                  <h2 className="truncate text-sm font-bold">{team.name}</h2>
                  <p className="mt-0.5 text-xs text-[var(--muted)]">
                    {team.member_count} member{team.member_count === 1 ? "" : "s"} ·{" "}
                    {team.meeting_count} meeting
                    {team.meeting_count === 1 ? "" : "s"} · you are{" "}
                    {team.is_owner ? "an owner" : "a member"}
                  </p>
                </div>
                <div className="flex shrink-0 flex-wrap gap-2">
                  {team.is_owner && (
                    <>
                      <button
                        onClick={() => makeInvite(team.id)}
                        disabled={busy}
                        className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-xs font-semibold text-[var(--accent-fg)] disabled:opacity-40"
                      >
                        Create invite link
                      </button>
                      <button
                        onClick={() => revoke(team.id)}
                        disabled={busy}
                        className="rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-semibold disabled:opacity-40"
                      >
                        Revoke all links
                      </button>
                    </>
                  )}
                  <button
                    onClick={() => leave(team)}
                    disabled={busy}
                    className="rounded-lg border border-transparent px-3 py-1.5 text-xs font-semibold text-[var(--muted-strong)] transition hover:border-[var(--danger)] hover:text-[var(--danger)] disabled:opacity-40"
                  >
                    Leave
                  </button>
                </div>
              </div>

              {invite[team.id] && (
                <div className="border-b border-[var(--border)] bg-[var(--surface-2)] px-5 py-3">
                  <p className="text-xs font-semibold text-[var(--muted-strong)]">
                    Invite link — expires{" "}
                    {new Date(invite[team.id].expires_at).toLocaleDateString()}, up
                    to {invite[team.id].max_uses} uses
                  </p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <code className="min-w-0 flex-1 truncate rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1.5 text-xs">
                      {invite[team.id].url}
                    </code>
                    <button
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(invite[team.id].url);
                          setCopied(team.id);
                          window.setTimeout(() => setCopied(null), 2000);
                        } catch {
                          setError("Could not copy — select the link and copy it.");
                        }
                      }}
                      className="shrink-0 rounded-lg border border-[var(--border)] px-3 py-1.5 text-xs font-semibold"
                    >
                      {copied === team.id ? "Copied" : "Copy"}
                    </button>
                  </div>
                  <p className="mt-1.5 text-[11px] text-[var(--muted)]">
                    Treat it like a password: anyone with the link can join.
                  </p>
                </div>
              )}

              <ul className="divide-y divide-[var(--border)]">
                {(members[team.id] ?? []).map((m) => (
                  <li
                    key={m.user_id}
                    className="flex items-center justify-between gap-3 px-5 py-2.5"
                  >
                    <span className="min-w-0 truncate text-sm">
                      {m.name ?? m.email}
                      {m.is_you && (
                        <span className="ml-1.5 text-xs text-[var(--muted)]">(you)</span>
                      )}
                    </span>
                    <span className="shrink-0 text-xs capitalize text-[var(--muted)]">
                      {m.role}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}
    </main>
  );
}
