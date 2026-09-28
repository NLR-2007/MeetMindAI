"use client";

import { motion } from "motion/react";

export type AvatarColor =
  | "blue" | "orange" | "red" | "green" | "purple" | "yellow"
  | "cyan" | "pink" | "indigo" | "lime" | "turquoise" | "violet";
export type AvatarSize = "sm" | "md" | "lg";
export type AvatarShape = "circle" | "square" | "squircle";

export interface AvatarProps {
  blinking?: boolean;
  color?: AvatarColor;
  size?: AvatarSize;
  shape?: AvatarShape;
  className?: string;
}

const COLORS: Record<AvatarColor, [string, string, string]> = {
  blue: ["#0d4d9a", "#6fb3ff", "#d4ecff"],
  orange: ["#a63e10", "#ffb46a", "#ffd9b8"],
  red: ["#a60033", "#ff8aaa", "#ffcde4"],
  green: ["#0d6632", "#6dd187", "#c5f5d8"],
  purple: ["#4a0080", "#c896ff", "#e0c9ff"],
  yellow: ["#8a5500", "#ffc93a", "#fff0a8"],
  cyan: ["#003d66", "#5dd4ff", "#d0f0ff"],
  pink: ["#7a0055", "#ff6bb3", "#ffd6ed"],
  indigo: ["#2d157a", "#8b7eff", "#e0d9ff"],
  lime: ["#4a5910", "#bef264", "#f7fee8"],
  turquoise: ["#1a5555", "#2dd4bf", "#c0fdf5"],
  violet: ["#4a2a7a", "#d8b4fe", "#ede9fe"],
};

const SIZE = {
  sm: { orb: "h-8 w-8", eye: "h-1.5 w-1", gap: "gap-1.5" },
  md: { orb: "h-12 w-12", eye: "h-2.5 w-1.5", gap: "gap-2.5" },
  lg: { orb: "h-16 w-16", eye: "h-3 w-2", gap: "gap-3.5" },
};

const SHAPE = {
  circle: "rounded-full",
  square: "rounded-none",
  squircle: "rounded-[40%]",
};

export default function Avatar({
  blinking = true,
  color = "indigo",
  size = "md",
  shape = "circle",
  className = "",
}: AvatarProps) {
  const [deep, bright, iris] = COLORS[color];
  const dimensions = SIZE[size];

  return (
    <motion.div
      aria-label="MeetMind AI"
      role="img"
      whileTap={{ scaleX: 1.12, scaleY: 1.18 }}
      transition={{ type: "spring", stiffness: 260, damping: 18 }}
      className={`relative flex shrink-0 items-center justify-center overflow-hidden ${dimensions.orb} ${SHAPE[shape]} ${className}`}
      style={{
        background: `radial-gradient(circle at 50% 45%, ${deep} 0%, ${bright} 67%, ${iris} 100%)`,
        boxShadow: `0 0 4px ${bright}55, 0 0 20px ${bright}38, inset 0 0 0 1px rgba(255,255,255,.18)`,
      }}
    >
      <span className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_30%_22%,rgba(255,255,255,.8),rgba(255,255,255,.08)_48%,transparent_68%)]" />
      <span className={`relative z-10 flex -translate-y-0.5 items-center ${dimensions.gap}`}>
        {[0, 1].map((eye) => (
          <span
            key={eye}
            className={`${dimensions.eye} rounded-full bg-gradient-to-br from-white to-indigo-100`}
            style={blinking ? { animation: `avatar-blink 3.6s ease-in-out ${eye * 60}ms infinite` } : undefined}
          />
        ))}
      </span>
    </motion.div>
  );
}
