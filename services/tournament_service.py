import json
import math
import copy
import asyncio
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple, Protocol, runtime_checkable, Optional

from database.models import (
    Tournament, 
    TournamentFormat, 
    MatchStatus, 
    Match, 
    User,
    Role
)
from database.database import BaseRepository
from utils.logger import bot_logger, admin_logger, error_logger

# =====================================================================
# CUSTOM EXCEPTIONS
# =====================================================================
class TournamentError(Exception): pass
class TournamentNotFoundError(TournamentError): pass
class TournamentAlreadyStartedError(TournamentError): pass
class TournamentStateError(TournamentError): pass
class TournamentRegistrationError(TournamentError): pass
class TournamentValidationError(TournamentError): pass
class TournamentIntegrityError(TournamentError): pass

# =====================================================================
# SERVICE INTERFACES (Protocols)
# =====================================================================
@runtime_checkable
class BracketServiceProtocol(Protocol):
    async def generate_single_elimination(self, t_id: str) -> bool: ...
    async def generate_double_elimination(self, t_id: str) -> bool: ...
    async def advance_winner(self, match_id: str) -> bool: ...
    async def get_current_round(self, t_id: str) -> int: ...
    async def regenerate_bracket(self, t_id: str) -> bool: ...
    async def reseed_bracket(self, t_id: str, new_seed: List[int]) -> bool: ...

@runtime_checkable
class SwissServiceProtocol(Protocol):
    async def generate_round(self, t_id: str, round_number: int) -> bool: ...
    async def calculate_standings(self, t_id: str) -> Dict[int, int]: ...
    async def get_current_round(self, t_id: str) -> int: ...
    async def recalculate_swiss_after_forfeit(self, t_id: str, match_id: str) -> bool: ...

@runtime_checkable
class MatchServiceProtocol(Protocol):
    async def cancel_match(self, match_id: str, reason: str) -> bool: ...
    async def apply_technical_defeat(self, match_id: str, loser_id: int) -> bool: ...
    async def get_active_matches(self, t_id: str) -> List[Match]: ...
    async def get_all_matches(self, t_id: str) -> List[Match]: ...
    async def force_set_result(self, match_id: str, p1_score: int, p2_score: int, winner_id: Optional[int]) -> bool: ...
    async def revert_match_result(self, match_id: str) -> bool: ...

@runtime_checkable
class ResultServiceProtocol(Protocol):
    async def verify_results(self, t_id: str) -> bool: ...
    async def bulk_verify_results(self, match_ids: List[str]) -> bool: ...

@runtime_checkable
class DisputeServiceProtocol(Protocol):
    async def has_active_disputes(self, t_id: str) -> bool: ...
    async def resolve_all_auto(self, t_id: str) -> bool: ...
    async def count_disputes(self, t_id: str) -> int: ...

@runtime_checkable
class RankingServiceProtocol(Protocol):
    async def update_tournament_rankings(self, t_id: str) -> bool: ...
    async def get_top_players(self, t_id: str, limit: int) -> List[int]: ...
    async def calculate_streaks(self, t_id: str) -> Dict[int, int]: ...

@runtime_checkable
class ReminderServiceProtocol(Protocol):
    async def schedule_tournament_reminders(self, t_id: str) -> bool: ...
    async def trigger_match_deadlines(self, t_id: str) -> bool: ...
    async def cancel_all_reminders(self, t_id: str) -> bool: ...

@runtime_checkable
class UserServiceProtocol(Protocol):
    async def get_user(self, user_id: int) -> Optional[User]: ...
    async def is_banned(self, user_id: int) -> bool: ...
    async def get_role(self, user_id: int) -> Role: ...

@runtime_checkable
class EloServiceProtocol(Protocol):
    async def process_tournament_results(self, t_id: str) -> bool: ...

# =====================================================================
# TRANSACTION & CONCURRENCY CONTEXT
# =====================================================================
_tournament_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

class TournamentTransactionContext:
    """Обеспечивает in-memory блокировки от race conditions и rollback через deepcopy."""
    def __init__(self, repo: BaseRepository, t_id: str):
        self.repo = repo
        self.t_id = t_id
        self.snapshot: Optional[Tournament] = None

    async def __aenter__(self):
        await _tournament_locks[self.t_id].acquire()
        try:
            tournament = await self.repo.get_tournament(self.t_id)
            if not tournament:
                raise TournamentNotFoundError(f"Турнир {self.t_id} не найден.")
            self.snapshot = copy.deepcopy(tournament)
            return self
        except Exception:
            _tournament_locks[self.t_id].release()
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is not None and self.snapshot is not None:
                await self.repo.save_tournament(self.snapshot)
                error_logger.error(f"Откат состояния турнира {self.t_id}. Ошибка: {exc_val}")
        finally:
            _tournament_locks[self.t_id].release()
            if not _tournament_locks[self.t_id].locked():
                _tournament_locks.pop(self.t_id, None)
        return False

def _get_waitlist(tournament: Tournament) -> List[int]:
    """Безопасное получение или инициализация очереди ожидания."""
    try:
        if tournament.waiting_list is None:
            tournament.waiting_list = []
    except AttributeError:
        tournament.waiting_list = []
    return tournament.waiting_list

def _get_max_participants(tournament: Tournament, fallback: int) -> int:
    try:
        return tournament.max_participants
    except AttributeError:
        return fallback

# =====================================================================
# INTERNAL DOMAIN MANAGERS
# =====================================================================

class _PlayerManager:
    def __init__(self, repo: BaseRepository, user_service: UserServiceProtocol, match_service: MatchServiceProtocol, max_limit: int):
        self.repo = repo
        self.user_service = user_service
        self.match_service = match_service
        self.max_limit = max_limit

    async def register_player(self, t_id: str, user_id: int) -> bool:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self.repo.get_tournament(t_id)
            if t.status != "Registration":
                raise TournamentStateError("Регистрация закрыта.")
            if user_id in t.participants:
                raise TournamentRegistrationError("Игрок уже в основном списке.")
            if await self.user_service.is_banned(user_id):
                raise TournamentRegistrationError("Игрок забанен.")
            
            role = await self.user_service.get_role(user_id)
            if role == Role.BANNED:
                raise TournamentRegistrationError("Роль не позволяет участие.")

            wl = _get_waitlist(t)
            if user_id in wl:
                raise TournamentRegistrationError("Игрок уже в очереди.")

            limit = _get_max_participants(t, self.max_limit)
            if len(t.participants) >= limit:
                wl.append(user_id)
                await self.repo.save_tournament(t)
                bot_logger.info(f"Игрок {user_id} в резерве турнира {t_id}")
                return True
                
            t.participants.append(user_id)
            await self.repo.save_tournament(t)
            bot_logger.info(f"Игрок {user_id} зарегистрирован в турнире {t_id}")
            return True

    async def unregister_player(self, t_id: str, user_id: int) -> bool:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self.repo.get_tournament(t_id)
            if t.status not in ["Draft", "Registration", "Ready"]:
                raise TournamentStateError("Нельзя отменить регистрацию.")
                
            wl = _get_waitlist(t)
            if user_id in wl:
                wl.remove(user_id)
                await self.repo.save_tournament(t)
                return True

            if user_id not in t.participants:
                raise TournamentRegistrationError("Игрок не найден.")
                
            t.participants.remove(user_id)
            if wl:
                promoted = wl.pop(0)
                t.participants.append(promoted)
                bot_logger.info(f"Игрок {promoted} переведен из резерва в {t_id}")

            await self.repo.save_tournament(t)
            return True

    async def kick_player(self, t_id: str, user_id: int, admin_id: int) -> bool:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self.repo.get_tournament(t_id)
            if user_id not in t.participants:
                raise TournamentRegistrationError("Игрок не найден.")

            t.participants.remove(user_id)
            if t.status == "Running":
                for m in await self.match_service.get_active_matches(t_id):
                    if m.player1_id == user_id or m.player2_id == user_id:
                        opp = m.player2_id if m.player1_id == user_id else m.player1_id
                        if opp:
                            await self.match_service.apply_technical_defeat(m.id, loser_id=user_id)
                        else:
                            await self.match_service.cancel_match(m.id, "Исключен администратором")
                            
            await self.repo.save_tournament(t)
            admin_logger.warning(f"Админ {admin_id} исключил {user_id} из {t_id}")
            return True

    async def replace_player(self, t_id: str, old_id: int, new_id: int, admin_id: int) -> bool:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self.repo.get_tournament(t_id)
            if old_id not in t.participants:
                raise TournamentRegistrationError("Заменяемый игрок не найден.")
            if new_id in t.participants:
                raise TournamentRegistrationError("Новый игрок уже в турнире.")
            if await self.user_service.is_banned(new_id):
                raise TournamentRegistrationError("Новый игрок забанен.")

            idx = t.participants.index(old_id)
            t.participants[idx] = new_id

            for match in await self.match_service.get_all_matches(t_id):
                updated = False
                if match.player1_id == old_id: match.player1_id = new_id; updated = True
                if match.player2_id == old_id: match.player2_id = new_id; updated = True
                if updated: await self.repo.save_match(match)

            await self.repo.save_tournament(t)
            admin_logger.info(f"Админ {admin_id} заменил {old_id} на {new_id} в {t_id}")
            return True


class _LifecycleManager:
    def __init__(self, repo, bracket, swiss, match, dispute, ranking, elo, reminder):
        self.repo = repo
        self.bracket = bracket
        self.swiss = swiss
        self.match = match
        self.dispute = dispute
        self.ranking = ranking
        self.elo = elo
        self.reminder = reminder

    async def start_tournament(self, t_id: str, admin_id: int) -> bool:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self.repo.get_tournament(t_id)
            if t.status != "Ready":
                raise TournamentAlreadyStartedError("Турнир не в статусе Ready.")
            if len(t.participants) < 2:
                raise TournamentValidationError("Нужно минимум 2 участника.")

            success = False
            if t.format == TournamentFormat.SINGLE_ELIMINATION:
                success = await self.bracket.generate_single_elimination(t_id)
            elif t.format == TournamentFormat.DOUBLE_ELIMINATION:
                success = await self.bracket.generate_double_elimination(t_id)
            elif t.format == TournamentFormat.SWISS:
                success = await self.swiss.generate_round(t_id, 1)
            elif t.format == TournamentFormat.LEAGUE:
                success = await self._generate_league(t)
            else:
                raise TournamentError(f"Неизвестный формат: {t.format}")

            if not success:
                raise TournamentError("Сбой генерации сетки.")

            t.status = "Running"
            await self.repo.save_tournament(t)
            await self.reminder.schedule_tournament_reminders(t_id)
            admin_logger.info(f"Турнир {t_id} запущен админом {admin_id}.")
            return True

    async def advance_round(self, t_id: str) -> bool:
        t = await self.repo.get_tournament(t_id)
        if t.format in [TournamentFormat.SINGLE_ELIMINATION, TournamentFormat.DOUBLE_ELIMINATION]:
            matches = await self.match.get_all_matches(t_id)
            if not matches: return False
            last_match = matches[-1]
            if getattr(last_match, 'stage', '') in ['Final', 'Финал'] and last_match.status == MatchStatus.FINISHED:
                await self.finalize(t)
                return True
            return True
        elif t.format == TournamentFormat.SWISS:
            current = await self.swiss.get_current_round(t_id)
            max_r = math.ceil(math.log2(len(t.participants)))
            if current >= max_r:
                await self.finalize(t)
                return True
            return await self.swiss.generate_round(t_id, current + 1)
        elif t.format == TournamentFormat.LEAGUE:
            await self.finalize(t)
            return True
        return False

    async def finalize(self, t: Tournament) -> Tournament:
        t.status = "Finished"
        await self.repo.save_tournament(t)
        await self.ranking.update_tournament_rankings(t.id)
        await self.elo.process_tournament_results(t.id)
        await self.reminder.cancel_all_reminders(t.id)
        bot_logger.info(f"Турнир {t.id} завершен.")
        return t

    async def _generate_league(self, t: Tournament) -> bool:
        p = t.participants
        n = len(p)
        for i in range(n):
            for j in range(i + 1, n):
                match = Match(
                    tournament_id=t.id, player1_id=p[i], player2_id=p[j],
                    stage="League Phase", status=MatchStatus.PENDING
                )
                await self.repo.save_match(match)
                t.matches.append(match.id)
        return True


# =====================================================================
# TOURNAMENT SERVICE (The Facade)
# =====================================================================
class TournamentService:
    STATE_DRAFT = "Draft"
    STATE_REGISTRATION = "Registration"
    STATE_READY = "Ready"
    STATE_RUNNING = "Running"
    STATE_PAUSED = "Paused"
    STATE_FINISHED = "Finished"
    STATE_ARCHIVED = "Archived"
    STATE_CANCELLED = "Cancelled"

    def __init__(
        self,
        repo: BaseRepository,
        user_service: UserServiceProtocol,
        bracket_service: BracketServiceProtocol,
        swiss_service: SwissServiceProtocol,
        match_service: MatchServiceProtocol,
        result_service: ResultServiceProtocol,
        dispute_service: DisputeServiceProtocol,
        ranking_service: RankingServiceProtocol,
        reminder_service: ReminderServiceProtocol,
        elo_service: EloServiceProtocol,
        max_players_limit: int = 1024
    ):
        self.repo = repo
        self.max_players_limit = max_players_limit
        self.user_service = user_service
        self.match_service = match_service
        self.dispute_service = dispute_service
        self.reminder_service = reminder_service
        self.result_service = result_service
        self.swiss_service = swiss_service
        self.bracket_service = bracket_service
        self.ranking_service = ranking_service
        
        self._players = _PlayerManager(repo, user_service, match_service, max_players_limit)
        self._life = _LifecycleManager(
            repo, bracket_service, swiss_service, match_service,
            dispute_service, ranking_service, elo_service, reminder_service
        )

    async def _get_tournament_or_raise(self, t_id: str) -> Tournament:
        t = await self.repo.get_tournament(t_id)
        if not t: raise TournamentNotFoundError(f"Турнир '{t_id}' не найден.")
        return t

    def _validate_name(self, name: str) -> None:
        if not name or len(name.strip()) < 3: raise TournamentValidationError("Минимум 3 символа.")
        if len(name) > 120: raise TournamentValidationError("Максимум 120 символов.")

    # --- Core CRUD ---
    async def create_tournament(self, name: str, fmt: TournamentFormat, creator_id: int, max_participants: int = 128) -> Tournament:
        self._validate_name(name)
        if not await self.user_service.get_user(creator_id):
            raise TournamentValidationError("Создатель не найден.")
            
        t = Tournament(
            name=name.strip(), format=fmt, status=self.STATE_DRAFT,
            participants=[], matches=[], created_by=creator_id,
            max_participants=min(max_participants, self.max_players_limit),
            created_at=datetime.now(timezone.utc)
        )
        await self.repo.save_tournament(t)
        admin_logger.info(f"Турнир '{name}' создан пользователем {creator_id}")
        return t

    async def edit_tournament(self, t_id: str, admin_id: int, updates: Dict[str, Any]) -> Tournament:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self._get_tournament_or_raise(t_id)
            if t.status not in [self.STATE_DRAFT, self.STATE_REGISTRATION, self.STATE_READY]:
                if "format" in updates or "max_participants" in updates:
                    raise TournamentStateError("Нельзя менять формат после старта.")
            if "name" in updates:
                self._validate_name(updates["name"])
                t.name = updates["name"].strip()
            if "format" in updates: t.format = updates["format"]
            if "max_participants" in updates:
                t.max_participants = min(updates["max_participants"], self.max_players_limit)
            await self.repo.save_tournament(t)
            return t

    async def delete_tournament(self, t_id: str, admin_id: int) -> bool:
        t = await self._get_tournament_or_raise(t_id)
        if t.status not in [self.STATE_DRAFT, self.STATE_CANCELLED]:
            raise TournamentStateError("Только Draft или Cancelled.")
        await self.repo.delete_tournament(t_id)
        return True

    async def clone_tournament(self, t_id: str, admin_id: int, new_name: str) -> Tournament:
        src = await self._get_tournament_or_raise(t_id)
        return await self.create_tournament(new_name, src.format, admin_id, _get_max_participants(src, 128))

    async def archive_tournament(self, t_id: str, admin_id: int) -> Tournament:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self._get_tournament_or_raise(t_id)
            if t.status != self.STATE_FINISHED: raise TournamentStateError("Только Finished.")
            t.status = self.STATE_ARCHIVED
            await self.repo.save_tournament(t)
            return t

    async def merge_tournaments(self, primary_t_id: str, secondary_t_id: str, admin_id: int) -> Tournament:
        async with TournamentTransactionContext(self.repo, primary_t_id):
            prim = await self._get_tournament_or_raise(primary_t_id)
            sec = await self._get_tournament_or_raise(secondary_t_id)
            if prim.status != self.STATE_REGISTRATION or sec.status != self.STATE_REGISTRATION:
                raise TournamentStateError("Слияние только в стадии регистрации.")
            for p_id in sec.participants:
                if p_id not in prim.participants and len(prim.participants) < _get_max_participants(prim, self.max_players_limit):
                    prim.participants.append(p_id)
            await self.repo.save_tournament(prim)
            await self.repo.delete_tournament(secondary_t_id)
            return prim

    async def split_tournament(self, t_id: str, new_name: str, admin_id: int) -> Tuple[Tournament, Tournament]:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self._get_tournament_or_raise(t_id)
            if t.status != self.STATE_REGISTRATION: raise TournamentStateError("Только при регистрации.")
            mid = len(t.participants) // 2
            h1, h2 = t.participants[:mid], t.participants[mid:]
            t.participants = h1
            await self.repo.save_tournament(t)
            
            t2 = await self.create_tournament(new_name, t.format, admin_id, _get_max_participants(t, 128))
            t2.participants = h2
            await self.repo.save_tournament(t2)
            return t, t2

    # --- Lifecycle API ---
    async def open_registration(self, t_id: str, admin_id: int) -> Tournament:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self._get_tournament_or_raise(t_id)
            if t.status != self.STATE_DRAFT: raise TournamentStateError("Только из Draft.")
            t.status = self.STATE_REGISTRATION
            await self.repo.save_tournament(t)
            return t

    async def close_registration(self, t_id: str, admin_id: int) -> Tournament:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self._get_tournament_or_raise(t_id)
            if t.status != self.STATE_REGISTRATION: raise TournamentStateError("Не в регистрации.")
            if len(t.participants) < 2: raise TournamentValidationError("Недостаточно участников.")
            
            if t.format in [TournamentFormat.SINGLE_ELIMINATION, TournamentFormat.DOUBLE_ELIMINATION]:
                c = len(t.participants)
                byes = (2 ** math.ceil(math.log2(c))) - c
                for i in range(byes):
                    t.participants.append(-1 - i)
            t.status = self.STATE_READY
            await self.repo.save_tournament(t)
            return t

    async def pause_tournament(self, t_id: str, admin_id: int) -> Tournament:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self._get_tournament_or_raise(t_id)
            if t.status != self.STATE_RUNNING: raise TournamentStateError("Только из Running.")
            t.status = self.STATE_PAUSED
            await self.reminder_service.cancel_all_reminders(t_id)
            await self.repo.save_tournament(t)
            return t

    async def resume_tournament(self, t_id: str, admin_id: int) -> Tournament:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self._get_tournament_or_raise(t_id)
            if t.status != self.STATE_PAUSED: raise TournamentStateError("Только из Paused.")
            t.status = self.STATE_RUNNING
            await self.reminder_service.schedule_tournament_reminders(t_id)
            await self.repo.save_tournament(t)
            return t

    async def cancel_tournament(self, t_id: str, admin_id: int) -> Tournament:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self._get_tournament_or_raise(t_id)
            if t.status in [self.STATE_FINISHED, self.STATE_ARCHIVED]:
                raise TournamentStateError("Нельзя отменить завершенный.")
            t.status = self.STATE_CANCELLED
            await self.reminder_service.cancel_all_reminders(t_id)
            for m in await self.match_service.get_active_matches(t_id):
                await self.match_service.cancel_match(m.id, "Отменен админом")
            await self.repo.save_tournament(t)
            return t

    async def force_finish(self, t_id: str, admin_id: int) -> Tournament:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self._get_tournament_or_raise(t_id)
            if t.status not in [self.STATE_RUNNING, self.STATE_PAUSED]:
                raise TournamentStateError("Только Running или Paused.")
            await self.dispute_service.resolve_all_auto(t_id)
            return await self._life.finalize(t)

    async def start_tournament(self, t_id: str, admin_id: int) -> bool:
        return await self._life.start_tournament(t_id, admin_id)

    # --- Players API ---
    async def register_player(self, t_id: str, user_id: int) -> bool:
        return await self._players.register_player(t_id, user_id)

    async def unregister_player(self, t_id: str, user_id: int) -> bool:
        return await self._players.unregister_player(t_id, user_id)

    async def kick_player(self, t_id: str, user_id: int, admin_id: int) -> bool:
        return await self._players.kick_player(t_id, user_id, admin_id)

    async def replace_player(self, t_id: str, old_id: int, new_id: int, admin_id: int) -> bool:
        return await self._players.replace_player(t_id, old_id, new_id, admin_id)

    async def add_player_after_start(self, t_id: str, user_id: int, admin_id: int) -> bool:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self._get_tournament_or_raise(t_id)
            if t.status != self.STATE_RUNNING: raise TournamentStateError("Только в запущенном.")
            if await self.user_service.is_banned(user_id): raise TournamentRegistrationError("Забанен.")
            t.participants.append(user_id)
            await self.repo.save_tournament(t)
            return True

    async def shuffle_players(self, t_id: str, admin_id: int) -> bool:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self._get_tournament_or_raise(t_id)
            if t.status not in [self.STATE_REGISTRATION, self.STATE_READY]: raise TournamentStateError("Только до старта.")
            random.shuffle(t.participants)
            await self.repo.save_tournament(t)
            return True

    async def reseed(self, t_id: str, new_seed: List[int], admin_id: int) -> bool:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self._get_tournament_or_raise(t_id)
            if set(new_seed) != set(t.participants): raise TournamentValidationError("Должны совпадать участники.")
            t.participants = new_seed
            await self.repo.save_tournament(t)
            return True

    async def swap_players(self, t_id: str, u1: int, u2: int, admin_id: int) -> bool:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self._get_tournament_or_raise(t_id)
            if u1 not in t.participants or u2 not in t.participants: raise TournamentValidationError("Игроки не найдены.")
            i1, i2 = t.participants.index(u1), t.participants.index(u2)
            t.participants[i1], t.participants[i2] = t.participants[i2], t.participants[i1]
            await self.repo.save_tournament(t)
            return True

    # --- Match & Admin API ---
    async def check_round_completion(self, t_id: str) -> bool:
        t = await self._get_tournament_or_raise(t_id)
        if t.status != self.STATE_RUNNING: return False
        if await self.dispute_service.has_active_disputes(t_id): return False
        if len(await self.match_service.get_active_matches(t_id)) > 0: return False
        return await self._life.advance_round(t_id)

    async def advance_round(self, t_id: str) -> bool:
        return await self._life.advance_round(t_id)

    async def force_round(self, t_id: str, round_num: int, admin_id: int) -> bool:
        t = await self._get_tournament_or_raise(t_id)
        if t.format == TournamentFormat.SWISS:
            return await self.swiss_service.generate_round(t_id, round_num)
        raise TournamentStateError("Только для Swiss.")

    async def regenerate_round(self, t_id: str, admin_id: int) -> bool:
        t = await self._get_tournament_or_raise(t_id)
        if t.format == TournamentFormat.SWISS:
            curr = await self.swiss_service.get_current_round(t_id)
            return await self.swiss_service.generate_round(t_id, curr)
        raise TournamentStateError("Только для Swiss.")

    async def regenerate_bracket(self, t_id: str, admin_id: int) -> bool:
        t = await self._get_tournament_or_raise(t_id)
        if t.format in [TournamentFormat.SINGLE_ELIMINATION, TournamentFormat.DOUBLE_ELIMINATION]:
            return await self.bracket_service.regenerate_bracket(t_id)
        raise TournamentStateError("Только для Elimination.")

    async def rollback_round(self, t_id: str, admin_id: int) -> bool:
        async with TournamentTransactionContext(self.repo, t_id):
            for m in await self.match_service.get_active_matches(t_id):
                await self.match_service.revert_match_result(m.id)
            return True

    async def force_win(self, t_id: str, match_id: str, winner_id: int, admin_id: int) -> bool:
        if await self.match_service.force_set_result(match_id, 1, 0, winner_id):
            await self.check_round_completion(t_id)
            return True
        return False

    async def force_loss(self, t_id: str, match_id: str, loser_id: int, admin_id: int) -> bool:
        if await self.match_service.apply_technical_defeat(match_id, loser_id):
            await self.check_round_completion(t_id)
            return True
        return False

    async def force_draw(self, t_id: str, match_id: str, admin_id: int) -> bool:
        if await self.match_service.force_set_result(match_id, 0, 0, None):
            await self.check_round_completion(t_id)
            return True
        return False

    async def bulk_verify_match_results(self, t_id: str, match_ids: List[str], admin_id: int) -> bool:
        if await self.result_service.bulk_verify_results(match_ids):
            await self.check_round_completion(t_id)
            return True
        return False

    async def cancel_match_result(self, t_id: str, match_id: str, admin_id: int) -> bool:
        return await self.match_service.revert_match_result(match_id)

    async def apply_auto_forfeits(self, t_id: str) -> List[str]:
        t = await self._get_tournament_or_raise(t_id)
        if t.status != self.STATE_RUNNING: return []
        logs = []
        now = datetime.now(timezone.utc)
        for m in await self.match_service.get_active_matches(t_id):
            dl = getattr(m, 'deadline', None)
            if dl and now > dl:
                await self.match_service.cancel_match(m.id, "Дедлайн")
                logs.append(f"{m.id}: автотехлуз")
        if logs: await self.check_round_completion(t_id)
        return logs

    async def extend_deadline(self, t_id: str, match_id: str, hours: int, admin_id: int) -> bool:
        for m in await self.match_service.get_active_matches(t_id):
            if m.id == match_id and hasattr(m, 'deadline') and m.deadline:
                m.deadline += timedelta(hours=hours)
                await self.repo.save_match(m)
                return True
        return False

    # --- Analytics & Data ---
    async def get_statistics(self, t_id: str) -> Dict[str, Any]:
        t = await self._get_tournament_or_raise(t_id)
        all_m = await self.match_service.get_all_matches(t_id)
        fin = [m for m in all_m if m.status == MatchStatus.FINISHED]
        d_cnt = await self.dispute_service.count_disputes(t_id)
        
        sm = sum(getattr(m, 'p1_score', 0) + getattr(m, 'p2_score', 0) for m in fin)
        fc = sum(1 for m in fin if getattr(m, 'is_forfeit', False))
        
        return {
            "tournament_id": t_id,
            "name": t.name,
            "status": t.status,
            "total_participants": len(t.participants),
            "waiting_list_count": len(_get_waitlist(t)),
            "total_matches": len(all_m),
            "finished_matches": len(fin),
            "completion_percent": round((len(fin) / len(all_m) * 100) if all_m else 0, 2),
            "average_score": round((sm / len(fin)) if fin else 0, 2),
            "forfeit_percent": round((fc / len(fin) * 100) if fin else 0, 2),
            "active_disputes_count": d_cnt,
            "player_streaks": await self.ranking_service.calculate_streaks(t_id)
        }

    async def get_winners(self, t_id: str, top_n: int = 3) -> List[int]:
        t = await self._get_tournament_or_raise(t_id)
        if t.status not in [self.STATE_FINISHED, self.STATE_ARCHIVED]: return []
        return await self.ranking_service.get_top_players(t_id, limit=top_n)

    async def get_active_matches(self, t_id: str) -> List[Match]:
        await self._get_tournament_or_raise(t_id)
        return await self.match_service.get_active_matches(t_id)

    async def get_tournament_history(self, t_id: str) -> List[Dict[str, Any]]:
        await self._get_tournament_or_raise(t_id)
        matches = await self.match_service.get_all_matches(t_id)
        return [{"match_id": m.id, "status": m.status, "winner": getattr(m, 'winner_id', None)} for m in matches]

    async def export_tournament(self, t_id: str) -> str:
        t = await self._get_tournament_or_raise(t_id)
        m = await self.match_service.get_all_matches(t_id)
        return json.dumps({"tournament": t.model_dump(), "matches": [x.model_dump() for x in m]}, default=str, ensure_ascii=False)

    async def import_tournament(self, json_data: str, admin_id: int) -> Tournament:
        try:
            data = json.loads(json_data)
            t = Tournament(**data["tournament"])
            if await self.repo.get_tournament(t.id): raise TournamentIntegrityError("Уже существует.")
            await self.repo.save_tournament(t)
            for md in data.get("matches", []):
                await self.repo.save_match(Match(**md))
            return t
        except Exception as e:
            raise TournamentValidationError(f"Ошибка импорта: {str(e)}")

    async def verify_integrity(self, t_id: str) -> List[str]:
        t = await self._get_tournament_or_raise(t_id)
        logs = []
        if len(t.participants) != len(set(t.participants)): logs.append("Дубликаты игроков.")
        if len(t.matches) != len(set(t.matches)): logs.append("Дубликаты матчей.")
        return logs

    async def restore_corrupted_data(self, t_id: str) -> bool:
        async with TournamentTransactionContext(self.repo, t_id):
            t = await self._get_tournament_or_raise(t_id)
            p_seen, clean_p = set(), []
            for p in t.participants:
                if p not in p_seen: p_seen.add(p); clean_p.append(p)
            mod = len(t.participants) != len(clean_p)
            if mod:
                t.participants = clean_p
                await self.repo.save_tournament(t)
            return mod

    async def restore_tournament_after_crash(self, t_id: str) -> bool:
        try:
            await self.restore_corrupted_data(t_id)
            t = await self._get_tournament_or_raise(t_id)
            if t.status == self.STATE_RUNNING:
                await self.check_round_completion(t_id)
            return True
        except Exception:
            return False
