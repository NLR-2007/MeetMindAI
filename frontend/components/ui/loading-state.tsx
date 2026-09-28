"use client";

import { useEffect, useState } from "react";

const chevron = Array.from({ length: 9 }, (_, index) => {
  const row = Math.floor(index / 3);
  const column = index % 3;
  return (column + Math.abs(row - 1)) * 90;
});

const ORBIT_ORDER = [0, 1, 2, 5, 8, 7, 6, 3];
const orbit = Array.from({ length: 9 }, (_, index) => {
  const order = ORBIT_ORDER.indexOf(index);
  return order === -1 ? null : order * 110;
});

const PATTERNS = {
  Drive: { delays: chevron, duration: 650, round: false },
  Dots: { delays: chevron, duration: 650, round: true },
  Orbit: { delays: orbit, duration: 950, round: false },
} as const;

export type LoadingStateVariant = keyof typeof PATTERNS;

function useElapsed() {
  const [deciseconds, setDeciseconds] = useState(0);

  useEffect(() => {
    const timer = window.setInterval(
      () => setDeciseconds((current) => current + 1),
      100,
    );
    return () => window.clearInterval(timer);
  }, []);

  const total = deciseconds / 10;
  if (total < 60) return `${total.toFixed(1)}s`;
  return `${Math.floor(total / 60)}m ${(total % 60).toFixed(1)}s`;
}

export default function LoadingState({
  label = "Thinking",
  variant = "Dots",
}: {
  label?: string;
  variant?: LoadingStateVariant;
}) {
  const elapsed = useElapsed();
  const { delays, duration, round } = PATTERNS[variant];

  return (
    <div
      className="flex w-fit items-center gap-2.5"
      role="status"
      aria-live="polite"
      aria-label={`${label}, ${elapsed} elapsed`}
    >
      <span aria-hidden="true" className="grid grid-cols-[repeat(3,4px)] gap-[1.5px]">
        {delays.map((delay, index) => (
          <span
            key={index}
            className={`size-[4px] bg-foreground ${round ? "rounded-full" : "rounded-[1px]"}`}
            style={{
              opacity: delay === null ? 0.07 : 0.15,
              animation:
                delay === null
                  ? "none"
                  : `pixel-on ${duration}ms ease-in-out ${delay}ms infinite`,
            }}
          />
        ))}
      </span>
      <span
        aria-hidden="true"
        className="bg-clip-text text-[13px] font-medium text-transparent"
        style={{
          backgroundImage:
            "linear-gradient(90deg, var(--muted) 35%, var(--foreground) 50%, var(--muted) 65%)",
          backgroundSize: "200% 100%",
          animation: "shimmer-text 1.4s linear infinite",
        }}
      >
        {label}
      </span>
      <span aria-hidden="true" className="font-mono text-[12px] text-muted tabular-nums">
        {elapsed}
      </span>
    </div>
  );
}
