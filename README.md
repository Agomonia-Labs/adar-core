# Adar ARCL — আদর

> AI-powered cricket assistant for the American Recreational Cricket League (ARCL).
> Multi-agent system with team authentication, Stripe subscriptions, live stats,
> community polls, and LLM-as-judge response evaluation.

**Live app:** `https://arcl.tigers.agomoniai.com`  
**API:** `https://api.arcl.tigers.agomoniai.com`  
**Admin:** log in with admin credentials at the same URL

---

## Table of contents

1. [What it does](#what-it-does)
2. [Full architecture](#full-architecture)
3. [Infrastructure](#infrastructure)
4. [Project structure](#project-structure)
5. [Multi-agent system](#multi-agent-system)
6. [Data design](#data-design)
7. [Authentication](#authentication)
8. [Stripe payments](#stripe-payments)
9. [Response evaluation](#response-evaluation)
10. [Frontend design](#frontend-design)
11. [Security](#security)
12. [Local development](#local-development)
13. [Ingestion — manual runs](#ingestion--manual-runs)
14. [Scheduled jobs](#scheduled-jobs)
15. [Production deployment](#production-deployment)
16. [API reference](#api-reference)
17. [Debug scripts](#debug-scripts)
18. [Cost estimate](#cost-estimate)
19. [Future — adar-core repo structure](#future--adar-core-repo-structure)

---

## What it does

| Question | Agent | Data source |
|---|---|---|
| "What is the wide rule in ARCL?" | Rules | arcl.org/Rules.aspx (men's) |
| "What are the women's league umpiring rules?" | Rules | arcl.org/Docs/Womens_League_Rules.htm |
| "How many runs has Anijit Roy scored?" | Player | arcl_player_seasons (Firestore) |
| "Show Agomoni Tigers players in Spring 2026" | Team | Live arcl.org TeamStats.aspx |
| "Agomoni Tigers top 5 batsmen all time" | Team | Live arcl.org (all seasons) |
| "How was Jiban Adhikary dismissed?" | Team | Live arcl.org Matchscorecard.aspx |
| "Show scorecard for match 28045" | Team | Live arcl.org Matchscorecard.aspx |
| "Show Agomoni Tigers schedule" | Team | Live arcl.org LeagueSchedule.aspx |
| "What is Agomoni Tigers team strength?" | Team | Live arcl.org (all seasons) |
| "Current standings in Div H?" | Live | Live arcl.org DivHome.aspx |

---

## Full architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Browser  (Firebase Hosting)                                 │
│  arcl.tigers.agomoniai.com                                   │
│                                                              │
│  React + MUI · Login · Chat · Polls · Billing · Admin        │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTPS  X-API-Key / JWT Bearer
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  FastAPI  (Cloud Run — adar-arcl-api)                        │
│  api.arcl.tigers.agomoniai.com                               │
│                                                              │
│  /api/chat   /api/auth   /api/payments   /api/polls          │
│  /admin/*    /health     /api/tenant                         │
│                                                              │
│  ┌──────────────────┐   ┌──────────────────────────────┐    │
│  │  Rate limiter    │   │  JWT / API key middleware     │    │
│  │  20 req/min/IP   │   │  team_id → Firestore lookup  │    │
│  └──────────────────┘   └──────────────────────────────┘    │
└──────────┬──────────────────────────┬───────────────────────┘
           │                          │
           ▼                          ▼
┌──────────────────┐      ┌────────────────────────────────┐
│  Google ADK      │      │  Stripe API                     │
│  Orchestrator    │      │  Subscriptions · Webhooks       │
│                  │      │  Invoices · Customer Portal     │
│  ┌─ rules_agent  │      └────────────────────────────────┘
│  ├─ player_agent │
│  ├─ team_agent   │      ┌────────────────────────────────┐
│  └─ live_agent   │      │  Firestore (tigers-arcl)        │
│                  │      │                                 │
│  gemini-2.5-flash│      │  adar_teams    arcl_rules       │
└────────┬─────────┘      │  arcl_players  arcl_faq         │
         │                │  arcl_teams    arcl_polls       │
         │ live HTTP       │  arcl_player_seasons            │
         ▼                │  arcl_evals    arcl_ingestion.. │
┌──────────────────┐      └────────────────────────────────┘
│  arcl.org        │
│                  │      ┌────────────────────────────────┐
│  TeamStats.aspx  │      │  Cloud SQL (Postgres)           │
│  Scorecard.aspx  │      │  arcl_sessions                  │
│  Schedule.aspx   │      │  (ADK session storage)          │
│  DivHome.aspx    │      └────────────────────────────────┘
│  Rules.aspx      │
└──────────────────┘      ┌────────────────────────────────┐
                          │  Evaluation (LLM-as-judge)      │
                          │                                 │
                          │  Every chat response scored:    │
                          │  accuracy · completeness        │
                          │  relevance · format · overall   │
                          │                                 │
                          │  gemini-2.5-flash (same model)  │
                          │  → arcl_evals collection        │
                          └────────────────────────────────┘
```

---

## Infrastructure

| Component | Resource | Details |
|---|---|---|
| Backend | Cloud Run `adar-arcl-api` | `api.arcl.tigers.agomoniai.com` |
| Frontend | Firebase Hosting | `arcl.tigers.agomoniai.com` |
| GCP Project | `bdas-493785` | us-central1 |
| Firestore | `tigers-arcl` database | Native mode |
| Cloud SQL | `adar-pgdev` (Postgres) | `arcl_sessions` DB, `arcl_user` |
| Artifact Registry | `us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest` | |
| Service Account | `adar-sa@bdas-493785.iam.gserviceaccount.com` | |
| DNS | AWS Route 53 — `agomoniai.com` | |
| Ingestion job | Cloud Run Job `arcl-indexer` | |
| Scheduler | Cloud Scheduler `arcl-weekly-reindex` | Every Sunday 2am PT |
| Payments | Stripe | Subscriptions + webhooks |

### DNS records (Route 53)

| Record | Type | Value |
|---|---|---|
| `api.arcl.tigers.agomoniai.com` | CNAME | `ghs.googlehosted.com.` |
| `arcl.tigers.agomoniai.com` | CNAME | `bdas-493785.web.app.` |

---

## Project structure

```
adar-arcl/
│
├── main.py                  FastAPI app — chat, auth, admin, payments, polls, health
├── agents.py                Agent factory — reads agents_config.json
├── agents_config.json       All agent definitions, tools, and instructions
├── auth.py                  Team registration, login, JWT issue/verify
├── admin.py                 Admin endpoints — manage teams, approvals, quotas, evals
├── payments.py              Stripe subscriptions — checkout, webhooks, billing, portal
├── polls.py                 Community polls CRUD
├── tenants.py               Multi-tenant registry (ready for future leagues)
├── notify.py                Email notifications (SendGrid + Gmail SMTP fallback)
├── config.py                Settings, Firestore collections, season ID map, ADK model
├── db.py                    Firestore client, vector search, direct queries
├── models.py                Pydantic request/response schemas (includes eval field)
│
├── evaluation/
│   ├── __init__.py          Exports evaluate_response, get_eval_summary
│   └── judge.py             LLM-as-judge — Gemini scores every response (5 dimensions)
│
├── tools/
│   ├── __init__.py          TOOL_REGISTRY — maps tool name to async function
│   ├── rules_tools.py       vector_search_rules · get_rule_section · get_faq_answer
│   ├── player_tools.py      get_player_stats · get_player_season_stats ·
│   │                        get_player_teams · get_top_performers
│   ├── team_tools.py        get_team_players_live · get_team_schedule ·
│   │                        get_team_career_stats · get_match_scorecard ·
│   │                        get_player_dismissals · get_teams_in_division ·
│   │                        get_season_info · list_divisions
│   └── live_tools.py        get_standings · get_schedule · get_recent_results
│
├── ingestion/
│   ├── __init__.py
│   ├── arcl_scraper.py      Crawls arcl.org — rules, players, standings, TeamStats
│   │                        Tags rules with [MEN'S LEAGUE] / [WOMEN'S LEAGUE]
│   │                        Tags umpiring rules with [UMPIRING RULE] prefix
│   ├── arcl_embedder.py     Embeds text chunks → Firestore vector search
│   └── run_ingestion.py     CLI entry point — --only, --seasons, --clear flags
│
├── arcl-chat-app/           React + MUI frontend (Vite)
│   ├── src/
│   │   ├── App.jsx          Auth routing · chat · tabs · auto-logout (30 min)
│   │   ├── Login.jsx        Team login page
│   │   ├── Register.jsx     Team self-registration
│   │   ├── AdminDashboard.jsx  Approve/suspend teams · usage stats
│   │   ├── Checkout.jsx     Stripe plan selection · 14-day trial
│   │   ├── Billing.jsx      Subscription status · invoice history · portal
│   │   ├── Polls.jsx        Create/vote/results · auto-refresh 15s
│   │   ├── StatsChart.jsx   CSS bar charts (no library) — batting/bowling toggle
│   │   ├── theme.js         Light green MUI theme (#2EB87E primary)
│   │   └── main.jsx
│   ├── .env.production      VITE_API_URL · VITE_API_KEY
│   ├── package.json
│   └── vite.config.js
│
├── tests/
│   ├── debug_teams.py       Check adar_teams Firestore collection
│   ├── debug_stripe.py      Check Stripe subscriptions + sync to Firestore
│   ├── debug_eval.py        Full evaluation system debug + model discovery
│   ├── debug_scorecard.py   Inspect Matchscorecard table structure
│   ├── debug_teamstats_headers.py  Print exact TeamStats table headers
│   ├── find_team_ids.py     Find team_id per season from DivHome
│   └── test_season.py       Verify season_id resolution
│
├── Dockerfile
├── requirements.txt         fastapi · uvicorn · google-adk · stripe · bcrypt ·
│                            python-jose · google-cloud-firestore · httpx · bs4
├── create_indexes.sh        One-command Firestore composite index setup
├── .env.example             Template of all environment variables
└── README.md
```

---

## Multi-agent system

All agent behaviour defined in `agents_config.json`. Edit and restart server to update — no redeploy needed.

### ADK model

```python
# config.py
ADK_MODEL: str = "gemini-2.5-flash"
```

Both the ADK agents and the evaluation judge use this same model.

### Routing rules (orchestrator)

```
"show all Agomoni Tigers players"       → team_agent (team's own players)
"top batsmen in Div H"                  → player_agent (cross-team comparison)
"how was Jiban dismissed"               → team_agent (dismissal tool)
"scorecard for match 28045"             → team_agent (scorecard tool)
"what is the wide rule"                 → rules_agent
"men's league umpiring rules"           → rules_agent (filters to MEN'S LEAGUE only)
"current standings"                     → live_agent
"show batting stats as a graph"         → team_agent (returns table, frontend renders chart)
```

### Agents and tools

| Agent | Tools |
|---|---|
| `arcl_orchestrator` | Routes to sub-agents based on query intent |
| `rules_agent` | `vector_search_rules` · `get_rule_section` · `get_faq_answer` |
| `player_agent` | `get_player_stats` · `get_player_season_stats` · `get_player_teams` · `get_top_performers` |
| `team_agent` | `get_team_players_live` · `get_team_schedule` · `get_team_career_stats` · `get_match_scorecard` · `get_player_dismissals` · `get_team_season` · `get_team_history` · `get_teams_in_division` · `get_season_info` · `list_divisions` |
| `live_agent` | `get_standings` · `get_schedule` · `get_recent_results` · `get_announcements` |

---

## Data design

### Live fetch vs Firestore cache

| Data | Strategy | Why |
|---|---|---|
| Player batting/bowling per season | **Live** — TeamStats.aspx | arcl.org assigns new `team_id` each season |
| Team schedule / fixtures | **Live** — LeagueSchedule.aspx | Always current |
| Match scorecards / dismissals | **Live** — Matchscorecard.aspx | Per-match detail |
| Career stats (all seasons) | **Live** — fetches all seasons, aggregates on the fly | |
| Team standings (W/L/pts) | **Firestore cache** | Changes rarely mid-season |
| Player career overview | **Firestore cache** | Stable data |
| Rules / FAQ | **Firestore cache** | Changes only when ARCL updates rules |
| Eval results | **Firestore** | arcl_evals collection |

### Season ID map (confirmed from arcl.org)

| Season | season_id | Agomoni Tigers team_id | league_id |
|---|---|---|---|
| Spring 2026 | 69 | 7778 | 10 |
| Summer 2025 | 66 | 7262 | 10 |
| Spring 2025 | 65 | 7178 | 10 |
| Summer 2024 | 63 | 6670 | 10 |

Each season arcl.org assigns a new `team_id`. Resolved via `TEAM_ID_CACHE` → Firestore → live DivHome search.

### TeamStats.aspx table structure (confirmed)

```
Table 3 — Batting:  Player, Player_Id, Team, Innings, Runs, Balls, Fours, Sixs, Strike Rate
Table 4 — Bowling:  Player, Player_Id, Team, Innings, Overs, Maidens, Runs, Wickets, Average, Eco Rate
```

### Matchscorecard.aspx table structure (confirmed)

```
Table 1 — Match info:          Teams, Date, Result, MOTM, Umpire, Ground, Toss
Table 2 — 1st innings batting: Batter, How_out, Fielder, Bowler, Sixs, Fours, Runs, Balls
Table 3 — 1st innings bowling: Bowler, Overs, Maiden, No_Balls, Wide, Runs, Wicket
Table 4 — 2nd innings batting
Table 5 — 2nd innings bowling
```

### Rules tagging (men's vs women's league)

Three sources scraped and tagged:

| Source | Tag applied |
|---|---|
| `Rules.aspx` | `[MEN'S LEAGUE]` prefix on every chunk |
| `Mens_League_Rules.htm` | `[MEN'S LEAGUE]` prefix |
| `Womens_League_Rules.htm` | `[WOMEN'S LEAGUE]` prefix |

Umpiring sections additionally tagged: `[UMPIRING RULE — section name]`

`vector_search_rules` detects league intent from the query and filters results accordingly.

### Firestore collections

| Collection | Contents | Key |
|---|---|---|
| `adar_teams` | Team auth, billing, quotas | team_id (doc ID) |
| `arcl_rules` | Rules chunks with league tags | embedding (vector) |
| `arcl_faq` | FAQ pairs | embedding (vector) |
| `arcl_players` | Player career overview | embedding (vector) |
| `arcl_teams` | Standings per season | team_name + season |
| `arcl_player_seasons` | Batting/bowling per player per season | player_name + season |
| `arcl_polls` | Community polls with votes | poll_id (doc ID) |
| `arcl_evals` | LLM-as-judge scores per response | eval_id (doc ID) |
| `arcl_ingestion_state` | Last run timestamps for incremental jobs | job_name (doc ID) |

---

## Authentication

JWT-based team authentication. 30-day token expiry. Admin role separate from team role. Sessions auto-logout after 30 minutes of inactivity in the frontend.

### Registration and approval flow

```
Team captain visits /register
  → fills team name, email, password, contact person
  → POST /api/auth/register → status: pending

Admin logs in → Admin Dashboard
  → sees pending teams
  → clicks ✓ to approve → status: active

Team captain logs in → JWT issued (30 days)
  → stored in localStorage
  → every request sends Authorization: Bearer <token>
  → auto-logout after 30 minutes
```

### Endpoints

| Endpoint | Auth | Description |
|---|---|---|
| `POST /api/auth/register` | None | Self-registration — status: pending |
| `POST /api/auth/login` | None | Email + password → JWT |
| `GET  /api/auth/me` | JWT | Current team info from token |
| `GET  /admin/teams` | Admin JWT | List all teams with status |
| `POST /admin/teams/{id}/approve` | Admin JWT | Approve pending registration |
| `POST /admin/teams/{id}/suspend` | Admin JWT | Suspend team |
| `POST /admin/teams/{id}/activate` | Admin JWT | Reactivate team |
| `PUT  /admin/teams/{id}/quota` | Admin JWT | Update daily quota + RPM |
| `GET  /admin/polls` | Admin JWT | All polls across all teams |
| `GET  /admin/stats` | Admin JWT | Team count summary |

### `adar_teams` Firestore document

```json
{
  "team_id":                "agomoni_tigers",
  "team_name":              "Agomoni Tigers",
  "email":                  "captain@email.com",
  "password_hash":          "bcrypt hash",
  "contact_person":         "Braja Das",
  "status":                 "active",
  "role":                   "team",
  "approved_at":            "2026-04-29T02:19:14",
  "created_at":             "2026-04-28T23:29:05",
  "quota_rpm":              20,
  "quota_daily":            200,
  "stripe_customer_id":     "cus_xxx",
  "stripe_subscription_id": "sub_xxx",
  "subscription_status":    "trialing",
  "subscription_plan":      "standard",
  "subscription_ends_at":   "2026-05-14",
  "trial_ends_at":          "2026-05-14",
  "daily_quota":            200,
  "usage_today":            5,
  "cancel_at_period_end":   false
}
```

---

## Stripe payments

Auto-renewing monthly subscriptions with 14-day free trial. Teams enter card once — Stripe charges automatically every billing period.

### Plans

| Plan | Price | Daily quota | Env var |
|---|---|---|---|
| Basic | $5/month | 50 messages | `STRIPE_PRICE_BASIC` |
| Standard | $15/month | 200 messages | `STRIPE_PRICE_STANDARD` |
| Unlimited | $30/month | 1000 messages | `STRIPE_PRICE_UNLIMITED` |

### Auto-payment flow

```
Team selects plan → POST /api/payments/create-checkout
  → Stripe Customer created (or reused)
  → Checkout session created (team_id in metadata)
  → Team redirected to Stripe hosted page
  → Enters card once → 14-day free trial starts
  → Stripe webhook fires checkout.session.completed
  → Firestore updated: subscription_status: trialing
  → Auto-charged monthly after trial
  → invoice.payment_succeeded → subscription_status: active
  → Card fails → invoice.payment_failed → status: past_due
  → 3 retries over 7 days → then customer.subscription.deleted
```

### Endpoints

| Endpoint | Description |
|---|---|
| `GET  /api/payments/plans` | List plans with prices |
| `POST /api/payments/create-checkout` | Create Stripe checkout → returns URL |
| `GET  /api/payments/billing` | Subscription status + invoice history |
| `POST /api/payments/cancel` | Cancel at period end (access continues) |
| `POST /api/payments/reactivate` | Undo cancellation |
| `POST /api/payments/portal` | Stripe Customer Portal (update card, view invoices) |
| `POST /api/payments/webhook` | Stripe webhook — verified by signature |

### Webhook events handled

| Event | Firestore action |
|---|---|
| `checkout.session.completed` | Sets subscription_status, plan, daily_quota |
| `invoice.payment_succeeded` | Sets status active, resets usage_today |
| `invoice.payment_failed` | Sets status past_due |
| `customer.subscription.deleted` | Sets status canceled, daily_quota 0 |
| `customer.subscription.updated` | Syncs status, period end, quota |
| `customer.subscription.trial_will_end` | Logs (hook for notifications) |

### Stripe webhook URL

```
https://api.arcl.tigers.agomoniai.com/api/payments/webhook

Events to register in Stripe Dashboard:
  checkout.session.completed
  customer.subscription.deleted
  customer.subscription.trial_will_end
  customer.subscription.updated
  invoice.payment_failed
  invoice.payment_succeeded
```

### Stripe email receipts (enable in Dashboard)

```
Stripe Dashboard → Settings → Emails → Customer emails
☑ Successful payments
☑ Failed payments
☑ Trial will end
```

---

## Response evaluation

Every agent response is automatically scored by Gemini Flash using LLM-as-judge.
Score badges appear below each response in the chat UI.
Results stored in `arcl_evals` Firestore collection for admin review.

### Evaluation flow

```
User asks question
       ↓
ADK agent returns response
       ↓
evaluate_response() called (async, non-blocking)
       ↓
Gemini (ADK_MODEL) scores response → JSON
       ↓
Stored in arcl_evals collection
       ↓
eval field returned in ChatResponse
       ↓
Frontend shows color-coded badges:
  🟢 green ≥4   🟡 amber ≥3   🔴 red <3
```

### Scoring dimensions

| Dimension | Weight | What it measures |
|---|---|---|
| Accuracy | 35% | Are the stats, names, and facts correct? |
| Completeness | 25% | Does it fully answer what was asked? |
| Relevance | 25% | Is every part on-topic? |
| Format | 15% | Tables for stats, readable markdown? |
| Overall | — | Weighted average (0.0 – 5.0) |

### Admin endpoints

```
GET /admin/evals              aggregate scores across all teams
GET /admin/evals/{team_id}    scores for a specific team
GET /admin/evals/recent/low   responses scoring < 3.0 for review
```

### Configuration

```bash
EVAL_ENABLED=true    # set to false to disable
```

Evaluation uses the existing `GOOGLE_API_KEY` — no new secrets needed.

### `arcl_evals` Firestore document

```json
{
  "eval_id":     "uuid",
  "team_id":     "agomoni_tigers",
  "session_id":  "session_uuid",
  "question":    "Show batting stats...",
  "response":    "| Player | Runs |...",
  "scores": {
    "accuracy":     5,
    "completeness": 4,
    "relevance":    5,
    "format":       4,
    "overall":      4.65
  },
  "explanation": "Response correctly shows batting stats with proper table format.",
  "model":       "gemini-2.5-flash",
  "created_at":  "2026-05-01T..."
}
```

### Cost impact

~1,500 input + ~100 output tokens of `gemini-2.5-flash` per eval.
Approximately $0.0004 per evaluation — negligible relative to chat cost.

---

## Frontend design

**Theme:** Light green — primary `#2EB87E`, accent `#EF9F27`, background `#F5FBF7`
**Logo:** Bengali আদর in green rounded square
**Browser tab:** `(আদর) Adar ARCL — Cricket Assistant`

### Page routing

| Page state | Component | When shown |
|---|---|---|
| `login` | `Login.jsx` | No token in localStorage |
| `register` | `Register.jsx` | Click "Register your team" |
| `chat` | `App.jsx` (main) | Valid JWT |
| `admin` | `AdminDashboard.jsx` | Admin JWT role |
| `checkout` | `Checkout.jsx` | Click billing → no subscription |
| `billing` | `Billing.jsx` | Click 💳 Billing button |

### Chat features

- **Tabs:** 💬 Chat and 📊 Polls
- **Markdown rendering:** `react-markdown` + `remark-gfm` — tables, bold, lists
- **Stats charts:** CSS bar charts — `📊 Batting` / `📊 Bowling` toggle below stats
- **Chart stat selection:** detects user's requested stat (runs, SR, wickets, economy)
- **Eval badges:** Accuracy / Complete / Relevance / Format / Overall below each response
- **Auto-logout:** 30 minutes after login
- **Session:** persisted in localStorage, cleared on logout

---

## Security

| Layer | Implementation |
|---|---|
| Rate limiting | 20 req/min per IP (in-memory) |
| CORS | `arcl.tigers`, `adar.agomoniai.com`, localhost variants |
| API key | `X-API-Key` header for unauthenticated access |
| JWT auth | `Authorization: Bearer` for team endpoints |
| Admin auth | Admin role in JWT — separate from team role |
| Stripe webhook | Verified by `stripe-signature` header |
| Input validation | Max 2000 chars, sanitised user_id |
| Swagger UI | Disabled in production (`APP_ENV=production`) |
| Passwords | bcrypt hashed, never stored plain |

---

## Local development

### Prerequisites

Python 3.11+, Node.js 18+, Google AI Studio API key, GCP project with Firestore Native mode, Stripe account (test mode for dev).

### 1 — Clone and install

```bash
git clone https://github.com/agomonia-labs/adar-core
cd adar-core
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2 — Configure `.env`

```bash
# Google / GCP
GOOGLE_API_KEY=your_gemini_api_key
GCP_PROJECT_ID=bdas-493785
FIRESTORE_DATABASE=tigers-arcl
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Session storage (local SQLite)
SESSION_DB_URL=sqlite+aiosqlite:///./arcl_sessions.db

# Auth
JWT_SECRET=your-random-32-char-string   # openssl rand -hex 32
ADMIN_EMAIL=admin@adar.agomoniai.com
ADMIN_PASSWORD=your-strong-password

# Stripe (test mode for local dev)
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx   # from: stripe listen output
STRIPE_PRICE_BASIC=price_xxx
STRIPE_PRICE_STANDARD=price_xxx
STRIPE_PRICE_UNLIMITED=price_xxx
FRONTEND_URL=http://localhost:5173

# API key
ARCL_API_KEY=your-api-key

# Evaluation
EVAL_ENABLED=true
```

### 3 — Run initial data ingestion

```bash
# Full ingestion (first time — takes ~20 minutes)
python -m ingestion.run_ingestion

# Or just the current season to get started quickly
python -m ingestion.run_ingestion --only teamstats --seasons 69
python -m ingestion.run_ingestion --only rules
```

### 4 — Start Stripe webhook listener (for payment testing)

```bash
# Install Stripe CLI: brew install stripe/stripe-cli/stripe
stripe login
stripe listen --forward-to localhost:8020/api/payments/webhook
# Copy the whsec_xxx printed → add to .env as STRIPE_WEBHOOK_SECRET
```

### 5 — Start backend

```bash
python main.py
# API: http://localhost:8020
# Docs: http://localhost:8020/docs (dev only — disabled in production)
```

### 6 — Start frontend

```bash
cd arcl-chat-app
npm install
npm run dev
# App: http://localhost:5173
```

### 7 — First login

```bash
# Login as admin
curl -X POST http://localhost:8020/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@adar.agomoniai.com","password":"YOUR_PASSWORD"}'

# Or open http://localhost:5173 → login with admin credentials
```

---

## Ingestion — manual runs

### Run locally

```bash
# Full re-index everything (all seasons, rules, players)
python -m ingestion.run_ingestion

# Specific phases only
python -m ingestion.run_ingestion --only rules          # Rules + FAQ only (~2 min)
python -m ingestion.run_ingestion --only teamstats      # Player stats all seasons (~15 min)
python -m ingestion.run_ingestion --only standings      # W/L/pts for all teams (~2 min)
python -m ingestion.run_ingestion --only players        # Player career overview (~5 min)

# Specific season
python -m ingestion.run_ingestion --only teamstats --seasons 69          # Spring 2026 only
python -m ingestion.run_ingestion --only teamstats --seasons 66,69       # Two seasons
python -m ingestion.run_ingestion --only teamstats --seasons "Spring 2026"

# Clear and re-index (wipe Firestore first)
python -m ingestion.run_ingestion --only rules --clear
python -m ingestion.run_ingestion --only teamstats --seasons 69 --clear

# Parallel (open 3 terminals for speed)
python -m ingestion.run_ingestion --only teamstats --seasons 65,66,67,68,69
python -m ingestion.run_ingestion --only teamstats --seasons 60,61,62,63,64
python -m ingestion.run_ingestion --only teamstats --seasons 55,56,57,58,59
```

### Run on GCP (triggers production job)

```bash
# Execute the Cloud Run job
gcloud run jobs execute arcl-indexer \
  --region us-central1 \
  --project bdas-493785

# Watch execution status
gcloud run jobs executions list \
  --job arcl-indexer \
  --region us-central1 \
  --project bdas-493785

# Stream logs
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=arcl-indexer" \
  --project bdas-493785 \
  --limit 50 \
  --freshness 10m
```

### Quick reference

| Command | What it does | Time |
|---|---|---|
| `python -m ingestion.run_ingestion` | Everything | ~20 min |
| `--only rules` | Rules + FAQ | ~2 min |
| `--only teamstats --seasons 69` | Current season only | ~3 min |
| `--only standings` | W/L/pts all teams | ~2 min |
| `gcloud run jobs execute arcl-indexer` | Full run on GCP | ~20 min |

---

## Scheduled jobs

### Weekly full re-index (existing)

Runs every Sunday 2am Pacific. Wipes and rebuilds all Firestore cricket data.

```bash
# Create job (one time)
gcloud run jobs create arcl-indexer \
  --image us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest \
  --region us-central1 \
  --command "python" \
  --args "-m,ingestion.run_ingestion" \
  --service-account adar-sa@bdas-493785.iam.gserviceaccount.com \
  --set-secrets "GOOGLE_API_KEY=google-api-key:latest" \
  --set-env-vars "GCP_PROJECT_ID=bdas-493785,FIRESTORE_DATABASE=tigers-arcl,APP_ENV=production" \
  --memory 1Gi --max-retries 2 --task-timeout 3600

# Schedule it (one time)
PROJECT_NUMBER=$(gcloud projects describe bdas-493785 --format="value(projectNumber)")

gcloud scheduler jobs create http arcl-weekly-reindex \
  --location us-central1 \
  --schedule "0 2 * * 0" \
  --time-zone "America/Los_Angeles" \
  --uri "https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_NUMBER}/jobs/arcl-indexer:run" \
  --http-method POST \
  --oauth-service-account-email adar-sa@bdas-493785.iam.gserviceaccount.com
```

### Daily incremental (future)

Only processes matches played since the last run — ~2 minutes vs 20 minutes.

```bash
# Daily at 11pm — teamstats incremental only
gcloud scheduler jobs create http arcl-daily-incremental \
  --location us-central1 \
  --schedule "0 23 * * *" \
  --time-zone "America/Los_Angeles" \
  --uri "..." \
  --message-body '{"args": ["--only", "teamstats", "--incremental"]}'

# Every 2 hours on weekends — after match days
gcloud scheduler jobs create http arcl-match-check \
  --location us-central1 \
  --schedule "0 */2 * * 6,0" \
  --time-zone "America/Los_Angeles" \
  --uri "..."
```

### Schedule summary

| Job | Schedule | What | Duration |
|---|---|---|---|
| `arcl-weekly-reindex` | Sunday 2am PT | Full re-index all data | ~20 min |
| `arcl-daily-incremental` | Nightly 11pm (future) | New matches only | ~2 min |
| `arcl-match-check` | Every 2hrs weekends (future) | Standings + new scores | ~1 min |

---

## Production deployment

### Step 1 — GCP secrets (one-time setup)

```bash
# Generate JWT secret
echo -n "$(openssl rand -hex 32)" | gcloud secrets create jwt-secret \
  --data-file=- --project=bdas-493785

# Admin credentials
echo -n "admin@adar.agomoniai.com" | gcloud secrets create admin-email \
  --data-file=- --project=bdas-493785
echo -n "YOUR_STRONG_PASSWORD" | gcloud secrets create admin-password \
  --data-file=- --project=bdas-493785

# Stripe (use live keys for production)
echo -n "sk_live_xxx" | gcloud secrets create stripe-secret-key \
  --data-file=- --project=bdas-493785
echo -n "whsec_live_xxx" | gcloud secrets create stripe-webhook-secret \
  --data-file=- --project=bdas-493785
echo -n "price_live_xxx" | gcloud secrets create stripe-price-basic \
  --data-file=- --project=bdas-493785
echo -n "price_live_xxx" | gcloud secrets create stripe-price-standard \
  --data-file=- --project=bdas-493785
echo -n "price_live_xxx" | gcloud secrets create stripe-price-unlimited \
  --data-file=- --project=bdas-493785
echo -n "https://arcl.tigers.agomoniai.com" | gcloud secrets create frontend-url \
  --data-file=- --project=bdas-493785

# Update an existing secret (new version)
echo -n "new_value" | gcloud secrets versions add SECRET_NAME \
  --data-file=- --project=bdas-493785
```

### Step 2 — Grant service account access to secrets

```bash
for SECRET in google-api-key arcl-api-key jwt-secret admin-email admin-password \
              stripe-secret-key stripe-webhook-secret stripe-price-basic \
              stripe-price-standard stripe-price-unlimited frontend-url; do
  gcloud secrets add-iam-policy-binding $SECRET \
    --member="serviceAccount:adar-sa@bdas-493785.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor" \
    --project=bdas-493785
done
```

### Step 3 — Build and push Docker image

```bash
cd adar-arcl

docker build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest .

docker push us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest
```

### Step 4 — Deploy backend to Cloud Run

```bash
gcloud run deploy adar-arcl-api \
  --image us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 3 \
  --memory 1Gi \
  --cpu 1 \
  --port 8020 \
  --service-account adar-sa@bdas-493785.iam.gserviceaccount.com \
  --set-secrets "GOOGLE_API_KEY=google-api-key:latest,ARCL_API_KEY=arcl-api-key:latest,\
JWT_SECRET=jwt-secret:latest,ADMIN_EMAIL=admin-email:latest,ADMIN_PASSWORD=admin-password:latest,\
STRIPE_SECRET_KEY=stripe-secret-key:latest,STRIPE_WEBHOOK_SECRET=stripe-webhook-secret:latest,\
STRIPE_PRICE_BASIC=stripe-price-basic:latest,STRIPE_PRICE_STANDARD=stripe-price-standard:latest,\
STRIPE_PRICE_UNLIMITED=stripe-price-unlimited:latest,FRONTEND_URL=frontend-url:latest" \
  --set-env-vars "APP_NAME=adar-arcl-api,APP_ENV=production,GCP_PROJECT_ID=bdas-493785,\
FIRESTORE_DATABASE=tigers-arcl,EVAL_ENABLED=true,\
SESSION_DB_URL=postgresql+asyncpg://arcl_user:765793@/arcl_sessions?host=/cloudsql/bdas-493785:us-central1:adar-pgdev" \
  --add-cloudsql-instances bdas-493785:us-central1:adar-pgdev \
  --update-labels product=adar,service=arcl,env=production
```

### Step 5 — Deploy frontend

```bash
# Verify .env.production
cat arcl-chat-app/.env.production
# VITE_API_URL=https://api.arcl.tigers.agomoniai.com
# VITE_API_KEY=your_arcl_api_key

cd arcl-chat-app
npm install
npm run build
firebase deploy --only hosting
```

### Step 6 — Register Stripe webhook

```
Stripe Dashboard (LIVE mode) → Developers → Webhooks → Add endpoint
URL: https://api.arcl.tigers.agomoniai.com/api/payments/webhook
Events: checkout.session.completed · customer.subscription.deleted
        customer.subscription.trial_will_end · customer.subscription.updated
        invoice.payment_failed · invoice.payment_succeeded
```

### Step 7 — Verify production

```bash
# Health check
curl https://api.arcl.tigers.agomoniai.com/health

# Test admin login
curl -X POST https://api.arcl.tigers.agomoniai.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@adar.agomoniai.com","password":"YOUR_ADMIN_PASSWORD"}'

# Test chat with eval
curl -s -X POST https://api.arcl.tigers.agomoniai.com/api/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_KEY" \
  -d '{"message":"what is the wide rule","user_id":"test"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('eval:', d.get('eval'))"
```

### Quick redeploy (backend only)

```bash
docker build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest . \
  && docker push us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest \
  && gcloud run deploy adar-arcl-api \
    --image us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest \
    --region us-central1

# Frontend only
cd arcl-chat-app && npm run build && firebase deploy --only hosting
```

---

## API reference

### Chat

```
POST /api/chat
Headers: X-API-Key or Authorization: Bearer JWT
Body:     { "message": "...", "user_id": "...", "session_id": "..." }
Response: {
  "response":   "...",
  "session_id": "...",
  "user_id":    "...",
  "eval": {
    "scores": {
      "accuracy": 5, "completeness": 4,
      "relevance": 5, "format": 4, "overall": 4.65
    },
    "explanation": "Response correctly shows batting stats..."
  }
}

GET    /api/sessions/{id}?user_id=...
DELETE /api/sessions/{id}?user_id=...
GET    /api/tenant
GET    /health
```

### Polls

```
POST   /api/polls              create poll
GET    /api/polls              list latest 5 active
GET    /api/polls/{id}         get with vote counts
POST   /api/polls/{id}/vote    vote (voter_name, option_index)
```

---

## Debug scripts

| Script | Purpose |
|---|---|
| `tests/debug_teams.py` | Check `adar_teams` Firestore collection |
| `tests/debug_stripe.py` | Check Stripe subscriptions + sync to Firestore |
| `tests/debug_eval.py` | Full evaluation system debug — model discovery, JSON test, Firestore check |
| `tests/debug_scorecard.py` | Inspect Matchscorecard table structure from arcl.org |
| `tests/debug_teamstats_headers.py` | Print exact TeamStats table headers |
| `tests/find_team_ids.py` | Find team_id per season from DivHome |
| `tests/test_season.py` | Verify season_id resolution |

---

## Cost estimate

| Service | Monthly estimate |
|---|---|
| Cloud Run (scale-to-zero) | $2–5 |
| Firestore reads/writes | $1–3 |
| Cloud SQL (Postgres) | $3 |
| Firebase Hosting | Free |
| Cloud Scheduler | Free |
| Gemini API — chat (~1,500 messages/month/team) | ~$0.53/team |
| Gemini API — eval (~1,500 evals/month/team) | ~$0.60/team |
| **Total per team** | **~$7–12/month** |

At $15/month Standard plan: **~$3–8 margin per team per month.**

---

## Future — adar-core repo structure

Target repo organization for `agomonia-labs/adar-core`:

```
adar-core/
├── src/adar/              reusable core (agents, db, config, notify, tenants)
├── domains/arcl/          ARCL-specific tools, ingestion, prompts, examples
├── api/                   FastAPI routes split by domain
├── evaluation/            LLM-as-judge (judge.py, __init__.py)
├── ui/                    React frontend (from arcl-chat-app/)
├── tests/                 debug and test scripts
├── infra/                 Dockerfile, deploy.sh, create_indexes.sh
├── docs/                  architecture.md, setup.md, deployment.md
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

Adding a second league — just add `domains/nwcl/` with its own tools and ingestion.

---

## Naming convention

| Resource | Name |
|---|---|
| Cloud Run service | `adar-arcl-api` |
| Docker image | `us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest` |
| Firestore database | `tigers-arcl` |
| Cloud SQL instance | `bdas-493785:us-central1:adar-pgdev` |
| Cloud SQL database | `arcl_sessions` |
| API subdomain | `api.arcl.tigers.agomoniai.com` |
| Frontend subdomain | `arcl.tigers.agomoniai.com` |
| Cloud Run Job | `arcl-indexer` |
| Scheduler job | `arcl-weekly-reindex` |
| Service account | `adar-sa@bdas-493785.iam.gserviceaccount.com` |
| GCP Project | `bdas-493785` |

---

## License

MIT