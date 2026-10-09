"use client";

import { useEffect, useState } from "react";
import { type MemoryStatus, memoryApi } from "@/lib/api";

/**
 * Live proof that Hindsight is actually wired up.
 *
 * Reads the public /memory/status endpoint, which reports the *live* backend
 * rather than the configured one — so if Hindsight is down this says
 * "MySQL fallback" instead of claiming an integration that is not there.
 *
 * Details expand inline rather than in a popover: the sidebar is 252px wide,
 * and an absolutely positioned panel gets clipped by it.
 */
export function MemoryBadge() {
  const [status, setStatus] = useState<MemoryStatus | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    memoryApi
      .status()
      .then(setStatus)
      .catch(() => setStatus(null));
  }, []);

  if (!status) return null;

  const live = status.hindsight_integrated;
  const colour = live ? "var(--success)" : "var(--warning)";
  const soft = live ? "var(--success-soft)" : "var(--warning-soft)";

  return (
    <div className="w-full">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={status.note}
        className="flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-left transition"
        style={{ borderColor: colour, background: soft }}
      >
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${live ? "recording-dot" : ""}`}
          style={{ background: colour }}
        />
        <span className="min-w-0 flex-1">
          <span
            className="block truncate text-[11px] font-bold leading-tight"
            style={{ color: colour }}
          >
            {live ? "Hindsight memory" : "MySQL fallback"}
          </span>
          <span className="block truncate text-[10px] leading-tight text-[var(--muted-strong)]">
            {live
              ? `${status.memory_banks ?? 0} memory banks`
              : "Hindsight unreachable"}
          </span>
        </span>
        <span
          aria-hidden
          className="shrink-0 text-[10px] text-[var(--muted-strong)]"
        >
          {open ? "▲" : "▼"}
        </span>
      </button>

      {open && (
        <div className="mt-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-2">
          <dl className="space-y-1 text-[10px]">
            <Row label="Active" value={status.backend} />
            <Row label="Requested" value={status.requested} />
            {status.memory_banks !== null && (
              <Row label="Banks" value={String(status.memory_banks)} />
            )}
            {status.llm_model && (
              <Row label="Model" value={status.llm_model.split("/").pop() ?? ""} />
            )}
          </dl>
          <p className="mt-2 border-t border-[var(--border)] pt-1.5 text-[9px] leading-3 text-[var(--muted-strong)]">
            Verify: <code>GET /memory/status</code>
          </p>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="shrink-0 text-[var(--muted-strong)]">{label}</dt>
      <dd className="truncate font-mono text-[10px] font-semibold">{value}</dd>
    </div>
  );
}
