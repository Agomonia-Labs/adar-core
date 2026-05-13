"""
api/routes/polls.py
Poll endpoints — domain-aware.
Polls stored in Firestore under {DOMAIN}_polls collection.
Works for both ARCL (cricket) and Geetabitan (Tagore songs) with no code duplication.
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from google.cloud import firestore

# ── CHANGE 1: import DOMAIN and API_KEY alongside settings ───────────────────
from src.adar.config import settings, DOMAIN, API_KEY

router = APIRouter(prefix="/api/polls", tags=["polls"])

# ── CHANGE 2: collection name is domain-scoped ────────────────────────────────
POLLS_COLLECTION = f"{DOMAIN}_polls"


def get_db():
    return firestore.AsyncClient(
        project=settings.GCP_PROJECT_ID,
        database=settings.FIRESTORE_DATABASE,
    )


# ── Models ────────────────────────────────────────────────────────────────────

class CreatePollRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=300)
    options: list[str] = Field(..., min_length=2, max_length=10)
    created_by: str = Field(..., min_length=1, max_length=50)


class VoteRequest(BaseModel):
    voter_name: str = Field(..., min_length=1, max_length=50)
    option_index: int = Field(..., ge=0)


class PollOption(BaseModel):
    text: str
    votes: list[str] = []   # list of voter names


class PollResponse(BaseModel):
    poll_id: str
    question: str
    options: list[PollOption]
    created_by: str
    created_at: str
    total_votes: int


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("", response_model=PollResponse)
async def create_poll(request: CreatePollRequest):
    """Create a new poll with a question and options."""
    options = [o.strip() for o in request.options if o.strip()]
    if len(options) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 options")
    if len(set(o.lower() for o in options)) != len(options):
        raise HTTPException(status_code=400, detail="Duplicate options not allowed")

    poll_id = str(uuid.uuid4())[:8].upper()

    poll_data = {
        "poll_id":    poll_id,
        "question":   request.question.strip(),
        "options":    [{"text": o, "votes": []} for o in options],
        "created_by": request.created_by.strip(),
        "created_at": datetime.utcnow().isoformat(),
        "active":     True,
    }

    db = get_db()
    await db.collection(POLLS_COLLECTION).document(poll_id).set(poll_data)

    return PollResponse(
        poll_id=poll_id,
        question=poll_data["question"],
        options=[PollOption(**o) for o in poll_data["options"]],
        created_by=poll_data["created_by"],
        created_at=poll_data["created_at"],
        total_votes=0,
    )


@router.get("/{poll_id}", response_model=PollResponse)
async def get_poll(poll_id: str):
    """Get a poll and its current vote results."""
    db = get_db()
    doc = await db.collection(POLLS_COLLECTION).document(poll_id.upper()).get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Poll not found")

    data = doc.to_dict()
    total = sum(len(o.get("votes", [])) for o in data["options"])

    return PollResponse(
        poll_id=data["poll_id"],
        question=data["question"],
        options=[PollOption(**o) for o in data["options"]],
        created_by=data["created_by"],
        created_at=data["created_at"],
        total_votes=total,
    )


@router.post("/{poll_id}/vote", response_model=PollResponse)
async def vote(poll_id: str, request: VoteRequest):
    """Submit a vote. Each person (by name) can only vote once per poll."""
    db = get_db()
    ref = db.collection(POLLS_COLLECTION).document(poll_id.upper())
    doc = await ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail="Poll not found")

    data = doc.to_dict()

    if not data.get("active", True):
        raise HTTPException(status_code=400, detail="This poll is closed")

    options = data["options"]
    voter = request.voter_name.strip()

    for opt in options:
        if voter.lower() in [v.lower() for v in opt.get("votes", [])]:
            raise HTTPException(
                status_code=400,
                detail=f"'{voter}' has already voted in this poll",
            )

    if request.option_index >= len(options):
        raise HTTPException(status_code=400, detail="Invalid option")

    options[request.option_index]["votes"].append(voter)
    await ref.update({"options": options})

    total = sum(len(o.get("votes", [])) for o in options)

    return PollResponse(
        poll_id=data["poll_id"],
        question=data["question"],
        options=[PollOption(**o) for o in options],
        created_by=data["created_by"],
        created_at=data["created_at"],
        total_votes=total,
    )


@router.get("", response_model=list[PollResponse])
async def list_polls():
    """List all active polls, newest first."""
    db = get_db()
    polls = []
    async for doc in db.collection(POLLS_COLLECTION) \
                       .where("active", "==", True) \
                       .limit(5) \
                       .stream():
        data = doc.to_dict()
        total = sum(len(o.get("votes", [])) for o in data["options"])
        polls.append(PollResponse(
            poll_id=data["poll_id"],
            question=data["question"],
            options=[PollOption(**o) for o in data["options"]],
            created_by=data["created_by"],
            created_at=data["created_at"],
            total_votes=total,
        ))

    polls.sort(key=lambda p: p.created_at, reverse=True)
    return polls


@router.post("/{poll_id}/close")
async def close_poll(poll_id: str, admin_key: str = ""):
    # ── CHANGE 3: use domain-scoped API_KEY (was ARCL_API_KEY) ───────────────
    if API_KEY and admin_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    db = get_db()
    ref = db.collection(POLLS_COLLECTION).document(poll_id.upper())
    doc = await ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Poll not found")
    await ref.update({"active": False, "closed_at": datetime.utcnow().isoformat()})
    return {"closed": True, "poll_id": poll_id.upper()}


# ── Weekly auto-poll questions (domain-specific) ──────────────────────────────
# ── CHANGE 4: WEEKLY_QUESTIONS keyed by DOMAIN ───────────────────────────────

_WEEKLY_QUESTIONS_ARCL = [
    {
        "question": "Who was the best batter of the week?",
        "options":  ["Jiban Adhikary", "Anijit Roy", "Madhusudan Banik",
                     "Aushik Pyne", "Shariful Shaikot", "Other"],
    },
    {
        "question": "Who was the best bowler of the week?",
        "options":  ["Shariful Shaikot", "Anijit Roy", "Swadesh Poddar",
                     "Sujit Biswas", "Madhusudan Banik", "Other"],
    },
    {
        "question": "Best fielding performance of the week?",
        "options":  ["Jiban Adhikary", "Aurko Khandakar", "BRAJA KRISHNA DAS",
                     "Hillol Debnath", "Abdul Kiyum", "Other"],
    },
    {
        "question": "How would you rate the team performance this week?",
        "options":  ["Excellent", "Good", "Average", "Needs improvement"],
    },
    {
        "question": "Player of the match this week?",
        "options":  ["Jiban Adhikary", "Anijit Roy", "Shariful Shaikot",
                     "Swadesh Poddar", "Madhusudan Banik", "Other"],
    },
    {
        "question": "What should the team focus on next practice?",
        "options":  ["Batting technique", "Bowling accuracy", "Fielding",
                     "Running between wickets", "Team strategy"],
    },
]

_WEEKLY_QUESTIONS_GEETABITAN = [
    {
        "question": "এই সপ্তাহের প্রিয় রবীন্দ্রসঙ্গীত কোনটি?",
        "options":  ["আমার সোনার বাংলা", "একলা চলো রে", "আনন্দলোকে মঙ্গলালোকে",
                     "আমি চিনি গো চিনি তোমারে", "গহন কুসুমকুঞ্জ মাঝে", "অন্যটি"],
    },
    {
        "question": "কোন পর্যায়ের গান আপনার সবচেয়ে প্রিয়?",
        "options":  ["পূজা", "প্রেম", "স্বদেশ", "প্রকৃতি", "বিচিত্র", "আনুষ্ঠানিক"],
    },
    {
        "question": "কোন রাগে রবীন্দ্রনাথের গান আপনাকে সবচেয়ে বেশি স্পর্শ করে?",
        "options":  ["ভৈরবী", "বাউল", "কাফি", "ইমন", "বেহাগ", "পিলু"],
    },
    {
        "question": "রবীন্দ্রনাথের কোন তালের গান আপনার সবচেয়ে ভালো লাগে?",
        "options":  ["দাদরা", "কাহারবা", "তিনতাল", "রূপকড়া", "ঝাঁপতাল"],
    },
    {
        "question": "গীতবিতানের কোন গানটি আপনি সবার আগে শিখতে চান?",
        "options":  ["আমার সোনার বাংলা", "যদি তোর ডাক শুনে কেউ না আসে",
                     "আমার মাথা নত করে দাও হে", "আনন্দধারা বহিছে ভুবনে",
                     "বাজে করুণ সুরে", "অন্যটি"],
    },
    {
        "question": "রবীন্দ্রসঙ্গীতের কোন বিষয়টি আপনি আরও জানতে চান?",
        "options":  ["রাগ-রাগিণী", "তাল-লয়", "গানের প্রেক্ষাপট",
                     "গানের অর্থ ও ব্যাখ্যা", "রবীন্দ্রনাথের জীবন", "অন্যটি"],
    },
]

_WEEKLY_QUESTIONS_MAP = {
    "arcl":       _WEEKLY_QUESTIONS_ARCL,
    "geetabitan": _WEEKLY_QUESTIONS_GEETABITAN,
}
WEEKLY_QUESTIONS = _WEEKLY_QUESTIONS_MAP.get(DOMAIN, _WEEKLY_QUESTIONS_ARCL)

# ── CHANGE 5: admin display name is domain-scoped ─────────────────────────────
_ADMIN_NAME = {
    "arcl":       "ARCL Admin",
    "geetabitan": "Geetabitan Admin",
}.get(DOMAIN, "Admin")


# ── Weekly auto-poll endpoints (called by Cloud Scheduler) ────────────────────

@router.post("/weekly/open")
async def open_weekly_poll(admin_key: str = ""):
    """
    Create this week's poll. Called by Cloud Scheduler every Monday at 8 AM.
    Rotates through WEEKLY_QUESTIONS based on current week number.
    """
    # ── CHANGE 3 (continued): use domain-scoped API_KEY ───────────────────────
    if API_KEY and admin_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    from datetime import date
    week_num = date.today().isocalendar()[1]
    template = WEEKLY_QUESTIONS[week_num % len(WEEKLY_QUESTIONS)]

    db = get_db()

    # Close any previously open weekly poll
    async for doc in db.collection(POLLS_COLLECTION) \
                       .where("active", "==", True) \
                       .where("is_weekly", "==", True) \
                       .stream():
        await doc.reference.update({
            "active":    False,
            "closed_at": datetime.utcnow().isoformat(),
        })

    poll_id = f"WEEK{date.today().strftime('%Y%V')}"

    poll_data = {
        "poll_id":     poll_id,
        "question":    template["question"],
        "options":     [{"text": o, "votes": []} for o in template["options"]],
        # ── CHANGE 5: domain-scoped admin name ───────────────────────────────
        "created_by":  _ADMIN_NAME,
        "created_at":  datetime.utcnow().isoformat(),
        "active":      True,
        "is_weekly":   True,
        "week_number": week_num,
    }

    await db.collection(POLLS_COLLECTION).document(poll_id).set(poll_data)

    return {
        "created":  True,
        "poll_id":  poll_id,
        "question": template["question"],
        "opens":    "Monday 8 AM",
        "closes":   "Friday 8 AM",
    }


@router.post("/weekly/close")
async def close_weekly_poll(admin_key: str = ""):
    """
    Close this week's poll. Called by Cloud Scheduler every Friday at 8 AM.
    """
    if API_KEY and admin_key != API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    db = get_db()
    closed = []

    async for doc in db.collection(POLLS_COLLECTION) \
                       .where("active", "==", True) \
                       .where("is_weekly", "==", True) \
                       .stream():
        await doc.reference.update({
            "active":    False,
            "closed_at": datetime.utcnow().isoformat(),
        })
        closed.append(doc.id)

    return {
        "closed":   len(closed) > 0,
        "poll_ids": closed,
        "message":  f"Closed {len(closed)} weekly poll(s)",
    }


@router.get("/weekly/current")
async def get_current_weekly_poll():
    """Get the currently active weekly poll."""
    db = get_db()
    async for doc in db.collection(POLLS_COLLECTION) \
                       .where("active", "==", True) \
                       .where("is_weekly", "==", True) \
                       .limit(1) \
                       .stream():
        data = doc.to_dict()
        total = sum(len(o.get("votes", [])) for o in data["options"])
        return PollResponse(
            poll_id=data["poll_id"],
            question=data["question"],
            options=[PollOption(**o) for o in data["options"]],
            created_by=data["created_by"],
            created_at=data["created_at"],
            total_votes=total,
        )
    return {"message": "No active weekly poll. Opens Monday 8 AM PT."}