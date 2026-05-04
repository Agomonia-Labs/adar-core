"""
polls.py — ARCL poll endpoints.
Polls stored in Firestore arcl_polls collection.
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from google.cloud import firestore

from config import settings

router = APIRouter(prefix="/api/polls", tags=["polls"])

POLLS_COLLECTION = "arcl_polls"


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
    # Validate options
    options = [o.strip() for o in request.options if o.strip()]
    if len(options) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 options")
    if len(set(o.lower() for o in options)) != len(options):
        raise HTTPException(status_code=400, detail="Duplicate options not allowed")

    poll_id = str(uuid.uuid4())[:8].upper()  # Short readable ID e.g. "A3F8C2D1"

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

    # Check if already voted
    for opt in options:
        if voter.lower() in [v.lower() for v in opt.get("votes", [])]:
            raise HTTPException(
                status_code=400,
                detail=f"'{voter}' has already voted in this poll",
            )

    # Validate option index
    if request.option_index >= len(options):
        raise HTTPException(status_code=400, detail="Invalid option")

    # Add vote
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
    async for doc in db.collection(POLLS_COLLECTION)\
                       .where("active", "==", True)\
                       .limit(5)\
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
    """Close a poll so no more votes can be submitted."""
    expected = getattr(settings, "ARCL_API_KEY", "")
    if expected and admin_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    db = get_db()
    ref = db.collection(POLLS_COLLECTION).document(poll_id.upper())
    doc = await ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Poll not found")
    await ref.update({"active": False, "closed_at": datetime.utcnow().isoformat()})
    return {"closed": True, "poll_id": poll_id.upper()}


# ── Weekly auto-poll endpoints (called by Cloud Scheduler) ────────────────────

# Rotate through these questions weekly
WEEKLY_QUESTIONS = [
    {
        "question": "Who was the best batter of the week?",
        "options": ["Jiban Adhikary", "Anijit Roy", "Madhusudan Banik",
                    "Aushik Pyne", "Shariful Shaikot", "Other"],
    },
    {
        "question": "Who was the best bowler of the week?",
        "options": ["Shariful Shaikot", "Anijit Roy", "Swadesh Poddar",
                    "Sujit Biswas", "Madhusudan Banik", "Other"],
    },
    {
        "question": "Best fielding performance of the week?",
        "options": ["Jiban Adhikary", "Aurko Khandakar", "BRAJA KRISHNA DAS",
                    "Hillol Debnath", "Abdul Kiyum", "Other"],
    },
    {
        "question": "How would you rate the team performance this week?",
        "options": ["Excellent", "Good", "Average", "Needs improvement"],
    },
    {
        "question": "Player of the match this week?",
        "options": ["Jiban Adhikary", "Anijit Roy", "Shariful Shaikot",
                    "Swadesh Poddar", "Madhusudan Banik", "Other"],
    },
    {
        "question": "What should the team focus on next practice?",
        "options": ["Batting technique", "Bowling accuracy", "Fielding",
                    "Running between wickets", "Team strategy"],
    },
]


@router.post("/weekly/open")
async def open_weekly_poll(admin_key: str = ""):
    """
    Create this week's poll. Called by Cloud Scheduler every Monday at 8 AM.
    Rotates through WEEKLY_QUESTIONS based on current week number.
    """
    expected = getattr(settings, "ARCL_API_KEY", "")
    if expected and admin_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    from datetime import date
    week_num = date.today().isocalendar()[1]
    template = WEEKLY_QUESTIONS[week_num % len(WEEKLY_QUESTIONS)]

    db = get_db()

    # Close any previously open weekly poll
    async for doc in db.collection(POLLS_COLLECTION)                       .where("active", "==", True)                       .where("is_weekly", "==", True)                       .stream():
        await doc.reference.update({
            "active": False,
            "closed_at": datetime.utcnow().isoformat(),
        })

    # Create new weekly poll
    poll_id = f"WEEK{date.today().strftime('%Y%V')}"

    poll_data = {
        "poll_id":    poll_id,
        "question":   template["question"],
        "options":    [{"text": o, "votes": []} for o in template["options"]],
        "created_by": "ARCL Admin",
        "created_at": datetime.utcnow().isoformat(),
        "active":     True,
        "is_weekly":  True,
        "week_number": week_num,
    }

    await db.collection(POLLS_COLLECTION).document(poll_id).set(poll_data)

    return {
        "created": True,
        "poll_id": poll_id,
        "question": template["question"],
        "opens": "Monday 8 AM",
        "closes": "Friday 8 AM",
    }


@router.post("/weekly/close")
async def close_weekly_poll(admin_key: str = ""):
    """
    Close this week's poll. Called by Cloud Scheduler every Friday at 8 AM.
    """
    expected = getattr(settings, "ARCL_API_KEY", "")
    if expected and admin_key != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    db = get_db()
    closed = []

    async for doc in db.collection(POLLS_COLLECTION)                       .where("active", "==", True)                       .where("is_weekly", "==", True)                       .stream():
        await doc.reference.update({
            "active": False,
            "closed_at": datetime.utcnow().isoformat(),
        })
        closed.append(doc.id)

    return {
        "closed": len(closed) > 0,
        "poll_ids": closed,
        "message": f"Closed {len(closed)} weekly poll(s)",
    }


@router.get("/weekly/current")
async def get_current_weekly_poll():
    """Get the currently active weekly poll."""
    db = get_db()
    async for doc in db.collection(POLLS_COLLECTION)                       .where("active", "==", True)                       .where("is_weekly", "==", True)                       .limit(1)                       .stream():
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