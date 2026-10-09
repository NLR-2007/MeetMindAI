"use client";

import { useId, useState } from "react";

/**
 * Charts for the progress dashboard.
 *
 * Inline SVG rather than a charting library: these are two small, fixed forms,
 * and a dependency would cost more bundle than it saves in code.
 *
 * Colour choices are not free-hand. The four status hues were validated as a
 * categorical set against the white card surface; the run returned two
 * obligations, both honoured here:
 *   - colour-vision separation sits in the warn band, so every mark carries a
 *     second encoding (direct value labels, a legend, 2px gaps);
 *   - two hues fall below 3:1 contrast on white, so every value is printed as
 *     text and nothing is conveyed by colour alone.
 * Each chart also exposes a screen-reader table, so the data is readable with
 * no colour at all.
 */

export interface Slice {
  label: string;
  value: number;
  /** A CSS colour, normally one of the --chart-* tokens. */
  color: string;
}

function Tooltip({ text, x }: { text: string; x: "left" | "right" }) {
  return (
    <span
      role="tooltip"
      className={`pointer-events-none absolute -top-1 z-10 -translate-y-full whitespace-nowrap rounded-lg bg-[var(--navy)] px-2.5 py-1.5 text-[11px] font-semibold text-white shadow-lg ${
        x === "left" ? "left-0" : "right-0"
      }`}
    >
      {text}
    </span>
  );
}

function DataTable({ rows, unit }: { rows: Slice[]; unit: string }) {
  return (
    <table className="sr-only">
      <caption>{unit}</caption>
      <thead>
        <tr>
          <th scope="col">Category</th>
          <th scope="col">Count</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.label}>
            <th scope="row">{r.label}</th>
            <td>{r.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * Part-to-whole across a handful of states, with the total as the headline.
 * Kept to four segments: a ring stops being readable past about six.
 */
export function DonutChart({
  slices,
  total,
  totalLabel,
  size = 184,
  thickness = 22,
}: {
  slices: Slice[];
  total: number;
  totalLabel: string;
  size?: number;
  thickness?: number;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const titleId = useId();

  const sum = slices.reduce((acc, s) => acc + s.value, 0);
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  // A 2px breathing gap between segments, so adjacent fills never touch.
  const gap = sum > 0 ? 2 : 0;

  // Prefix sums rather than a running counter: each segment's start is
  // derived from the ones before it, so nothing is mutated during render.
  const visible = slices.filter((s) => s.value > 0);
  const drawn = visible.map((s, i) => {
    const fraction = sum > 0 ? s.value / sum : 0;
    const offset = visible
      .slice(0, i)
      .reduce((acc, prev) => acc + (prev.value / sum) * circumference, 0);
    return {
      ...s,
      fraction,
      offset,
      length: Math.max(fraction * circumference - gap, 0),
    };
  });

  if (sum === 0) {
    return (
      <p className="py-8 text-center text-sm text-[var(--muted)]">
        Nothing tracked yet.
      </p>
    );
  }

  return (
    <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-center sm:gap-7">
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          role="img"
          aria-labelledby={titleId}
          className="-rotate-90"
        >
          <title id={titleId}>{`${totalLabel}: ${total} in total`}</title>
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="var(--chart-track)"
            strokeWidth={thickness}
          />
          {drawn.map((s) => (
            <circle
              key={s.label}
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke={s.color}
              strokeWidth={hovered === s.label ? thickness + 5 : thickness}
              strokeDasharray={`${s.length} ${circumference - s.length}`}
              strokeDashoffset={-s.offset}
              strokeLinecap="butt"
              className="cursor-default transition-[stroke-width] duration-150"
              onMouseEnter={() => setHovered(s.label)}
              onMouseLeave={() => setHovered(null)}
            />
          ))}
        </svg>
        {/* The headline number lives in the hole: the ring shows the split,
            this answers "how many altogether" without reading the legend. */}
        <div className="pointer-events-none absolute inset-0 grid place-items-center text-center">
          <div>
            <p className="text-[32px] font-bold leading-none tracking-tight tabular-nums">
              {total}
            </p>
            <p className="mt-1 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
              {totalLabel}
            </p>
          </div>
        </div>
      </div>

      {/* Legend doubles as the direct-label layer: every slice shows its own
          count and share, so neither hue nor contrast has to carry meaning. */}
      <ul className="w-full min-w-0 space-y-1.5">
        {slices.map((s) => {
          const pct = sum > 0 ? Math.round((s.value / sum) * 100) : 0;
          return (
            <li
              key={s.label}
              onMouseEnter={() => setHovered(s.label)}
              onMouseLeave={() => setHovered(null)}
              className={`flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition ${
                hovered === s.label ? "bg-[var(--surface-2)]" : ""
              }`}
            >
              <span
                aria-hidden
                className="h-2.5 w-2.5 shrink-0 rounded-full"
                style={{ background: s.color }}
              />
              <span className="min-w-0 flex-1 truncate text-sm text-[var(--muted-strong)]">
                {s.label}
              </span>
              <span className="shrink-0 text-sm font-bold tabular-nums">{s.value}</span>
              <span className="w-9 shrink-0 text-right text-xs tabular-nums text-[var(--muted)]">
                {pct}%
              </span>
            </li>
          );
        })}
      </ul>
      <DataTable rows={slices} unit={totalLabel} />
    </div>
  );
}

export interface BarRow {
  label: string;
  /** Completed out of total. */
  value: number;
  total: number;
  /** Shown as a red count beside the bar when above zero. */
  overdue?: number;
  href?: string;
}

/**
 * Magnitude comparison across projects. One hue, not a categorical set: every
 * bar measures the same thing, so a different colour per project would imply a
 * distinction that is not there.
 */
export function ProgressBars({ rows }: { rows: BarRow[] }) {
  const [hovered, setHovered] = useState<string | null>(null);

  if (rows.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-[var(--muted)]">
        No projects with commitments yet.
      </p>
    );
  }

  return (
    <ul className="space-y-3.5">
      {rows.map((r) => {
        const pct = r.total > 0 ? Math.round((r.value / r.total) * 100) : 0;
        const isHot = hovered === r.label;
        return (
          <li
            key={r.label}
            className="relative"
            onMouseEnter={() => setHovered(r.label)}
            onMouseLeave={() => setHovered(null)}
          >
            {isHot && (
              <Tooltip
                x="right"
                text={`${r.value} of ${r.total} done${
                  r.overdue ? ` · ${r.overdue} overdue` : ""
                }`}
              />
            )}
            <div className="mb-1.5 flex items-baseline justify-between gap-3">
              <span className="min-w-0 truncate text-sm font-medium">{r.label}</span>
              <span className="flex shrink-0 items-baseline gap-2 text-xs tabular-nums">
                {r.overdue ? (
                  <span className="font-semibold" style={{ color: "var(--chart-overdue)" }}>
                    {r.overdue} overdue
                  </span>
                ) : null}
                <span className="text-[var(--muted)]">
                  {r.value}/{r.total}
                </span>
                <span className="w-9 text-right font-bold">{pct}%</span>
              </span>
            </div>
            {/* 4px rounded ends, anchored to the track's start. */}
            <div
              className="h-2 w-full overflow-hidden rounded"
              style={{ background: "var(--chart-track)" }}
            >
              <div
                className="h-full rounded transition-[width,filter] duration-300"
                style={{
                  width: `${pct}%`,
                  background: "var(--chart-pending)",
                  filter: isHot ? "brightness(1.12)" : undefined,
                }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Commitments made versus closed over recent weeks. A trend is the one thing
 * the numbers alone cannot show: whether the backlog is growing.
 */
export function TrendBars({
  buckets,
}: {
  buckets: { label: string; made: number; closed: number }[];
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const peak = Math.max(1, ...buckets.map((b) => Math.max(b.made, b.closed)));

  if (buckets.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-[var(--muted)]">
        Not enough history yet.
      </p>
    );
  }

  return (
    <div>
      <div className="flex items-end justify-between gap-1.5" style={{ height: 150 }}>
        {buckets.map((b, i) => (
          <div
            key={b.label}
            className="relative flex h-full min-w-0 flex-1 flex-col justify-end"
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(null)}
          >
            {hovered === i && (
              <Tooltip
                x={i > buckets.length / 2 ? "right" : "left"}
                text={`${b.label}: ${b.made} made, ${b.closed} closed`}
              />
            )}
            {/* Two thin bars with a 2px gap, never stacked: made and closed
                are different measures, not parts of one total. */}
            <div className="flex h-full items-end justify-center gap-[2px]">
              <div
                className="w-full max-w-[14px] rounded-t transition-all duration-300"
                style={{
                  height: `${(b.made / peak) * 100}%`,
                  minHeight: b.made > 0 ? 3 : 0,
                  background: "var(--chart-pending)",
                  opacity: hovered === null || hovered === i ? 1 : 0.45,
                }}
              />
              <div
                className="w-full max-w-[14px] rounded-t transition-all duration-300"
                style={{
                  height: `${(b.closed / peak) * 100}%`,
                  minHeight: b.closed > 0 ? 3 : 0,
                  background: "var(--chart-completed)",
                  opacity: hovered === null || hovered === i ? 1 : 0.45,
                }}
              />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2 flex justify-between gap-1.5 border-t border-[var(--border)] pt-2">
        {buckets.map((b) => (
          <span
            key={b.label}
            className="min-w-0 flex-1 truncate text-center text-[10px] font-medium text-[var(--muted)]"
          >
            {b.label}
          </span>
        ))}
      </div>
      <div className="mt-3 flex items-center justify-center gap-4 text-xs">
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="h-2.5 w-2.5 rounded-full"
            style={{ background: "var(--chart-pending)" }}
          />
          <span className="text-[var(--muted-strong)]">Made</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span
            aria-hidden
            className="h-2.5 w-2.5 rounded-full"
            style={{ background: "var(--chart-completed)" }}
          />
          <span className="text-[var(--muted-strong)]">Closed</span>
        </span>
      </div>
    </div>
  );
}
