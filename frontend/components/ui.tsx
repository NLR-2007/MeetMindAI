"use client";

import { statusLabel, type MeetingStatus } from "@/lib/api";

export function StatusBadge({ status }: { status: MeetingStatus }) {
  const { label, tone } = statusLabel(status);

  const tones: Record<string, string> = {
    idle: "bg-zinc-500/10 text-zinc-500 border-zinc-500/20",
    active: "bg-amber-500/10 text-amber-600 border-amber-500/25 dark:text-amber-400",
    recording: "bg-red-500/10 text-red-600 border-red-500/25 dark:text-red-400",
    done: "bg-emerald-500/10 text-emerald-600 border-emerald-500/25 dark:text-emerald-400",
    error: "bg-red-500/10 text-red-600 border-red-500/25 dark:text-red-400",
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${tones[tone]}`}
    >
      {tone === "recording" && (
        <span className="recording-dot h-1.5 w-1.5 rounded-full bg-current" />
      )}
      {label}
    </span>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`animate-spin ${className}`}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="3"
        className="opacity-25"
      />
      <path
        d="M22 12a10 10 0 0 1-10 10"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function ErrorBanner({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-300"
    >
      <span>{message}</span>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="shrink-0 font-medium underline underline-offset-2"
        >
          Dismiss
        </button>
      )}
    </div>
  );
}

export function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-[var(--shadow-sm)] ${className}`}
    >
      {children}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-5 py-12 text-center">
      <p className="text-sm font-medium text-[var(--foreground)]">{title}</p>
      {hint && <p className="mt-1 text-sm text-[var(--muted)]">{hint}</p>}
    </div>
  );
}
