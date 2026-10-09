"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ApiError, teamApi, type TeamSummary } from "@/lib/api";
import { Card, ErrorBanner, Spinner } from "@/components/ui";

/**
 * Where an invite link lands. Joining is a deliberate click rather than
 * something that happens on page load: following a link someone forwarded
 * should not silently add you to their team.
 */
export default function JoinTeamPage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-lg px-4 py-16 sm:px-6">
          <p className="flex items-center gap-2 text-sm text-[var(--muted)]">
            <Spinner /> Loading invite…
          </p>
        </main>
      }
    >
      <JoinTeamView />
    </Suspense>
  );
}

function JoinTeamView() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [joined, setJoined] = useState<TeamSummary | null>(null);

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      setJoined(await teamApi.join(token));
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not join with that link.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-lg px-4 py-16 sm:px-6">
      <Card className="p-6">
        <h1 className="text-xl font-semibold tracking-tight">Join a team</h1>

        {!token ? (
          <p className="mt-2 text-sm text-[var(--muted)]">
            This link has no invite token in it. Ask whoever sent it for a fresh
            one, or paste it on the{" "}
            <Link href="/teams" className="text-[var(--accent)] hover:underline">
              Teams page
            </Link>
            .
          </p>
        ) : joined ? (
          <>
            <p className="mt-2 text-sm">
              You are now in <strong>{joined.name}</strong>.
            </p>
            <p className="mt-1 text-sm text-[var(--muted)]">
              Meetings this team records from now on will appear in your history.
              Your promises, coaching and progress stay private.
            </p>
            <div className="mt-4 flex gap-2">
              <Link
                href="/teams"
                className="rounded-lg bg-[var(--accent)] px-3.5 py-2 text-sm font-semibold text-[var(--accent-fg)]"
              >
                View teams
              </Link>
              <button
                onClick={() => router.push("/dashboard")}
                className="rounded-lg border border-[var(--border)] px-3.5 py-2 text-sm font-semibold"
              >
                Go to dashboard
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="mt-2 text-sm text-[var(--muted)]">
              Joining lets one bot cover meetings this team records, and lets
              spoken names resolve to the right person. It does{" "}
              <strong>not</strong> share your promises, coaching or progress
              with anyone, and meetings recorded before you join stay invisible
              to you.
            </p>
            {error && (
              <div className="mt-4">
                <ErrorBanner message={error} onDismiss={() => setError(null)} />
              </div>
            )}
            <button
              onClick={accept}
              disabled={busy}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2.5 text-sm font-bold text-[var(--accent-fg)] transition hover:bg-[var(--accent-hover)] disabled:opacity-50"
            >
              {busy && <Spinner />}
              {busy ? "Joining…" : "Join this team"}
            </button>
          </>
        )}
      </Card>
    </main>
  );
}
