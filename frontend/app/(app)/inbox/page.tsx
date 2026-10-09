"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiError,
  inboxApi,
  type InboxEmail,
  type PrioritySender,
} from "@/lib/api";
import { Card, EmptyState, ErrorBanner, Spinner } from "@/components/ui";

/**
 * The handful of senders that matter, and what their mail actually said.
 *
 * Not an inbox: nothing is read except mail from senders named here, and no
 * message body is kept. What survives is the summary, the highlights, and any
 * promise — which joins the same ledger as promises made in meetings.
 */
export default function InboxPage() {
  const [senders, setSenders] = useState<PrioritySender[] | null>(null);
  const [mail, setMail] = useState<InboxEmail[] | null>(null);
  const [pattern, setPattern] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function refresh(unread = unreadOnly) {
    const [s, m] = await Promise.all([
      inboxApi.senders().catch(() => [] as PrioritySender[]),
      inboxApi.list(unread).catch(() => [] as InboxEmail[]),
    ]);
    setSenders(s);
    setMail(m);
  }

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [s, m] = await Promise.all([
        inboxApi.senders().catch(() => [] as PrioritySender[]),
        inboxApi.list(false).catch(() => [] as InboxEmail[]),
      ]);
      if (cancelled) return;
      setSenders(s);
      setMail(m);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  async function addSender(e: React.FormEvent) {
    e.preventDefault();
    if (!pattern.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await inboxApi.addSender(pattern.trim());
      setPattern("");
      await refresh();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Enter an email address or a domain.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function sync() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const r = await inboxApi.sync();
      await refresh();
      setNotice(
        r.message ??
          `Checked ${r.synced} message${r.synced === 1 ? "" : "s"} · ${r.new} new · ` +
            `${r.commitments} promise${r.commitments === 1 ? "" : "s"} added.`,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not check mail.");
    } finally {
      setBusy(false);
    }
  }

  const field =
    "w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/20";
  const urgentCount = (mail ?? []).filter((m) => m.urgent && !m.read).length;

  return (
    <main className="mx-auto max-w-5xl px-4 py-10 sm:px-6">
      <Link href="/dashboard" className="text-sm text-[var(--accent)] hover:underline">
        ← Dashboard
      </Link>

      <header className="mt-4 mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Priority inbox</h1>
          <p className="mt-1 text-sm text-[var(--muted)]">
            Mail from the people who matter, summarised — and any promise in it
            lands in My Promises alongside the ones from meetings.
          </p>
        </div>
        <button
          onClick={sync}
          disabled={busy}
          className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-[var(--accent)] px-3.5 py-2 text-sm font-semibold text-[var(--accent-fg)] transition hover:bg-[var(--accent-hover)] disabled:opacity-50"
        >
          {busy && <Spinner />}
          {busy ? "Checking…" : "Check mail"}
        </button>
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

      <Card className="mb-6 p-4">
        <p className="text-sm font-semibold">Who counts</p>
        <p className="mt-0.5 text-xs text-[var(--muted)]">
          An address (<code>ravi@acme.com</code>) or a whole domain (
          <code>acme.com</code>). Nothing else in your mailbox is read.
        </p>
        <form onSubmit={addSender} className="mt-3 flex flex-wrap gap-2">
          <input
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            placeholder="acme.com"
            aria-label="Priority sender"
            className={`${field} min-w-0 flex-1`}
          />
          <button
            type="submit"
            disabled={busy || !pattern.trim()}
            className="shrink-0 rounded-lg border border-[var(--border)] px-3.5 py-2 text-sm font-semibold transition hover:bg-[var(--surface-2)] disabled:opacity-40"
          >
            Add
          </button>
        </form>
        {senders && senders.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-2">
            {senders.map((s) => (
              <li
                key={s.id}
                className="flex items-center gap-1.5 rounded-full border border-[var(--border)] py-1 pl-3 pr-1.5 text-xs"
              >
                <span className="font-medium">{s.pattern}</span>
                <button
                  onClick={async () => {
                    await inboxApi.removeSender(s.id).catch(() => null);
                    await refresh();
                  }}
                  aria-label={`Remove ${s.pattern}`}
                  className="grid h-5 w-5 place-items-center rounded-full text-[var(--muted)] transition hover:bg-[var(--danger-soft)] hover:text-[var(--danger)]"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        {urgentCount > 0 && (
          <span
            className="rounded-full px-2.5 py-1 text-xs font-bold"
            style={{
              background: "color-mix(in oklab, var(--chart-overdue) 12%, transparent)",
              color: "var(--chart-overdue)",
            }}
          >
            {urgentCount} needing a reply
          </span>
        )}
        <label className="flex cursor-pointer items-center gap-2 text-xs text-[var(--muted-strong)]">
          <input
            type="checkbox"
            checked={unreadOnly}
            onChange={(e) => {
              setUnreadOnly(e.target.checked);
              void refresh(e.target.checked);
            }}
            className="h-3.5 w-3.5 accent-[var(--accent)]"
          />
          Unread only
        </label>
      </div>

      {mail === null ? (
        <Card className="flex items-center gap-2 px-5 py-10 text-sm text-[var(--muted)]">
          <Spinner /> Loading mail…
        </Card>
      ) : mail.length === 0 ? (
        <Card>
          <EmptyState
            title={
              senders && senders.length === 0
                ? "Name a sender first"
                : "Nothing from your priority senders yet"
            }
            hint={
              senders && senders.length === 0
                ? "Add a client's address or domain above, then press Check mail."
                : "Press Check mail to look for recent messages."
            }
          />
        </Card>
      ) : (
        <ul className="space-y-3">
          {mail.map((m) => (
            <li key={m.id}>
              <Card
                className={
                  m.urgent && !m.read
                    ? "border-red-500/40 p-4 ring-2 ring-red-500/25"
                    : `p-4 ${m.read ? "opacity-70" : ""}`
                }
              >
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2">
                      {m.urgent && (
                        <span
                          className="rounded-full px-2 py-0.5 text-[11px] font-bold"
                          style={{
                            background:
                              "color-mix(in oklab, var(--chart-overdue) 12%, transparent)",
                            color: "var(--chart-overdue)",
                          }}
                        >
                          Needs a reply
                        </span>
                      )}
                      <span className="text-sm font-semibold">
                        {m.subject || "(no subject)"}
                      </span>
                    </p>
                    <p className="mt-0.5 text-xs text-[var(--muted)]">
                      {m.sender_name ? `${m.sender_name} · ` : ""}
                      {m.sender}
                      {m.received_at
                        ? ` · ${new Date(m.received_at).toLocaleString()}`
                        : ""}
                      {m.matched_pattern ? ` · matched ${m.matched_pattern}` : ""}
                    </p>
                  </div>
                  <button
                    onClick={async () => {
                      await inboxApi.markRead(m.id, !m.read).catch(() => null);
                      await refresh();
                    }}
                    className="shrink-0 rounded-lg border border-[var(--border)] px-2.5 py-1 text-xs font-semibold transition hover:bg-[var(--surface-2)]"
                  >
                    {m.read ? "Mark unread" : "Mark read"}
                  </button>
                </div>

                {m.summary && <p className="mt-2 text-sm">{m.summary}</p>}

                {m.highlights.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {m.highlights.map((h, i) => (
                      <li
                        key={i}
                        className="flex gap-2 text-sm text-[var(--muted-strong)]"
                      >
                        <span aria-hidden className="text-[var(--accent)]">
                          •
                        </span>
                        <span>{h}</span>
                      </li>
                    ))}
                  </ul>
                )}

                {m.urgent && m.urgency_reason && (
                  <p className="mt-2 text-xs font-medium text-[var(--muted-strong)]">
                    Why now: {m.urgency_reason}
                  </p>
                )}
              </Card>
            </li>
          ))}
        </ul>
      )}

      <p className="mt-6 text-xs text-[var(--muted)]">
        Promises found in this mail appear in{" "}
        <Link href="/promises" className="text-[var(--accent)] hover:underline">
          My Promises
        </Link>
        , in the same list as promises made in meetings.
      </p>
    </main>
  );
}
