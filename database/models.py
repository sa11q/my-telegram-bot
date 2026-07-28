from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from enum import Enum
from datetime import datetime
import uuid

class Role(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MODERATOR = "MODERATOR"
    REFEREE = "REFEREE"
    USER = "USER"

class MatchStatus(str, Enum):
    PENDING = "PENDING"
    PLAYING = "PLAYING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    FINISHED = "FINISHED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"

class TournamentFormat(str, Enum):
    SINGLE_ELIMINATION = "SINGLE_ELIMINATION"
    DOUBLE_ELIMINATION = "DOUBLE_ELIMINATION"
    SWISS = "SWISS"
    LEAGUE = "LEAGUE"

class User(BaseModel):
    id: int
    username: Optional[str] = None
    role: Role = Role.USER
    elo: int = 1200
    max_elo: int = 1200
    wins: int = 0
    losses: int = 0
    matches_played: int = 0
    is_banned: bool = False
    ban_reason: Optional[str] = None

class Match(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tournament_id: str
    player1_id: Optional[int]
    player2_id: Optional[int]
    score_p1: int = 0
    score_p2: int = 0
    status: MatchStatus = MatchStatus.PENDING
    stage: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    deadline: Optional[datetime] = None
    winner_id: Optional[int] = None

class Tournament(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    format: TournamentFormat
    participants: List[int] = []
    is_active: bool = True
    matches: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)

