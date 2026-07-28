# database/models.py

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict
from enum import Enum
from datetime import datetime
import uuid


# ==========================
# ENUMS
# ==========================

class Role(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MODERATOR = "MODERATOR"
    REFEREE = "REFEREE"
    USER = "USER"


class TournamentFormat(str, Enum):
    SINGLE_ELIMINATION = "SINGLE_ELIMINATION"
    SWISS = "SWISS"
    LEAGUE = "LEAGUE"


class TournamentStatus(str, Enum):
    REGISTRATION = "REGISTRATION"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


class MatchStatus(str, Enum):
    PENDING = "PENDING"
    PLAYING = "PLAYING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    FINISHED = "FINISHED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class MatchStage(str, Enum):
    ROUND_OF_128 = "1/128"
    ROUND_OF_64 = "1/64"
    ROUND_OF_32 = "1/32"
    ROUND_OF_16 = "1/8"
    QUARTER_FINAL = "1/4"
    SEMI_FINAL = "1/2"
    FINAL = "FINAL"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    REVIEWING = "REVIEWING"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"



# ==========================
# USER
# ==========================

class User(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    id: int

    username: Optional[str] = None

    first_name: Optional[str] = None

    role: Role = Role.USER


    # Rating system
    elo: int = 1200
    peak_elo: int = 1200


    # Statistics
    matches_played: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0


    # Tournament stats
    tournaments_played: int = 0
    tournaments_won: int = 0


    # Security
    is_banned: bool = False
    ban_reason: Optional[str] = None
    banned_until: Optional[datetime] = None


    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )



# ==========================
# CHAT ROLES
# ==========================

class ChatRole(BaseModel):

    chat_id: int

    user_id: int

    role: Role = Role.USER

    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )



# ==========================
# TOURNAMENT
# ==========================

class Tournament(BaseModel):
    model_config = ConfigDict(use_enum_values=True)


    id: str = Field(
        default_factory=lambda: str(uuid.uuid4())
    )


    name: str


    creator_id: int


    format: TournamentFormat


    status: TournamentStatus = (
        TournamentStatus.REGISTRATION
    )


    max_players: int = 128


    participants: List[int] = []


    matches: List[str] = []


    current_round: int = 0


    # Swiss rounds
    total_rounds: int = 0


    # History
    winner_id: Optional[int] = None


    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )


    finished_at: Optional[datetime] = None



# ==========================
# MATCH
# ==========================

class Match(BaseModel):
    model_config = ConfigDict(use_enum_values=True)


    id: str = Field(
        default_factory=lambda: str(uuid.uuid4())
    )


    tournament_id: str


    player1_id: Optional[int] = None

    player2_id: Optional[int] = None



    score_player1: Optional[int] = None

    score_player2: Optional[int] = None



    winner_id: Optional[int] = None



    stage: MatchStage


    status: MatchStatus = (
        MatchStatus.PENDING
    )



    # Confirmation
    submitted_by: Optional[int] = None

    confirmed_by: List[int] = []



    # Deadline system
    deadline: Optional[datetime] = None


    reminder_sent: bool = False



    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )



# ==========================
# DISPUTE
# ==========================

class Dispute(BaseModel):

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4())
    )


    match_id: str


    creator_id: int


    reason: str


    evidence: Optional[str] = None


    status: DisputeStatus = (
        DisputeStatus.OPEN
    )


    resolved_by: Optional[int] = None


    resolution: Optional[str] = None



    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )



# ==========================
# TOURNAMENT HISTORY
# ==========================

class TournamentHistory(BaseModel):

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4())
    )


    tournament_id: str


    winner_id: int


    participants_count: int


    format: TournamentFormat


    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )



# ==========================
# GLOBAL SETTINGS
# ==========================

class BotSettings(BaseModel):

    maintenance_mode: bool = False


    default_elo: int = 1200


    allow_registration: bool = True


    language: str = "ru"



# ==========================
# DATABASE ROOT STRUCTURE
# ==========================

class DatabaseSchema(BaseModel):

    users: Dict[str, User] = {}

    tournaments: Dict[str, Tournament] = {}

    matches: Dict[str, Match] = {}

    disputes: Dict[str, Dispute] = {}

    chat_roles: Dict[str, ChatRole] = {}

    history: Dict[str, TournamentHistory] = {}

    settings: BotSettings = BotSettings()
