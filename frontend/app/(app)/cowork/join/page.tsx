"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ApiError, coworkApi } from "@/lib/api";
import { Card, ErrorBanner, Spinner } from "@/components/ui";

/**
 * Where a Co-Work link lands.
 *
 * The link asks; it does not admit. Being let in makes your progress visible
 * to that room, so somebody has to decide it — and the page says so before
 * you press anything.
 */
export default function JoinCoWorkPage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-lg px-4 py-16 sm:px-6">
          <p className="flex items-center gap-2 text-sm text-[var(--muted)]">
            <Spinner /> Loading…
          </p>
        </main>
      }
    >
      <JoinCoWorkView />
    </Suspense>
  );
}

function JoinCoWorkView() {
  const token = useSearchParams().get("token") ?? "";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ status: string; message: string } | null>(
    null,
  );

  async function ask() {
    setBusy(true);
    setError(null);
    try {
      const r = await coworkApi.askToJoin(token);
      setResult({ status: r.status, message: r.message });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not use that link.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-lg px-4 py-16 sm:px-6">
      <Card className="p-6">
        <h1 className="text-xl font-semibold tracking-tight">
          Join a Co-Work space
        </h1>

        {!token ? (
          <p className="mt-2 text-sm text-[var(--muted)]">
            This link has no token in it. Ask for a fresh one, or paste it on
            the{" "}
            <Link href="/cowork" className="text-[var(--accent)] hover:underline">
              Co-Work page
            </Link>
            .
          </p>
        ) : result ? (
          <>
            <p className="mt-2 text-sm">{result.message}</p>
            {result.status === "pending" && (
              <p className="mt-1 text-sm text-[var(--muted)]">
                You will see the space here once the owner accepts.
              </p>
            )}
            <Link
              href="/cowork"
              className="mt-4 inline-block rounded-lg bg-[var(--accent)] px-3.5 py-2 text-sm font-semibold text-[var(--accent-fg)]"
            >
              Go to Co-Work
            </Link>
          </>
        ) : (
          <>
            <p className="mt-2 text-sm text-[var(--muted)]">
              In a Co-Work space, everyone can see how each person&apos;s tasks
              are going — that is what makes shared work coordinate. Only you
              can mark your own tasks done.
            </p>
            <p className="mt-2 text-sm text-[var(--muted)]">
              Because joining makes your progress visible, this sends a request
              the owner accepts or rejects. Nothing else from your account is
              shared: your meetings, promises and coaching stay private.
            </p>
            {error && (
              <div className="mt-4">
                <ErrorBanner message={error} onDismiss={() => setError(null)} />
              </div>
            )}
            <button
              onClick={ask}
              disabled={busy}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-[var(--accent)] px-4 py-2.5 text-sm font-bold text-[var(--accent-fg)] transition hover:bg-[var(--accent-hover)] disabled:opacity-50"
            >
              {busy && <Spinner />}
              {busy ? "Sending…" : "Ask to join"}
            </button>
          </>
        )}
      </Card>
    </main>
  );
}
