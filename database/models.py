from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict
from pydantic import BaseModel, Field, ConfigDict
import uuid


# ==========================
# ROLES
# ==========================

class Role(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MODERATOR = "MODERATOR"
    REFEREE = "REFEREE"
    USER = "USER"


# ==========================
# TOURNAMENT TYPES
# ==========================

class TournamentFormat(str, Enum):
    SINGLE_ELIMINATION = "SINGLE_ELIMINATION"
    DOUBLE_ELIMINATION = "DOUBLE_ELIMINATION"
    SWISS = "SWISS"
    LEAGUE = "LEAGUE"


class TournamentStatus(str, Enum):
    REGISTRATION = "REGISTRATION"
    ACTIVE = "ACTIVE"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


# ==========================
# MATCH
# ==========================

class MatchStatus(str, Enum):
    PENDING = "PENDING"
    PLAYING = "PLAYING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    FINISHED = "FINISHED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


# ==========================
# USER
# ==========================

class User(BaseModel):

    model_config = ConfigDict(use_enum_values=True)


    id: int

    username: Optional[str] = None

    role: Role = Role.USER


    # рейтинг
    elo: int = 1200
    peak_elo: int = 1200


    # статистика
    matches_played: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0


    # турниры
    tournaments_played: int = 0
    tournaments_won: int = 0


    # безопасность

    is_banned: bool = False
    ban_reason: Optional[str] = None


    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )



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


    score_p1: int = 0
    score_p2: int = 0


    status: MatchStatus = MatchStatus.PENDING


    # стадия турнира

    stage: str
    # Примеры:
    # 1/8 финала
    # 1/4 финала
    # 1/2 финала
    # Финал
    # Swiss Round 3


    winner_id: Optional[int] = None


    # подтверждение

    submitted_by: Optional[int] = None
    confirmed_by: Optional[int] = None


    # дедлайн

    deadline: Optional[datetime] = None


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


    format: TournamentFormat


    status: TournamentStatus = TournamentStatus.REGISTRATION


    owner_id: int


    max_players: int = 128


    participants: List[int] = Field(
        default_factory=list
    )


    matches: List[str] = Field(
        default_factory=list
    )


    current_round: int = 0


    # настройки

    settings: Dict = Field(
        default_factory=dict
    )


    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )


    finished_at: Optional[datetime] = None



# ==========================
# DISPUTE
# ==========================

class Dispute(BaseModel):

    model_config = ConfigDict(use_enum_values=True)


    id: str = Field(
        default_factory=lambda: str(uuid.uuid4())
    )


    match_id: str


    creator_id: int


    reason: str


    evidence: Optional[str] = None


    status: str = "OPEN"


    resolution: Optional[str] = None


    resolved_by: Optional[int] = None


    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )



# ==========================
# CHAT ROLE
# ==========================

class ChatRole(BaseModel):

    chat_id: int

    user_id: int

    role: Role = Role.USER



# ==========================
# TOURNAMENT HISTORY
# ==========================

class TournamentHistory(BaseModel):

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4())
    )


    tournament_id: str


    winner_id: int


    participants: List[int]


    created_at: datetime = Field(
        default_factory=datetime.utcnow
    )
