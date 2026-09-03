# Scheduling domain

The scheduling voice assistant, built as a new ADAR domain (`DOMAIN=scheduling`)
per the "Adding a new domain" recipe in `docs/arcl.md`. Reference vertical:
clinician-practice appointment booking. See the build plan (§5, §8) for the
full rationale and phased roadmap this implements the first slice of.

**Current scope: in-app voice / chat only** (record in the browser, talk to
the agent, get a spoken or text response back — same shape as Geetabitan's
voice mode). Real telephony is a later phase and touches none of the files
below when it's added — see the build plan §7/§8.

## What's here

```
domains/scheduling/
├── tools/
│   ├── availability_tools.py   Real logic: availability, holds, bookings
│   └── __init__.py             TOOL_REGISTRY — maps tool names to functions
├── ingestion/
│   ├── run_ingestion.py        Seeds a practice's providers/hours into Firestore
│   └── sample_practice.json    A demo clinician practice to seed and test with
└── README.md                   This file
```

Also touched: `src/adar/config.py` (new `scheduling` branch — Firestore
collection names, app name, off-topic guard keywords) and
`src/adar/agents/agents_config.scheduling.json` (the orchestrator + agent
definition). Nothing in `api/main.py` needed to change — `/api/chat`,
`/api/stt`, and `/api/demo/tts` are already domain-generic (confirmed by
reading the actual chat handler — see the build plan §0).

On the frontend: `ui/src/tenant.js` (new `scheduling` entry — branding,
chat copy, suggested questions, voice strings) and `ui/.env.scheduling`
(`VITE_DOMAIN=scheduling`, same shape as `.env.restaurants`). Nothing else
in `ui/` is domain-specific — the chat/voice components already read
everything from `tenant.js`.

## Firestore schema

Every collection is scoped by `practice_id` (the tenant boundary — same role
`workspace_id` plays in adar-rag, `team_id`/`adar_teams` plays for ARCL).

| Collection | Purpose | Key fields |
|---|---|---|
| `scheduling_practices` | One doc per practice/tenant | `name`, `timezone`, `lead_time_minutes`, `max_advance_days` |
| `scheduling_providers` | Bookable resources (a clinician, a stylist, …) | `practice_id`, `name`, `role`, `appointment_type_ids`, `working_hours` (list of `{weekday, start, end}`), `active` |
| `scheduling_appointment_types` | Services offered | `practice_id`, `name`, `duration_minutes`, `buffer_minutes`, `description` |
| `scheduling_appointments` | Confirmed/cancelled bookings | `practice_id`, `provider_id`, `appointment_type_id`, `start_time`, `end_time`, `status`, `caller_name`, `caller_phone`, `caller_email`, `reason` |
| `scheduling_holds` | Short-lived (10 min) holds while a caller confirms | same shape as an appointment, plus `expires_at`, `status: active\|confirmed` |

Collection names are overridable via env vars (`SCHEDULING_PROVIDERS_COLLECTION`
etc.) exactly like every other domain's collections in `config.py`.

## Tools (registered in `TOOL_REGISTRY`, called by `scheduling_agent`)

`find_practice`, `list_appointment_types`, `list_providers`, `check_availability`,
`get_weekly_availability`, `hold_slot`, `confirm_booking`, `cancel_appointment`,
`reschedule_appointment`, `list_my_appointments`. See `availability_tools.py`
docstrings for exact signatures — they're intentionally plain typed functions
(str/int/bool), the same style Geetabitan and ARCL's tools use, since that's
what ADK's automatic function-calling introspects.

`find_practice` is always the agent's first tool call (see Step 1 of
`agents_config.scheduling.json`'s instruction) — it resolves which practice
the conversation is about, by name ("Riverside Family Medicine") or, when no
name is given and `SCHEDULING_DEFAULT_PRACTICE_ID` is configured, to that
deployment's default. It returns a `practice_id` that the agent then carries
forward itself and passes explicitly on every later tool call — no tool
remembers `practice_id` between calls, only the LLM's own context window
does, which is standard ADK function-calling behavior. If a name matches more
than one practice (or none was given and more than one active practice
exists with no default configured), it returns a short numbered list instead
and the agent reads it back to the caller to choose from.

`check_availability` defaults to scanning the next 7 days from now, but takes
an optional `start_date` (`YYYY-MM-DD`) to scan a specific week instead —
`lead_time_minutes`/`max_advance_days` guardrails still anchor to the real
current time regardless of which week is being browsed, so a caller can't use
`start_date` to route around them. `get_weekly_availability` is the "browse
broadly" counterpart: one scan across ~8 weeks (`weeks_ahead`, default 8),
grouped into a per-week summary of which days have any opening (e.g. "Week of
Sep 8–14: Mon, Wed, Fri"). It's for letting a caller pick a week, not for
reading out bookable times — the agent is instructed (see
`agents_config.scheduling.json`) to call `check_availability` with that
week's Monday as `start_date` afterward to get the actual slot times before
offering anything concrete.

`check_availability` → `hold_slot` → `confirm_booking` is the booking
sequence; `hold_slot`/`confirm_booking` run inside Firestore transactions so
two callers can't grab the same opening at once. That's sufficient for
turn-based in-app voice; a live-telephony build with much higher concurrency
may eventually want a faster lock in front of it (Redis) — see the build
plan §7.

`confirm_booking` takes an optional `caller_email`. When given, it sends a
confirmation email (`src/adar/notify.py`'s `send_appointment_confirmation_email`,
reusing the same Gmail SMTP sender as the OTP login codes — `GMAIL_USER` /
`GMAIL_APP_PASSWORD` in `.env.scheduling`) after the Firestore write commits.
The send is best-effort: a failed email never undoes an already-confirmed
booking, it just logs and tells the caller to hold onto the confirmation ID.

## Single-practice vs multi-practice

Every tool takes `practice_id`, and a single deployment can now genuinely
serve more than one practice at once — the agent resolves which one a
conversation is about by calling `find_practice` first (see above), then
carries that `practice_id` forward itself for the rest of the conversation.
`SCHEDULING_DEFAULT_PRACTICE_ID` still matters: for a single-practice pilot
(or any deployment where most callers don't say a practice name), it's the
fallback `find_practice` resolves to when no name was given, so the agent
still never has to ask in the common case. Set it from `run_ingestion.py`'s
printed `practice_id`, or leave it unset in a genuinely multi-practice
deployment and `find_practice` will ask the caller to choose whenever more
than one active practice matches (or none was named).

## Admin console

A practice-facing admin UI lives inside the existing admin dashboard (same
login as the Teams/Evals tabs — `page === 'admin'` in `ui/src/App.jsx`), as
a "🏥 Practices" tab that only renders when `tenant.id === 'scheduling'`
(`ui/src/AdminDashboard.jsx` → `ui/src/scheduling/SchedulingAdmin.jsx`). It
covers full CRUD for the three config collections plus a read view of
bookings:

- **Practices** — create/edit name, timezone (IANA string), lead time,
  booking window, and an `active` flag to hide a practice from callers
  without deleting it (`SchedulingAdmin.jsx`).
- **Providers** — name, role, which appointment types they offer, weekly
  working hours (`WorkingHoursEditor.jsx` — per-weekday ranges, supports
  split shifts like a lunch break), and `active`
  (`SchedulingProviders.jsx`).
- **Appointment types** — name, duration, buffer, description, `active`
  (`SchedulingAppointmentTypes.jsx`).
- **Calendar** — a month-grid view of confirmed/cancelled bookings for the
  selected practice, with a provider filter and a day-agenda panel showing
  full detail (caller name/phone/email, reason, status) for whichever day
  is selected (`SchedulingCalendar.jsx`). **Read-only** — cancelling or
  rescheduling a booking still goes through the voice/chat assistant's
  `cancel_appointment`/`reschedule_appointment` tools, not this view.

All of it is served by a new admin-only API router,
`api/routes/scheduling_admin.py` (mounted at `/admin/scheduling/...` in
`api/main.py`, gated by the same `get_admin` dependency —
`api/routes/auth.py` — as the rest of `/admin/*`, and 404s outright when
`DOMAIN != scheduling`):

```
GET    /admin/scheduling/practices
POST   /admin/scheduling/practices
PATCH  /admin/scheduling/practices/{practice_id}
GET    /admin/scheduling/practices/{practice_id}/providers
POST   /admin/scheduling/practices/{practice_id}/providers
PATCH  /admin/scheduling/providers/{provider_id}
GET    /admin/scheduling/practices/{practice_id}/appointment-types
POST   /admin/scheduling/practices/{practice_id}/appointment-types
PATCH  /admin/scheduling/appointment-types/{type_id}
GET    /admin/scheduling/practices/{practice_id}/bookings?start=&end=&provider_id=&status=
```

Changes made here take effect immediately for the live assistant, with no
redeploy — availability is always computed live against current Firestore
state (`domains/scheduling/tools/availability_tools.py`). Turning a
provider or appointment type's `active` flag off hides it from
`list_providers`/`list_appointment_types`/`find_practice` right away (the
Python-side `r.get("active") is not False` filter treats a document with no
`active` field at all as active, so pre-existing seeded data that predates
this feature is unaffected).

## Running it locally

### Step 1 — seed a demo practice (just ingestion)

Ingestion only writes to Firestore — it never calls Gemini — so it needs a
smaller env var set than running the full app does:

```bash
export DOMAIN=scheduling                                          # required — picks the "scheduling" branch in config.py
export PYTHONPATH=$(pwd)                                          # required — so `domains.*` / `src.adar.*` imports resolve
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json  # required — Firestore auth (see .env.example);
                                                                     # `gcloud auth application-default login` also works locally
export GCP_PROJECT_ID=bdas-493785                                 # optional — already the default in config.py
export FIRESTORE_DATABASE=adar-scheduling-db                      # optional — already the default once DOMAIN=scheduling;
                                                                     # only set this if you want a different database name
```

`GOOGLE_API_KEY` is **not** needed for this step — ingestion doesn't touch
Gemini. You will need it for step 2.

The Firestore database named by `FIRESTORE_DATABASE` (`adar-scheduling-db`
by default) has to already exist in the GCP project — create it once in the
GCP console or via `gcloud firestore databases create --database=adar-scheduling-db --location=us-central1`,
the same way `geetabitan-db`/`tigers-arcl` were created for the other domains.

```bash
python -m domains.scheduling.ingestion.run_ingestion --file domains/scheduling/ingestion/sample_practice.json
# → prints practice_id; export it:
export SCHEDULING_DEFAULT_PRACTICE_ID=<printed id>
```

### Step 2 — run the backend (needs Gemini too)

```bash
export GOOGLE_API_KEY=...   # now required — the agent and evaluator both call Gemini
python api/main.py
# http://localhost:8040/api/chat  { "user_id": "...", "message": "I need to see a doctor next week" }
# Try both availability paths:
#   { "message": "what's open this week" }                     → check_availability (next 7 days)
#   { "message": "what do you have over the next couple months" } → get_weekly_availability, then
#                                                                    check_availability(start_date=<chosen Monday>)
```

### Step 3 — run the frontend (in-app voice UI)

Same React app every other domain uses, pointed at the scheduling branding
via `ui/.env.scheduling`:

```bash
cd ui
npm install            # first time only
npm run dev -- --mode scheduling
# http://localhost:6001  — dev server proxies /api to http://localhost:8040
```

Open it, allow microphone access, and talk to the assistant — same
record → `/api/stt` → `/api/chat` → `/api/demo/tts` round trip Geetabitan's
voice mode uses, just with the scheduling agent and copy from `tenant.js`.

## Deployment

Public URLs (following the same `<domain>.adar.agomoniai.com` /
`api.<domain>.adar.agomoniai.com` pattern as Geetabitan and Restaurants):

- Frontend: `https://scheduling.adar.agomoniai.com` (Firebase Hosting, site
  `scheduling-adar`)
- Backend: `https://api.scheduling.adar.agomoniai.com` (Cloud Run, service
  `adar-scheduling-api`)

```bash
# One-time: create the Firestore database, then secrets
gcloud firestore databases create --database=adar-scheduling-db \
  --location=us-central1 --type=firestore-native --project=bdas-493785
bash infra/create_scheduling_secrets.sh

# Backend (Cloud Run)
bash infra/deploy-scheduling.sh

# SCHEDULING_DEFAULT_PRACTICE_ID is a real parameter of deploy-scheduling.sh
# (defaulted to the seeded demo practice's ID), not a separate manual step —
# every deploy sets it explicitly, via --update-env-vars so nothing else you
# set on the service gets clobbered. Seeding a different/real practice?
#   DOMAIN=scheduling PYTHONPATH=$(pwd) GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json \
#     python -m domains.scheduling.ingestion.run_ingestion --file <your-practice.json>
#   SCHEDULING_DEFAULT_PRACTICE_ID=<printed practice_id> bash infra/deploy-scheduling.sh
# (or edit the default at the top of the script so you don't need the
# override every time). No separate `gcloud run services update` step
# needed — that was the old, easy-to-forget way this used to work, and
# forgetting it is exactly what caused appointment data to "disappear"
# after a redeploy in earlier testing.

# Frontend (Firebase)
cd ui
# VITE_API_URL is passed inline, not left to ui/.env.scheduling — that file
# points at localhost:8040 for local dev (matching ui/.env.restaurants), and
# an env var passed on the command line overrides it for the prod build.
VITE_API_URL=https://api.scheduling.adar.agomoniai.com npm run build -- --mode scheduling
firebase deploy --only hosting:scheduling
```

Custom domains need DNS records at your registrar — `firebase hosting:sites`
and `gcloud beta run domain-mappings create` (see `deploy-scheduling.sh`'s
printed command) will each output the exact records once the site/mapping
exists; get those records before touching DNS rather than guessing them.

## Not built yet (see the build plan for when/why)

- Real telephony (Twilio, live phone calls) — §3/§7 of the build plan
- SMS confirmations and reminders, and email *reminders* ahead of the visit
  (email *confirmation* at booking time is built — see above) — §3, Phase 4
- Cancel/reschedule from the admin console itself — the "🏥 Practices" tab's
  calendar is view-only for now (see Admin console above); staff-facing
  practice/provider/appointment-type management and a bookings calendar are
  built — §3, Phase 4
- Stripe billing plan for this domain — §5's "Billing" note
- A second reference vertical to prove the schema generalizes — §5
