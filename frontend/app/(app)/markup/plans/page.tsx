"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ApiError, markupApi, type PrepPlan } from "@/lib/api";
import { Card, EmptyState, ErrorBanner, Spinner } from "@/components/ui";

/**
 * Every briefing ever generated. Mark Up itself shows only the newest few, so
 * this page carries the search and mode filter that a short preview does not
 * need.
 */
export default function AllPlansPage() {
  const [plans, setPlans] = useState<PrepPlan[] | null>(null);
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await markupApi.plans();
        if (!cancelled) setPlans(rows);
      } catch (err) {
        if (cancelled) return;
        setError(
          err instanceof ApiError ? err.message : "Could not load preparations.",
        );
        setPlans([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (plans ?? []).filter(
      (p) =>
        (!mode || p.mode === mode) &&
        (!q || (p.title ?? "").toLowerCase().includes(q)),
    );
  }, [plans, query, mode]);

  const field =
    "rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20";

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <Link href="/markup" className="text-sm text-[var(--accent)] hover:underline">
        ← Mark Up
      </Link>

      <header className="mt-4 mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">All preparations</h1>
        <p className="mt-1 text-sm text-[var(--muted)]">
          Every briefing MeetMind has built for you, newest first.
        </p>
      </header>

      {error && (
        <div className="mb-5">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by title…"
          aria-label="Search preparations"
          className={`${field} min-w-0 flex-1`}
        />
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value)}
          aria-label="Filter by type"
          className={field}
        >
          <option value="">All types</option>
          <option value="existing">Existing project</option>
          <option value="new">New project</option>
        </select>
      </div>

      <Card>
        <h2 className="flex items-baseline justify-between gap-3 border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
          <span>Preparations</span>
          {plans !== null && (
            <span className="text-xs font-medium normal-case tabular-nums">
              {filtered.length}
              {filtered.length !== plans.length ? ` of ${plans.length}` : ""}
            </span>
          )}
        </h2>

        {plans === null ? (
          <div className="flex items-center justify-center gap-2 px-5 py-12 text-sm text-[var(--muted)]">
            <Spinner /> Loading preparations…
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            title={plans.length === 0 ? "No preparations yet" : "Nothing matches"}
            hint={
              plans.length === 0
                ? "Build a briefing from Mark Up before your next meeting."
                : "Try a different search or type."
            }
          />
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {filtered.map((p) => (
              <li key={p.id}>
                {/* Mark Up opens a plan from its own state, so this links back
                    there with the id rather than duplicating the plan view. */}
                <Link
                  href={`/markup?plan=${p.id}`}
                  className="block px-5 py-3 transition hover:bg-[var(--background)]"
                >
                  <p className="text-sm font-medium">{p.title || "Untitled"}</p>
                  <p className="text-xs text-[var(--muted)]">
                    {p.mode} · {new Date(p.created_at).toLocaleString()}
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </main>
  );
}
