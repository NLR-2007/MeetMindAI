# MeetMind AI

An AI meeting assistant that **remembers what was decided** and **helps you
communicate better next time**.

A bot joins your meeting, transcribes it live, and extracts the decisions,
owners and deadlines. Those commitments then persist across every meeting that
follows — so the promise you made three meetings ago still surfaces when it
matters.

> **Recording notice.** The bot joins as a visible participant named
> **MeetMind AI Notetaker**. Both the UI and the API refuse to dispatch it
> unless consent is explicitly confirmed. Tell every participant beforehand,
> respect your meeting platform's rules, and follow the recording consent laws
> that apply to you.

---

## What works

Everything below has been verified end to end against live services, not mocks.

| Capability | Status |
|---|---|
| Bot joins Google Meet / Zoom / Teams | ✅ |
| **Live transcript during the call** | ✅ streams via signed webhooks |
| Post-meeting summary, decisions, action items, deadlines | ✅ |
| **Hindsight persistent memory** | ✅ survives application restarts |
| PromiseMirror — commitments tracked across meetings | ✅ |
| Mark Up — pre-meeting briefing and AI practice | ✅ |
| **Live Assist** — drafts an answer when you are asked a question | ✅ |
| Personal coaching, scoped to your own words | ✅ |
| Manager / employee roles with read-only team view | ✅ |
| Google Calendar — deadlines pushed as events | ✅ |
| Whisper fallback when Recall produces no transcript | ⚠️ tested with mocks only |

**82 backend tests pass.** TypeScript and the production build are clean.

---

## Tech stack

Next.js 16 · TypeScript · Tailwind 4 · FastAPI · MySQL/MariaDB ·
Recall.ai (bot + transcripts) · Groq (summaries, Whisper) ·
**Hindsight** (agent memory) · NVIDIA NIM (LLM behind Hindsight) ·
Google Calendar API

---

## Setup (Windows)

You need **four** things running: MySQL, Hindsight, the backend, the frontend —
started in that order.

### 1. Secrets

```powershell
Copy-Item .env.example .env
```

Fill in `.env`. At minimum: `RECALL_API_KEY`, `GROQ_API_KEY`, `DATABASE_URL`,
`HINDSIGHT_LLM_API_KEY`.

`RECALL_REGION` must match the region your Recall key was created in — each
region is a separate deployment with separate credentials.

### 2. MySQL

Start **MySQL** in XAMPP, then create the database:

```powershell
& "C:\xampp\mysql\bin\mysql.exe" -u root -e "CREATE DATABASE IF NOT EXISTS meetmind CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
```

### 3. Backend dependencies

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

This pulls torch and transformers for Hindsight's local embedding and reranker
models — roughly **1.7 GB**, and slow the first time.

Then run the migrations, in order:

```powershell
.\.venv\Scripts\python.exe migrations\001_auth_and_ownership.py
.\.venv\Scripts\python.exe migrations\002_markup_promisemirror.py
.\.venv\Scripts\python.exe migrations\003_roles_and_assignment.py
.\.venv\Scripts\python.exe migrations\004_speaker_scoped_coaching.py
```

They are idempotent and safe to re-run.

### 4. Hindsight — start this BEFORE the backend

Hindsight runs as its own long-lived server. In a dedicated terminal:

```powershell
$env:PYTHONIOENCODING = "utf-8"        # its banner is Unicode; cp1252 crashes it
$env:HINDSIGHT_API_LLM_PROVIDER = "openai"
$env:HINDSIGHT_API_LLM_MODEL = "openai/gpt-oss-20b"
$env:HINDSIGHT_API_LLM_BASE_URL = "https://integrate.api.nvidia.com/v1"
$env:HINDSIGHT_API_LLM_API_KEY = "<your NVIDIA NIM key>"
$env:HINDSIGHT_API_PORT = "8888"
$env:HINDSIGHT_API_MODEL_INIT_TIMEOUT = "900"
D:\MicroSoft_Hackthon\backend\.venv\Scripts\hindsight-api.exe
```

Wait for `http://127.0.0.1:8888/health` to return 200. The first start loads
models and can take a few minutes; later starts are quicker.

**Leave this terminal open.** If Hindsight is down the backend still runs — it
falls back to MySQL memory and `/health` reports
`"hindsight_integrated": false` rather than pretending.

### 5. Backend

```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8001 --reload
```

Check <http://127.0.0.1:8001/health> shows `"hindsight_integrated": true`.

### 6. Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. Point it at the backend with
`NEXT_PUBLIC_API_BASE` in `frontend/.env.local` if you change the port.

### 7. Webhooks (optional, but needed for live transcript)

Recall must reach your machine:

```powershell
ngrok http 8001
```

Put the HTTPS URL in `.env` as `PUBLIC_BASE_URL`, and register
`<PUBLIC_BASE_URL>/webhooks/recall` in the Recall webhooks dashboard,
subscribed to `bot.done`.

Without this, transcripts still arrive **after** the meeting; live streaming
and automatic processing do not.

---

## Hindsight integration

Hindsight is the memory layer. MySQL remains the source of truth for structured
records; Hindsight holds the semantic memory that makes recall work.

**Where it plugs in.** `backend/app/services/memory.py` defines one interface:

```python
class MemoryService(abc.ABC):
    def save_memory(content, *, scope, scope_id, metadata) -> str
    def recall_memory(query, *, scope, scope_id, limit) -> list[dict]
```

`HindsightMemoryService` implements it; `MySQLMemoryService` is the fallback.
`get_memory_service()` is the single swap point.

**Scopes map to Hindsight banks** — `meeting-<id>`, `project-<id>` — so one
meeting's memories stay isolated exactly as they were under MySQL.

**What gets stored:** the summary, each decision, each action item with its
owner and due date, and each deadline.

**Why recall is better than the MySQL fallback**, measured on real data:

| Question | MySQL (lexical) | Hindsight (semantic) |
|---|---|---|
| "What did we agree about the database?" | returned the Groq decision ❌ | *"User wants to keep MySQL as the database for the demo"* ✅ |
| "Who is writing the docs?" | returned a generic summary ❌ | *"Bunny Reddy will write the project documentation, due 1 October"* ✅ |

Hindsight resolves "docs" → "documentation"; word-overlap cannot.

**Three implementation details worth knowing:**

1. Its sync client calls `asyncio.run()` internally, which fails inside a
   FastAPI request. Calls run on a worker thread, and the client is built
   *inside* that thread because its aiohttp session binds to the creating loop.
2. Retains use `retain_async=True`. Fact extraction is an LLM call per memory;
   done synchronously a single meeting took over 280 s, versus ~10 s queued.
3. Because extraction is queued, memories become searchable roughly **60 s**
   after processing.

---

## Using it

1. Sign in, paste a meeting link, tick the consent box, **Join meeting**
2. Admit **MeetMind AI Notetaker** from the waiting room
3. Watch the transcript appear live on the meeting page
4. Leave the meeting — with webhooks configured it processes itself
5. **Mark Up → Review** compares what you planned with what you said
6. **My Promises** shows commitments, including deadlines that moved

---

## Roles

| Role | Sees |
|---|---|
| **Employee** | only their own meetings, promises, progress and coaching |
| **Manager** | the same, plus **About My Team** — read-only |

A manager **cannot** mark a report's task complete: once a commitment is
assigned, only the assignee may close it. Recording a meeting does not make its
promises yours.

Employees supply their manager's email at registration; that is what scopes
name-matching, so a "Bunny" in another team can never be matched.

---

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/auth/register`, `/auth/login` | Accounts and JWTs |
| `GET` | `/auth/me`, `/auth/team` | Profile, visible team |
| `POST` | `/meetings/join` | Dispatch the notetaker |
| `GET` | `/meetings`, `/meetings/{id}` | History and detail |
| `POST` | `/meetings/{id}/process` | Transcript + Groq analysis |
| `POST` | `/meetings/{id}/chat` | Ask about one meeting |
| `POST` | `/webhooks/recall` | Status events (Svix-signed) |
| `POST` | `/webhooks/recall/realtime` | Live transcript chunks |
| `GET` | `/promisemirror/findings`, `/timeline` | Commitment intelligence |
| `POST` | `/markup/prepare/existing`, `/new` | Build a briefing |
| `POST` | `/markup/plans/{id}/practice` | AI rehearsal |
| `GET` | `/markup/plans/{id}/live-assist` | Live Assist state |
| `POST` | `/coach/{meeting_id}/review` | Speaker-scoped coaching |
| `GET` | `/progress`, `/team/overview` | Dashboards |

---

## Design decisions

**Refuse rather than guess.** An ambiguous speaker name leaves a commitment
unassigned. Coaching is refused outright if you cannot be found in the
transcript, rather than reviewing someone else's words as yours.

**Verify in code, not only in prompts.** Coaching quotes are checked against
the user's own transcript lines; a suggestion quoting another speaker is
discarded even if the model produced it.

**404, not 403,** for another user's resources — confirming something exists is
itself a disclosure.

**Date arithmetic is deterministic.** The LLM was unreliable at it, so spoken
dates resolve in Python against the meeting date. "3rd of October" → `2026-10-03`.

**Transcription language is pinned to `en`.** Recall's `auto` detection flipped
to Hindi mid-meeting on accented English and emitted Devanagari.

---

## Known limitations

- **Speech-to-text mangles product names and Indian names** — "Hindsight" →
  "Insight", "Bunny" → "Pani". The mechanism is right; the transcription is not.
- **Speaker identity comes from the meeting platform's display name**, not
  voice. If your Meet name differs from your MeetMind aliases, attribution
  fails — deliberately, rather than guessing.
- **Whisper fallback is untested on real audio.** Recall's transcript has
  always succeeded, so that path has only ever run against mocks.
- **Live Assist is heuristic.** It detects questions by sentence shape and
  addressee by name, so an unaddressed question may still prompt an answer.
- **Free ngrok URLs change on restart**, breaking webhooks until re-registered.
