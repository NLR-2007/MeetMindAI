import Link from "next/link";

export const metadata = {
  title: "Meetings that move work forward",
  description:
    "MeetMind captures decisions, commitments, and deadlines so your team always knows what happens next.",
};

const FEATURES = [
  {
    number: "01",
    title: "Every decision, captured",
    body: "A clean transcript and focused summary give your team one reliable source of truth.",
    color: "var(--accent)",
  },
  {
    number: "02",
    title: "Promises stay visible",
    body: "Owners and due dates are tracked across meetings, even when plans change.",
    color: "var(--coral)",
  },
  {
    number: "03",
    title: "Progress, without chasing",
    body: "See what is on track, overdue, or unassigned before it becomes a blocker.",
    color: "var(--c-progress)",
  },
];

function Brand() {
  return (
    <span className="inline-flex items-center gap-2.5">
      <span className="brand-mark">MM</span>
      <span className="text-[15px] font-bold tracking-[-0.03em] text-[var(--navy)]">
        MeetMind <span className="text-[var(--accent)]">AI</span>
      </span>
    </span>
  );
}

export default function LandingPage() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-[#fbfbfe]">
      <div className="landing-grid pointer-events-none absolute inset-x-0 top-0 h-[760px]" />
      <div className="hero-orb pointer-events-none absolute -right-36 top-20 h-96 w-96 rounded-full bg-[var(--coral-soft)] opacity-80" />
      <div className="hero-orb pointer-events-none absolute -left-36 top-64 h-[28rem] w-[28rem] rounded-full bg-[var(--accent-soft)] opacity-80 [animation-delay:120ms]" />

      <nav className="relative z-10 mx-auto flex max-w-7xl items-center justify-between px-5 py-5 sm:px-8 lg:px-10">
        <Link href="/" aria-label="MeetMind home">
          <Brand />
        </Link>
        <div className="flex items-center gap-2 sm:gap-3">
          <Link
            href="/login"
            className="rounded-xl px-3 py-2 text-sm font-semibold text-[var(--muted-strong)] transition hover:bg-white hover:text-[var(--foreground)] sm:px-4"
          >
            Sign in
          </Link>
          <Link
            href="/register"
            className="rounded-xl bg-[var(--navy)] px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-slate-900/10 transition hover:-translate-y-0.5 hover:bg-[var(--accent)] sm:px-5"
          >
            Get started
          </Link>
        </div>
      </nav>

      <section className="relative z-[1] mx-auto grid max-w-7xl items-center gap-14 px-5 pb-20 pt-16 sm:px-8 sm:pt-24 lg:grid-cols-[1.04fr_.96fr] lg:px-10 lg:pb-28 lg:pt-28">
        <div className="mx-auto max-w-2xl text-center lg:mx-0 lg:text-left">
          <span className="eyebrow-pill">Your meeting memory</span>
          <h1 className="mt-7 font-[family-name:var(--font-display)] text-[clamp(3rem,7vw,6.2rem)] font-semibold leading-[0.96] tracking-[-0.065em] text-[var(--navy)]">
            Meetings end.
            <span className="mt-2 block text-[var(--accent)]">Momentum stays.</span>
          </h1>
          <p className="mx-auto mt-7 max-w-xl text-base leading-7 text-[var(--muted)] sm:text-lg sm:leading-8 lg:mx-0">
            MeetMind turns conversations into clear decisions, owned action items,
            and deadlines your team can actually follow.
          </p>
          <div className="mt-9 flex flex-col justify-center gap-3 sm:flex-row lg:justify-start">
            <Link
              href="/register"
              className="rounded-xl bg-[var(--accent)] px-6 py-3.5 text-center text-sm font-bold text-white shadow-[0_16px_34px_-15px_rgb(99_91_255/.75)] transition hover:-translate-y-0.5 hover:bg-[var(--accent-hover)]"
            >
              Start for free
            </Link>
            <a
              href="#how-it-works"
              className="rounded-xl border border-[var(--border)] bg-white/75 px-6 py-3.5 text-center text-sm font-bold text-[var(--foreground)] shadow-[var(--shadow-sm)] backdrop-blur transition hover:border-[var(--accent)]/30 hover:bg-white"
            >
              See how it works
            </a>
          </div>
          <p className="mt-4 text-xs font-medium text-[var(--muted)]">
            Works with Google Meet, Microsoft Teams, and Zoom.
          </p>
        </div>

        <div className="relative mx-auto w-full max-w-xl">
          <div className="absolute -inset-5 rounded-[2rem] bg-gradient-to-br from-[var(--accent)]/12 to-[var(--coral)]/12 blur-2xl" />
          <div className="relative overflow-hidden rounded-[1.75rem] border border-white bg-white p-3 shadow-[0_32px_90px_-35px_rgb(32_36_67/.35)] sm:p-4">
            <div className="rounded-[1.25rem] bg-[var(--navy)] p-5 text-white sm:p-7">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-white/45">Live meeting</p>
                  <p className="mt-1 font-[family-name:var(--font-display)] text-lg font-semibold">Product launch sync</p>
                </div>
                <span className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1.5 text-xs font-semibold text-white/90">
                  <span className="recording-dot h-2 w-2 rounded-full bg-[var(--coral)]" /> Recording
                </span>
              </div>
              <div className="mt-8 space-y-5">
                <div className="flex gap-3">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[var(--accent)] text-[10px] font-bold">AR</span>
                  <div>
                    <p className="text-xs font-semibold text-white/50">Ava · 10:24</p>
                    <p className="mt-1 text-sm leading-6 text-white/85">Let&apos;s move the beta launch to October 18 and share the checklist by Friday.</p>
                  </div>
                </div>
                <div className="flex gap-3">
                  <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[#268d7a] text-[10px] font-bold">JM</span>
                  <div>
                    <p className="text-xs font-semibold text-white/50">Jon · 10:25</p>
                    <p className="mt-1 text-sm leading-6 text-white/85">I&apos;ll own the final QA pass and report back in our Monday stand-up.</p>
                  </div>
                </div>
              </div>
            </div>

            <div className="grid gap-3 p-2 pt-5 sm:grid-cols-2">
              <div className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-4">
                <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--muted)]">Decision</p>
                <p className="mt-2 text-sm font-semibold">Beta launch · Oct 18</p>
                <span className="mt-3 inline-flex rounded-full bg-[var(--accent-soft)] px-2 py-1 text-[10px] font-bold text-[var(--accent)]">Captured</span>
              </div>
              <div className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-4">
                <p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--muted)]">Action item</p>
                <p className="mt-2 text-sm font-semibold">Final QA pass</p>
                <p className="mt-3 text-[11px] font-medium text-[var(--muted)]">Jon · due Monday</p>
              </div>
            </div>
          </div>
          <div className="absolute -bottom-6 -left-5 hidden rounded-2xl border border-[var(--border)] bg-white px-4 py-3 shadow-xl sm:block">
            <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--muted)]">Follow-through</p>
            <p className="mt-1 text-sm font-bold text-[var(--success)]">92% on track</p>
          </div>
        </div>
      </section>

      <section id="how-it-works" className="relative z-[1] border-y border-[var(--border)] bg-white/80 px-5 py-20 backdrop-blur sm:px-8 lg:px-10 lg:py-28">
        <div className="mx-auto max-w-7xl">
          <div className="max-w-2xl">
            <span className="eyebrow-pill">From talk to traction</span>
            <h2 className="mt-6 font-[family-name:var(--font-display)] text-3xl font-semibold tracking-[-0.045em] text-[var(--navy)] sm:text-5xl">
              Everything your meeting should leave behind.
            </h2>
          </div>
          <div className="mt-12 grid gap-4 md:grid-cols-3">
            {FEATURES.map((feature) => (
              <article key={feature.number} className="rounded-2xl border border-[var(--border)] bg-white p-6 shadow-[var(--shadow-sm)] transition hover:-translate-y-1 hover:shadow-[var(--shadow-md)] sm:p-7">
                <span className="font-mono text-xs font-bold" style={{ color: feature.color }}>{feature.number}</span>
                <div className="mt-7 h-1 w-10 rounded-full" style={{ background: feature.color }} />
                <h3 className="mt-5 font-[family-name:var(--font-display)] text-xl font-bold tracking-[-0.03em]">{feature.title}</h3>
                <p className="mt-3 text-sm leading-6 text-[var(--muted)]">{feature.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="px-5 py-20 sm:px-8 lg:px-10 lg:py-28">
        <div className="relative mx-auto max-w-7xl overflow-hidden rounded-[2rem] bg-[var(--navy)] px-6 py-12 text-center text-white sm:px-12 sm:py-16">
          <div className="absolute -right-16 -top-20 h-64 w-64 rounded-full bg-[var(--accent)]/25 blur-3xl" />
          <div className="absolute -bottom-24 -left-16 h-64 w-64 rounded-full bg-[var(--coral)]/20 blur-3xl" />
          <div className="relative">
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-white/45">Make every word count</p>
            <h2 className="mx-auto mt-4 max-w-2xl font-[family-name:var(--font-display)] text-3xl font-semibold tracking-[-0.04em] sm:text-5xl">Your next meeting already has a follow-up plan.</h2>
            <Link href="/register" className="mt-8 inline-flex rounded-xl bg-white px-6 py-3.5 text-sm font-bold text-[var(--navy)] transition hover:-translate-y-0.5 hover:bg-[var(--coral-soft)]">Create your workspace</Link>
          </div>
        </div>
      </section>

      <footer className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 border-t border-[var(--border)] px-5 py-8 text-center sm:flex-row sm:px-8 sm:text-left lg:px-10">
        <Brand />
        <p className="text-xs text-[var(--muted)]">Meeting intelligence that keeps teams moving.</p>
      </footer>
    </main>
  );
}
