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

from src.adar.config import settings, DOMAIN

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

TEAMS_COLLECTION = "adar_teams"
JWT_ALGORITHM    = "HS256"
JWT_EXPIRE_DAYS  = 30

# ── FIX 1: read at call time via property, not at import time ─────────────────
# Reading at module load time means values set by load_dotenv() may not be
# present yet, and any trailing newline / quote in .env causes mismatches.
def _jwt_secret()      -> str: return os.environ.get("JWT_SECRET",      "change-me-in-production-use-secret-manager")
def _admin_email()     -> str: return os.environ.get("ADMIN_EMAIL",     "admin@agomoniai.com").strip().lower()
def _admin_password()  -> str: return os.environ.get("ADMIN_PASSWORD",  "").strip()

# ── FIX 2: auth always uses its own database, independent of DOMAIN ───────────
# Read at call time (function) not import time so load_dotenv() has already run.
# Default: geetabitan → geetabitan-db, arcl → tigers-arcl
def _auth_db() -> str:
    default = "geetabitan-db" if DOMAIN == "geetabitan" else "tigers-arcl"
    return os.environ.get("AUTH_FIRESTORE_DATABASE", default).strip()

# ── FIX 3: domain-aware admin display name ────────────────────────────────────
_ADMIN_NAME = {
    "arcl":       "ARCL Admin",
    "geetabitan": "Geetabitan Admin",
}.get(DOMAIN, "Admin")

bearer_scheme = HTTPBearer(auto_error=False)


# ── Models ────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    team_name:      str = Field(..., min_length=2, max_length=80)
    email:          str = Field(..., min_length=5, max_length=120)
    password:       str = Field(..., min_length=8, max_length=128)
    contact_person: str = Field(..., min_length=2, max_length=80)


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
    """
    Always connects to the shared auth database regardless of DOMAIN.
    adar_teams must live in one place so logins work across all deployments.
    """
    return firestore.AsyncClient(
        project=settings.GCP_PROJECT_ID,
        database=_auth_db(),
    )


def _slug(name: str) -> str:
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
    return jwt.encode(data, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises HTTPException on failure."""
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid or expired token: {e}")


# ── Auth dependency ───────────────────────────────────────────────────────────

async def get_current_team(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    return decode_token(credentials.credentials)


async def get_admin(team: dict = Depends(get_current_team)) -> dict:
    if team.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return team


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/register")
async def register(req: RegisterRequest):
    db    = get_db()
    email = req.email.strip().lower()

    query = db.collection(TEAMS_COLLECTION).where("email", "==", email).limit(1)
    async for doc in query.stream():
        raise HTTPException(status_code=409, detail="Email already registered")

    team_id = _slug(req.team_name)
    doc = await db.collection(TEAMS_COLLECTION).document(team_id).get()
    if doc.exists:
        team_id = f"{team_id}_{int(datetime.now().timestamp()) % 10000}"

    team_data = {
        "team_id":        team_id,
        "team_name":      req.team_name.strip(),
        "email":          email,
        "password_hash":  _hash_password(req.password),
        "contact_person": req.contact_person.strip(),
        "status":         "pending_payment",
        "role":           "team",
        "quota_rpm":      20,
        "quota_daily":    500,
        "created_at":     datetime.utcnow().isoformat(),
        "approved_at":    None,
    }

    await db.collection(TEAMS_COLLECTION).document(team_id).set(team_data)
    logger.info(f"New registration: {team_id} ({email})")

    return {
        "message": "Registration successful! Please subscribe to start using Adar.",
        "team_id": team_id,
        "status":  "pending_payment",
    }


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    email          = req.email.strip().lower()
    admin_email    = _admin_email()
    admin_password = _admin_password()

    # ── Admin login ───────────────────────────────────────────────────────────
    if email == admin_email:
        if not admin_password:
            logger.error("ADMIN_PASSWORD env var is not set")
            raise HTTPException(status_code=500, detail="Admin password not configured")

        # .strip() on both sides prevents trailing-newline / quote mismatches
        if req.password.strip() != admin_password:
            logger.warning(f"Admin login failed for {email} — password mismatch")
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = _create_token({
            "team_id":   "admin",
            "team_name": _ADMIN_NAME,
            "email":     email,
            "role":      "admin",
            "status":    "active",
        })
        return TokenResponse(
            access_token=token,
            team_id="admin",
            team_name=_ADMIN_NAME,
            role="admin",
            status="active",
        )

    # ── Team login ────────────────────────────────────────────────────────────
    db   = get_db()
    team = None
    async for doc in db.collection(TEAMS_COLLECTION).stream():
        d = doc.to_dict()
        if d.get("email") == email:
            team = d
            break

    if not team:
        logger.warning(f"Login failed — email not found: {email} (db={_auth_db()})")
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not _verify_password(req.password, team.get("password_hash", "")):
        logger.warning(f"Login failed — wrong password for: {email}")
        raise HTTPException(status_code=401, detail="Invalid email or password")

    status = team.get("status", "")

    if status == "pending":
        raise HTTPException(
            status_code=403,
            detail="Your registration is pending approval. Please wait for admin confirmation.",
        )
    if status == "suspended":
        raise HTTPException(status_code=403, detail="Account suspended. Contact admin.")
    # pending_payment → allow login, frontend redirects to checkout

    token = _create_token({
        "team_id":   team["team_id"],
        "team_name": team["team_name"],
        "email":     team["email"],
        "role":      team.get("role", "team"),
        "status":    status,
    })

    try:
        if status in ("pending_payment", "pending"):
            from src.adar.db import get_firestore as _get_fs
            _db   = _get_fs()
            _doc  = await _db.collection(TEAMS_COLLECTION).document(team["team_id"]).get()
            _fresh = (_doc.to_dict() or {}).get("status", status) if _doc.exists else status
        else:
            _fresh = status
    except Exception:
        _fresh = status

    return TokenResponse(
        access_token=token,
        team_id=team["team_id"],
        team_name=team["team_name"],
        role=team.get("role", "team"),
        status=_fresh,
    )


# ── Password reset ────────────────────────────────────────────────────────────

class ForgotRequest(BaseModel):
    email: str

class ResetRequest(BaseModel):
    token:        str
    new_password: str

@router.post("/forgot-password")
async def forgot_password(req: ForgotRequest):
    import secrets
    from src.adar.notify import send_email

    db    = get_db()
    email = req.email.strip().lower()

    team_id   = None
    team_name = ""
    query = db.collection(TEAMS_COLLECTION).where("email", "==", email).limit(1)
    async for doc in query.stream():
        d         = doc.to_dict()
        team_id   = d.get("team_id") or doc.id
        team_name = d.get("team_name", "")
        break

    if team_id:
        token      = secrets.token_urlsafe(32)
        expires    = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        reset_coll = f"{DOMAIN}_password_resets"
        await db.collection(reset_coll).document(token).set({
            "token":      token,
            "team_id":    team_id,
            "email":      email,
            "expires_at": expires,
            "used":       False,
        })
        frontend   = os.environ.get("FRONTEND_URL", settings.FRONTEND_URL)
        reset_url  = f"{frontend}?reset_token={token}"
        html = f"""
        <div style="font-family:sans-serif;max-width:480px;margin:0 auto">
          <h2>Reset your Adar password</h2>
          <p>Hi <strong>{team_name}</strong>,</p>
          <p>Click below to reset your password. Link expires in 1 hour.</p>
          <div style="text-align:center;margin:24px 0">
            <a href="{reset_url}"
               style="background:#2EB87E;color:#fff;padding:12px 28px;
                      border-radius:10px;text-decoration:none;font-weight:600">
              Reset password →
            </a>
          </div>
          <p style="font-size:0.82rem;color:#888">
            If you didn't request this, ignore this email.
          </p>
        </div>
        """
        try:
            await send_email(email, "Reset your Adar password", html)
            logger.info(f"Password reset email sent to {email}")
        except Exception as e:
            logger.warning(f"Reset email failed: {e}")

    return {"message": "If that email is registered you will receive a reset link shortly."}


@router.post("/reset-password")
async def reset_password(req: ResetRequest):
    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    db         = get_db()
    reset_coll = f"{DOMAIN}_password_resets"
    doc        = await db.collection(reset_coll).document(req.token).get()

    if not doc.exists:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    reset = doc.to_dict()

    if reset.get("used"):
        raise HTTPException(status_code=400, detail="Reset link already used")

    if datetime.fromisoformat(reset["expires_at"]) < datetime.utcnow():
        raise HTTPException(status_code=400, detail="Reset link expired. Please request a new one.")

    team_id = reset["team_id"]
    await db.collection(TEAMS_COLLECTION).document(team_id).update({
        "password_hash": _hash_password(req.new_password)
    })
    await db.collection(reset_coll).document(req.token).update({"used": True})
    logger.info(f"Password reset for team: {team_id}")

    return {"message": "Password updated successfully. You can now log in."}


@router.get("/me", response_model=TeamInfo)
async def me(team: dict = Depends(get_current_team)):
    db = get_db()
    if team.get("role") == "admin":
        return TeamInfo(
            team_id="admin", team_name=_ADMIN_NAME,
            email=team.get("email", ""), role="admin",
            status="active", contact_person="Admin",
            created_at="",
        )
    doc = await db.collection(TEAMS_COLLECTION).document(team["team_id"]).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Team not found")
    d = doc.to_dict()
    return TeamInfo(
        team_id=d["team_id"],         team_name=d["team_name"],
        email=d["email"],             role=d.get("role", "team"),
        status=d["status"],           contact_person=d.get("contact_person", ""),
        created_at=d.get("created_at", ""),
    )