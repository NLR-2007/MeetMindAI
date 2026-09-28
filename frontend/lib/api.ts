/**
 * Typed client for the MeetMind AI backend.
 *
 * The API base is public config only — no secret ever reaches the browser.
 * All Recall and Groq keys live server-side in the FastAPI process.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

export type MeetingStatus = string | null;

export interface Meeting {
  id: string;
  bot_id: string;
  meeting_url: string;
  platform: string;
  bot_name: string;
  title: string | null;
  status: MeetingStatus;
  created_at: string;
  has_transcript: boolean;
  has_summary: boolean;
}

export interface StatusChange {
  code: string;
  message: string | null;
  created_at: string;
  sub_code: string | null;
}

export interface Participant {
  id: string;
  name: string | null;
  email: string | null;
  is_host: boolean;
}

export interface Summary {
  summary_text: string | null;
  decisions: string[];
  model: string | null;
  tokens_used: number | null;
}

export interface ActionItem {
  id: string;
  task: string;
  owner_name: string | null;
  due_text: string | null;
  done: boolean;
}

export interface Deadline {
  id: string;
  what: string;
  when_text: string | null;
  due_at: string | null;
  google_event_id: string | null;
  google_event_link: string | null;
}

export interface MeetingDetail extends Meeting {
  status_changes: StatusChange[];
  participants: Participant[];
  summary: Summary | null;
  action_items: ActionItem[];
  deadlines: Deadline[];
  transcript_word_count: number | null;
  transcript_text: string | null;
}

export interface MeetingStatusResponse {
  meeting_id: string;
  bot_id: string;
  status: MeetingStatus;
  platform: string;
  meeting_url: string;
  status_changes: StatusChange[];
  is_terminal: boolean;
}

export interface ProcessResult {
  meeting_id: string;
  transcript_saved: boolean;
  analysis_saved: boolean;
  skipped_reason: string | null;
  word_count: number | null;
  participants: number | null;
  action_items: number | null;
  deadlines: number | null;
  tokens_used: number | null;
}

export interface ChatResponse {
  meeting_id: string;
  answer: string;
  tokens_used: number | null;
  context_switch_required: boolean;
  pending_meeting_id: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
}

/** Turn FastAPI's error shapes into one readable string. */
function readError(body: unknown, fallback: string): string {
  if (typeof body === "string") return body;
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) =>
          typeof d === "object" && d && "msg" in d
            ? String((d as { msg: unknown }).msg)
            : String(d),
        )
        .join("; ");
    }
  }
  return fallback;
}

// --- auth token (browser-only; kept out of React state so every caller sees it) ---

const TOKEN_KEY = "meetmind_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* private mode: the session simply will not persist */
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      `Cannot reach the backend at ${API_BASE}. Is FastAPI running?`,
      0,
    );
  }

  if (res.status === 401) {
    // The session is gone; drop the stale token so the UI can re-prompt.
    setToken(null);
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  }

  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(
      readError(body, `Request failed with status ${res.status}`),
      res.status,
    );
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export interface AuthUser {
  id: string;
  email: string;
  name: string | null;
  role: string;
  manager_id: string | null;
  display_names: string[] | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  email: string;
  name: string | null;
  role: string;
}

export interface TeamMember {
  id: string;
  email: string;
  name: string | null;
  role: string;
}

export const authApi = {
  register: (
    email: string,
    password: string,
    name?: string,
    role: string = "employee",
    managerEmail?: string,
  ) =>
    request<TokenResponse>("/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        name: name || undefined,
        role,
        manager_email: managerEmail || undefined,
      }),
    }),

  team: () => request<TeamMember[]>("/auth/team"),

  setAliases: (names: string[]) =>
    request<AuthUser>("/auth/me/aliases", {
      method: "PUT",
      body: JSON.stringify({ display_names: names }),
    }),

  login: (email: string, password: string) =>
    request<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  me: () => request<AuthUser>("/auth/me"),
};

export const api = {
  health: () => request<Record<string, unknown>>("/health"),

  listMeetings: () => request<Meeting[]>("/meetings"),

  joinMeeting: (payload: {
    meeting_url: string;
    consent_acknowledged: boolean;
    title?: string;
    bot_name?: string;
  }) =>
    request<Meeting>("/meetings/join", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  getMeeting: (id: string, includeTranscript = false) =>
    request<MeetingDetail>(
      `/meetings/${id}${includeTranscript ? "?include_transcript=true" : ""}`,
    ),

  getStatus: (id: string) =>
    request<MeetingStatusResponse>(`/meetings/${id}/status`),

  processMeeting: (id: string, force = false) =>
    request<ProcessResult>(`/meetings/${id}/process${force ? "?force=true" : ""}`, {
      method: "POST",
    }),

  leaveMeeting: (id: string) =>
    request<MeetingStatusResponse>(`/meetings/${id}/leave`, { method: "POST" }),

  chatHistory: (id: string) => request<ChatMessage[]>(`/meetings/${id}/chat`),

  chat: (id: string, message: string, confirmContextSwitch = false) =>
    request<ChatResponse>(`/meetings/${id}/chat`, {
      method: "POST",
      body: JSON.stringify({
        message,
        confirm_context_switch: confirmContextSwitch,
      }),
    }),
};

/** Human-readable label + colour for a Recall bot status code. */
export function statusLabel(status: MeetingStatus): {
  label: string;
  tone: "idle" | "active" | "recording" | "done" | "error";
} {
  switch (status) {
    case "joining_call":
      return { label: "Joining", tone: "active" };
    case "in_waiting_room":
      return { label: "Waiting to be admitted", tone: "active" };
    case "in_call_not_recording":
      return { label: "In call", tone: "active" };
    case "in_call_recording":
      return { label: "Recording", tone: "recording" };
    case "call_ended":
      return { label: "Call ended", tone: "done" };
    case "recording_done":
      return { label: "Recording saved", tone: "done" };
    case "done":
      return { label: "Done", tone: "done" };
    case "fatal":
      return { label: "Failed to join", tone: "error" };
    default:
      return { label: status ?? "Pending", tone: "idle" };
  }
}

export const TERMINAL_STATUSES = new Set(["done", "fatal"]);

// --- Calendar ------------------------------------------------------------

export interface CalendarConnection {
  id: string;
  recall_calendar_id: string;
  platform: string;
  email: string | null;
  status: string | null;
  auto_record: boolean;
}

export interface CalendarEvent {
  id: string;
  title: string | null;
  start_time: string;
  end_time: string;
  meeting_url: string | null;
  meeting_platform: string | null;
  is_deleted: boolean;
  bot_scheduled: boolean;
  bots: unknown[];
}

export interface DeadlineEntry {
  id: string;
  what: string;
  when_text: string | null;
  due_at: string | null;
  on_calendar: boolean;
  google_event_link: string | null;
  meeting_id: string;
  meeting_title: string | null;
}

export const calendarApi = {
  deadlines: () => request<DeadlineEntry[]>("/calendar/deadlines"),

  startOAuth: () =>
    request<{ authorization_url: string }>("/calendar/oauth/start"),

  list: () => request<CalendarConnection[]>("/calendar"),

  events: (calendarId: string, daysAhead = 7) =>
    request<CalendarEvent[]>(
      `/calendar/${calendarId}/events?days_ahead=${daysAhead}`,
    ),

  schedule: (eventId: string, consent: boolean) =>
    request<{ event_id: string; bots: unknown[] }>(
      `/calendar/events/${eventId}/schedule?consent_acknowledged=${consent}`,
      { method: "POST" },
    ),

  pushDeadline: (deadlineId: string) =>
    request<{
      deadline_id: string;
      already_present: boolean;
      google_event_id: string | null;
      google_event_link: string | null;
    }>(`/calendar/deadlines/${deadlineId}/push`, { method: "POST" }),

  removeDeadline: (deadlineId: string) =>
    request<{ deadline_id: string; removed: boolean }>(
      `/calendar/deadlines/${deadlineId}/push`,
      { method: "DELETE" },
    ),

  unschedule: (eventId: string) =>
    request<{ event_id: string; scheduled: boolean }>(
      `/calendar/events/${eventId}/schedule`,
      { method: "DELETE" },
    ),
};

// --- PromiseMirror / Mark Up / Coaching / Progress ------------------------

export interface Finding {
  kind: string;
  severity: "high" | "medium" | "low";
  title: string;
  detail: string;
  commitment_id: string | null;
  meeting_id: string | null;
  meeting_title: string | null;
  evidence: string | null;
  due_at: string | null;
  related: { commitment_id?: string; role?: string; text?: string; due_at?: string | null; meeting_title?: string | null; evidence?: string | null }[];
}

export interface Commitment {
  id: string;
  kind: string;
  text: string;
  owner_name: string | null;
  status: string;
  due_at: string | null;
  due_text: string | null;
  evidence: string | null;
  meeting_id: string | null;
  meeting_title: string | null;
  project_id: string | null;
  supersedes_id: string | null;
  superseded_by_id: string | null;
}

export interface TimelineEvent {
  at: string;
  event: string;
  commitment_id: string;
  text: string;
  status: string;
  owner_name?: string | null;
  due_at: string | null;
  meeting_id: string | null;
  supersedes_id?: string | null;
  evidence?: string | null;
}

export interface ProjectSummary {
  id: string;
  name: string;
  description: string | null;
}

export interface PrepPlan {
  id: string;
  mode: string;
  title: string | null;
  project_id: string | null;
  meeting_id: string | null;
  briefing: string | null;
  talking_points: string[];
  questions_to_ask: string[];
  open_commitments: Finding[];
  risks: string[];
  role_guidance?: string | null;
  opening_script?: string | null;
  speaking_strategy?: string[];
  past_improvements?: string[];
  past_coaching_count?: number;
  created_at: string;
}

export interface CoachNote {
  id: string;
  meeting_id: string;
  meeting_title: string | null;
  category: string;
  /** What this user actually said, in their own words. */
  said: string | null;
  /** What was unclear, missing or repeated about it. */
  suggestion: string;
  /** A concrete rewrite to use next time. */
  better: string | null;
  evidence: string | null;
  rejected: boolean;
  created_at: string;
}

export interface ProgressData {
  totals: { pending: number; completed: number; overdue: number; upcoming: number };
  pending: Commitment[];
  completed: Commitment[];
  overdue: Commitment[];
  upcoming: Commitment[];
  by_project: {
    project_id: string | null;
    project_name: string;
    total: number;
    completed: number;
    pending: number;
    overdue: number;
    percent: number;
  }[];
  recent_meetings: { id: string; title: string; status: string | null; created_at: string }[];
  alerts: Finding[];
}

function scopeQuery(
  projectId?: string,
  meetingId?: string,
  assignedTo?: string,
): string {
  const params = new URLSearchParams();
  if (projectId) params.set("project_id", projectId);
  if (meetingId) params.set("meeting_id", meetingId);
  if (assignedTo) params.set("assigned_to", assignedTo);
  const q = params.toString();
  return q ? `?${q}` : "";
}

export const promiseApi = {
  findings: (projectId?: string, meetingId?: string, assignedTo?: string) =>
    request<{ count: number; by_kind: Record<string, number>; findings: Finding[] }>(
      `/promisemirror/findings${scopeQuery(projectId, meetingId, assignedTo)}`,
    ),
  commitments: (projectId?: string, meetingId?: string, assignedTo?: string) =>
    request<Commitment[]>(
      `/promisemirror/commitments${scopeQuery(projectId, meetingId, assignedTo)}`,
    ),
  timeline: (projectId?: string, meetingId?: string) =>
    request<TimelineEvent[]>(
      `/promisemirror/timeline${scopeQuery(projectId, meetingId)}`,
    ),
  setStatus: (id: string, status: string) =>
    request<Commitment>(`/promisemirror/commitments/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status, confirmed: true }),
    }),
  sync: (meetingId: string) =>
    request<Record<string, number>>(`/promisemirror/sync/${meetingId}`, { method: "POST" }),
};

export const projectApi = {
  list: () => request<ProjectSummary[]>("/projects"),
  create: (name: string, description?: string) =>
    request<ProjectSummary>("/projects", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    }),
};

export const markupApi = {
  plans: () => request<PrepPlan[]>("/markup/plans"),
  plan: (id: string) => request<PrepPlan>(`/markup/plans/${id}`),
  prepareExisting: (projectId: string | null, title: string) =>
    request<PrepPlan>("/markup/prepare/existing", {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, title }),
    }),
  prepareNew: (intake: Record<string, string | null>) =>
    request<PrepPlan>("/markup/prepare/new", {
      method: "POST",
      body: JSON.stringify(intake),
    }),
  startPractice: (planId: string, persona: string) =>
    request<{ session_id: string; persona: string; opening: string }>(
      `/markup/plans/${planId}/practice`,
      { method: "POST", body: JSON.stringify({ persona }) },
    ),
  practiceReply: (sessionId: string, message: string) =>
    request<{ session_id: string; reply: string; turns: number }>(
      `/markup/practice/${sessionId}/reply`,
      { method: "POST", body: JSON.stringify({ message }) },
    ),
  finishPractice: (sessionId: string) =>
    request<{ feedback: string; strengths: string[]; improvements: string[] }>(
      `/markup/practice/${sessionId}/finish`,
      { method: "POST" },
    ),
  liveAnswer: (planId: string, question: string) =>
    request<{ answer: string }>(`/markup/plans/${planId}/live-answer`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
  configureLiveAssist: (
    planId: string,
    meetingId: string | null,
    enabled: boolean,
    answerOwnQuestions = false,
  ) =>
    request<{
      enabled: boolean;
      meeting_id: string | null;
      answer_own_questions: boolean;
    }>(`/markup/plans/${planId}/live-assist`, {
      method: "POST",
      body: JSON.stringify({
        meeting_id: meetingId,
        enabled,
        answer_own_questions: answerOwnQuestions,
      }),
    }),
  liveAssistStatus: (planId: string) =>
    request<{ enabled: boolean; state: "off" | "listening" | "waiting" | "ready"; question: string | null; answer: string | null }>(
      `/markup/plans/${planId}/live-assist`,
    ),
};

export const coachApi = {
  review: (meetingId: string, prepPlanId?: string) =>
    request<{ meeting_id: string; had_plan: boolean; count: number; notes: CoachNote[] }>(
      `/coach/${meetingId}/review`,
      { method: "POST", body: JSON.stringify({ prep_plan_id: prepPlanId ?? null }) },
    ),
  notes: () =>
    request<{ recurring_themes: [string, number][]; notes: CoachNote[] }>("/coach/notes"),
  ask: (meetingId: string, message: string, history: { role: "user" | "assistant"; content: string }[]) =>
    request<{ answer: string }>(`/coach/${meetingId}/ask`, {
      method: "POST",
      body: JSON.stringify({ message, history }),
    }),
  reject: (noteId: string, rejected: boolean) =>
    request<{ id: string; rejected: boolean }>(
      `/coach/notes/${noteId}/reject?rejected=${rejected}`,
      { method: "POST" },
    ),
};

export const progressApi = {
  get: (projectId?: string, assignedTo?: string) => {
    const params = new URLSearchParams();
    if (projectId) params.set("project_id", projectId);
    if (assignedTo) params.set("assigned_to", assignedTo);
    const q = params.toString();
    return request<ProgressData>(`/progress${q ? `?${q}` : ""}`);
  },
};

// --- My Team (manager-only, read-only) ------------------------------------

export interface TeamMemberRollup {
  user_id: string | null;
  name: string;
  email: string;
  role: string;
  is_you: boolean;
  total: number;
  pending: number;
  completed: number;
  overdue: number;
  next_due: string | null;
  percent: number;
}

export interface TeamOverview {
  manager: { id: string; name: string };
  members: TeamMemberRollup[];
  totals: { people: number; pending: number; completed: number; overdue: number };
}

export interface TeamCommitment {
  id: string;
  kind: string;
  text: string;
  status: string;
  spoken_owner: string | null;
  assigned_to: string | null;
  assigned_user_id: string | null;
  due_at: string | null;
  due_text: string | null;
  evidence: string | null;
  meeting_id: string | null;
  meeting_title: string | null;
  superseded_by_id: string | null;
  supersedes_id: string | null;
}

export interface TeamDeadlineItem {
  id: string;
  text: string;
  due_at: string;
  assigned_to: string;
  assigned_user_id: string | null;
  meeting_id: string | null;
}

export interface TeamProjectRollup {
  project_id: string | null;
  project_name: string;
  total: number;
  completed: number;
  pending: number;
  overdue: number;
  percent: number;
}

export const teamApi = {
  overview: (projectId?: string) =>
    request<TeamOverview>(
      `/team/overview${projectId ? `?project_id=${projectId}` : ""}`,
    ),
  commitments: (memberId?: string, statusFilter?: string) => {
    const params = new URLSearchParams();
    if (memberId) params.set("member_id", memberId);
    if (statusFilter) params.set("status_filter", statusFilter);
    const q = params.toString();
    return request<TeamCommitment[]>(`/team/commitments${q ? `?${q}` : ""}`);
  },
  deadlines: () =>
    request<{ overdue: TeamDeadlineItem[]; upcoming: TeamDeadlineItem[] }>(
      "/team/deadlines",
    ),
  findings: (memberId?: string) =>
    request<{ count: number; by_kind: Record<string, number>; findings: Finding[] }>(
      `/team/findings${memberId ? `?member_id=${memberId}` : ""}`,
    ),
  projects: () => request<TeamProjectRollup[]>("/team/projects"),
};
