"""
auth.py — Team authentication: register, login, JWT issue/verify.

Endpoints:
  POST /api/auth/register  — team self-registration (status: pending)
  POST /api/auth/login     — email + password → JWT
  GET  /api/auth/me        — current team info from token

JWT payload: { team_id, team_name, email, role, exp }
All tokens expire in 30 days. Admin tokens never expire (role=admin).
"""
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field
from google.cloud import firestore

from src.adar.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

TEAMS_COLLECTION = "adar_teams"
JWT_SECRET       = os.environ.get("JWT_SECRET", "change-me-in-production-use-secret-manager")
JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_DAYS  = 30
ADMIN_EMAIL      = os.environ.get("ADMIN_EMAIL", "admin@arcl.org")
ADMIN_PASSWORD   = os.environ.get("ADMIN_PASSWORD", "")   # Set via Secret Manager

bearer_scheme = HTTPBearer(auto_error=False)


# ── Models ────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    team_name:        str   = Field(..., min_length=2, max_length=80)
    email:            str   = Field(..., min_length=5, max_length=120)
    password:         str   = Field(..., min_length=8, max_length=128)
    contact_person:   str   = Field(..., min_length=2, max_length=80)


class LoginRequest(BaseModel):
    email:    str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    team_id:      str
    team_name:    str
    role:         str
    status:       str


class TeamInfo(BaseModel):
    team_id:        str
    team_name:      str
    email:          str
    role:           str
    status:         str
    contact_person: str
    created_at:     str


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_db():
    return firestore.AsyncClient(
        project=settings.GCP_PROJECT_ID,
        database=settings.FIRESTORE_DATABASE,
    )


def _slug(name: str) -> str:
    """Convert team name to a safe collection prefix slug."""
    import re
    slug = re.sub(r'[^a-z0-9]+', '_', name.lower().strip())
    return slug.strip('_')[:30]


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


def _create_token(payload: dict) -> str:
    data = dict(payload)
    if data.get("role") != "admin":
        data["exp"] = datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS)
    return jwt.encode(data, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises HTTPException on failure."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {e}")


# ── Auth dependency — use in any route that requires login ────────────────────

async def get_current_team(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """
    FastAPI dependency. Validates Bearer JWT and returns team payload.

    Usage:
        @app.get("/api/chat")
        async def chat(team = Depends(get_current_team)):
            team["team_id"]   # e.g. "agomoni_tigers"
            team["team_name"] # e.g. "Agomoni Tigers"
            team["role"]      # "team" or "admin"
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    return decode_token(credentials.credentials)


async def get_admin(team: dict = Depends(get_current_team)) -> dict:
    """Require admin role."""
    if team.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return team


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/register")
async def register(req: RegisterRequest):
    """
    Team self-registration. Status starts as 'pending' until admin approves.
    """
    db = get_db()
    email = req.email.strip().lower()

    # Check email not already used (scan avoids needing a Firestore index)
    async for doc in db.collection(TEAMS_COLLECTION).stream():
        if doc.to_dict().get("email") == email:
            raise HTTPException(status_code=409, detail="Email already registered")

    team_id   = _slug(req.team_name)
    # Ensure unique team_id
    doc = await db.collection(TEAMS_COLLECTION).document(team_id).get()
    if doc.exists:
        team_id = f"{team_id}_{int(datetime.now().timestamp()) % 10000}"

    team_data = {
        "team_id":        team_id,
        "team_name":      req.team_name.strip(),
        "email":          email,
        "password_hash":  _hash_password(req.password),
        "contact_person": req.contact_person.strip(),
        "status":         "pending_payment",  # awaiting Stripe checkout
        "role":           "team",
        "quota_rpm":      20,
        "quota_daily":    500,
        "created_at":     datetime.utcnow().isoformat(),
        "approved_at":    None,
    }

    await db.collection(TEAMS_COLLECTION).document(team_id).set(team_data)
    logger.info(f"New registration: {team_id} ({email})")

    return {
        "message":  "Registration successful! Please subscribe to start using Adar.",
        "team_id":  team_id,
        "status":   "pending_payment",
    }


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    """
    Login with email + password. Returns JWT on success.
    """
    email = req.email.strip().lower()

    # Admin login
    if email == ADMIN_EMAIL.lower():
        if not ADMIN_PASSWORD:
            raise HTTPException(status_code=500, detail="Admin password not configured")
        if req.password != ADMIN_PASSWORD:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = _create_token({
            "team_id":   "admin",
            "team_name": "ARCL Admin",
            "email":     email,
            "role":      "admin",
            "status":    "active",
        })
        return TokenResponse(
            access_token=token,
            team_id="admin",
            team_name="ARCL Admin",
            role="admin",
            status="active",
        )

    # Team login — scan for email (avoids needing a Firestore index)
    db = get_db()
    team = None
    async for doc in db.collection(TEAMS_COLLECTION).stream():
        d = doc.to_dict()
        if d.get("email") == email:
            team = d
            break

    if not team:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not _verify_password(req.password, team.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if team.get("status") == "pending":
        raise HTTPException(
            status_code=403,
            detail="Your registration is pending approval. Please wait for admin confirmation."
        )

    if team.get("status") == "pending_payment":
        # Allow login — frontend will redirect to checkout
        pass

    if team.get("status") == "suspended":
        raise HTTPException(status_code=403, detail="Account suspended. Contact admin.")

    token = _create_token({
        "team_id":   team["team_id"],
        "team_name": team["team_name"],
        "email":     team["email"],
        "role":      team.get("role", "team"),
        "status":    team["status"],
    })

    # Re-read status from Firestore — webhook may have updated it since token was cached
    try:
        from src.adar.db import get_firestore as _get_fs
        _db = _get_fs()
        _doc = await _db.collection(TEAMS_COLLECTION).document(team["team_id"]).get()
        _fresh_status = (_doc.to_dict() or {}).get("status", team["status"]) if _doc.exists else team["status"]
    except Exception:
        _fresh_status = team["status"]

    return TokenResponse(
        access_token=token,
        team_id=team["team_id"],
        team_name=team["team_name"],
        role=team.get("role", "team"),
        status=_fresh_status,
    )


# ── Password reset ────────────────────────────────────────────────────────────

class ForgotRequest(BaseModel):
    email: str

class ResetRequest(BaseModel):
    token: str
    new_password: str

@router.post("/forgot-password")
async def forgot_password(req: ForgotRequest):
    """
    Send password reset link to team email.
    Always returns success to prevent email enumeration.
    """
    import secrets
    from src.adar.notify import send_email

    db = get_db()
    email = req.email.strip().lower()

    # Find team by email
    team_id = None
    team_name = ""
    async for doc in db.collection(TEAMS_COLLECTION).stream():
        d = doc.to_dict()
        if d.get("email") == email:
            team_id = d.get("team_id")
            team_name = d.get("team_name", "")
            break

    if team_id:
        token = secrets.token_urlsafe(32)
        expires = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        await db.collection("arcl_password_resets").document(token).set({
            "token":      token,
            "team_id":    team_id,
            "email":      email,
            "expires_at": expires,
            "used":       False,
        })
        reset_url = f"{os.environ.get('FRONTEND_URL', 'https://arcl.tigers.agomoniai.com')}?reset_token={token}"
        html = f"""
        <div style="font-family:sans-serif;max-width:480px;margin:0 auto">
          <h2 style="color:#1A3326">Reset your Adar password</h2>
          <p>Hi <strong>{team_name}</strong>,</p>
          <p>Click the button below to reset your password. This link expires in 1 hour.</p>
          <div style="text-align:center;margin:24px 0">
            <a href="{reset_url}" style="background:#2EB87E;color:#fff;padding:12px 28px;border-radius:10px;text-decoration:none;font-weight:600">
              Reset password →
            </a>
          </div>
          <p style="font-size:0.82rem;color:#5A8A70">If you didn't request this, ignore this email.</p>
        </div>
        """
        try:
            await send_email(email, "Reset your Adar password", html)
            logger.info(f"Password reset email sent to {email}")
        except Exception as e:
            logger.warning(f"Reset email failed: {e}")

    # Always return success to prevent enumeration
    return {"message": "If that email is registered you will receive a reset link shortly."}


@router.post("/reset-password")
async def reset_password(req: ResetRequest):
    """Validate reset token and set new password."""
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    db = get_db()
    doc = await db.collection("arcl_password_resets").document(req.token).get()

    if not doc.exists:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    reset = doc.to_dict()

    if reset.get("used"):
        raise HTTPException(status_code=400, detail="Reset link already used")

    if datetime.fromisoformat(reset["expires_at"]) < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Reset link expired. Please request a new one.")

    # Update password
    team_id = reset["team_id"]
    await db.collection(TEAMS_COLLECTION).document(team_id).update({
        "password_hash": _hash_password(req.new_password)
    })

    # Mark token as used
    await db.collection("arcl_password_resets").document(req.token).update({"used": True})
    logger.info(f"Password reset for team: {team_id}")

    return {"message": "Password updated successfully. You can now log in."}


@router.get("/me", response_model=TeamInfo)
async def me(team: dict = Depends(get_current_team)):
    """Return current team info from JWT."""
    db = get_db()
    if team.get("role") == "admin":
        return TeamInfo(
            team_id="admin", team_name="ARCL Admin",
            email=team.get("email", ""), role="admin",
            status="active", contact_person="Admin",
            created_at="",
        )
    doc = await db.collection(TEAMS_COLLECTION).document(team["team_id"]).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Team not found")
    d = doc.to_dict()
    return TeamInfo(
        team_id=d["team_id"], team_name=d["team_name"],
        email=d["email"], role=d.get("role", "team"),
        status=d["status"], contact_person=d.get("contact_person", ""),
        created_at=d.get("created_at", ""),
    )