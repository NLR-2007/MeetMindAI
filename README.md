# MeetMind AI

AI-powered meeting assistant. A Recall.ai bot joins your meeting, records and
transcribes it, and Groq turns the transcript into a summary, decisions,
action items and deadlines. You can then chat with each meeting individually.

> **Recording notice.** The bot is a visible participant named
> **MeetMind AI Notetaker**. It records and transcribes. Both the UI and the
> API refuse to dispatch a bot unless consent is explicitly confirmed. Tell
> every participant before joining, respect your meeting platform's rules, and
> follow the recording consent laws that apply to you.

## Status

| Milestone | State |
|---|---|
| 1. Project setup, bot joins Google Meet | ✅ verified live |
| 2. MySQL + SQLAlchemy models | ✅ 10 tables created |
| 3. Transcript retrieval + webhooks | ✅ transcript verified live; webhook needs a secret |
| 4. Groq summary / decisions / action items | ✅ verified on a real transcript |
| 5. Next.js dashboard | ✅ builds and renders |
| 6. Meeting-scoped chat + MemoryService | ✅ verified live |
| 7. Calendar-based scheduling | ✅ built; needs a live Google connect to verify |
| 8. Whisper fallback | ✅ wired and tested |
| 9. Hindsight persistent memory | ❌ **not integrated** |

## Tech stack

Next.js 16 + TypeScript + Tailwind 4 (frontend) · FastAPI (backend) · MySQL ·
Recall.ai (bot + transcripts) · Groq (LLM + Whisper fallback) · Hindsight (later)

## Layout

```
.
├── .env                      # real secrets — gitignored, never commit
├── .env.example              # template
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app, CORS, lifespan, /health
│   │   ├── config.py         # env loading + validation
│   │   ├── db.py             # SQLAlchemy engine/session
│   │   ├── models.py         # users, projects, meetings, participants,
│   │   │                     # transcripts, summaries, action_items,
│   │   │                     # deadlines, chat_messages, memories
│   │   ├── schemas.py        # request/response models, URL validation
│   │   ├── routers/
│   │   │   ├── meetings.py   # join / status / detail / process / leave
│   │   │   ├── chat.py       # meeting-scoped chat
│   │   │   └── webhooks.py   # Recall webhooks + signature verification
│   │   └── services/
│   │       ├── recall.py         # Recall.ai REST client
│   │       ├── transcripts.py    # transcript download + normalisation
│   │       ├── groq_client.py    # analysis, chat, Whisper fallback
│   │       ├── meeting_service.py# orchestration
│   │       └── memory.py         # MemoryService (MySQL today, Hindsight later)
│   ├── tests/
│   └── requirements.txt
└── frontend/
    ├── app/
    │   ├── page.tsx                  # dashboard: join form + history
    │   └── meetings/[id]/page.tsx    # detail: summary, items, transcript, chat
    ├── components/
    └── lib/api.ts                    # typed API client
```

## Setup (Windows + VS Code)

Open a **PowerShell** terminal in VS Code (`` Ctrl+` ``) at the repo root.

### 1. Secrets

```powershell
Copy-Item .env.example .env
```

Fill in `.env`:

```
RECALL_API_KEY=your_actual_api_key
RECALL_REGION=us-west-2
GROQ_API_KEY=your_groq_api_key
DATABASE_URL=mysql+pymysql://root:@127.0.0.1:3306/meetmind?charset=utf8mb4
```

`RECALL_REGION` must match the region the key was created in — each Recall
region is a separate deployment with separate credentials.

### 2. MySQL (XAMPP)

Start **MySQL** from the XAMPP Control Panel, then create the database:

```powershell
& "C:\xampp\mysql\bin\mysql.exe" -u root -e "CREATE DATABASE IF NOT EXISTS meetmind CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
```

Tables are created automatically on backend startup.

### 3. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

- Health: http://127.0.0.1:8000/health
- API docs: http://127.0.0.1:8000/docs

### 4. Frontend

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

### 5. Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

Tests run against throwaway SQLite and mock every Recall/Groq call, so they
never spend bot minutes or tokens.

## Using it

1. Open the dashboard, paste a meeting link, tick the consent checkbox, click
   **Join meeting**.
2. Admit **MeetMind AI Notetaker** from the waiting room.
3. Status moves `joining_call → in_waiting_room → in_call_recording`.
4. When the meeting ends, open it and click **Get transcript & summary**.
5. Ask questions in the per-meeting chat panel.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness + redacted config view |
| `POST` | `/meetings/join` | Dispatch the notetaker bot |
| `GET` | `/meetings` | Meeting history |
| `GET` | `/meetings/{id}` | Full detail (`?include_transcript=true`) |
| `GET` | `/meetings/{id}/status` | Live status from Recall |
| `POST` | `/meetings/{id}/process` | Fetch transcript + run Groq analysis |
| `POST` | `/meetings/{id}/leave` | Remove the bot from the call |
| `GET` | `/meetings/{id}/chat` | Chat history for that meeting |
| `POST` | `/meetings/{id}/chat` | Ask about that meeting |
| `POST` | `/webhooks/recall` | Status/completion events (signature verified) |
| `POST` | `/webhooks/recall/realtime` | Per-bot real-time transcript events |

`POST /meetings/join` body:

| Field | Type | Required | Notes |
|---|---|---|---|
| `meeting_url` | string | yes | Google Meet, Zoom or Teams link |
| `consent_acknowledged` | bool | yes | Must be `true` |
| `title` | string | no | Shown in the dashboard |
| `bot_name` | string | no | Defaults to `MeetMind AI Notetaker` |
| `transcription` | bool | no | Defaults to `true` |

## Webhooks

Recall signs webhooks with HMAC via Svix. Verification needs a **workspace
secret**:

1. Recall dashboard → **Developers → API Keys & Secrets → Create Workspace Secret**
2. Put it in `.env` as `RECALL_WEBHOOK_SECRET=whsec_...`

Until that is set, `/webhooks/recall` returns **401 by design** — the app will
not trust unsigned payloads. For local testing only you may set
`ALLOW_UNVERIFIED_WEBHOOKS=true`.

Recall must reach your machine, so expose the backend with a tunnel:

```powershell
ngrok http 8000
```

Set `PUBLIC_BASE_URL` to the HTTPS URL ngrok prints, and register
`<PUBLIC_BASE_URL>/webhooks/recall` in the Recall webhooks dashboard.

## Recall.ai reference

Verified against the official docs and live responses, not inferred:

- Regions / base URLs — https://docs.recall.ai/docs/regions
- Create Bot — https://docs.recall.ai/reference/bot_create
- Transcription config — https://docs.recall.ai/docs/transcription
- Webhook verification — https://docs.recall.ai/docs/authenticating-requests-from-recallai
- Calendar integration — https://docs.recall.ai/docs/calendar-integration

Auth is `Authorization: Token <RECALL_API_KEY>` — **not** `Bearer`.

The transcript download URL is a pre-signed S3 link at
`recordings[].media_shortcuts.transcript.data.download_url`. It needs no auth
header and it expires, so it is never persisted.

## Implementation notes

- **Groq reasoning models.** The default `openai/gpt-oss-120b` returns a
  `reasoning` field alongside `content`, and both draw from `max_tokens`. Too
  small a budget yields empty `content`. `GROQ_MAX_TOKENS` defaults to 4096.
  This account has no Llama chat models available; `whisper-large-v3` is
  present and is the Whisper fallback.
- **Chat context.** Every answer is built from one meeting only. Naming a
  different stored meeting returns `context_switch_required` instead of
  silently switching.
- **Secrets never reach the browser.** The frontend only knows
  `NEXT_PUBLIC_API_BASE`. All Recall and Groq calls happen server-side.
- **Hindsight is not integrated.** `MemoryService` in
  `backend/app/services/memory.py` defines `save_memory()` / `recall_memory()`,
  and `MySQLMemoryService` is the current implementation with MySQL as
  temporary storage. Recall there is lexical, not semantic. When Hindsight
  works, add a `HindsightMemoryService` with the same interface and change the
  factory — no chat or meeting code needs to change. `/health` reports
  `"hindsight_integrated": false` until that is true.

## Calendar scheduling

Uses **Recall Calendar V2** (app-managed scheduling: Recall syncs the calendar,
MeetMind decides which events get a bot).

Before connecting, in Google Cloud Console:

1. **APIs & Services → Library** → enable **Google Calendar API**
2. **APIs & Services → Credentials** → your OAuth client → add the redirect URI
   `http://localhost:8000/calendar/oauth/callback`
3. If the consent screen is in *Testing*, add your Google account under
   **Audience → Test users**

Then open http://localhost:3000/calendar and click **Connect Google Calendar**.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/calendar/oauth/start` | Google consent URL |
| `GET` | `/calendar/oauth/callback` | OAuth redirect target |
| `GET` | `/calendar` | Connected calendars |
| `GET` | `/calendar/{id}/events` | Upcoming events (`?days_ahead=`) |
| `POST` | `/calendar/events/{id}/schedule` | Schedule the notetaker |
| `DELETE` | `/calendar/events/{id}/schedule` | Cancel it |

Scopes requested are **read-only** (`calendar.events.readonly`). The Google
refresh token is handed to Recall and is **not** stored in MySQL; only Recall's
calendar id is.

## Speech-to-text: two paths

Recall's `recallai_streaming` provider is the primary source and gives text
**with speaker attribution and word timestamps**. Whisper is a fallback for the
case where Recall produced no transcript at all — transcription disabled on the
bot, or the provider failed — but audio was still recorded. It downloads
`audio_mixed` and sends it to Groq `whisper-large-v3`.

The fallback returns **plain text only**: no speaker names, no per-word
timings, so no participant rows are created. The response field
`used_whisper_fallback` tells you which path ran.

## Not built yet

- Authentication: `users` and `projects` tables exist but nothing writes to
  them; all meetings are currently unowned
- Auto-record: the `calendars.auto_record` column exists but no job acts on it,
  so events are scheduled manually
