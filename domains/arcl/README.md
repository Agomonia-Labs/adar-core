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
bash infra/deploy.sh
```

Frontend:

```bash
cd ui
npm run build -- --mode arcl
firebase deploy --only hosting:arcl
```
