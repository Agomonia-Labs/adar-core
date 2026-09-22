# Adar ARCL

Adar ARCL is the `arcl` ADK domain in this repo. It is an AI assistant for the American Recreational Cricket League, focused on league rules, teams, players, standings, schedules, scorecards, and cricket statistics.

## Key Files

- Agent config: [agents_config.arcl.json](/Users/brajadas/project/adar-core/src/adar/agents/agents_config.arcl.json)
- Tools: [domains/arcl/tools](/Users/brajadas/project/adar-core/domains/arcl/tools)
- Ingestion: [domains/arcl/ingestion](/Users/brajadas/project/adar-core/domains/arcl/ingestion)
- Deployment script: [infra/deploy.sh](/Users/brajadas/project/adar-core/infra/deploy.sh)

## Agents

- `arcl_orchestrator`: routes ARCL questions to the right specialist.
- `rules_agent`: answers rules, regulations, umpiring, eligibility, and FAQ questions.
- `player_agent`: answers player stats and top performer questions.
- `team_agent`: answers team roster, schedule, history, season, and career-stat questions.
- `live_agent`: fetches current standings, schedules, results, and announcements.

## Common Questions

```text
What is the wide-ball rule in men's ARCL?
Show top batsmen in Div H.
Show Agomoni Tigers batting stats.
What is Agomoni Tigers schedule?
Show current standings.
How was a player dismissed in a match?
```

## Local Run

```bash
DOMAIN=arcl PYTHONPATH=$(pwd) python api/main.py
```

Frontend:

```bash
cd ui
npm run dev -- --mode arcl
```

Demo:

```text
http://localhost:5173/demo.html
```

## Deployment

Backend:

```bash
export ARCL_GUEST_ACCESS_ENABLED=true
export ARCL_GUEST_VOICE_ENABLED=true
bash infra/deploy.sh
```

The deployment script preserves the existing Cloud Run configuration and
enables the public, least-privilege ARCL guest facade. Guest access uses
short-lived JWTs and exposes only cricket chat, temporary sessions,
capabilities, examples, STT, and TTS:

```text
POST   /api/arcl/guest/session
GET    /api/arcl/guest/capabilities
GET    /api/arcl/guest/examples
POST   /api/arcl/guest/chat
POST   /api/arcl/guest/stt
POST   /api/arcl/guest/tts
DELETE /api/arcl/guest/session/{session_id}
```

Run the focused guest-boundary tests before deployment:

```bash
venv/bin/python -m unittest tests.test_arcl_guest tests.test_scheduling_guest
```

Frontend:

```bash
cd ui
npm run build -- --mode arcl
firebase deploy --only hosting:arcl
```

The Agomonia Labs public experience is maintained separately in
`/Users/brajadas/project/adar-web/arcl.html` and should be deployed only after
the backend guest endpoints are available.
