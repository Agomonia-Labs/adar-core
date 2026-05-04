from typing import Optional, Any
from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    user_id: str = "anonymous"
    session_id: Optional[str] = None

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