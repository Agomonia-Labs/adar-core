# Adar — আদর

> **ADAR: Agentic Data Access and Reasoning**
>
> A general-purpose multi-agent AI platform for building domain-specific assistants.
> Each domain brings its own tools, ingestion pipeline, and agent configuration.
> The core framework is domain-agnostic and reusable across any vertical.

**Reference implementation:** ARCL cricket assistant — `https://arcl.tigers.agomoniai.com`  
**Demo:** `https://adar.agomoniai.com/demo.html`  
**Repo:** `github.com/agomonia-labs/adar-core`

---

## What ADAR means

| Letter | Word | What it means in practice |
|---|---|---|
| **A** | Agentic | Autonomous agents decide which tools to call, in what order, and how to chain multiple steps — no hardcoded flows |
| **D** | Data | Live data fetched on demand from external sources — not a static database |
| **A** | Access | Multi-source access unified behind one interface — web scraping, vector search, SQL, APIs |
| **R** | Reasoning | The AI reasons over retrieved data — computes scores, aggregates seasons, interprets patterns — not just retrieval |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend  (React + MUI · Firebase Hosting)                  │
│  Chat · Auth · Polls · Billing · Admin · Demo page           │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTPS  JWT / API Key
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  FastAPI  (Cloud Run)                                        │
│  /api/chat  /api/auth  /api/payments  /api/polls  /admin     │
│                                                              │
│  Off-topic guard → Rate limiter → Auth middleware            │
└──────────┬──────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────┐
│  Google ADK — Multi-agent system                          │
│                                                           │
│  Orchestrator agent                                       │
│    ├── Domain agent 1  (e.g. team_agent)                  │
│    ├── Domain agent 2  (e.g. rules_agent)                 │
│    ├── Domain agent 3  (e.g. player_agent)                │
│    └── Domain agent 4  (e.g. live_agent)                  │
│                                                           │
│  Each agent has a set of tools → functions that fetch     │
│  real data from external sources                          │
│                                                           │
│  Judge agent scores every response (LLM-as-judge)         │
└──────────┬────────────────────────┬──────────────────────┘
           │                        │
           ▼                        ▼
┌──────────────────┐    ┌────────────────────────────────┐
│  Domain sources  │    │  Firestore (vector + cache)     │
│  (live HTTP)     │    │  Cloud SQL (sessions)           │
│                  │    │  Stripe (subscriptions)         │
│  arcl.org        │    │  Secret Manager (secrets)       │
│  any web source  │    └────────────────────────────────┘
└──────────────────┘
```

---

## Project structure

```
adar-core/
│
├── src/adar/                        domain-agnostic core framework
│   ├── agents/
│   │   ├── agents.py                Agent factory — reads agents_config.json
│   │   └── agents_config.json       Agent definitions — swap per domain
│   ├── tools/
│   │   ├── rules_tools.py           Vector search tools (reusable)
│   │   └── live_tools.py            Live data fetch tools (reusable)
│   ├── config.py                    Settings — ADK model, Firestore, season map
│   ├── db.py                        Firestore client, vector search, queries
│   ├── tenants.py                   Multi-tenant registry
│   └── notify.py                    Email notifications (SendGrid + Gmail)
│
├── domains/                         domain-specific implementations
│   └── arcl/                        reference implementation — ARCL cricket
│       ├── tools/
│       │   ├── __init__.py          TOOL_REGISTRY — maps tool name to function
│       │   ├── team_tools.py        Team stats, scorecards, dismissals, schedule
│       │   └── player_tools.py      Player stats, career data, top performers
│       └── ingestion/
│           ├── arcl_scraper.py      Crawls arcl.org — rules, players, standings
│           ├── arcl_embedder.py     Embeds chunks → Firestore vector search
│           └── run_ingestion.py     CLI — --only, --seasons, --team flags
│
├── api/                             FastAPI application
│   ├── main.py                      Entry point — chat, health, sessions
│   ├── schemas.py                   Pydantic models (includes eval field)
│   └── routes/
│       ├── auth.py                  Registration, login, JWT
│       ├── admin.py                 Team management, approvals, quotas
│       ├── payments.py              Stripe — checkout, webhooks, billing
│       └── polls.py                 Community polls CRUD
│
├── evaluation/
│   ├── __init__.py
│   └── judge.py                     LLM-as-judge — scores every response (5 dims)
│
├── ui/                              React + MUI frontend (Vite)
│   ├── src/
│   │   ├── App.jsx                  Chat, tabs, auth routing, auto-logout
│   │   ├── Login.jsx                Login + demo link
│   │   ├── Register.jsx             Self-registration
│   │   ├── AdminDashboard.jsx       Team management, eval scores
│   │   ├── Checkout.jsx             Stripe plan selection + branded redirect
│   │   ├── Billing.jsx              Subscription status + invoice history
│   │   ├── Polls.jsx                Polls — create, vote, results
│   │   ├── StatsChart.jsx           CSS bar charts (no library)
│   │   └── theme.js                 Light green MUI theme
│   └── public/
│       ├── demo.html                Interactive product demo (auto-narrated)
│       └── go.html                  Branded Stripe checkout redirect
│
├── tests/                           Debug and test scripts
├── infra/
│   ├── Dockerfile
│   ├── deploy.sh
│   └── create_indexes.sh
├── docs/
│   └── architecture.md
├── requirements.txt
├── pyproject.toml
├── .env.example
├── .gitignore
└── README.md
```

**PYTHONPATH note:** always set before running:
```bash
export PYTHONPATH=/path/to/adar-core
```

---

## Adding a new domain

To build an assistant for a new domain (e.g. a restaurant chain, another sports league, a retail catalogue):

**1. Create the domain folder:**
```
domains/
└── my_domain/
    ├── tools/
    │   ├── __init__.py          TOOL_REGISTRY with your tools
    │   └── my_tools.py          Functions that fetch your data
    └── ingestion/
        └── run_ingestion.py     Scrape + embed your knowledge base
```

**2. Write your tools:**
```python
# domains/my_domain/tools/my_tools.py
async def get_product_info(product_name: str) -> str:
    """Fetch product data from your source."""
    ...
```

**3. Configure your agents in `agents_config.json`:**
```json
{
  "agents": [
    {
      "name": "my_orchestrator",
      "instruction": "You are the assistant for [domain]. Route questions to the right agent.",
      "sub_agents": ["my_domain_agent"]
    },
    {
      "name": "my_domain_agent",
      "tools": ["get_product_info"],
      "instruction": "Answer questions about products using the tools provided."
    }
  ]
}
```

**4. Run ingestion to populate Firestore:**
```bash
PYTHONPATH=$(pwd) python -m domains.my_domain.ingestion.run_ingestion
```

**5. Start the server — same API, same frontend:**
```bash
PYTHONPATH=$(pwd) python api/main.py
```

The core framework (auth, billing, sessions, evaluation, polls) is inherited automatically.

---

## Reference implementation — ARCL cricket

The ARCL domain demonstrates the full platform capabilities end to end.

### What it answers

| Question | Agent | Source |
|---|---|---|
| "What is the wide rule in men's league?" | Rules | arcl.org Rules.aspx (vector search) |
| "How many runs has Jiban Adhikary scored?" | Player | arcl.org TeamStats.aspx (live) |
| "Show Agomoni Tigers batting stats Spring 2026" | Team | arcl.org TeamStats.aspx (live) |
| "How was Jiban dismissed this season?" | Team | arcl.org Matchscorecard.aspx (live) |
| "What is our team strength?" | Team | arcl.org all seasons (live aggregate) |
| "Top 5 batsmen in Div H Spring 2026?" | Player | arcl.org DivHome + TeamStats all teams (live) |
| "Current standings in Div H?" | Live | arcl.org DivHome.aspx (live) |

### Five agents

| Agent | Handles | Tools |
|---|---|---|
| `arcl_orchestrator` | Routes every question using explicit routing rules | — |
| `rules_agent` | Rules, umpiring, FAQ | `vector_search_rules` · `get_rule_section` · `get_faq_answer` |
| `player_agent` | Named players + cross-division top performers | `get_player_stats` · `get_player_season_stats` · `get_top_performers` · `get_top_performers_live` |
| `team_agent` | Team-specific stats, scorecards, dismissals | `get_team_players_live` · `get_match_scorecard` · `get_player_dismissals` · `get_team_career_stats` · `get_team_schedule` |
| `live_agent` | Standings, schedule, results | `get_standings` · `get_schedule` · `get_recent_results` |

### Live fetch vs Firestore cache

| Data | Strategy | Why |
|---|---|---|
| Player batting/bowling per season | **Live** — TeamStats.aspx | arcl.org assigns new `team_id` each season |
| Match scorecards / dismissals | **Live** — Matchscorecard.aspx | Per-match detail, always fresh |
| Schedule | **Live** — LeagueSchedule.aspx | Changes weekly |
| Rules / FAQ | **Firestore** — vector search | Semantic search, rarely changes |
| Player career overview | **Firestore** — vector search | Stable, cross-team queries |

---

## Infrastructure

| Component | Resource |
|---|---|
| Backend | Cloud Run `adar-arcl-api` · `api.arcl.tigers.agomoniai.com` |
| Frontend | Firebase Hosting · `arcl.tigers.agomoniai.com` |
| GCP Project | `bdas-493785` · us-central1 |
| Firestore | `tigers-arcl` database · Native mode |
| Cloud SQL | `adar-pgdev` · `arcl_sessions` DB |
| Artifact Registry | `us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest` |
| Service Account | `adar-sa@bdas-493785.iam.gserviceaccount.com` |
| DNS | AWS Route 53 · `agomoniai.com` |
| ADK model | `gemini-2.5-flash` (agents + judge) |

---

## Multi-agent system

All agent behaviour defined in `src/adar/agents/agents_config.json`.
Edit and restart to update — no redeploy needed.

### How agents communicate

```
User question
    ↓
Orchestrator reads question → decides which agent
    ↓
Agent decides which tools to call (1 to N calls)
    ↓
Each tool call fetches real data (HTTP, Firestore, SQL)
    ↓
Agent reasons over all results → generates response
    ↓
Judge agent scores response on 5 dimensions
    ↓
Response + scores returned to frontend
```

### Orchestrator routing rules

| Query pattern | Agent | Tool |
|---|---|---|
| "top batsmen in **Agomoni Tigers**" (specific team) | `team_agent` | `get_team_players_live` |
| "top batsmen in **Div H**" (cross-team, division) | `player_agent` | `get_top_performers_live` |
| "how many runs has **Jiban** scored" (named player) | `player_agent` | `get_player_stats` |
| "**wide rule** in men's league" | `rules_agent` | `vector_search_rules` |
| "current **standings** in Div H" | `live_agent` | `get_standings` |

`get_top_performers_live` scrapes all teams in a division live from `DivHome.aspx` → fetches each team's `TeamStats.aspx` → aggregates all players → sorts by runs or wickets. Works for any division, any team, any season.

### Example — "How was Jiban dismissed in Spring 2026?"

```
1. Orchestrator → team_agent  (keyword: "dismissed")
2. team_agent → get_team_schedule("Agomoni Tigers", 69)
   → fetches LeagueSchedule.aspx → returns 8 match IDs
3. team_agent → get_match_scorecard(match_id) × 8
   → fetches each Matchscorecard.aspx → parses How_out column
4. team_agent reasons over 8 scorecards
   → aggregates: Caught 7, Bowled 5, Run Out 3, Not Out 4
   → ranks top dismissers
5. Returns formatted table + eval scores
```

---

## Scope control

Adar only answers domain-relevant questions. Off-topic questions (coding, math, cooking, general knowledge) are blocked by two layers:

**Layer 1 — keyword pre-check** in `api/main.py` (instant, zero LLM cost)
Blocks obvious off-topic queries before they reach the agent.

**Layer 2 — orchestrator system prompt**
The LLM itself is instructed to refuse off-topic questions and redirect.

The scope is configured per domain via `agents_config.json` — swap the orchestrator instruction to change what the assistant covers.

---

## Memory model

### Short-term — conversation context

```
Storage:  Cloud SQL (Postgres) via Google ADK SessionService
Scope:    per user · per session
Expiry:   30 minutes (frontend auto-logout)
Purpose:  Adar remembers what was said earlier in the chat
          "show our batting stats" → "now show bowling"
          ← Adar knows "our" = Agomoni Tigers from context
```

### Long-term — knowledge base

```
Storage:  Firestore — vector search (768-dim Gemini embeddings)
Scope:    shared across all sessions
Purpose:  Rules, FAQ, player career overviews
          Semantic search: "ball hits umpire" → finds "dead ball rule"
Collections:
  arcl_rules          Rules chunks with [MEN'S/WOMEN'S LEAGUE] tags
  arcl_faq            FAQ pairs
  arcl_players        Player career overview
  arcl_teams          Standings per season
  arcl_player_seasons Batting/bowling per player per season
  arcl_evals          LLM-as-judge scores (audit trail)
```

### Ephemeral — live data

```
Fetched fresh on every query — never cached
Sources:  TeamStats.aspx · Matchscorecard.aspx · DivHome.aspx
Why:      Match results and player stats change after every game
```

---

## Authentication

JWT-based. 30-day token expiry. Admin role separate from domain users.

```
Team registers → status: pending
Admin approves → status: active
Team logs in → JWT (30 days)
Frontend auto-logout after 30 min inactivity
```

| Endpoint | Description |
|---|---|
| `POST /api/auth/register` | Self-registration |
| `POST /api/auth/login` | Email + password → JWT |
| `GET  /api/auth/me` | Current user info |
| `GET  /admin/teams` | List all teams (admin) |
| `POST /admin/teams/{id}/approve` | Approve registration |

---

## Stripe payments

14-day free trial · Auto-renewing monthly · PCI DSS compliant

| Plan | Price | Daily quota |
|---|---|---|
| Basic | $10/month | 50 messages |
| Standard | $15/month | 200 messages |
| Unlimited | $30/month | 1000 messages |

Webhook URL:
```
https://api.arcl.tigers.agomoniai.com/api/payments/webhook
```

Events: `checkout.session.completed` · `invoice.payment_succeeded` · `invoice.payment_failed` · `customer.subscription.deleted` · `customer.subscription.updated`

---

## Response evaluation (LLM-as-judge)

Every response scored automatically by a second Gemini instance.

| Dimension | Weight | Measures |
|---|---|---|
| Accuracy | 35% | Facts and stats correct? |
| Completeness | 25% | Fully answers the question? |
| Relevance | 25% | On topic? |
| Format | 15% | Tables, markdown, readable? |
| Overall | — | Weighted average 0–5 |

Scores appear as badges in the chat UI. Stored in `arcl_evals` Firestore collection. Admin can view aggregates and flag low-scoring responses.

```
GET /admin/evals              → aggregate scores all teams
GET /admin/evals/{team_id}    → per-team scores
GET /admin/evals/recent/low   → responses scoring < 3.0
```

---

## Local development

### Setup

```bash
git clone https://github.com/agomonia-labs/adar-core
cd adar-core
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export PYTHONPATH=$(pwd)
cp .env.example .env   # fill in your values
```

### Start backend

```bash
PYTHONPATH=$(pwd) python api/main.py
# http://localhost:8040
# Docs: http://localhost:8040/docs (dev only)
```

### Start frontend

```bash
cd ui
npm install
npm run dev
# http://localhost:5173
```

### Run ingestion (ARCL domain)

```bash
# Current season
PYTHONPATH=$(pwd) python -m domains.arcl.ingestion.run_ingestion --only teamstats --seasons 69

# Rules only
PYTHONPATH=$(pwd) python -m domains.arcl.ingestion.run_ingestion --only rules

# Full reindex
PYTHONPATH=$(pwd) python -m domains.arcl.ingestion.run_ingestion
```

### Run debug scripts

```bash
PYTHONPATH=$(pwd) python tests/debug_teams.py
PYTHONPATH=$(pwd) python tests/debug_eval.py
PYTHONPATH=$(pwd) python tests/debug_stripe.py
```

### `.env` reference

```bash
# Google / GCP
GOOGLE_API_KEY=
GCP_PROJECT_ID=bdas-493785
FIRESTORE_DATABASE=tigers-arcl
GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json  # local only

# Session storage
SESSION_DB_URL=sqlite+aiosqlite:///./arcl_sessions.db

# Auth
JWT_SECRET=                   # openssl rand -hex 32
ADMIN_EMAIL=
ADMIN_PASSWORD=

# Stripe (test mode)
STRIPE_SECRET_KEY=sk_test_
STRIPE_WEBHOOK_SECRET=whsec_  # from: stripe listen output
STRIPE_PRICE_BASIC=price_
STRIPE_PRICE_STANDARD=price_
STRIPE_PRICE_UNLIMITED=price_
FRONTEND_URL=http://localhost:5173

# API protection
ARCL_API_KEY=

# Evaluation
EVAL_ENABLED=true
```

---

## Production deployment

### Step 1 — Build and push

```bash
docker build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest .
docker push us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest
```

### Step 2 — Deploy to Cloud Run

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
  --port 8040 \
  --service-account adar-sa@bdas-493785.iam.gserviceaccount.com \
  --set-secrets "GOOGLE_API_KEY=google-api-key:latest,ARCL_API_KEY=arcl-api-key:latest,\
JWT_SECRET=jwt-secret:latest,ADMIN_EMAIL=admin-email:latest,ADMIN_PASSWORD=admin-password:latest,\
STRIPE_SECRET_KEY=stripe-secret-key:latest,STRIPE_WEBHOOK_SECRET=stripe-webhook-secret:latest,\
STRIPE_PRICE_BASIC=stripe-price-basic:latest,STRIPE_PRICE_STANDARD=stripe-price-standard:latest,\
STRIPE_PRICE_UNLIMITED=stripe-price-unlimited:latest,FRONTEND_URL=frontend-url:latest" \
  --set-env-vars "APP_NAME=adar-arcl-api,APP_ENV=production,GCP_PROJECT_ID=bdas-493785,\
FIRESTORE_DATABASE=tigers-arcl,EVAL_ENABLED=true,\
SESSION_DB_URL=postgresql+asyncpg://arcl_user:765793@/arcl_sessions?host=/cloudsql/bdas-493785:us-central1:adar-pgdev" \
  --add-cloudsql-instances bdas-493785:us-central1:adar-pgdev
```

### Step 3 — Deploy frontend

```bash
cp adar-demo.html ui/public/demo.html
cd ui
npm run build
firebase deploy --only hosting
```

### Quick redeploy

```bash
# Backend
docker build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest . \
  && docker push us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest \
  && gcloud run deploy adar-arcl-api \
    --image us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest \
    --region us-central1

# Frontend only
cd ui && npm run build && firebase deploy --only hosting
```

---

## Scheduled ingestion

```bash
# Run on GCP now
gcloud run jobs execute arcl-indexer --region us-central1

# Manual weekly run (local)
PYTHONPATH=$(pwd) python -m domains.arcl.ingestion.run_ingestion --only teamstats --seasons 69

# Change schedule
gcloud scheduler jobs update http arcl-weekly-reindex \
  --schedule "0 2 * * 0" --location us-central1
```

---

## Debug scripts

| Script | Purpose |
|---|---|
| `tests/debug_teams.py` | Check `adar_teams` Firestore collection |
| `tests/debug_stripe.py` | Stripe subscriptions + sync |
| `tests/debug_eval.py` | Evaluation system + model discovery |
| `tests/debug_scorecard.py` | Matchscorecard table structure |
| `tests/find_team_ids.py` | Find team_id per season |

---

## Cost estimate (ARCL reference implementation)

| Service | Monthly |
|---|---|
| Cloud Run (scale-to-zero) | $2–5 |
| Firestore reads/writes | $1–3 |
| Cloud SQL (Postgres) | $3 |
| Firebase Hosting | Free |
| Gemini API (chat + eval ~1500 msgs) | ~$1.13 |
| **Total per tenant** | **~$7–12** |

At $15/month Standard plan → **$3–8 margin per tenant per month.**

---

## Naming

| Resource | Name |
|---|---|
| Repo | `agomonia-labs/adar-core` |
| Cloud Run service | `adar-arcl-api` |
| Docker image | `us-central1-docker.pkg.dev/bdas-493785/adar/arcl-api:latest` |
| Firestore database | `tigers-arcl` |
| Cloud SQL | `bdas-493785:us-central1:adar-pgdev` |
| API subdomain | `api.arcl.tigers.agomoniai.com` |
| Frontend subdomain | `arcl.tigers.agomoniai.com` |
| Service account | `adar-sa@bdas-493785.iam.gserviceaccount.com` |

---

## GitHub topics

```
agentic-ai  multi-agent  google-adk  gemini  fastapi
rag  vector-search  firestore  stripe  llm-evaluation
python  react  cloud-run  google-cloud
```

---

## License

MIT