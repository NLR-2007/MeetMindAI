"use client";

import { useMemo, useState } from "react";

export type CalendarEventKind = "meeting" | "deadline" | "scheduled" | "event";

export interface CalendarItem {
  id: string;
  date: string; // ISO date or datetime
  title: string;
  kind: CalendarEventKind;
  detail?: string | null;
  href?: string | null;
  /** Deadline already pushed to Google, or a bot already scheduled. */
  confirmed?: boolean;
}

const KIND_STYLE: Record<CalendarEventKind, { color: string; label: string }> = {
  meeting: { color: "var(--c-chat)", label: "Meeting" },
  deadline: { color: "var(--c-promises)", label: "Deadline" },
  scheduled: { color: "var(--c-markup)", label: "Bot scheduled" },
  event: { color: "var(--c-calendar)", label: "Calendar event" },
};

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function ymd(d: Date): string {
  // Local date key, so an event never lands on the wrong day through UTC drift.
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate(),
  ).padStart(2, "0")}`;
}

function startOfGrid(year: number, month: number): Date {
  const first = new Date(year, month, 1);
  // Monday-first: JS getDay() is 0=Sunday.
  const offset = (first.getDay() + 6) % 7;
  return new Date(year, month, 1 - offset);
}

/**
 * Month view of everything happening: past meetings, extracted deadlines,
 * scheduled bots and synced calendar events.
 *
 * Deliberately dependency-free — a date library would be more than this needs.
 */
export function MonthCalendar({
  items,
  onRefresh,
  busy,
}: {
  items: CalendarItem[];
  onRefresh?: () => void;
  busy?: boolean;
}) {
  const today = new Date();
  const [cursor, setCursor] = useState(
    () => new Date(today.getFullYear(), today.getMonth(), 1),
  );
  const [selected, setSelected] = useState<string>(ymd(today));

  const byDay = useMemo(() => {
    const map = new Map<string, CalendarItem[]>();
    for (const item of items) {
      const d = new Date(item.date);
      if (Number.isNaN(d.getTime())) continue;
      const key = ymd(d);
      const list = map.get(key);
      if (list) list.push(item);
      else map.set(key, [item]);
    }
    return map;
  }, [items]);

  const grid = useMemo(() => {
    const start = startOfGrid(cursor.getFullYear(), cursor.getMonth());
    return Array.from({ length: 42 }, (_, i) => {
      const d = new Date(start);
      d.setDate(start.getDate() + i);
      return d;
    });
  }, [cursor]);

  const monthLabel = cursor.toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
  const todayKey = ymd(today);
  const selectedItems = byDay.get(selected) ?? [];

  return (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-sm)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-3.5">
        <div className="flex items-center gap-2">
          <button
            onClick={() =>
              setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))
            }
            aria-label="Previous month"
            className="grid h-8 w-8 place-items-center rounded-lg border border-[var(--border)] text-sm transition hover:bg-[var(--surface-2)]"
          >
            ‹
          </button>
          <button
            onClick={() =>
              setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))
            }
            aria-label="Next month"
            className="grid h-8 w-8 place-items-center rounded-lg border border-[var(--border)] text-sm transition hover:bg-[var(--surface-2)]"
          >
            ›
          </button>
          <h2 className="ml-1 text-base font-semibold tracking-tight">{monthLabel}</h2>
        </div>

        <div className="flex items-center gap-3">
          <div className="hidden flex-wrap gap-3 sm:flex">
            {Object.entries(KIND_STYLE).map(([kind, s]) => (
              <span
                key={kind}
                className="flex items-center gap-1.5 text-[11px] text-[var(--muted-strong)]"
              >
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ background: s.color }}
                />
                {s.label}
              </span>
            ))}
          </div>
          <button
            onClick={() => {
              setCursor(new Date(today.getFullYear(), today.getMonth(), 1));
              setSelected(todayKey);
            }}
            className="rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[11px] font-semibold transition hover:bg-[var(--surface-2)]"
          >
            Today
          </button>
          {onRefresh && (
            <button
              onClick={onRefresh}
              disabled={busy}
              className="rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[11px] font-semibold transition hover:bg-[var(--surface-2)] disabled:opacity-50"
            >
              {busy ? "Refreshing…" : "Refresh"}
            </button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-7 border-b border-[var(--border)] px-2 pt-2 text-center">
        {WEEKDAYS.map((d) => (
          <div
            key={d}
            className="pb-2 text-[11px] font-semibold uppercase tracking-wide text-[var(--muted-strong)]"
          >
            {d}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-7 gap-px bg-[var(--border)] p-px">
        {grid.map((day) => {
          const key = ymd(day);
          const inMonth = day.getMonth() === cursor.getMonth();
          const dayItems = byDay.get(key) ?? [];
          const isToday = key === todayKey;
          const isSelected = key === selected;

          return (
            <button
              key={key}
              onClick={() => setSelected(key)}
              className={`min-h-[86px] bg-[var(--surface)] p-1.5 text-left align-top transition hover:bg-[var(--surface-2)] ${
                inMonth ? "" : "opacity-45"
              } ${isSelected ? "ring-2 ring-inset ring-[var(--accent)]" : ""}`}
            >
              <span
                className={`mb-1 inline-grid h-6 w-6 place-items-center rounded-full text-[11px] font-semibold ${
                  isToday
                    ? "bg-[var(--accent)] text-[var(--accent-fg)]"
                    : "text-[var(--foreground)]"
                }`}
              >
                {day.getDate()}
              </span>

              <span className="block space-y-0.5">
                {dayItems.slice(0, 3).map((item) => (
                  <span
                    key={item.id}
                    title={item.title}
                    className="flex items-center gap-1 truncate rounded px-1 py-0.5 text-[10px] font-medium"
                    style={{
                      background: `color-mix(in oklab, ${KIND_STYLE[item.kind].color} 14%, transparent)`,
                      color: KIND_STYLE[item.kind].color,
                    }}
                  >
                    <span
                      className="h-1.5 w-1.5 shrink-0 rounded-full"
                      style={{ background: KIND_STYLE[item.kind].color }}
                    />
                    <span className="truncate">{item.title}</span>
                  </span>
                ))}
                {dayItems.length > 3 && (
                  <span className="block px-1 text-[10px] text-[var(--muted-strong)]">
                    +{dayItems.length - 3} more
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>

      <div className="border-t border-[var(--border)] px-5 py-4">
        <h3 className="mb-2 text-sm font-semibold">
          {new Date(`${selected}T00:00:00`).toLocaleDateString(undefined, {
            weekday: "long",
            day: "numeric",
            month: "long",
          })}
        </h3>
        {selectedItems.length === 0 ? (
          <p className="text-sm text-[var(--muted-strong)]">Nothing on this day.</p>
        ) : (
          <ul className="space-y-2">
            {selectedItems.map((item) => {
              const style = KIND_STYLE[item.kind];
              const body = (
                <>
                  <span
                    className="mt-1.5 h-2 w-2 shrink-0 rounded-full"
                    style={{ background: style.color }}
                  />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{item.title}</span>
                    <span className="block text-xs text-[var(--muted-strong)]">
                      {style.label}
                      {item.detail ? ` · ${item.detail}` : ""}
                      {item.confirmed ? " · on Google Calendar" : ""}
                    </span>
                  </span>
                </>
              );
              return (
                <li key={item.id}>
                  {item.href ? (
                    <a
                      href={item.href}
                      className="flex gap-2 rounded-lg border border-[var(--border)] px-3 py-2 transition hover:bg-[var(--surface-2)]"
                    >
                      {body}
                    </a>
                  ) : (
                    <div className="flex gap-2 rounded-lg border border-[var(--border)] px-3 py-2">
                      {body}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
