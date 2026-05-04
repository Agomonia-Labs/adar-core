"""
admin.py — Admin-only endpoints.
All routes require admin JWT (role=admin).

Endpoints:
  GET  /admin/teams              — list all teams
  POST /admin/teams/{id}/approve — approve pending registration
  POST /admin/teams/{id}/suspend — suspend a team
  POST /admin/teams/{id}/activate — reactivate suspended team
  PUT  /admin/teams/{id}/quota   — update rate limits
  GET  /admin/teams/{id}/usage   — usage report
  GET  /admin/polls              — all polls across all teams
"""
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from google.cloud import firestore

from src.adar.config import settings
from api.routes.auth import get_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

TEAMS_COLLECTION = "adar_teams"


def get_db():
    return firestore.AsyncClient(
        project=settings.GCP_PROJECT_ID,
        database=settings.FIRESTORE_DATABASE,
    )


# ── Models ────────────────────────────────────────────────────────────────────

class QuotaUpdate(BaseModel):
    quota_rpm:   int = 20
    quota_daily: int = 500


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/teams")
async def list_teams(_: dict = Depends(get_admin)):
    """List all registered teams with their status and stats."""
    db = get_db()
    teams = []
    async for doc in db.collection(TEAMS_COLLECTION).stream():
        d = doc.to_dict()
        if d.get("team_id") == "admin":
            continue
        teams.append({
            "team_id":        d.get("team_id"),
            "team_name":      d.get("team_name"),
            "email":          d.get("email"),
            "contact_person": d.get("contact_person"),
            "status":         d.get("status", "pending"),
            "created_at":     d.get("created_at"),
            "approved_at":    d.get("approved_at"),
            "quota_rpm":      d.get("quota_rpm", 20),
            "quota_daily":    d.get("quota_daily", 500),
        })
    teams.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return {"teams": teams, "total": len(teams)}


@router.post("/teams/{team_id}/approve")
async def approve_team(team_id: str, _: dict = Depends(get_admin)):
    """Approve a pending team registration."""
    db  = get_db()
    ref = db.collection(TEAMS_COLLECTION).document(team_id)
    doc = await ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Team not found")
    d = doc.to_dict()
    if d.get("status") == "active":
        return {"message": f"{team_id} is already active"}
    await ref.update({
        "status":      "active",
        "approved_at": datetime.utcnow().isoformat(),
    })
    logger.info(f"Admin approved team: {team_id}")
    return {"message": f"{d.get('team_name')} approved successfully", "team_id": team_id}


@router.post("/teams/{team_id}/suspend")
async def suspend_team(team_id: str, _: dict = Depends(get_admin)):
    """Suspend a team — they cannot log in until reactivated."""
    db  = get_db()
    ref = db.collection(TEAMS_COLLECTION).document(team_id)
    doc = await ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Team not found")
    await ref.update({"status": "suspended"})
    logger.info(f"Admin suspended team: {team_id}")
    return {"message": f"{team_id} suspended", "team_id": team_id}


@router.post("/teams/{team_id}/activate")
async def activate_team(team_id: str, _: dict = Depends(get_admin)):
    """Reactivate a suspended team."""
    db  = get_db()
    ref = db.collection(TEAMS_COLLECTION).document(team_id)
    doc = await ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Team not found")
    await ref.update({"status": "active"})
    logger.info(f"Admin activated team: {team_id}")
    return {"message": f"{team_id} reactivated", "team_id": team_id}


@router.put("/teams/{team_id}/quota")
async def update_quota(team_id: str, quota: QuotaUpdate, _: dict = Depends(get_admin)):
    """Update rate limits for a team."""
    db  = get_db()
    ref = db.collection(TEAMS_COLLECTION).document(team_id)
    doc = await ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Team not found")
    await ref.update({
        "quota_rpm":   quota.quota_rpm,
        "quota_daily": quota.quota_daily,
    })
    return {"message": "Quota updated", "team_id": team_id, "quota": quota}


@router.get("/teams/{team_id}")
async def get_team(team_id: str, _: dict = Depends(get_admin)):
    """Get full details for a single team."""
    db  = get_db()
    doc = await db.collection(TEAMS_COLLECTION).document(team_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Team not found")
    d = doc.to_dict()
    d.pop("password_hash", None)   # never expose hash
    return d


@router.get("/polls")
async def list_all_polls(_: dict = Depends(get_admin)):
    """List polls from all teams — admin sees everything."""
    db    = get_db()
    polls = []

    # Get all team IDs first
    async for doc in db.collection(TEAMS_COLLECTION).stream():
        team_id = doc.to_dict().get("team_id")
        if not team_id or team_id == "admin":
            continue
        collection_name = f"{team_id}_polls"
        try:
            async for poll_doc in db.collection(collection_name).stream():
                pd = poll_doc.to_dict()
                pd["_team_id"] = team_id
                total = sum(len(o.get("votes", [])) for o in pd.get("options", []))
                pd["total_votes"] = total
                polls.append(pd)
        except Exception:
            continue

    polls.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return {"polls": polls, "total": len(polls)}


@router.get("/stats")
async def admin_stats(_: dict = Depends(get_admin)):
    """High-level stats for the admin dashboard."""
    db = get_db()
    stats = {"total": 0, "active": 0, "pending": 0, "suspended": 0}
    async for doc in db.collection(TEAMS_COLLECTION).stream():
        d = doc.to_dict()
        if d.get("team_id") == "admin":
            continue
        stats["total"] += 1
        status = d.get("status", "pending")
        stats[status] = stats.get(status, 0) + 1
    return stats


# ── Evaluation endpoints ──────────────────────────────────────────────────────

@router.get("/evals")
async def list_evals(_: dict = Depends(get_admin)):
    """Get evaluation summary across all teams."""
    from evaluation.judge import get_eval_summary
    return await get_eval_summary()


@router.get("/evals/{team_id}")
async def team_evals(team_id: str, _: dict = Depends(get_admin)):
    """Get evaluation summary for a specific team."""
    from evaluation.judge import get_eval_summary
    return await get_eval_summary(team_id=team_id)


@router.get("/evals/recent/low")
async def low_scoring_evals(_: dict = Depends(get_admin)):
    """Get recent low-scoring responses (overall < 3.0) for review."""
    from evaluation.judge import get_eval_summary
    summary = await get_eval_summary(limit=200)
    return {
        "low_scoring": summary.get("low_scoring", []),
        "total_low":   len(summary.get("low_scoring", [])),
        "total_evals": summary.get("total", 0),
    }