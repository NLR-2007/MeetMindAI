"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useAuth } from "./AuthGate";

interface NavItem {
  href: string;
  label: string;
  hint: string;
  tile: string;
  icon: string;
}

const NAV: NavItem[] = [
  { href: "/dashboard", label: "Home", hint: "Meetings", tile: "var(--accent)", icon: "HM" },
  { href: "/markup", label: "Mark Up", hint: "Prepare", tile: "var(--c-markup)", icon: "MU" },
  { href: "/promises", label: "My Promises", hint: "Commitments", tile: "var(--c-promises)", icon: "MP" },
  { href: "/progress", label: "My Progress", hint: "Overview", tile: "var(--c-progress)", icon: "PG" },
  { href: "/calendar", label: "Calendar", hint: "Schedule", tile: "var(--c-calendar)", icon: "CL" },
];

// Shown only to managers; employees have no team to look at.
const MANAGER_NAV: NavItem[] = [
  { href: "/team", label: "About My Team", hint: "Team overview", tile: "var(--coral)", icon: "MT" },
];

function Brand() {
  return (
    <span className="inline-flex min-w-0 items-center gap-2.5">
      <span className="brand-mark shrink-0">MM</span>
      <span className="truncate text-[15px] font-bold tracking-[-0.03em] text-[var(--navy)]">
        MeetMind <span className="text-[var(--accent)]">AI</span>
      </span>
    </span>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const { user, signOut } = useAuth();
  const visibleNav =
    user?.role === "manager" ? [...NAV, ...MANAGER_NAV] : NAV;
  const [open, setOpen] = useState(false);

  const isActive = (href: string) =>
    pathname === href || pathname.startsWith(`${href}/`);

  const navigation = (
    <nav aria-label="Main navigation" className="flex flex-col gap-1.5">
      {visibleNav.map((item) => {
        const active = isActive(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={() => setOpen(false)}
            aria-current={active ? "page" : undefined}
            style={{ ["--tile" as string]: item.tile }}
            className={`group flex items-center gap-3 rounded-xl px-3 py-2.5 transition ${
              active
                ? "bg-[color-mix(in_oklab,var(--tile)_12%,white)] font-semibold shadow-sm"
                : "text-[var(--foreground)] hover:bg-[var(--surface-2)]"
            }`}
          >
            <span
              aria-hidden="true"
              className="grid h-8 w-8 shrink-0 place-items-center rounded-lg font-mono text-[9px] font-bold tracking-tight"
              style={{
                color: item.tile,
                background: "color-mix(in oklab, var(--tile) 13%, white)",
              }}
            >
              {item.icon}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px]">{item.label}</span>
              <span className="mt-0.5 block truncate text-[11px] font-medium text-[var(--muted-strong)]">{item.href === "/dashboard" && user?.role === "manager" ? "Team overview" : item.hint}</span>
            </span>
            {active && <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full" style={{ background: item.tile }} />}
          </Link>
        );
      })}
    </nav>
  );

  const account = (
    <div className="rounded-2xl border border-[var(--border)] bg-[var(--background)] p-3">
      <div className="flex items-center gap-2.5">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[var(--accent-soft)] text-xs font-bold uppercase text-[var(--accent)]">
          {(user?.name ?? user?.email ?? "M").slice(0, 1)}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-bold text-[var(--foreground)]">{user?.name ?? user?.email}</p>
          <p className="mt-0.5 truncate text-[11px] font-medium capitalize text-[var(--muted-strong)]">
            {user?.role === "manager" ? "Manager · Team view" : "Team member"}
          </p>
        </div>
      </div>
      <button onClick={signOut} className="mt-3 w-full rounded-lg border border-[var(--border)] bg-white px-3 py-2 text-[12px] font-semibold text-[var(--foreground)] transition hover:border-[#ccd0dc] hover:bg-[var(--surface-2)]">
        Sign out
      </button>
    </div>
  );

  return (
    <>
      {/* Mobile bar. Sticky rather than fixed, and the menu panel sits in
          normal flow beneath it, so no hard-coded header height is needed. */}
      <div className="sticky top-0 z-40 lg:hidden">
        <header className="flex items-center justify-between gap-3 border-b border-[var(--border)] bg-white/92 px-[max(1rem,env(safe-area-inset-left))] py-3 pr-[max(1rem,env(safe-area-inset-right))] backdrop-blur-xl">
          <Link
            href="/dashboard"
            aria-label="MeetMind dashboard"
            className="min-w-0 shrink"
          >
            <Brand />
          </Link>
          <button
            onClick={() => setOpen((value) => !value)}
            aria-label={open ? "Close navigation" : "Open navigation"}
            aria-expanded={open}
            aria-controls="mobile-nav"
            className="inline-flex h-10 shrink-0 items-center gap-2 rounded-xl border border-[var(--border)] bg-white px-3.5 text-xs font-bold text-[var(--muted-strong)] shadow-sm transition active:scale-95"
          >
            <span aria-hidden className="flex flex-col gap-[3px]">
              <span className="block h-[2px] w-4 rounded bg-current" />
              <span className="block h-[2px] w-4 rounded bg-current" />
              <span className="block h-[2px] w-4 rounded bg-current" />
            </span>
            {open ? "Close" : "Menu"}
          </button>
        </header>

        {open && (
          <div
            id="mobile-nav"
            className="max-h-[70vh] overflow-y-auto border-b border-[var(--border)] bg-white px-[max(1rem,env(safe-area-inset-left))] py-4 pr-[max(1rem,env(safe-area-inset-right))] shadow-2xl"
          >
            {navigation}
            <div className="mt-4">{account}</div>
          </div>
        )}
      </div>

      {/* Tap-away backdrop, below the bar so it never covers the controls. */}
      {open && (
        <button
          type="button"
          aria-hidden
          tabIndex={-1}
          onClick={() => setOpen(false)}
          className="fixed inset-0 z-30 cursor-default bg-[var(--navy)]/20 backdrop-blur-sm lg:hidden"
        />
      )}

      <aside className="fixed inset-y-0 left-0 z-30 hidden h-dvh w-[252px] flex-col overflow-hidden border-r border-[var(--border)] bg-white/92 px-4 py-6 backdrop-blur-xl lg:flex">
        <Link href="/dashboard" className="mb-8 px-1" aria-label="MeetMind dashboard"><Brand /></Link>
        <p className="mb-2 px-3 text-[10px] font-bold uppercase tracking-[0.16em] text-[var(--muted-strong)]">Workspace</p>
        {navigation}
        <div className="mt-auto pt-5">{account}</div>
      </aside>
    </>
  );
}
