# গীতবিতান আদর — Geetabitan Adar

> **আগোমোনিয়া ল্যাবস** নির্মিত রবীন্দ্রসঙ্গীতের এআই সহায়ক  
> An AI-powered assistant for Rabindranath Tagore's complete works, built on the **ADAR** platform.

🌐 **Live:** https://geetabitan.adar.agomoniai.com  
📖 **Demo:** https://geetabitan.adar.agomoniai.com/demo.geetabitan.html  
🔧 **API:** https://api.geetabitan.adar.agomoniai.com

---

## What is ADAR?

| Letter | Meaning | What it does |
|--------|---------|--------------|
| **A** | Agentic | Autonomous agents decide which tools to call and when |
| **D** | Data | Live data from Geetabitan — lyrics, raag, taal, paryay |
| **A** | Access | Multi-source access via Firestore vector search |
| **R** | Reasoning | Gemini models reason over retrieved data in Bengali |

---

## Features

### Chat
- 🎵 **Song search** — find any Tagore song by title, keyword, or description
- 🎼 **Raag filter** — search by raag (ভৈরবী, বাউল, কাফি, ইমন and 22 more)
- 🥁 **Taal filter** — filter by taal (দাদরা, কাহারবা, তিনতাল and more)
- 📚 **Paryay filter** — browse by category (পূজা, প্রেম, স্বদেশ, প্রকৃতি, বিচিত্র)
- 💡 **Song analysis** — context, meaning, emotion, imagery for any song
- 📝 **Swaralipi** — notation links + OCR'd notation text from ingested books

### Voice
- 🎤 **Speech-to-text** — speak in Bengali, get answers instantly
  - Chrome/Edge: Web Speech API (free, instant)
  - Firefox: Google Cloud STT via `/api/stt`
  - Safari: Google Cloud STT with MP4→FLAC conversion

### Platform
- 🔐 **Auth** — JWT-based login, team accounts in Firestore
- 💳 **Billing** — Stripe subscriptions (Basic $10 / Standard $15 / Unlimited $30)
- 📊 **Polls** — weekly Bengali polls, auto-open Monday, auto-close Friday
- ⭐ **Eval** — every response auto-scored by a second Gemini judge
- 🔊 **TTS** — `bn-IN-Chirp3-HD-Fenrir` voice for the demo presentation

---

## Architecture

```
Browser / Mobile App
        │
        ▼
Firebase Hosting (React + Vite)
geetabitan.adar.agomoniai.com
        │  REST
        ▼
Cloud Run  — adar-geetabitan-api
api.geetabitan.adar.agomoniai.com
        │
        ├── Google ADK Orchestrator (gemini-2.5-flash)
        │       └── Song Agent
        │               ├── vector_search_songs      (Firestore vector)
        │               ├── get_full_song
        │               ├── get_songs_by_raag
        │               ├── get_songs_by_taal
        │               ├── get_songs_by_paryay
        │               ├── summarize_aspect
        │               ├── get_notation_link
        │               └── get_notation_text
        │
        ├── /api/demo/tts   → Google Cloud TTS  (bn-IN-Chirp3-HD-Fenrir)
        ├── /api/stt        → Google Cloud STT  (WEBM_OPUS / OGG_OPUS / FLAC)
        │
        ├── Firestore  geetabitan-db
        │       ├── geetabitan_songs     (lyrics + embeddings)
        │       ├── adar_teams           (user accounts)
        │       ├── geetabitan_evals     (LLM-as-judge scores)
        │       └── geetabitan_polls     (weekly polls)
        │
        └── Secret Manager  (API keys, JWT secret, Stripe keys)
```

---

## GCP Resources

| Resource | Name / ID |
|----------|-----------|
| Project | `bdas-493785` |
| Cloud Run | `adar-geetabitan-api` · `us-central1` |
| Firebase Hosting | `geetabitan-adar` |
| Firestore DB | `geetabitan-db` |
| TTS API Key | `geetabitan-tts` · `f40f0f20-fb7d-4f20-8a2c-c0d3b68a7774` |
| Speech API Key | `geetabitan-speech` · `a616aaf4-e358-4836-858b-3dc6e50a17e4` |
| Gemini API Key | `bdas-gemini-apikey` · `1974d0d0-d363-4ee7-bce6-212008977531` |

---

## Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment
cp .env.geetabitan.example .env.geetabitan
# Edit .env.geetabitan with your keys

# Run backend
DOTENV_FILE=.env.geetabitan PYTHONPATH=$(pwd) python api/main.py

# Run frontend
cd ui
npm install
npm run dev -- --mode geetabitan
```

---

## Deployment

```bash
# Backend (Cloud Run)
bash infra/deploy-geetabitan.sh

# Frontend (Firebase)
cd ui
npm run build -- --mode geetabitan
firebase deploy --only hosting:geetabitan
```

---

## Ingestion Pipeline

```bash
set -a && source .env.geetabitan && set +a

# 1. Scrape song data from geetabitan.com
PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only scrape

# 2. Enrich metadata to Bengali Unicode
PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only enrich

# 3. Embed songs into Firestore vector store
PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only songs

# 4. Generate summaries
PYTHONPATH=$(pwd) python -m domains.geetabitan.ingestion.run_ingestion --only summaries
```

### Swaralipi (Notation) OCR

```bash
# Dry run — preview OCR output without saving
DOTENV_FILE=.env.geetabitan PYTHONPATH=$(pwd) \
python -m domains.geetabitan.ingestion.swaralipi_ocr \
  --pdf /path/to/swaralipi_vol1.pdf \
  --source "গীতবিতান স্বরলিপি ১ম খণ্ড" \
  --dry-run

# Full ingestion
DOTENV_FILE=.env.geetabitan PYTHONPATH=$(pwd) \
python -m domains.geetabitan.ingestion.swaralipi_ocr \
  --pdf /path/to/swaralipi_vol1.pdf \
  --source "গীতবিতান স্বরলিপি ১ম খণ্ড"
```

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/login` | — | Login, returns JWT |
| POST | `/api/auth/register` | — | Register new team |
| POST | `/api/chat` | JWT | Main chat endpoint |
| POST | `/api/demo/tts` | — | Bengali TTS (Fenrir voice) |
| POST | `/api/stt` | JWT | Speech-to-text (all browsers) |
| GET | `/api/polls` | JWT | Get active polls |
| POST | `/api/polls/{id}/vote` | JWT | Cast a vote |
| GET | `/api/usage` | JWT | Check message quota |
| GET | `/health` | — | Health check |

---

## Suggested Questions

```
# Song search
আমার সোনার বাংলা গানটি খুঁজুন
একলা চলো রে গানটি দেখাও

# By raag
ভৈরবী রাগের গান দেখাও
বাউল রাগের গান কী কী?

# By taal
দাদরা তালের গান কী কী?
কাহারবা তালে কতটি গান আছে?

# By paryay
স্বদেশ পর্যায়ের গানগুলো দেখাও
পূজা পর্যায়ে কতটি গান আছে?

# Analysis
একলা চলো রে গানের অর্থ কী?
আমার সোনার বাংলা গানের প্রেক্ষাপট বলো

# Notation
আমার সোনার বাংলা গানের স্বরলিপি দাও

# Special
বর্ষার গান দেখাও
দেশপ্রেমের গান দেখাও
```

---

## Quality Scores

Every response is automatically evaluated by a second Gemini model:

| Dimension | Weight |
|-----------|--------|
| Accuracy | 35% |
| Completeness | 25% |
| Relevance | 25% |
| Format | 15% |

Current average: **4.65 / 5.0**  
Scores stored in `geetabitan_evals` Firestore collection.

---

## Subscription Plans

| Plan | Price | Messages/day |
|------|-------|-------------|
| Basic | $10/mo | 50 |
| Standard | $15/mo | 200 |
| Unlimited | $30/mo | 1000 |

All plans include 14-day free trial. Powered by Stripe.

---

*Built with ❤️ by [Agomonia Labs](https://agomoniai.com)*