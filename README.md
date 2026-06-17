# ADAR Core

ADAR Core contains multiple domain-specific AI assistant apps. Each domain keeps its own setup, agent, ingestion, deployment, and troubleshooting documentation in its domain folder.

## Domain READMEs

| Domain App | Description | README |
|------------|-------------|--------|
| Geetabitan Adar | Bengali Rabindra Sangeet assistant for songs, raag, taal, paryay, notation, and voice. | [domains/geetabitan/README.md](domains/geetabitan/README.md) |
| ARCL Adar | American Recreational Cricket League assistant for rules, teams, players, schedules, standings, and stats. | [domains/arcl/README.md](domains/arcl/README.md) |
| Restaurant Recommender | Restaurant food recommender for menus, prices, reviews, locations, and comparisons. | [domains/restaurants/README.md](domains/restaurants/README.md) |

## Shared App Areas

| Area | Path |
|------|------|
| API | [api](api) |
| ADK agent loader/configs | [src/adar/agents](src/adar/agents) |
| Shared UI | [ui](ui) |
| Infrastructure scripts | [infra](infra) |

## Domain Selection

Run a domain by setting `DOMAIN`:

```bash
DOMAIN=geetabitan
DOMAIN=arcl
DOMAIN=restaurants
```

Each domain README includes the exact local development, ingestion, deployment, and production configuration steps for that app.
