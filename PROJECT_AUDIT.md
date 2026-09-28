# MeetMind AI — Project Audit

**Date:** 27 September 2026
**Auditor:** senior full-stack / QA / AI-systems review
**Scope:** read-only inspection. No application code was modified during this audit.
**Deadline under review:** 29 September 2026 (2 days remaining)

---

## Verdict at a glance

| # | Feature | Status |
|---|---------|--------|
| 1 | Automatic meeting joining (Recall.ai) | **PASS** |
| 2 | AI meeting summaries (Groq) | **PASS** |
| 3 | Deadline extraction → Google Calendar | **PARTIAL** |
| 4 | Meeting chatbot | **PASS** |
| 5 | MySQL persistence | **PARTIAL** |
| 6 | Frontend | **PARTIAL** |
| 7 | Hindsight persistent memory | **MISSING** (interface ready) |
| 8 | Authentication / multi-user isolation | **MISSING** |

**Automated checks:** 41/41 backend tests pass · TypeScript clean · production build succeeds · 6 ESLint errors.

**Headline risks:** no authentication of any kind; the webhook tunnel is currently dead; `python-dateutil` is missing from `requirements.txt` so a fresh install breaks.

---

## 1. Technology stack — verified

| Layer | Declared | Actual | Status |
|---|---|---|---|
| Frontend | Next.js | Next.js **16.3.6**, React 19.2.8, TypeScript, Tailwind **4** | PASS |
| Backend | FastAPI | FastAPI **0.115.6**, uvicorn 0.34.0, Pydantic 2.10.4 | PASS |
| Database | MySQL | **MariaDB 10.4.32** via XAMPP, SQLAlchemy 2.0.36 + PyMySQL 1.1.1 | PASS |
| Meetings | Recall.ai | REST v1 + Calendar v2, region `us-west-2` | PASS |
| AI | Groq | `openai/gpt-oss-120b`, `whisper-large-v3` | PASS |
| Calendar | Google Calendar API | OAuth 2.0 + Calendar v3 | PASS |
| Memory | Hindsight | **not present** — MySQL stand-in behind an interface | MISSING |

### Live connectivity (read-only probes)

```
Recall REST      /api/v1/bot/           HTTP 200
Recall Calendar  /api/v2/calendars/     HTTP 200
Groq             /openai/v1/models      HTTP 200
Backend          /health                HTTP 200
Frontend         :3000                  HTTP 200
ngrok tunnel     /health                HTTP 404   ← BROKEN
```

`/health` reports: `database_reachable: true`, `groq_configured: true`,
`recall_webhook_secret_present: true`, `google_oauth_ready: true`,
`hindsight_integrated: false`.

### Issue 1.1 — `python-dateutil` missing from requirements.txt — **CRITICAL**

- **File:** `backend/requirements.txt`
- **Used by:** `backend/app/services/meeting_service.py` → `resolve_due_date()`
- **Detail:** `dateutil` is installed in the local venv but never declared. A clean
  `pip install -r requirements.txt` produces an `ImportError` the first time a
  deadline is parsed — i.e. on any meeting that mentions a date.
- **Severity:** Critical. Breaks the demo on any fresh machine.
- **Fix:** add `python-dateutil==2.9.0.post0` to `requirements.txt`.

### Issue 1.2 — project is not under version control — **HIGH**

- **Detail:** no `.git` at the project root. A nested repo exists in `frontend/`
  (created by `create-next-app`). The root `.gitignore` therefore protects nothing.
- **Severity:** High. No rollback two days before a deadline; `.env` is unprotected
  if the folder is ever shared or zipped.
- **Fix:** `git init` at root, verify `.env` is ignored, remove `frontend/.git`,
  commit.

---

## 2. Feature verification

### Feature 1 — Automatic meeting joining · **PASS**

Verified end to end against live Google Meet calls, not mocks.

Observed lifecycle on bot `dc04a559-…`:

```
joining_call → in_waiting_room → in_call_not_recording
→ in_call_recording → call_ended → recording_done → done
```

| Check | Result | Evidence |
|---|---|---|
| Create bot | PASS | `POST /api/v1/bot/` → 201, 3 live meetings |
| Auth scheme | PASS | `Authorization: Token …` (not Bearer) — verified against docs |
| Status reporting | PASS | `status_changes[]` persisted and surfaced |
| Leave call | PASS | `leave_call/` → `call_ended (bot_received_leave_call)` |
| Transcript retrieval | PASS | 43-, 53- and 135-word transcripts with speaker names |
| Webhook signature verification | PASS | valid Svix sig → 200; unsigned → 401; forged → 401; stale timestamp → 401 |
| Automatic post-meeting processing | PASS | verified from Recall's own IP `52.24.126.164` |
| Error handling | PASS | Recall 4xx surfaced as 502 with upstream detail, not a bare 500 |

**Files:** `app/services/recall.py`, `app/routers/meetings.py`, `app/routers/webhooks.py`

#### Issue 2.1 — webhook tunnel is dead — **CRITICAL (demo blocker)**

- **File:** `.env` → `PUBLIC_BASE_URL=https://additionally-apposite-pedro.ngrok-free.dev`
- **Detail:** that URL now returns an ngrok error page. Recall cannot deliver
  webhooks, so **automatic post-meeting processing is currently broken**. The
  code is correct and was proven working; only the tunnel is gone.
- **Severity:** Critical for a live demo. Users must press "Get transcript &
  summary" manually.
- **Fix:** restart `ngrok http 8000`, update `PUBLIC_BASE_URL`, re-register the
  endpoint in the Recall dashboard. Free ngrok URLs change on every restart —
  budget for redoing this immediately before the demo, or use a reserved domain.

#### Issue 2.2 — webhook handler swallows processing failures — **LOW**

- **File:** `app/routers/webhooks.py:118-124`
- **Detail:** deliberate (`except Exception` → log, still return 200) so Recall
  does not retry half-finished work. Correct choice, but a permanently failing
  meeting is invisible outside the logs.
- **Fix:** persist a `processing_error` column and surface it in the UI.

---

### Feature 2 — AI meeting summaries · **PASS**

Verified on three real transcripts.

| Check | Result | Notes |
|---|---|---|
| Real transcript reaches the model | PASS | `plain_text` built from Recall utterances |
| Summary quality | PASS | accurate on all three meetings |
| Decisions | PASS | 2 distinct decisions extracted correctly |
| Action items | PASS | 3 extracted with tasks and due text |
| Speaker attribution | PASS | participants stored with `is_host` |
| Owner assignment | PASS | `Bunny Reddy`, `Lokesh` correctly attached |
| Refuses to invent | PASS | empty arrays when nothing was discussed |
| JSON reliability | PASS | `response_format: json_object` |
| Graceful LLM failure | PASS | transcript still saved if Groq fails |

**Reasoning-model handling (good):** `gpt-oss-120b` returns a `reasoning` field
that shares the `max_tokens` budget. `GROQ_MAX_TOKENS=4096` and an explicit
empty-content guard in `groq_client.py:105-112` prevent silent empty summaries.

#### Issue 2.3 — speech-to-text errors propagate into stored records — **MEDIUM**

- **Evidence:** "hackathon" → "akathon"; "Bunny" → "Pani"; "Lokesh" → "locus";
  "on the task, Lokesh" → owner `task location`.
- **Mitigation already present:** known-participant hints recover most names, and
  the guard returns `null` rather than guessing when ambiguous.
- **Residual risk:** summaries can still contain garbled nouns. Accept for the
  hackathon; note it verbally in the demo.

#### Issue 2.4 — no de-duplication between action items and deadlines — **MEDIUM**

- **File:** `app/services/meeting_service.py` (persist block)
- **Evidence:** one meeting produced "record the demo video" as both an action
  item **and** a deadline, with conflicting dates (13 Sep vs 30 Sep) drawn from a
  self-correction in speech.
- **Impact:** duplicate and contradictory rows; duplicate calendar events.
- **Fix:** de-duplicate on normalised `(text, date)` before insert; prefer the
  later-mentioned date when a speaker corrects themselves.

---

### Feature 3 — Deadline extraction → Google Calendar · **PARTIAL**

| Check | Result | Notes |
|---|---|---|
| Deadline extraction | PASS | 5 deadlines across meetings |
| Date normalisation | PASS | `28-9-2026` → `2026-09-28`; `3rd of October` → `2026-10-03` |
| Relative dates | PASS | resolved against the meeting date |
| Refuses vague dates | PASS | "soon", "later this quarter" → `null` |
| Google OAuth | PASS | offline + `prompt=consent`; CSRF state with 10-min TTL |
| Event creation | PASS | 7 events verified present via Google's own API |
| Duplicate prevention | PARTIAL | idempotent per row; **not** across meetings |
| **Times and time zones** | **MISSING** | all-day events only |
| Error handling | PASS | read-only token → actionable 502 |

#### Issue 3.1 — no time-of-day or time-zone support — **HIGH (explicitly requested)**

- **File:** `app/services/calendar.py:224-260` (`create_all_day_event`)
- **Detail:** only `start.date` / `end.date` are written. "29th **afternoon**" and
  "29th **evening**" were captured in `due_text` but both became the same all-day
  event. `Deadline.due_at` is a tz-naive `DateTime`; no IANA zone is stored anywhere.
- **Severity:** High — the audit brief explicitly asks for dates, **times** and
  **time zones**.
- **Fix:** have the model emit `time` and `timezone`; add a `timezone` column;
  write `start.dateTime` + `timeZone` when a time is known, falling back to
  all-day otherwise.

#### Issue 3.2 — duplicate calendar events across re-analysis — **MEDIUM**

- **Evidence:** the calendar holds both `hard deadline for the whole hackathon
  submission` and `hard hackathon submission` on 2026-10-03 — the same deadline,
  reworded by a later analysis run.
- **Partially fixed:** `_deadline_key()` now preserves `google_event_id` across
  reprocessing when title+date match. Wording changes still orphan the old event.
- **Fix:** match on meeting + date alone, or delete orphans instead of logging.

#### Issue 3.3 — dedicated "MeetMind AI" calendar not yet active — **MEDIUM**

- **File:** `app/services/calendar.py` → `ensure_meetmind_calendar()`
- **Detail:** implemented and unit-tested, but requires the wider
  `https://www.googleapis.com/auth/calendar` scope. The stored grant is still
  `calendar.events`, so creation fails with a clear message. All 7 existing events
  sit on the user's **primary** calendar and `deadlines.google_calendar_id` is NULL.
- **Fix:** reconnect Google Calendar once to upgrade the grant.

#### Issue 3.4 — past-dated deadline accepted — **LOW**

- **Evidence:** `record the demo video` → `2027-09-13`.
- **Cause:** speaker said "13th of September" then corrected to "30th". The
  model's explicit ISO date wins over the roll-forward rule.
- **Fix:** covered by the de-duplication fix in Issue 2.4.

---

### Feature 4 — Meeting chatbot · **PASS**

| Check | Result | Evidence |
|---|---|---|
| Answers from the correct transcript | PASS | correctly listed owners and dates |
| Conversation history | PASS | 30 rows in `chat_messages`, scoped per meeting |
| No cross-meeting leakage | PASS | context built from one meeting only |
| Handles unanswerable questions | PASS | *"the transcript and summary do not include any information about a project budget"* |
| Context-switch detection | PASS | returns `context_switch_required: true` |
| User confirmation before switching | PASS | no answer produced until confirmed |
| Requires processed meeting | PASS | 409 with remediation text |
| Groq unavailable | PASS | 503, not a 500 |

**Context isolation** (`meeting_service.build_chat_context`) draws solely from the
single `Meeting` row, its transcript, summary, action items and deadlines, plus
memories filtered by `scope_id == meeting.id`. A test asserts memories in scope
`A` are invisible from scope `B`.

#### Issue 4.1 — context-switch detection is substring matching — **LOW**

- **File:** `app/routers/chat.py:129-141` (`_referenced_other_meeting`)
- **Detail:** matches a meeting title of >4 chars appearing in the message. Titles
  such as "Testing" would false-positive against ordinary sentences; unnamed
  meetings are never detected.
- **Fix:** require a stronger signal, or ask the model to classify intent.

#### Issue 4.2 — transcript truncation keeps only the tail — **LOW**

- **File:** `app/services/meeting_service.py` → `build_chat_context`, 24 000 chars
- **Detail:** long meetings silently lose their opening. Fine at current sizes
  (135 words); would matter for a 60-minute meeting.
- **Fix:** summarise-then-stuff, or retrieve relevant chunks — naturally solved by
  Hindsight.

---

### Feature 5 — MySQL · **PARTIAL**

11 tables created. Schema, relationships and cascades are sound.

```
action_items   7 rows   fk → meetings
calendars      1        fk → users
chat_messages 30        fk → meetings
deadlines      5        fk → meetings
meetings       4        fk → users, projects
memories      22        NO FK
participants   4        fk → meetings
projects       0
summaries      4        fk → meetings (unique)
transcripts    4        fk → meetings (unique)
users          0
```

**Good:** unique `bot_id` (webhook routing), unique `meeting_id` on transcripts and
summaries (1:1 enforced), `uq_participant_per_meeting`, indexes on `bot_id`,
`recording_id`, `status`, `MEDIUMTEXT` for transcripts, `pool_pre_ping` for XAMPP's
idle disconnects.

#### Issue 5.1 — no meeting is associated with a user or project — **CRITICAL**

- **Evidence:** `users = 0`, `projects = 0`, `owner_id IS NULL` on **4 of 4**
  meetings, `project_id IS NULL` on 4 of 4.
- **Detail:** the columns and FKs exist, but nothing ever writes them. The audit
  brief asks to confirm every meeting is associated with the correct user and
  project — **it is not**.
- **Severity:** Critical for the stated requirement.
- **Fix:** see Issue 8.1.

#### Issue 5.2 — `memories` has no foreign key — **MEDIUM**

- **File:** `app/models.py` → `Memory.scope_id` is a plain `String(64)`
- **Detail:** deliberate, so the table can later hold project- or user-scoped
  memories. Consequence: deleting a meeting leaves its memories behind — MySQL
  cannot cascade. Currently 0 orphans, but only because nothing has been deleted.
- **Fix:** add a cleanup step on meeting delete, or a nullable FK for the
  meeting-scoped case.

#### Issue 5.3 — no migration tooling — **MEDIUM**

- **Detail:** schema is created by `Base.metadata.create_all()`, which **never
  alters existing tables**. Four columns (`google_refresh_token`,
  `google_event_id`, `google_event_link`, `meetmind_calendar_id`,
  `google_calendar_id`) had to be added by hand-written `ALTER TABLE` during
  development. Any further model change silently fails to apply.
- **Fix:** adopt Alembic, or ship a documented `migrate.py`.

#### Issue 5.4 — timestamps are timezone-naive — **LOW**

- **Detail:** values are written as UTC via `datetime.now(timezone.utc)` but stored
  in `DATETIME`, losing the offset. Renders correctly today; will mislead once
  users are in multiple zones. Related to Issue 3.1.

---

### Feature 6 — Frontend · **PARTIAL**

Pages: `/` (dashboard), `/meetings/[id]`, `/calendar`, `/chat`.

| Check | Result | Notes |
|---|---|---|
| Meeting URL submission | PASS | validates Meet/Zoom/Teams |
| Recording consent gate | PASS | checkbox disables submit; backend rejects independently |
| Meeting status | PASS | polls while live, stops at terminal state |
| Transcript display | PASS | scrollable, word count |
| Summary / decisions / action items | PASS | per-section empty states |
| Deadline highlighting | PARTIAL | listed with dates and calendar badges; **not visually emphasised by urgency** |
| Calendar integration | PASS | connect, event list, schedule, deadline push |
| Meeting history | PASS | newest first, status badges |
| Chatbot | PASS | dedicated `/chat` plus per-meeting panel |
| Loading states | PASS | spinners throughout |
| Error messages | PASS | dismissible banners; backend-down message names the fix |
| Navigation | PASS | dashboard links to both sections |
| Responsiveness | PARTIAL | grids collapse at `lg`; **not verified below 640 px** |
| Dark mode | PASS | tokens for both themes |
| Type safety | PASS | `tsc --noEmit` clean |
| Production build | PASS | 6 routes |

#### Issue 6.1 — 6 ESLint errors — **MEDIUM**

- `app/calendar/page.tsx:28, 45, 57, 69` — `react-hooks/set-state-in-effect`
- `app/chat/page.tsx:53` — `react-hooks/set-state-in-effect`
- `app/chat/page.tsx:66` — `react-hooks/purity` (`Date.now()` during render)
- **Impact:** does not block the build; React 19 may behave unpredictably on
  re-render. `Date.now()` is used for temporary optimistic-message ids.
- **Fix:** move `Date.now()` into an event handler or use `useId()`; move state
  initialisation out of effects.

#### Issue 6.2 — deadlines not visually prioritised — **LOW**

- Brief asks for "deadline highlighting". Dates render in muted grey with no
  colour coding for overdue / imminent.
- **Fix:** red for past, amber for ≤48 h, neutral otherwise.

#### Issue 6.3 — mobile layout unverified — **LOW**

- Only desktop widths were exercised. `h-[620px]` on the chat panel is a fixed
  height that may overflow small screens.

---

## 3. End-to-end workflow trace

| # | Step | Status | Risk |
|---|---|---|---|
| 1 | User submits meeting URL | PASS | — |
| 2 | Recall joins | PASS | needs manual admission from the waiting room |
| 3 | Meeting transcribed | PASS | STT accuracy (Issue 2.3) |
| 4 | Transcript reaches backend | **PARTIAL** | **tunnel down (Issue 2.1)** → manual trigger |
| 5 | Groq processes | PASS | — |
| 6 | Notes/decisions/tasks/deadlines | PASS | duplication (Issue 2.4) |
| 7 | Saved to MySQL | **PARTIAL** | no user/project association (Issue 5.1) |
| 8 | Deadlines → Google Calendar | PARTIAL | all-day only (Issue 3.1) |
| 9 | User opens a meeting and asks | PASS | — |
| 10 | Chatbot retrieves correct meeting | PASS | verified isolated |

### Where data can be lost, duplicated or misattributed

| Risk | Where | Severity |
|---|---|---|
| **Misattribution — every meeting is unowned; any caller sees all meetings** | no auth layer | **CRITICAL** |
| Lost — webhook undeliverable while the tunnel is down; no retry after Recall gives up | `PUBLIC_BASE_URL` | **CRITICAL** |
| Duplicated — reworded deadlines orphan their calendar event and a new one is created | `meeting_service` / `calendar` | MEDIUM |
| Duplicated — the same commitment stored as both action item and deadline | persist block | MEDIUM |
| Lost — re-analysis deletes and recreates derived rows; a manual edit to an action item would be destroyed | `process_completed_meeting` | MEDIUM |
| Lost — transcript head truncated beyond 24 000 chars | `build_chat_context` | LOW |
| Orphaned — memories survive meeting deletion | `memories`, no FK | LOW |

---

## 4. Hindsight readiness

**Status: MISSING — but the seam is built and honest about itself.**

`/health` reports `"hindsight_integrated": false`, and
`MySQLMemoryService.is_persistent_memory_backend` is `False`. A test asserts the
code never claims otherwise.

### What exists

`backend/app/services/memory.py` defines an ABC:

```python
class MemoryService(abc.ABC):
    def save_memory(content, *, scope, scope_id, metadata) -> str
    def recall_memory(query, *, scope, scope_id, limit) -> list[dict]
```

`MySQLMemoryService` implements it against the `memories` table (22 rows, all
scope `meeting`). `get_memory_service(db)` is the single swap point — one function.

Write path: `meeting_service.process_completed_meeting` saves the summary and each
decision. Read path: `routers/chat.py` recalls the top 5 into chat context.

### Capability assessment

| Capability | Supported today | Gap |
|---|---|---|
| Separate meeting/project memory | **Partial** | `scope`/`scope_id` exist; only `"meeting"` ever used |
| Persistent across conversations | **Yes** | survives restarts in MySQL |
| Saving verified decisions | **Yes** | summary + decisions written on processing |
| Retrieving relevant past discussions | **No** | keyword `LIKE`-style ranking, not semantic; scoped to one meeting so cross-meeting recall is impossible |
| Tracking updated deadlines / superseded decisions | **No** | append-only; no supersession model |
| Controlled context switching | **Yes** | confirmation flow implemented and tested |

### Integration plan

1. **Add `HindsightMemoryService(MemoryService)`** in `app/services/memory.py` —
   same two methods. No caller changes.
2. **Flip the factory** in `get_memory_service()`, chosen by a
   `MEMORY_BACKEND=hindsight|mysql` env var so it can be reverted mid-demo.
3. **Widen scopes** — start writing `scope="project"` and `scope="user"`, already
   supported by the column.
4. **Cross-meeting recall** — in `chat.py`, call `recall_memory` at project scope
   and label those results clearly so the meeting-isolation guarantee stays intact.
5. **Supersession** — add `superseded_by` / `valid_from` to `Memory`; on each
   processing run, mark prior decisions on the same topic superseded.
6. **Dual-write during cutover** — write to both backends, read from Hindsight,
   so MySQL remains a fallback.

**Files to touch:** `memory.py` (new class + factory), `config.py` (one env var),
`chat.py` (optional project-scope recall). **No changes to routers, models or
frontend.**

---

## 5. Security and reliability

| Control | Status | Notes |
|---|---|---|
| **Authentication** | **MISSING** | no login, no session, no token anywhere |
| **Authorization** | **MISSING** | no endpoint filters by user |
| **Meeting access control** | **MISSING** | any caller can read any meeting |
| API keys server-side only | **PASS** | no secrets in frontend source; only `NEXT_PUBLIC_API_BASE` is exposed |
| `.env` gitignored | PASS | but the root is not a git repo (Issue 1.2) |
| SQL injection | **PASS** | SQLAlchemy ORM throughout; the only `text()` is a literal `SELECT 1` |
| Webhook verification | **PASS** | Svix HMAC; fail-closed; replay protection confirmed |
| Recording consent | **PASS** | enforced in UI *and* backend validator; also on calendar scheduling |
| Calendar permissions | PASS | minimal scope for each capability; secret never leaves the server |
| CORS | PARTIAL | restricted to `localhost:3000`, but `allow_methods=["*"]` with credentials |
| Error disclosure | PARTIAL | upstream provider errors are passed to the client verbatim |

### Issue 8.1 — no authentication; total absence of tenant isolation — **CRITICAL**

- **Files:** every route in `app/routers/`
- **Detail:** `GET /meetings` returns **all** meetings. `GET /meetings/{id}` needs
  only a guessable-by-listing id. `POST /meetings/{id}/chat` will answer questions
  about anyone's transcript. `GET /calendar` exposes connected accounts.
- **Answer to the brief's question — "could one user retrieve another user's
  private meeting information?"** **Yes, trivially.** There are no users, so every
  caller is effectively the same super-user.
- **Mitigating context:** binds to `127.0.0.1` only. **However**, `PUBLIC_BASE_URL`
  exposes the backend through ngrok — while that tunnel is up, **the entire API is
  reachable from the public internet with no authentication**. Only
  `/webhooks/recall` is protected.
- **Fix (minimum for the hackathon):** add a single-user session or a shared
  `X-API-Key` header checked by a FastAPI dependency, and restrict the ngrok tunnel
  to the webhook path.
- **Fix (proper):** real auth, populate `users`, set `owner_id` on create, and
  filter every query by the current user.

### Issue 8.2 — upstream error text returned to clients — **LOW**

- **Files:** `meetings.py:78-82`, `calendar.py` (several)
- **Detail:** Recall/Google error bodies are echoed in `detail`. Helpful in
  development; could disclose internals in production.

---

## 6. Test execution results

| Check | Command | Result |
|---|---|---|
| Backend tests | `pytest -q` | **41 passed** |
| Type checking | `tsc --noEmit` | **clean** |
| Linting | `eslint .` | **6 errors** (Issue 6.1) |
| Production build | `npm run build` | **success**, 6 routes |
| Backend lint | — | **no linter configured** (no ruff/flake8/mypy) |

### Coverage by area

| Area | Tests | Verified live |
|---|---|---|
| URL validation / consent gate | 5 | yes |
| Bot dispatch payload | 3 | yes |
| Transcript + analysis pipeline | 3 | yes |
| Whisper fallback | 2 | **no — mocks only** |
| Webhook verification | 3 | yes |
| Chat + context switching | 5 | yes |
| MemoryService | 3 | yes |
| Calendar OAuth / events / scheduling | 8 | partially |
| Date resolution | 2 | yes |

#### Issue 9.1 — Whisper fallback never run on real audio — **UNVERIFIED**

- **File:** `app/services/groq_client.py` → `transcribe_audio()`
- **Detail:** logic is covered by mocked tests, but Recall's transcript has
  succeeded every time, so the real path has never executed. The 24 MB cap and
  the multipart upload shape are untested against Groq.
- **Fix:** create one bot with `transcription: false`, then process it.

#### Issue 9.2 — `schedule_bot` on a calendar event never exercised live — **UNVERIFIED**

- **File:** `app/routers/calendar.py:227`
- **Detail:** blocked throughout testing because no synced calendar event had a
  Google Meet link. Payload shape is asserted against the documented schema.
- **Fix:** create one calendar event **with Google Meet attached**, then schedule.

#### Issue 9.3 — no backend linter or type checker — **LOW**

- Frontend has `tsc` + ESLint; backend has neither. Add `ruff` and `mypy`.

---

## 7. Summary

### 7.1 Completed and verified

1. Recall.ai bot joins Google Meet; full lifecycle tracked
2. Transcript retrieval with speaker identification
3. Groq summaries, decisions, action items, owner assignment
4. Webhook signature verification (fail-closed, replay-protected)
5. Automatic post-meeting processing (proven from Recall's servers)
6. Meeting-scoped chatbot with confirmed context switching
7. Deadline extraction with deterministic date normalisation
8. Google OAuth + deadline push (7 events verified in Google)
9. MySQL persistence across 11 tables
10. Next.js dashboard, meeting detail, calendar and chat pages
11. Consent enforced in two independent layers

### 7.2 Implemented but unverified

1. Whisper fallback (mocks only) — Issue 9.1
2. Scheduling a bot from a calendar event — Issue 9.2
3. Dedicated "MeetMind AI" calendar (needs scope upgrade) — Issue 3.3
4. Mobile/responsive layout — Issue 6.3

### 7.3 Bugs and incomplete features

| Severity | Issue |
|---|---|
| **CRITICAL** | 8.1 No authentication — any caller reads every meeting, publicly reachable via ngrok |
| **CRITICAL** | 2.1 Webhook tunnel dead — auto-processing broken |
| **CRITICAL** | 1.1 `python-dateutil` missing from requirements |
| **CRITICAL** | 5.1 No meeting is linked to a user or project |
| **HIGH** | 3.1 No time-of-day or time-zone support for deadlines |
| **HIGH** | 1.2 Not under version control |
| MEDIUM | 2.4 Action-item/deadline duplication with conflicting dates |
| MEDIUM | 3.2 Duplicate calendar events after re-analysis |
| MEDIUM | 3.3 Dedicated calendar inactive pending reconnect |
| MEDIUM | 5.3 No migration tooling |
| MEDIUM | 6.1 Six ESLint errors |
| MEDIUM | 2.3 STT errors propagate into stored records |
| LOW | 4.1, 4.2, 5.2, 5.4, 6.2, 6.3, 8.2, 9.3 |

### 7.4 Missing hackathon requirements

1. **Hindsight** — mandatory, not integrated (interface ready)
2. **Authentication / multi-user** — users and projects tables are empty
3. **Deadline times and time zones** — explicitly requested
4. **Deadline highlighting in the UI** — listed but not visually prioritised

### 7.5 Ordered fix plan

**P0 — before anything else (≈1 hour)**

1. Add `python-dateutil==2.9.0.post0` to `requirements.txt` *(2 min)*
2. `git init` at root; confirm `.env` ignored; commit *(10 min)*
3. Restart ngrok; update `PUBLIC_BASE_URL`; re-register the Recall webhook *(10 min)*
4. Add an `X-API-Key` dependency across all non-webhook routes *(30 min)*

**P1 — required requirements (≈4 hours)**

5. Integrate Hindsight behind `MemoryService`; keep MySQL as fallback *(2 h)*
6. Seed a default user + project; set `owner_id` on meeting create; filter queries *(1 h)*
7. Add time + time-zone support to deadlines *(1 h)*

**P2 — correctness (≈2 hours)**

8. De-duplicate action items against deadlines; prefer corrected dates *(45 min)*
9. Delete orphaned calendar events instead of logging *(30 min)*
10. Reconnect Google to activate the dedicated calendar; migrate the 7 events *(20 min)*
11. Fix the 6 ESLint errors *(20 min)*

**P3 — polish (≈2 hours)**

12. Deadline urgency colour-coding *(20 min)*
13. Verify Whisper fallback on real audio *(30 min)*
14. Verify calendar bot scheduling with a Meet-linked event *(20 min)*
15. Check mobile layout *(30 min)*
16. Add `ruff` + `mypy` *(20 min)*

### 7.6 Tasks remaining before 29 September

**Must have:** P0 items 1–4, plus Hindsight (5), user/project association (6),
and deadline times (7). **Estimated: 5 hours.**

**Should have:** P2 items 8–11. **Estimated: 2 hours.**

**Nice to have:** P3. **Estimated: 2 hours.**

**Total to a defensible submission: ~7 hours of focused work.**

---

## Auditor's note

The engineering quality here is above what the feature list implies: signature
verification fails closed, the consent gate is enforced twice, date arithmetic was
moved out of the LLM once it proved unreliable, and the code declines to claim
Hindsight works when it does not. The verified core — join, transcribe, summarise,
persist, chat — is genuinely working against live services, not mocked.

The gaps are concentrated in two places: **there is no concept of a user**, which
makes every isolation guarantee vacuous, and **Hindsight**, which the hackathon
requires. Both are addressable in the time remaining. Fix the authentication gap
before the tunnel is public again.
