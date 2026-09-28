"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { BriefcaseBusiness, Lightbulb, MessageSquareText, Plus, Sparkles, Target, Upload, UserRound } from "lucide-react";
import {
  ApiError,
  api,
  type CoachNote,
  type Meeting,
  type PrepPlan,
  type ProjectSummary,
  coachApi,
  markupApi,
  projectApi,
} from "@/lib/api";
import { Card, ErrorBanner, Spinner } from "@/components/ui";
import { ChatText } from "@/components/ChatText";
import Avatar from "@/components/ui/components-primitives-avatar";
import LoadingState from "@/components/ui/loading-state";

type Step = "choose" | "existing" | "new" | "plan";

const PERSONAS = [
  { value: "client", label: "Client", hint: "Pushes on scope, cost and delivery dates" },
  { value: "manager", label: "Manager", hint: "Probes progress, risks and your commitments" },
  { value: "teammate", label: "Teammate", hint: "Digs into detail and technical trade-offs" },
] as const;

export default function MarkUpPage() {
  const [step, setStep] = useState<Step>("choose");
  // Mark Up covers the whole arc: prepare beforehand, review afterwards.
  const [mode, setMode] = useState<"prepare" | "review">("prepare");
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [plans, setPlans] = useState<PrepPlan[]>([]);
  const [plan, setPlan] = useState<PrepPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // existing-project form
  const [projectId, setProjectId] = useState("");
  const [title, setTitle] = useState("");
  const [projectName, setProjectName] = useState("");
  const [fileName, setFileName] = useState("");
  const [fileText, setFileText] = useState("");

  // new-project intake
  const [intake, setIntake] = useState({
    purpose: "",
    project_description: "",
    participants: "",
    agenda: "",
    my_responsibilities: "",
    desired_outcomes: "",
  });

  useEffect(() => {
    projectApi.list().then(setProjects).catch(() => setProjects([]));
    markupApi.plans().then(setPlans).catch(() => setPlans([]));
  }, []);

  async function generateExisting() {
    setBusy(true);
    setError(null);
    try {
      const p = await markupApi.prepareExisting(projectId || null, title.trim());
      setPlan(p);
      setStep("plan");
      setPlans(await markupApi.plans());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not build the briefing.");
    } finally {
      setBusy(false);
    }
  }

  async function generateNew() {
    setBusy(true);
    setError(null);
    try {
      const uploaded = fileText ? `\n\nUploaded project brief (${fileName}):\n${fileText}` : "";
      let project = projects.find((candidate) => candidate.id === projectId);
      if (!project) {
        project = await projectApi.create(
          projectName.trim(),
          `${intake.project_description.trim()}${uploaded}`,
        );
        setProjectId(project.id);
        setProjects((current) => [...current, project!].sort((a, b) => a.name.localeCompare(b.name)));
      }
      const p = await markupApi.prepareNew({
        ...intake,
        purpose: intake.purpose.trim() || `${project.name} kickoff`,
        project_description: `${intake.project_description.trim()}${uploaded}`,
        project_id: project.id,
      });
      setPlan(p);
      setStep("plan");
      setPlans(await markupApi.plans());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not build the plan.");
    } finally {
      setBusy(false);
    }
  }

  async function readBrief(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 500_000) {
      setError("Please upload a text brief smaller than 500 KB.");
      event.target.value = "";
      return;
    }
    try {
      setFileName(file.name);
      setFileText((await file.text()).slice(0, 100_000));
    } catch {
      setError("Could not read that file. Please use TXT, Markdown, CSV, or JSON.");
    }
  }

  return (
    <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6 sm:py-10">
      <Link href="/dashboard" className="text-sm text-[var(--accent)] hover:underline">
        ← Dashboard
      </Link>

      <header className="mt-5 mb-7 flex items-start gap-4">
        <Avatar color="purple" size="md" shape="squircle" />
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-2xl font-semibold tracking-tight">Prepare for Your Next Meeting</h1>
            <span className="rounded-full bg-[var(--accent-soft)] px-2 py-1 text-[10px] font-bold text-[var(--accent)]">Mark Up</span>
          </div>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-[var(--muted)]">
            Build a personalized briefing from project details, past decisions, commitments, and the outcome you want.
          </p>
        </div>
      </header>

      <div
        role="tablist"
        aria-label="Mark Up sections"
        className="mb-6 inline-flex gap-1 rounded-xl border border-[var(--border)] bg-white p-1"
      >
        {([
          ["prepare", "Prepare", "Before the meeting"],
          ["review", "Review", "After the meeting"],
        ] as const).map(([value, label, hint]) => (
          <button
            key={value}
            role="tab"
            aria-selected={mode === value}
            onClick={() => setMode(value)}
            className={`rounded-lg px-4 py-2 text-left transition ${
              mode === value
                ? "bg-[var(--accent)] text-white"
                : "hover:bg-[var(--surface-2)]"
            }`}
          >
            <span className="block text-sm font-bold">{label}</span>
            <span
              className={`block text-[11px] ${
                mode === value ? "text-white/75" : "text-[var(--muted-strong)]"
              }`}
            >
              {hint}
            </span>
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-5">
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </div>
      )}

      {mode === "review" && <ReviewTab />}

      {mode === "prepare" && step === "choose" && (
        <>
          <Card className="p-5 sm:p-6">
            <div className="mb-5">
              <h2 className="text-base font-bold">Choose your project context</h2>
              <p className="mt-1 text-sm text-[var(--muted)]">Start fresh or use MeetMind&apos;s memory from an existing project.</p>
            </div>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <button
                onClick={() => {
                  setProjectId("");
                  setStep("new");
                }}
                className="group rounded-2xl border border-[var(--border)] bg-white p-5 text-left transition hover:-translate-y-0.5 hover:border-[var(--accent)]/40 hover:shadow-[var(--shadow-md)]"
              >
                <span className="grid h-10 w-10 place-items-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]"><Plus className="h-4 w-4" /></span>
                <p className="mt-4 font-bold">New project</p>
                <p className="mt-1 text-sm leading-6 text-[var(--muted)]">Add the project brief, your role, attendees, agenda, and expected outcome.</p>
              </button>
              <button
                onClick={() => setStep("existing")}
                className="group rounded-2xl border border-[var(--border)] bg-white p-5 text-left transition hover:-translate-y-0.5 hover:border-[var(--accent)]/40 hover:shadow-[var(--shadow-md)]"
              >
                <span className="grid h-10 w-10 place-items-center rounded-xl bg-[var(--success-soft)] text-[var(--success)]"><BriefcaseBusiness className="h-4 w-4" /></span>
                <p className="mt-4 font-bold">Continue an existing project</p>
                <p className="mt-1 text-sm leading-6 text-[var(--muted)]">Use earlier meetings, decisions, risks, and unresolved commitments.</p>
              </button>
            </div>
          </Card>

          {plans.length > 0 && (
            <Card className="mt-6">
              <h2 className="border-b border-[var(--border)] px-5 py-3 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
                Earlier preparations
              </h2>
              <ul className="divide-y divide-[var(--border)]">
                {plans.map((p) => (
                  <li key={p.id}>
                    <button
                      onClick={() => {
                        setPlan(p);
                        setStep("plan");
                      }}
                      className="w-full px-5 py-3 text-left hover:bg-[var(--background)]"
                    >
                      <p className="text-sm font-medium">{p.title || "Untitled"}</p>
                      <p className="text-xs text-[var(--muted)]">
                        {p.mode} · {new Date(p.created_at).toLocaleString()}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}

      {mode === "prepare" && step === "existing" && (
        <Card className="space-y-4 p-5 sm:p-6">
          <div>
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-[var(--success-soft)] text-[var(--success)]"><BriefcaseBusiness className="h-4 w-4" /></span>
            <h2 className="mt-4 text-lg font-bold">Continue an existing project</h2>
            <p className="mt-1 text-sm text-[var(--muted)]">MeetMind will review past meetings and bring forward decisions, risks, and unfinished commitments.</p>
          </div>
          <select
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className="w-full rounded-xl border border-[var(--border)] bg-white px-3.5 py-3 text-sm outline-none focus:border-[var(--accent)]"
          >
            <option value="">Select a project</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="What is the upcoming meeting about?"
            className="w-full rounded-xl border border-[var(--border)] bg-white px-3.5 py-3 text-sm outline-none focus:border-[var(--accent)] focus:ring-4 focus:ring-[var(--accent)]/10"
          />
          <div className="flex gap-2">
            <button
              onClick={generateExisting}
              disabled={busy || !projectId || !title.trim()}
              className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-5 py-3 text-sm font-bold text-white shadow-[0_14px_28px_-16px_rgb(99_91_255/.8)] disabled:opacity-40"
            >
              {busy ? <><Spinner /> Preparing…</> : <><Sparkles className="h-4 w-4" /> Prepare for this meeting</>}
            </button>
            <button
              onClick={() => setStep("choose")}
              className="rounded-xl border border-[var(--border)] px-4 py-3 text-sm font-semibold"
            >
              Back
            </button>
          </div>
        </Card>
      )}

      {mode === "prepare" && step === "new" && (
        <Card className="p-5 sm:p-6">
          <div className="mb-5">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]"><Plus className="h-4 w-4" /></span>
            <h2 className="mt-4 text-lg font-bold">Start a new project</h2>
            <p className="mt-1 text-sm text-[var(--muted)]">These details become the project&apos;s first preparation plan and will be available for future meetings.</p>
          </div>
          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">Project name *</label>
              <input value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="Project Alpha" className="w-full rounded-xl border border-[var(--border)] bg-white px-3.5 py-3 text-sm outline-none focus:border-[var(--accent)] focus:ring-4 focus:ring-[var(--accent)]/10" />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">What is this meeting for? *</label>
              <input value={intake.purpose} onChange={(event) => setIntake({ ...intake, purpose: event.target.value })} placeholder="Kickoff, scope review, client discovery…" className="w-full rounded-xl border border-[var(--border)] bg-white px-3.5 py-3 text-sm outline-none focus:border-[var(--accent)] focus:ring-4 focus:ring-[var(--accent)]/10" />
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">Project details *</label>
              <textarea value={intake.project_description} onChange={(event) => setIntake({ ...intake, project_description: event.target.value })} rows={5} placeholder="Explain the project, current stage, business need, constraints, and relevant background…" className="w-full resize-y rounded-xl border border-[var(--border)] bg-white px-3.5 py-3 text-sm outline-none focus:border-[var(--accent)] focus:ring-4 focus:ring-[var(--accent)]/10" />
            </div>
            <label className="flex cursor-pointer items-center gap-3 rounded-xl border border-dashed border-[var(--accent)]/35 bg-[var(--accent-soft)]/45 p-3.5 transition hover:bg-[var(--accent-soft)]">
              <span className="grid h-9 w-9 place-items-center rounded-xl bg-white text-[var(--accent)]"><Upload className="h-4 w-4" /></span>
              <span className="min-w-0 flex-1"><span className="block truncate text-xs font-bold">{fileName || "Upload supporting project details"}</span><span className="mt-0.5 block text-[10px] text-[var(--muted)]">TXT, Markdown, CSV, or JSON · up to 500 KB</span></span>
              <input type="file" accept=".txt,.md,.markdown,.csv,.json,text/plain,text/markdown,text/csv,application/json" onChange={readBrief} className="hidden" />
            </label>
            <div>
              <label className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">Your role and responsibilities *</label>
              <textarea value={intake.my_responsibilities} onChange={(event) => setIntake({ ...intake, my_responsibilities: event.target.value })} rows={3} placeholder="What are you expected to contribute, decide, explain, or own?" className="w-full resize-y rounded-xl border border-[var(--border)] bg-white px-3.5 py-3 text-sm outline-none focus:border-[var(--accent)] focus:ring-4 focus:ring-[var(--accent)]/10" />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div><label className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">Who will attend?</label><input value={intake.participants} onChange={(event) => setIntake({ ...intake, participants: event.target.value })} placeholder="Client, manager, engineering lead" className="w-full rounded-xl border border-[var(--border)] bg-white px-3.5 py-3 text-sm outline-none focus:border-[var(--accent)]" /></div>
              <div><label className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">Expected outcome</label><input value={intake.desired_outcomes} onChange={(event) => setIntake({ ...intake, desired_outcomes: event.target.value })} placeholder="Approve scope and next steps" className="w-full rounded-xl border border-[var(--border)] bg-white px-3.5 py-3 text-sm outline-none focus:border-[var(--accent)]" /></div>
            </div>
            <div><label className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">Agenda or likely topics</label><textarea value={intake.agenda} onChange={(event) => setIntake({ ...intake, agenda: event.target.value })} rows={3} placeholder="Introductions, requirements, scope, timeline, risks…" className="w-full resize-y rounded-xl border border-[var(--border)] bg-white px-3.5 py-3 text-sm outline-none focus:border-[var(--accent)]" /></div>
          </div>
          <div className="mt-5 flex flex-wrap gap-2">
            <button
              onClick={generateNew}
              disabled={busy || !projectName.trim() || !intake.purpose.trim() || !intake.project_description.trim() || !intake.my_responsibilities.trim()}
              className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-5 py-3 text-sm font-bold text-white shadow-[0_14px_28px_-16px_rgb(99_91_255/.8)] disabled:opacity-40"
            >
              {busy ? <><Spinner /> Preparing…</> : <><Sparkles className="h-4 w-4" /> Prepare for this meeting</>}
            </button>
            <button
              onClick={() => setStep("choose")}
              className="rounded-xl border border-[var(--border)] px-4 py-3 text-sm font-semibold"
            >
              Back
            </button>
          </div>
        </Card>
      )}

      {mode === "prepare" && step === "plan" && plan && (
        <PlanView plan={plan} onBack={() => setStep("choose")} />
      )}
    </main>
  );
}

function PlanView({ plan, onBack }: { plan: PrepPlan; onBack: () => void }) {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [persona, setPersona] = useState("client");
  const [turns, setTurns] = useState<{ role: string; content: string }[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{
    feedback: string;
    strengths: string[];
    improvements: string[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [liveMeetingId, setLiveMeetingId] = useState(plan.meeting_id ?? "");
  const [liveEnabled, setLiveEnabled] = useState(false);
  // Normally Live Assist answers questions others ask you. Practice mode also
  // answers your own, so one person can rehearse or demo it alone.
  const [answerOwn, setAnswerOwn] = useState(false);
  const [liveQuestion, setLiveQuestion] = useState("");
  const [liveAnswer, setLiveAnswer] = useState("");
  const [liveBusy, setLiveBusy] = useState(false);

  useEffect(() => {
    api.listMeetings()
      .then((rows) => {
        setMeetings(rows);
        setLiveMeetingId((current) => current || rows[0]?.id || "");
      })
      .catch(() => setMeetings([]));
  }, []);

  useEffect(() => {
    if (!liveEnabled) return;
    let cancelled = false;
    let polling = false;
    async function poll() {
      if (polling) return;
      polling = true;
      try {
        const status = await markupApi.liveAssistStatus(plan.id);
        if (cancelled) return;
        if (!status.enabled) {
          setLiveEnabled(false);
          return;
        }
        setLiveQuestion(status.question ?? "");
        if (status.answer) setLiveAnswer(status.answer);
        else if (status.state === "listening") setLiveAnswer("");
        setLiveBusy(status.state === "waiting");
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Live Assist lost connection.");
      } finally {
        polling = false;
      }
    }
    void poll();
    const timer = window.setInterval(poll, 1000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [liveEnabled, plan.id]);

  const activePersona =
    PERSONAS.find((o) => o.value === persona) ?? PERSONAS[0];

  // Changing who the AI plays changes the whole conversation, so the
  // rehearsal restarts rather than swapping character mid-thread.
  async function switchPersona(next: string) {
    setPersona(next);
    setSessionId(null);
    setTurns([]);
    setFeedback(null);
  }

  async function startPractice() {
    setBusy(true);
    setError(null);
    try {
      const res = await markupApi.startPractice(plan.id, persona);
      setSessionId(res.session_id);
      setTurns([{ role: "assistant", content: res.opening }]);
      setFeedback(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start practice.");
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    if (!sessionId || !input.trim()) return;
    const mine = input.trim();
    setInput("");
    setTurns((t) => [...t, { role: "user", content: mine }]);
    setBusy(true);
    try {
      const res = await markupApi.practiceReply(sessionId, mine);
      setTurns((t) => [...t, { role: "assistant", content: res.reply }]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Practice failed.");
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    if (!sessionId) return;
    setBusy(true);
    try {
      setFeedback(await markupApi.finishPractice(sessionId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not get feedback.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleLiveAssist() {
    if (!liveMeetingId && !liveEnabled) return;
    setLiveBusy(true);
    setError(null);
    try {
      const next = !liveEnabled;
      await markupApi.configureLiveAssist(plan.id, liveMeetingId || null, next, answerOwn);
      setLiveEnabled(next);
      if (!next) {
        setLiveQuestion("");
        setLiveAnswer("");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update Live Assist.");
    } finally {
      setLiveBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Avatar color="purple" size="sm" shape="squircle" />
          <div><p className="text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--muted)]">Your personalized preparation</p><h2 className="text-lg font-bold">{plan.title || "Preparation"}</h2></div>
        </div>
        <button onClick={onBack} className="text-sm font-bold text-[var(--accent)] hover:underline">
          New preparation
        </button>
      </div>

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}

      {plan.briefing && (
        <Card className="overflow-hidden">
          <div className="bg-[var(--navy)] p-5 text-white sm:p-6">
            <h3 className="mb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-white/45">60-second briefing</h3>
            <div className="text-sm leading-6 text-white/75"><ChatText content={plan.briefing} /></div>
          </div>
        </Card>
      )}

      {(plan.role_guidance || plan.opening_script) && (
        <div className="grid gap-4 md:grid-cols-2">
          {plan.role_guidance && <PlanCard icon={UserRound} title="Your role in the room"><p className="text-sm leading-6 text-[var(--muted-strong)]">{plan.role_guidance}</p></PlanCard>}
          {plan.opening_script && <PlanCard icon={MessageSquareText} title="A strong way to open"><blockquote className="rounded-xl border-l-4 border-[var(--coral)] bg-[var(--coral-soft)] px-4 py-3 text-sm leading-6">“{plan.opening_script}”</blockquote></PlanCard>}
        </div>
      )}

      {!!plan.speaking_strategy?.length && <PlanCard icon={Target} title="How to speak and contribute"><PlanList items={plan.speaking_strategy} color="var(--accent)" /></PlanCard>}

      {!!plan.past_improvements?.length && <PlanCard icon={Sparkles} title="Improve from earlier meetings" badge={`${plan.past_coaching_count ?? 0} private coaching notes considered`}><PlanList items={plan.past_improvements} color="var(--coral)" /></PlanCard>}

      <Card className="overflow-hidden border-[var(--accent)]/20">
        <div className="border-b border-[var(--border)] bg-[var(--accent-soft)]/55 p-5">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-white text-[var(--accent)] shadow-sm"><Lightbulb className="h-4 w-4" /></span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-bold">Private Live Assist</h3><span className="rounded-full bg-[var(--success-soft)] px-2 py-0.5 text-[9px] font-bold text-[var(--success)]">Only you see answers</span></div>
              <p className="mt-1 text-xs leading-5 text-[var(--muted)]">Listens through the meeting notetaker. After a question and two seconds of silence, a suggested answer appears here. The bot never speaks.</p>
            </div>
          </div>
        </div>
        <div className="p-5">
          <div className="flex flex-col gap-2 sm:flex-row">
            <select
              value={liveMeetingId}
              onChange={(event) => setLiveMeetingId(event.target.value)}
              disabled={liveEnabled}
              aria-label="Meeting for private live assistance"
              className="min-w-0 flex-1 rounded-xl border border-[var(--border)] bg-white px-3.5 py-3 text-sm outline-none focus:border-[var(--accent)]"
            >
              {meetings.length === 0 && <option value="">No meeting bot available</option>}
              {meetings.map((meeting) => <option key={meeting.id} value={meeting.id}>{meeting.title || meeting.meeting_url}</option>)}
            </select>
            <button onClick={toggleLiveAssist} disabled={liveBusy || (!liveEnabled && !liveMeetingId)} className={`rounded-xl px-5 py-3 text-sm font-bold transition disabled:opacity-40 ${liveEnabled ? "border border-[var(--danger)]/25 bg-[var(--danger-soft)] text-[var(--danger)]" : "bg-[var(--accent)] text-white"}`}>{liveEnabled ? "Stop listening" : "Start listening"}</button>
          </div>

          <label className="mt-3 flex cursor-pointer items-start gap-2.5 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2.5">
            <input
              type="checkbox"
              checked={answerOwn}
              disabled={liveEnabled}
              onChange={(event) => setAnswerOwn(event.target.checked)}
              className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--accent)]"
            />
            <span>
              <span className="block text-xs font-bold">
                Also answer my own questions (practice)
              </span>
              <span className="block text-[11px] leading-4 text-[var(--muted-strong)]">
                Off by default, Live Assist only replies to questions other
                people ask you. Turn this on to test it on your own.
              </span>
            </span>
          </label>
          {liveEnabled && (
            <div className="mt-4 flex items-center gap-2 rounded-xl border border-[var(--success)]/20 bg-[var(--success-soft)] px-3 py-2 text-xs font-semibold text-[var(--success)]">
              <span className="recording-dot h-2 w-2 rounded-full bg-[var(--success)]" /> Listening privately for questions
            </div>
          )}
          {liveBusy && liveEnabled && <div className="mt-4"><LoadingState label="Waiting two seconds" variant="Dots" /></div>}
          {liveQuestion && (
            <div className="mt-4 rounded-xl bg-[var(--surface-2)] px-4 py-3">
              <p className="mb-1 text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--muted)]">Question detected</p>
              <p className="text-sm leading-6 text-[var(--muted-strong)]">{liveQuestion}</p>
            </div>
          )}
          {liveAnswer && (
            <div className="mt-4 rounded-xl border border-[var(--success)]/20 bg-[var(--success-soft)] p-4">
              <p className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--success)]">You can say</p>
              <div className="text-sm leading-6 text-[var(--foreground)]"><ChatText content={liveAnswer} /></div>
            </div>
          )}
          <p className="mt-3 text-[10px] leading-4 text-[var(--muted)]">Keep this page open during the meeting. Suggestions are never sent to the call. If context is insufficient, the coach gives a safe clarifying response instead of guessing.</p>
        </div>
      </Card>

      {plan.talking_points.length > 0 && (
        <Card className="p-5">
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            Personalized talking points
          </h3>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {plan.talking_points.map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </Card>
      )}

      {plan.questions_to_ask.length > 0 && (
        <Card className="p-5">
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            Important questions to ask
          </h3>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {plan.questions_to_ask.map((q, i) => (
              <li key={i}>{q}</li>
            ))}
          </ul>
        </Card>
      )}

      {plan.open_commitments.length > 0 && (
        <Card className="p-5">
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            Previous commitments to address
          </h3>
          <ul className="space-y-2 text-sm">
            {plan.open_commitments.map((c, i) => (
              <li key={i} className="rounded-lg border border-[var(--border)] px-3 py-2">
                <p>{c.title}</p>
                <p className="text-xs text-[var(--muted)]">{c.detail}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {plan.risks.length > 0 && (
        <Card className="p-5">
          <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-[var(--muted)]">
            Potential risks
          </h3>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {plan.risks.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </Card>
      )}

      <Card className="overflow-hidden">
        <div className="border-b border-[var(--border)] bg-[var(--accent-soft)]/45 p-5">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-white text-[var(--accent)] shadow-sm"><MessageSquareText className="h-4 w-4" /></span>
            <div><h3 className="text-sm font-bold">AI practice session</h3><p className="mt-1 text-xs leading-5 text-[var(--muted)]">Rehearse with an AI client, manager, or teammate, then receive specific feedback on your answers.</p></div>
          </div>
        </div>
        <div className="p-5">

        {!sessionId ? (
          <div>
            <p className="mb-2 text-[10px] font-bold uppercase tracking-[0.14em] text-[var(--muted-strong)]">
              Who should the AI act as?
            </p>
            <div className="mb-4 grid gap-2 sm:grid-cols-3">
              {PERSONAS.map((option) => {
                const active = persona === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setPersona(option.value)}
                    aria-pressed={active}
                    className={`rounded-xl border p-3 text-left transition ${
                      active
                        ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                        : "border-[var(--border)] bg-white hover:bg-[var(--surface-2)]"
                    }`}
                  >
                    <span className="block text-sm font-bold">{option.label}</span>
                    <span className="mt-0.5 block text-[11px] leading-4 text-[var(--muted-strong)]">
                      {option.hint}
                    </span>
                  </button>
                );
              })}
            </div>
            <button
              onClick={startPractice}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2.5 text-sm font-bold text-white disabled:opacity-40"
            >
              {busy ? <><Spinner /> Starting…</> : <><Sparkles className="h-4 w-4" /> Start AI practice</>}
            </button>
          </div>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2">
              <span className="flex items-center gap-2 text-xs">
                <span
                  aria-hidden
                  className="grid h-6 w-6 place-items-center rounded-lg bg-[var(--accent)] text-[10px] font-bold text-white"
                >
                  {activePersona.label.slice(0, 2).toUpperCase()}
                </span>
                <span>
                  <span className="font-bold">AI is acting as your {activePersona.label.toLowerCase()}</span>
                  <span className="ml-1.5 text-[var(--muted-strong)]">{activePersona.hint}</span>
                </span>
              </span>
              <span className="flex items-center gap-1.5">
                {PERSONAS.filter((o) => o.value !== persona).map((o) => (
                  <button
                    key={o.value}
                    type="button"
                    onClick={() => switchPersona(o.value)}
                    disabled={busy}
                    title={`Restart the rehearsal with a ${o.label.toLowerCase()}`}
                    className="rounded-lg border border-[var(--border)] bg-white px-2.5 py-1 text-[11px] font-semibold transition hover:bg-[var(--surface-2)] disabled:opacity-40"
                  >
                    Switch to {o.label.toLowerCase()}
                  </button>
                ))}
              </span>
            </div>

            <div className="mb-3 max-h-80 space-y-2 overflow-y-auto">
              {turns.map((t, i) => (
                <div
                  key={i}
                  className={`max-w-[85%] rounded-2xl px-3.5 py-2 text-sm ${
                    t.role === "user"
                      ? "ml-auto bg-[var(--accent)] text-[var(--accent-fg)]"
                      : "bg-[var(--background)]"
                  }`}
                >
                  {t.content}
                </div>
              ))}
              {busy && <LoadingState label="Preparing feedback" variant="Dots" />}
            </div>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                send();
              }}
              className="flex gap-2"
            >
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={busy}
                placeholder="Your answer…"
                className="min-w-0 flex-1 rounded-lg border border-[var(--border)] bg-[var(--background)] px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"
              />
              <button
                type="submit"
                disabled={busy || !input.trim()}
                className="rounded-lg bg-[var(--accent)] px-3.5 py-2 text-sm font-semibold text-[var(--accent-fg)] disabled:opacity-40"
              >
                Send
              </button>
              <button
                type="button"
                onClick={finish}
                disabled={busy || turns.length < 2}
                className="rounded-lg border border-[var(--border)] px-3 py-2 text-sm disabled:opacity-40"
              >
                Finish
              </button>
            </form>
          </>
        )}

        {feedback && (
          <div className="mt-4 space-y-3 rounded-lg border border-[var(--border)] bg-[var(--background)] p-4">
            <ChatText content={feedback.feedback} />
            {feedback.strengths.length > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase text-emerald-600 dark:text-emerald-400">
                  Strengths
                </p>
                <ul className="list-disc pl-5 text-sm">
                  {feedback.strengths.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
            {feedback.improvements.length > 0 && (
              <div>
                <p className="text-xs font-semibold uppercase text-amber-600 dark:text-amber-400">
                  Improve
                </p>
                <ul className="list-disc pl-5 text-sm">
                  {feedback.improvements.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
        </div>
      </Card>
    </div>
  );
}

function PlanCard({ icon: Icon, title, badge, children }: { icon: typeof Target; title: string; badge?: string; children: React.ReactNode }) {
  return (
    <Card className="p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 className="flex items-center gap-2 text-sm font-bold"><span className="grid h-8 w-8 place-items-center rounded-lg bg-[var(--accent-soft)] text-[var(--accent)]"><Icon className="h-3.5 w-3.5" /></span>{title}</h3>
        {badge && <span className="rounded-full bg-[var(--coral-soft)] px-2.5 py-1 text-[9px] font-bold text-[var(--coral)]">{badge}</span>}
      </div>
      {children}
    </Card>
  );
}

function PlanList({ items, color }: { items: string[]; color: string }) {
  return (
    <ul className="space-y-2">
      {items.map((item, index) => <li key={`${item}-${index}`} className="flex gap-2.5 text-sm leading-6 text-[var(--muted-strong)]"><span className="mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color }} />{item}</li>)}
    </ul>
  );
}

const CATEGORY_LABEL: Record<string, string> = {
  missed_point: "Missed talking point",
  unanswered_question: "Unanswered question",
  unclear_commitment: "Unclear commitment",
  repetition: "Repeated yourself",
  clarity: "Clarity",
  general: "General",
};

/**
 * The other half of Mark Up: after a meeting, compare what you planned with
 * what you actually said. Kept in the same page so preparing and reviewing
 * are one workflow rather than two destinations.
 */
function ReviewTab() {
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [selected, setSelected] = useState("");
  const [notes, setNotes] = useState<CoachNote[] | null>(null);
  const [themes, setThemes] = useState<[string, number][]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadNotes = useCallback(async () => {
    try {
      const data = await coachApi.notes();
      setNotes(data.notes);
      setThemes(data.recurring_themes);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load reviews.");
      setNotes([]);
    }
  }, []);

  useEffect(() => {
    loadNotes();
    api
      .listMeetings()
      .then((rows) => {
        const ready = rows.filter((m) => m.has_transcript);
        setMeetings(ready);
        if (ready.length) setSelected((prev) => prev || ready[0].id);
      })
      .catch(() => setMeetings([]));
  }, [loadNotes]);

  async function review() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await coachApi.review(selected);
      setNotice(
        res.count === 0
          ? "Nothing to flag — no evidence-backed suggestions for this meeting."
          : `${res.count} suggestion(s)${res.had_plan ? ", compared against your Mark Up plan" : " (no plan found, reviewed the transcript alone)"}.`,
      );
      await loadNotes();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Review failed.");
    } finally {
      setBusy(false);
    }
  }

  async function toggleReject(note: CoachNote) {
    try {
      await coachApi.reject(note.id, !note.rejected);
      await loadNotes();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update.");
    }
  }

  return (
    <div className="space-y-5">
      <Card className="p-5">
        <h3 className="text-sm font-bold">How did it actually go?</h3>
        <p className="mt-1 text-xs leading-5 text-[var(--muted-strong)]">
          Pick a recorded meeting and MeetMind compares it with what you prepared.
          Every suggestion quotes the transcript, and you can reject any you think
          is unfair.
        </p>

        {meetings.length === 0 ? (
          <p className="mt-3 text-sm text-[var(--muted-strong)]">
            No meetings with a transcript yet.
          </p>
        ) : (
          <div className="mt-3 flex flex-wrap gap-2">
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              className="min-w-0 flex-1 rounded-xl border border-[var(--border)] bg-white px-3.5 py-2.5 text-sm"
            >
              {meetings.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.title || m.meeting_url}
                </option>
              ))}
            </select>
            <button
              onClick={review}
              disabled={busy || !selected}
              className="inline-flex items-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-2.5 text-sm font-bold text-white disabled:opacity-40"
            >
              {busy ? <><Spinner /> Reviewing…</> : "Review this meeting"}
            </button>
          </div>
        )}
      </Card>

      {error && <ErrorBanner message={error} onDismiss={() => setError(null)} />}
      {notice && (
        <p className="rounded-xl border border-[var(--border)] bg-white px-4 py-2.5 text-sm text-[var(--muted-strong)]">
          {notice}
        </p>
      )}

      {themes.length > 0 && (
        <Card className="p-5">
          <h3 className="mb-2 text-sm font-bold">Recurring areas</h3>
          <div className="flex flex-wrap gap-2">
            {themes.map(([cat, n]) => (
              <span
                key={cat}
                className="rounded-full border border-[var(--border)] px-3 py-1 text-xs"
              >
                {CATEGORY_LABEL[cat] ?? cat}: <strong>{n}</strong>
              </span>
            ))}
          </div>
          <p className="mt-2 text-[11px] text-[var(--muted-strong)]">
            Counted across meetings, excluding feedback you rejected.
          </p>
        </Card>
      )}

      {notes === null ? (
        <Card className="flex items-center gap-2 p-5 text-sm text-[var(--muted-strong)]">
          <Spinner /> Loading…
        </Card>
      ) : notes.length === 0 ? (
        <Card className="p-8 text-center">
          <p className="text-sm font-medium">No reviews yet</p>
          <p className="mt-1 text-sm text-[var(--muted-strong)]">
            Pick a meeting above and press “Review this meeting”.
          </p>
        </Card>
      ) : (
        <div className="space-y-3">
          {notes.map((n) => (
            <Card key={n.id} className={`p-4 ${n.rejected ? "opacity-50" : ""}`}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-[11px] font-semibold text-[var(--muted-strong)]">
                  {CATEGORY_LABEL[n.category] ?? n.category}
                </span>
                <button
                  onClick={() => toggleReject(n)}
                  className="text-xs text-[var(--accent)] hover:underline"
                >
                  {n.rejected ? "Restore" : "This isn’t fair"}
                </button>
              </div>

              <div className="mt-2 text-sm">
                <ChatText content={n.suggestion} />
              </div>

              <div className="mt-3 space-y-2">
                {(n.said || n.evidence) && (
                  <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2">
                    <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--muted-strong)]">
                      You said
                    </p>
                    <p className="mt-1 text-sm italic text-[var(--muted-strong)]">
                      “{n.evidence || n.said}”
                    </p>
                  </div>
                )}

                {n.better && (
                  <div
                    className="rounded-lg border px-3 py-2"
                    style={{
                      borderColor: "color-mix(in oklab, var(--success) 30%, transparent)",
                      background: "var(--success-soft)",
                    }}
                  >
                    <p
                      className="text-[10px] font-bold uppercase tracking-[0.12em]"
                      style={{ color: "var(--success)" }}
                    >
                      Say this next time
                    </p>
                    <p className="mt-1 text-sm">{n.better}</p>
                  </div>
                )}
              </div>

              <p className="mt-2 text-[11px] text-[var(--muted-strong)]">
                {n.meeting_title && (
                  <Link
                    href={`/meetings/${n.meeting_id}`}
                    className="text-[var(--accent)] hover:underline"
                  >
                    {n.meeting_title}
                  </Link>
                )}{" "}
                · {new Date(n.created_at).toLocaleDateString()}
              </p>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
