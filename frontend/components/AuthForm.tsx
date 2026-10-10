"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ApiError, authApi, setToken } from "@/lib/api";
import { googleSignInAvailable, signInWithGoogle } from "@/lib/firebase";
import { ErrorBanner, Spinner } from "./ui";

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

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const register = mode === "register";

  async function withGoogle() {
    setBusy(true);
    setError(null);
    try {
      const idToken = await signInWithGoogle();
      // The manager is only needed when the account does not exist yet; the
      // API ignores it for anyone already registered.
      const res = await authApi.google(idToken);
      setToken(res.access_token);
      router.replace("/dashboard");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Could not sign in with Google.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = register
        ? await authApi.register(email.trim(), password, name.trim())
        : await authApi.login(email.trim(), password);
      setToken(res.access_token);
      router.replace("/dashboard");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : register
            ? "Could not create your account."
            : "Sign-in failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  const field =
    "w-full rounded-xl border border-[var(--border)] bg-white px-3.5 py-3 text-sm shadow-sm outline-none transition placeholder:text-[#a2a8b8] hover:border-[#ccd0dc] focus:border-[var(--accent)] focus:ring-4 focus:ring-[var(--accent)]/10";

  return (
    <main className="relative min-h-screen overflow-hidden bg-[#f9f9fd]">
      <div className="landing-grid pointer-events-none absolute inset-0 opacity-70" />
      <div className="pointer-events-none absolute -left-40 -top-40 h-[30rem] w-[30rem] rounded-full bg-[var(--accent-soft)] blur-3xl" />
      <div className="pointer-events-none absolute -bottom-48 right-[-8rem] h-[32rem] w-[32rem] rounded-full bg-[var(--coral-soft)] blur-3xl" />

      <div className="relative mx-auto grid min-h-screen max-w-7xl lg:grid-cols-[0.92fr_1.08fr]">
        <section className="hidden flex-col justify-between p-10 lg:flex xl:p-14">
          <Link href="/" aria-label="MeetMind home">
            <Brand />
          </Link>

          <div className="max-w-lg">
            <span className="eyebrow-pill">Built for follow-through</span>
            <h1 className="mt-7 font-[family-name:var(--font-display)] text-5xl font-semibold leading-[1.04] tracking-[-0.055em] text-[var(--navy)] xl:text-6xl">
              Turn every conversation into momentum.
            </h1>
            <p className="mt-6 max-w-md text-base leading-7 text-[var(--muted)]">
              One calm workspace for meeting notes, decisions, promises, and the
              work that happens next.
            </p>
            <div className="mt-10 grid max-w-md grid-cols-3 gap-3">
              {[
                ["Live", "transcripts"],
                ["Clear", "ownership"],
                ["Visible", "progress"],
              ].map(([top, bottom], index) => (
                <div key={top} className="rounded-2xl border border-white/80 bg-white/65 p-4 shadow-[var(--shadow-sm)] backdrop-blur">
                  <div className={`mb-4 h-1.5 w-8 rounded-full ${index === 1 ? "bg-[var(--coral)]" : index === 2 ? "bg-[var(--c-progress)]" : "bg-[var(--accent)]"}`} />
                  <p className="text-sm font-bold text-[var(--foreground)]">{top}</p>
                  <p className="mt-0.5 text-xs text-[var(--muted)]">{bottom}</p>
                </div>
              ))}
            </div>
          </div>

          <p className="text-xs text-[var(--muted)]">Private by design · Built for modern teams</p>
        </section>

        <section className="flex min-h-screen items-center justify-center px-5 py-8 sm:px-8 lg:py-12">
          <div className="w-full max-w-[500px]">
            <div className="mb-8 flex items-center justify-between lg:hidden">
              <Link href="/" aria-label="MeetMind home"><Brand /></Link>
              <Link href="/" className="text-xs font-semibold text-[var(--muted)] hover:text-[var(--accent)]">Back home</Link>
            </div>

            <div className="rounded-[1.75rem] border border-white bg-white/90 p-5 shadow-[0_28px_90px_-36px_rgb(35_40_70/.34)] backdrop-blur sm:p-8 lg:p-10">
              <span className="inline-flex rounded-full bg-[var(--accent-soft)] px-3 py-1.5 text-[10px] font-bold uppercase tracking-[0.13em] text-[var(--accent)]">
                {register ? "Create workspace" : "Welcome back"}
              </span>
              <h1 className="mt-4 font-[family-name:var(--font-display)] text-3xl font-semibold tracking-[-0.045em] text-[var(--navy)] sm:text-4xl">
                {register ? "Start remembering better." : "Good to see you again."}
              </h1>
              <p className="mb-7 mt-3 text-sm leading-6 text-[var(--muted)]">
                {register
                  ? "Set up your account and let MeetMind handle the meeting details."
                  : "Sign in to see your meetings, commitments, and team progress."}
              </p>

              <form onSubmit={submit} className="space-y-4">
                {register && (
                  <>
                    <div>
                      <label htmlFor="full-name" className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">Full name</label>
                      <input id="full-name" required value={name} onChange={(e) => setName(e.target.value)} placeholder="Bunny Reddy" autoComplete="name" className={field} />
                    </div>

                  </>
                )}

                <div>
                  <label htmlFor="email" className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">Work email</label>
                  <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" autoComplete="email" className={field} />
                </div>

                <div>
                  <div className="mb-1.5 flex items-center justify-between gap-3">
                    <label htmlFor="password" className="block text-xs font-bold text-[var(--muted-strong)]">Password</label>
                    <span className="text-[10px] text-[var(--muted)]">8 characters minimum</span>
                  </div>
                  <div className="relative">
                    <input id="password" type={showPassword ? "text" : "password"} required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Enter your password" autoComplete={register ? "new-password" : "current-password"} className={`${field} pr-16`} />
                    <button type="button" onClick={() => setShowPassword((value) => !value)} className="absolute inset-y-0 right-0 px-4 text-[11px] font-bold text-[var(--accent)]" aria-label={showPassword ? "Hide password" : "Show password"}>
                      {showPassword ? "Hide" : "Show"}
                    </button>
                  </div>
                </div>

                {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

                <button
                  type="submit"
                  disabled={
                    busy ||
                    !email ||
                    password.length < 8 ||
                    (register && !name.trim())
                  }
                  className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-3.5 text-sm font-bold text-white shadow-[0_16px_32px_-16px_rgb(99_91_255/.8)] transition hover:-translate-y-0.5 hover:bg-[var(--accent-hover)] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:translate-y-0"
                >
                  {busy && <Spinner />}
                  {busy ? "Please wait…" : register ? "Create my account" : "Sign in to MeetMind"}
                </button>
              </form>

              {googleSignInAvailable && (
                <>
                  <div className="my-5 flex items-center gap-3">
                    <span className="h-px flex-1 bg-[var(--border)]" />
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--muted)]">
                      or
                    </span>
                    <span className="h-px flex-1 bg-[var(--border)]" />
                  </div>
                  {/* Outside the form on purpose: this is not a submit, and
                      pressing Enter in the password field must not trigger it. */}
                  <button
                    type="button"
                    onClick={withGoogle}
                    disabled={
                      busy
                    }
                    className="inline-flex w-full items-center justify-center gap-2.5 rounded-xl border border-[var(--border)] bg-white px-4 py-3 text-sm font-semibold text-[var(--foreground)] transition hover:bg-[var(--surface-2)] disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    <svg aria-hidden viewBox="0 0 18 18" className="h-4 w-4">
                      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62Z" />
                      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.32-1.58-5.03-3.7H.96v2.33A9 9 0 0 0 9 18Z" />
                      <path fill="#FBBC05" d="M3.97 10.72a5.4 5.4 0 0 1 0-3.44V4.95H.96a9 9 0 0 0 0 8.1l3.01-2.33Z" />
                      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.9 11.43 0 9 0A9 9 0 0 0 .96 4.95l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58Z" />
                    </svg>
                    Continue with Google
                  </button>
                </>
              )}

              <p className="mt-6 text-center text-xs text-[var(--muted)]">
                {register ? "Already have an account? " : "New to MeetMind? "}
                <Link href={register ? "/login" : "/register"} className="font-bold text-[var(--accent)] hover:underline">
                  {register ? "Sign in" : "Create an account"}
                </Link>
              </p>
            </div>

            {register && (
              <p className="mx-auto mt-5 max-w-sm text-center text-[10px] leading-5 text-[var(--muted)]">
                By creating an account, you agree to use recording features only with participant consent.
              </p>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
