"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { BookOpen, FileText, MessageSquareText, Sparkles, Target, Upload, UserRound } from "lucide-react";
import { ApiError, api, type CoachNote, type Meeting, type PrepPlan, coachApi, markupApi } from "@/lib/api";
import { Card, EmptyState, ErrorBanner, Spinner } from "@/components/ui";
import { ChatText } from "@/components/ChatText";
import Avatar from "@/components/ui/components-primitives-avatar";
import LoadingState from "@/components/ui/loading-state";
import { AiInput } from "@/components/ui/ai-input";

const CATEGORY_LABEL: Record<string, string> = {
  missed_point: "Missed talking point",
  unanswered_question: "Unanswered question",
  unclear_commitment: "Unclear commitment",
  repetition: "Repeated yourself",
  clarity: "Clarity",
  general: "General",
};

const field = "w-full rounded-xl border border-[var(--border)] bg-white px-3.5 py-3 text-sm outline-none transition placeholder:text-[#9aa1b2] focus:border-[var(--accent)] focus:ring-4 focus:ring-[var(--accent)]/10";

export default function CoachPage() {
  const [tab, setTab] = useState<"prepare" | "review">("prepare");
  const [notes, setNotes] = useState<CoachNote[] | null>(null);
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [selected, setSelected] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [plan, setPlan] = useState<PrepPlan | null>(null);
  const [purpose, setPurpose] = useState("");
  const [projectDetails, setProjectDetails] = useState("");
  const [participants, setParticipants] = useState("");
  const [agenda, setAgenda] = useState("");
  const [role, setRole] = useState("");
  const [outcome, setOutcome] = useState("");
  const [fileName, setFileName] = useState("");
  const [fileText, setFileText] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await coachApi.notes();
      setNotes(data.notes);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Failed to load coaching.");
      setNotes([]);
    }
  }, []);

  useEffect(() => {
    coachApi.notes()
      .then((data) => { setNotes(data.notes); })
      .catch(() => setNotes([]));
    api.listMeetings()
      .then((rows) => {
        const withTranscript = rows.filter((meeting) => meeting.has_transcript);
        setMeetings(withTranscript);
        if (withTranscript.length) setSelected(withTranscript[0].id);
      })
      .catch(() => setMeetings([]));
  }, []);

  async function review() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const response = await coachApi.review(selected);
      setNotice(response.count === 0 ? "No evidence-backed suggestions for this meeting—nothing to flag." : `${response.count} suggestion(s) generated${response.had_plan ? " against your preparation plan" : " from the transcript"}.`);
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Review failed.");
    } finally {
      setBusy(false);
    }
  }

  async function prepare(event: React.FormEvent) {
    event.preventDefault();
    if (!purpose.trim() || !projectDetails.trim() || !role.trim()) return;
    setBusy(true);
    setError(null);
    setPlan(null);
    try {
      const uploadedContext = fileText ? `\n\nUploaded project brief (${fileName}):\n${fileText}` : "";
      setPlan(await markupApi.prepareNew({
        purpose: purpose.trim(),
        project_description: `${projectDetails.trim()}${uploadedContext}`,
        participants: participants.trim() || null,
        agenda: agenda.trim() || null,
        my_responsibilities: role.trim(),
        desired_outcomes: outcome.trim() || null,
        project_id: null,
      }));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not create your meeting preparation.");
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

  async function toggleReject(note: CoachNote) {
    try {
      await coachApi.reject(note.id, !note.rejected);
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not update.");
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 sm:px-6 sm:py-10">
      <Link href="/dashboard" className="text-sm font-semibold text-[var(--accent)] hover:underline">← Dashboard</Link>

      <header className="mt-5 mb-6 flex items-start gap-4">
        <Avatar color="orange" size="md" shape="squircle" />
        <div>
          <div className="flex flex-wrap items-center gap-2"><h1 className="text-2xl font-semibold tracking-tight">Personal Meeting Coach</h1><span className="rounded-full bg-[var(--success-soft)] px-2 py-1 text-[10px] font-bold text-[var(--success)]">Only you can see this</span></div>
          <p className="mt-1 max-w-2xl text-sm text-[var(--muted)]">Prepare before a meeting or get simple advice after one.</p>
        </div>
      </header>

      {error && <div className="mb-5"><ErrorBanner message={error} onDismiss={() => setError(null)} /></div>}
      {notice && <p className="mb-5 rounded-xl border border-[var(--border)] bg-white px-4 py-3 text-sm text-[var(--muted)] shadow-[var(--shadow-sm)]">{notice}</p>}

      <div className="mb-6 inline-flex w-full rounded-xl border border-[var(--border)] bg-white p-1 shadow-[var(--shadow-sm)] sm:w-auto">
        <button onClick={() => setTab("prepare")} className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-bold transition sm:flex-none ${tab === "prepare" ? "bg-[var(--accent)] text-white" : "text-[var(--muted)] hover:bg-[var(--surface-2)]"}`}>
          <Sparkles className="h-3.5 w-3.5" /> Prepare for a meeting
        </button>
        <button onClick={() => setTab("review")} className={`flex flex-1 items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-bold transition sm:flex-none ${tab === "review" ? "bg-[var(--accent)] text-white" : "text-[var(--muted)] hover:bg-[var(--surface-2)]"}`}>
          <BookOpen className="h-3.5 w-3.5" /> Improve after a meeting
        </button>
      </div>

      {tab === "prepare" ? (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,.9fr)_minmax(0,1.1fr)]">
          <Card className="h-fit p-5 sm:p-6">
            <div className="mb-5"><h2 className="text-base font-bold">Plan your next meeting</h2><p className="mt-1 text-xs leading-5 text-[var(--muted)]">Add the project, your role, and what you want to achieve.</p></div>
            <form onSubmit={prepare} className="space-y-4">
              <div><label htmlFor="meeting-purpose" className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">Meeting or project name</label><input id="meeting-purpose" required value={purpose} onChange={(event) => setPurpose(event.target.value)} placeholder="Project Alpha kickoff" className={field} /></div>
              <div><label htmlFor="project-details" className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">What is the project about?</label><textarea id="project-details" required value={projectDetails} onChange={(event) => setProjectDetails(event.target.value)} placeholder="Explain the product, current stage, business need, constraints, and anything the AI should know…" rows={5} className={`${field} resize-y`} /></div>
              <label className="flex cursor-pointer items-center gap-3 rounded-xl border border-dashed border-[var(--accent)]/35 bg-[var(--accent-soft)]/45 p-3.5 transition hover:bg-[var(--accent-soft)]">
                <span className="grid h-9 w-9 place-items-center rounded-xl bg-white text-[var(--accent)]"><Upload className="h-4 w-4" /></span>
                <span className="min-w-0 flex-1"><span className="block truncate text-xs font-bold">{fileName || "Upload project details"}</span><span className="mt-0.5 block text-[10px] text-[var(--muted)]">TXT, Markdown, CSV, or JSON · up to 500 KB</span></span>
                <input type="file" accept=".txt,.md,.markdown,.csv,.json,text/plain,text/markdown,text/csv,application/json" onChange={readBrief} className="hidden" />
              </label>
              <div><label htmlFor="my-role" className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">What is your role in this meeting?</label><textarea id="my-role" required value={role} onChange={(event) => setRole(event.target.value)} placeholder="I am the backend engineer presenting feasibility and risks…" rows={3} className={`${field} resize-y`} /></div>
              <div className="grid gap-4 sm:grid-cols-2"><div><label htmlFor="participants" className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">Who will attend?</label><input id="participants" value={participants} onChange={(event) => setParticipants(event.target.value)} placeholder="Client, PM, engineering lead" className={field} /></div><div><label htmlFor="outcome" className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">What outcome do you want?</label><input id="outcome" value={outcome} onChange={(event) => setOutcome(event.target.value)} placeholder="Approval for the proposed approach" className={field} /></div></div>
              <div><label htmlFor="agenda" className="mb-1.5 block text-xs font-bold text-[var(--muted-strong)]">Agenda or likely topics <span className="font-normal text-[var(--muted)]">(optional)</span></label><textarea id="agenda" value={agenda} onChange={(event) => setAgenda(event.target.value)} placeholder="Introductions, scope, timeline, technical risks…" rows={3} className={`${field} resize-y`} /></div>
              <button type="submit" disabled={busy || !purpose.trim() || !projectDetails.trim() || !role.trim()} className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--accent)] px-4 py-3 text-sm font-bold text-white shadow-[0_14px_28px_-16px_rgb(99_91_255/.8)] transition hover:bg-[var(--accent-hover)] disabled:opacity-40">{busy ? <><Spinner /> Building your advantage…</> : <><Sparkles className="h-4 w-4" /> Prepare me for this meeting</>}</button>
            </form>
          </Card>

          {plan ? <PreparationPlan plan={plan} /> : (
            <Card className="flex min-h-[440px] flex-col items-center justify-center p-8 text-center">
              <Avatar color="orange" size="lg" shape="squircle" />
              <h2 className="mt-5 text-lg font-bold">Your meeting advantage will appear here</h2>
              <p className="mt-2 max-w-sm text-sm leading-6 text-[var(--muted)]">You&apos;ll get role guidance, a speaking strategy, a suggested opening, key questions, risks, and improvements drawn from your private coaching history.</p>
            </Card>
          )}
        </div>
      ) : (
        <ReviewWorkspace meetings={meetings} selected={selected} setSelected={setSelected} busy={busy} review={review} notes={notes} toggleReject={toggleReject} />
      )}
    </main>
  );
}

function PreparationPlan({ plan }: { plan: PrepPlan }) {
  return (
    <div className="space-y-4">
      <Card className="overflow-hidden"><div className="bg-[var(--navy)] p-5 text-white sm:p-6"><div className="flex items-start gap-3"><Avatar color="orange" size="sm" shape="squircle" /><div><p className="text-[10px] font-bold uppercase tracking-[0.14em] text-white/45">Your AI briefing</p><h2 className="mt-1 text-lg font-bold">{plan.title || "Upcoming meeting"}</h2></div></div><div className="mt-5 text-sm leading-6 text-white/75"><ChatText content={plan.briefing || "Your preparation plan is ready."} /></div></div></Card>
      {plan.role_guidance && <PlanSection icon={UserRound} title="Your role in the room"><p className="text-sm leading-6 text-[var(--muted-strong)]">{plan.role_guidance}</p></PlanSection>}
      {plan.opening_script && <PlanSection icon={MessageSquareText} title="A strong way to open"><blockquote className="rounded-xl border-l-4 border-[var(--coral)] bg-[var(--coral-soft)] px-4 py-3 text-sm leading-6 text-[var(--foreground)]">“{plan.opening_script}”</blockquote></PlanSection>}
      {!!plan.speaking_strategy?.length && <PlanSection icon={Target} title="How to speak and contribute"><BulletList items={plan.speaking_strategy} tone="accent" /></PlanSection>}
      {!!plan.past_improvements?.length && <PlanSection icon={Sparkles} title="Improve from your past meetings" badge={`${plan.past_coaching_count ?? 0} private coaching notes considered`}><BulletList items={plan.past_improvements} tone="coral" /></PlanSection>}
      <div className="grid gap-4 sm:grid-cols-2"><PlanSection icon={FileText} title="Talking points"><BulletList items={plan.talking_points} tone="accent" /></PlanSection><PlanSection icon={MessageSquareText} title="Questions to ask"><BulletList items={plan.questions_to_ask} tone="success" /></PlanSection></div>
      {!!plan.risks.length && <PlanSection icon={Target} title="Watch-outs"><BulletList items={plan.risks} tone="coral" /></PlanSection>}
    </div>
  );
}

function PlanSection({ icon: Icon, title, badge, children }: { icon: typeof Target; title: string; badge?: string; children: React.ReactNode }) {
  return <Card className="p-5"><div className="mb-3 flex flex-wrap items-center justify-between gap-2"><h3 className="flex items-center gap-2 text-sm font-bold"><span className="grid h-8 w-8 place-items-center rounded-lg bg-[var(--accent-soft)] text-[var(--accent)]"><Icon className="h-3.5 w-3.5" /></span>{title}</h3>{badge && <span className="rounded-full bg-[var(--coral-soft)] px-2.5 py-1 text-[9px] font-bold text-[var(--coral)]">{badge}</span>}</div>{children}</Card>;
}

function BulletList({ items, tone }: { items: string[]; tone: "accent" | "coral" | "success" }) {
  const color = tone === "coral" ? "var(--coral)" : tone === "success" ? "var(--success)" : "var(--accent)";
  return items.length ? <ul className="space-y-2">{items.map((item, index) => <li key={`${item}-${index}`} className="flex gap-2.5 text-sm leading-6 text-[var(--muted-strong)]"><span className="mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: color }} />{item}</li>)}</ul> : <p className="text-sm text-[var(--muted)]">Nothing specific to add.</p>;
}

function LegacyReviewMeeting({ meetings, selected, setSelected, busy, review, themes, notes, toggleReject }: { meetings: Meeting[]; selected: string; setSelected: (value: string) => void; busy: boolean; review: () => void; themes: [string, number][]; notes: CoachNote[] | null; toggleReject: (note: CoachNote) => void }) {
  return <div className="space-y-6"><Card className="p-5"><h2 className="mb-3 text-sm font-bold">Review a meeting</h2>{meetings.length === 0 ? <p className="text-sm text-[var(--muted)]">No meetings with a transcript yet.</p> : <div className="flex flex-col gap-2 sm:flex-row"><select value={selected} onChange={(event) => setSelected(event.target.value)} className={`${field} min-w-0 flex-1`}>{meetings.map((meeting) => <option key={meeting.id} value={meeting.id}>{meeting.title || meeting.meeting_url}</option>)}</select><button onClick={review} disabled={busy || !selected} className="inline-flex items-center justify-center gap-2 rounded-xl bg-[var(--accent)] px-5 py-3 text-sm font-bold text-white disabled:opacity-40">{busy && <Spinner />} Coach me</button></div>}</Card>{themes.length > 0 && <Card className="p-5"><h2 className="mb-3 text-sm font-bold">Recurring areas</h2><div className="flex flex-wrap gap-2">{themes.map(([category, count]) => <span key={category} className="rounded-full border border-[var(--border)] bg-[var(--background)] px-3 py-1.5 text-xs">{CATEGORY_LABEL[category] ?? category}: <strong>{count}</strong></span>)}</div><p className="mt-2 text-xs text-[var(--muted)]">These private themes help tailor your next meeting preparation.</p></Card>}{notes === null ? <Card className="flex items-center gap-2 px-5 py-10 text-sm text-[var(--muted)]"><Spinner /> Loading…</Card> : notes.length === 0 ? <Card><EmptyState title="No coaching yet" hint="Pick a meeting above and press Coach me." /></Card> : <ul className="space-y-3">{notes.map((note) => <li key={note.id}><Card className={`p-4 ${note.rejected ? "opacity-50" : ""}`}><div className="flex flex-wrap items-start justify-between gap-2"><span className="rounded-full border border-[var(--border)] px-2 py-0.5 text-[11px] font-medium text-[var(--muted)]">{CATEGORY_LABEL[note.category] ?? note.category}</span><button onClick={() => toggleReject(note)} className="text-xs font-semibold text-[var(--accent)] hover:underline">{note.rejected ? "Restore" : "This isn’t fair"}</button></div><div className="mt-2 text-sm"><ChatText content={note.suggestion} /></div>{note.evidence && <blockquote className="mt-2 border-l-2 border-[var(--accent)] bg-[var(--background)] px-3 py-2 text-xs italic text-[var(--muted)]">“{note.evidence}”</blockquote>}<p className="mt-2 text-xs text-[var(--muted)]">{note.meeting_title && <Link href={`/meetings/${note.meeting_id}`} className="text-[var(--accent)] hover:underline">{note.meeting_title}</Link>} · {new Date(note.created_at).toLocaleDateString()}</p></Card></li>)}</ul>}</div>;
}

void LegacyReviewMeeting;

type CoachChatTurn = { role: "user" | "assistant"; content: string };

function ReviewWorkspace({ meetings, selected, setSelected, busy, review, notes, toggleReject }: { meetings: Meeting[]; selected: string; setSelected: (value: string) => void; busy: boolean; review: () => void; notes: CoachNote[] | null; toggleReject: (note: CoachNote) => void }) {
  const [chat, setChat] = useState<CoachChatTurn[]>([]);
  const [input, setInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const selectedMeeting = meetings.find((meeting) => meeting.id === selected);
  const meetingNotes = (notes ?? []).filter((note) => note.meeting_id === selected);

  async function askCoach(message: string) {
    if (!selected || !message.trim() || chatBusy) return;
    const question = message.trim();
    const history = chat.slice(-8);
    setChat((current) => [...current, { role: "user", content: question }]);
    setInput("");
    setChatBusy(true);
    setChatError(null);
    try {
      const response = await coachApi.ask(selected, question, history);
      setChat((current) => [...current, { role: "assistant", content: response.answer }]);
    } catch (reason) {
      setChatError(reason instanceof ApiError ? reason.message : "Your AI coach could not answer.");
    } finally {
      setChatBusy(false);
    }
  }

  const suggestions = [
    "Explain one feedback point",
    "Help me say it more clearly",
    "Practise my next meeting with me",
  ];

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,.9fr)_minmax(0,1.1fr)] lg:items-start">
      <section className="min-w-0 space-y-4">
        <Card className="p-4 sm:p-5">
          <h2 className="text-sm font-bold">1. Choose a meeting</h2>
          <p className="mt-1 mb-3 text-xs text-[var(--muted)]">Select a past meeting to see simple, transcript-backed advice.</p>
          {meetings.length === 0 ? (
            <p className="text-sm text-[var(--muted)]">No meetings with a transcript yet.</p>
          ) : (
            <div className="flex flex-col gap-2 sm:flex-row">
              <select value={selected} onChange={(event) => { setSelected(event.target.value); setChat([]); setInput(""); setChatError(null); }} className={`${field} min-w-0 flex-1`}>
                {meetings.map((meeting) => <option key={meeting.id} value={meeting.id}>{meeting.title || meeting.meeting_url}</option>)}
              </select>
              <button onClick={review} disabled={busy || !selected} className="inline-flex items-center justify-center gap-2 rounded-xl bg-[var(--accent)] px-5 py-3 text-sm font-bold text-white disabled:opacity-40">{busy && <Spinner />} Review meeting</button>
            </div>
          )}
        </Card>

        <div className="flex items-center justify-between px-1">
          <div><h2 className="text-sm font-bold">Your feedback</h2><p className="mt-0.5 text-xs text-[var(--muted)]">Focus on one improvement at a time.</p></div>
          {meetingNotes.length > 0 && <span className="rounded-full bg-[var(--accent-soft)] px-2.5 py-1 text-[10px] font-bold text-[var(--accent)]">{meetingNotes.length} tips</span>}
        </div>

        <div className="space-y-3">
          {notes === null ? (
            <Card className="flex items-center gap-2 px-5 py-10 text-sm text-[var(--muted)]"><Spinner /> Loading…</Card>
          ) : meetingNotes.length === 0 ? (
            <Card><EmptyState title="No coaching for this meeting yet" hint="Select Coach me to generate evidence-backed feedback." /></Card>
          ) : (
            meetingNotes.map((note) => (
              <Card key={note.id} className={`overflow-hidden p-0 transition ${note.rejected ? "border-dashed bg-[var(--surface-2)]" : ""}`}>
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] px-4 py-3">
                  <div className="flex items-center gap-2">
                    <span className="rounded-full border border-[var(--border)] bg-white px-2 py-0.5 text-[10px] font-semibold text-[var(--muted)]">{CATEGORY_LABEL[note.category] ?? note.category}</span>
                    {note.rejected && <span className="text-[10px] font-semibold text-[var(--muted)]">Marked inaccurate</span>}
                  </div>
                  <button
                    onClick={() => toggleReject(note)}
                    title={note.rejected ? "Add this feedback back to your coaching" : "Hide this feedback and exclude it from future coaching"}
                    className={`rounded-lg border px-2.5 py-1.5 text-[11px] font-semibold transition ${note.rejected ? "border-[var(--accent)]/20 bg-[var(--accent-soft)] text-[var(--accent)] hover:bg-white" : "border-[var(--border)] bg-white text-[var(--muted-strong)] hover:border-[var(--danger)]/30 hover:bg-[var(--danger-soft)] hover:text-[var(--danger)]"}`}
                  >
                    {note.rejected ? "Undo" : "Mark as inaccurate"}
                  </button>
                </div>
                <div className={`px-4 py-3 ${note.rejected ? "opacity-55" : ""}`}>
                  <p className="mb-1 text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--muted)]">How to improve</p>
                  <div className="text-sm leading-6"><ChatText content={note.suggestion} /></div>
                  {note.evidence && (
                    <div className="mt-3 rounded-lg bg-[var(--background)] px-3 py-2.5">
                      <p className="mb-1 text-[10px] font-bold uppercase tracking-[0.12em] text-[var(--muted)]">What you said</p>
                      <blockquote className="border-l-2 border-[var(--accent)] pl-3 text-xs italic leading-5 text-[var(--muted-strong)]">“{note.evidence}”</blockquote>
                    </div>
                  )}
                </div>
              </Card>
            ))
          )}
        </div>
      </section>

      <Card className="flex min-h-[560px] min-w-0 flex-col overflow-hidden lg:sticky lg:top-6 lg:h-[min(720px,calc(100vh-110px))]">
        <header className="border-b border-[var(--border)] bg-white p-4 sm:p-5">
          <div className="flex items-center gap-3"><Avatar color="orange" size="sm" shape="squircle" /><div className="min-w-0"><div className="flex items-center gap-2"><h2 className="text-sm font-bold">2. Ask your coach</h2><span className="h-1.5 w-1.5 rounded-full bg-[var(--success)]" /></div><p className="mt-0.5 truncate text-[10px] text-[var(--muted)]">{selectedMeeting?.title || "Choose a meeting first"}</p></div></div>
        </header>

        <div className="flex-1 space-y-3 overflow-x-hidden overflow-y-auto bg-[var(--background)] p-4">
          {chat.length === 0 && (
            <div className="px-1 py-3">
              <h3 className="text-sm font-bold">What do you need help with?</h3>
              <p className="mt-1 text-xs leading-5 text-[var(--muted)]">Choose an option or type your own question below.</p>
              <div className="mt-4 grid gap-2">
                {suggestions.map((suggestion) => <button key={suggestion} onClick={() => askCoach(suggestion)} disabled={!selected} className="rounded-xl border border-[var(--border)] bg-white px-3.5 py-3 text-left text-xs font-semibold transition hover:border-[var(--accent)]/30 hover:bg-[var(--accent-soft)] hover:text-[var(--accent)] disabled:opacity-50">{suggestion}</button>)}
              </div>
            </div>
          )}
          {chat.map((turn, index) => turn.role === "user" ? (
            <div key={index} className="ml-auto max-w-[85%] rounded-2xl rounded-br-md bg-[var(--accent)] px-3.5 py-2.5 text-sm leading-6 text-white">{turn.content}</div>
          ) : (
            <div key={index} className="flex min-w-0 items-start gap-2"><Avatar color="orange" size="sm" shape="squircle" /><div className="min-w-0 flex-1 rounded-2xl rounded-tl-md border border-[var(--border)] bg-white px-3.5 py-2.5 text-sm leading-6 shadow-[var(--shadow-sm)]"><ChatText content={turn.content} /></div></div>
          ))}
          {chatBusy && <div className="flex items-center gap-2 text-xs text-[var(--muted)]"><Avatar color="orange" size="sm" shape="squircle" /><span className="rounded-full bg-white px-3 py-2"><LoadingState label="Shaping your answer" variant="Drive" /></span></div>}
          {chatError && <ErrorBanner message={chatError} onDismiss={() => setChatError(null)} />}
        </div>

        <div className="border-t border-[var(--border)] bg-white">
          <AiInput value={input} onChange={setInput} onSubmit={askCoach} disabled={!selected} busy={chatBusy} compact placeholder={selected ? "Ask how to improve or what to say…" : "Select a meeting first"} />
        </div>
      </Card>
    </div>
  );
}
