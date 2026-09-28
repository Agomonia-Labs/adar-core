from typing import Optional, Any
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    user_id: str = "anonymous"
    session_id: Optional[str] = None
    # Optional, currently used only by api/main.py's scheduling_guest_chat --
    # the ADAR Front Desk mobile app's "Ask ADAR" tab passes the practice_id
    # the customer has selected in the app's header picker, so the
    # scheduling agent grounds every tool call (list_providers,
    # list_appointment_types, check_availability, ...) to that practice
    # instead of guessing or falling back to SCHEDULING_DEFAULT_PRACTICE_ID.
    # Every other caller leaves this unset.
    practice_id: Optional[str] = None
    # Optional, also scheduling_guest_chat only -- the ADAR Front Desk app's
    # "Ask ADAR" tab lets the customer fill their name/phone/email in a
    # text-box form before chatting, matching the pre-chat-form hint the
    # scheduling_agent's own instructions already expect (see
    # agents_config.scheduling.json: "collected before the conversation
    # begins ... handed to you as a bracketed hint"). Sent once, right
    # after the customer saves the form (not on every turn) -- the agent is
    # instructed to confirm it once and never ask again.
    caller_name: Optional[str] = None
    caller_phone: Optional[str] = None
    caller_email: Optional[str] = None
    # Optional, also scheduling_guest_chat only -- the app's active
    # LangCode (e.g. "bn-BD"), so the agent's actual reply -- not just the
    # on-screen UI strings and STT/TTS -- happens in the language the
    # customer picked, regardless of what script they type in. Every other
    # caller leaves this unset and the agent falls back to its own
    # auto-detect-from-the-message behavior.
    preferred_language: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "message": "What is the wide rule in ARCL?",
                "user_id": "user_001",
            }
        }


class ChatResponse(BaseModel):
    response:   str
    session_id: str
    user_id:    str
    eval:       dict | None = None
    trace_id:   str | None = None


class SessionResponse(BaseModel):
    session_id: str
    state: dict[str, Any]


class PlayerStats(BaseModel):
    player_name: str
    player_id: Optional[str] = None
    teams: list[str] = []
    seasons: list[str] = []
    runs: Optional[int] = None
    wickets: Optional[int] = None
    matches: Optional[int] = None


class TeamHistory(BaseModel):
    team_name: str
    division: Optional[str] = None
    season: Optional[str] = None
    players: list[str] = []
    wins: Optional[int] = None
    losses: Optional[int] = None


class RuleChunk(BaseModel):
    content: str
    section: Optional[str] = None
    source: Optional[str] = None
    score: Optional[float] = None
