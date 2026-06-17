# Geetabitan Adar

Geetabitan Adar is the `geetabitan` ADK domain in this repo. It is a Bengali AI assistant for Rabindranath Tagore's songs, including song search, raag, taal, paryay, summaries, notation, YouTube links, voice, and response evaluation.

This file is the domain-level README for developers working on the Geetabitan app.

## Key Files

- Agent config: [agents_config.geetabitan.json](/Users/brajadas/project/adar-core/src/adar/agents/agents_config.geetabitan.json)
- Tools: [domains/geetabitan/tools](/Users/brajadas/project/adar-core/domains/geetabitan/tools)
- Ingestion: [domains/geetabitan/ingestion](/Users/brajadas/project/adar-core/domains/geetabitan/ingestion)
- Local config example: `.env.geetabitan`

## Main Capabilities

- Song search by title, lyric fragment, meaning, or semantic query.
- Browse songs by `raag`, `taal`, and `paryay`.
- Explain raag, taal, meaning, context, emotion, and imagery.
- Retrieve full lyrics, stanza follow-ups, notation links, and OCR notation text.
- Generate YouTube listening links.
- Bengali voice input/output for the product demo and chat flow.

## Local Run

```bash
DOTENV_FILE=.env.geetabitan DOMAIN=geetabitan PYTHONPATH=$(pwd) python api/main.py
```

Frontend:

```bash
cd ui
npm run dev -- --mode geetabitan
```

Demo:

```text
http://localhost:5173/demo.geetabitan.html
```

## Deployment

Backend:

```bash
bash infra/deploy-geetabitan.sh
```

Frontend:

```bash
cd ui
npm run build -- --mode geetabitan
firebase deploy --only hosting:geetabitan
```
