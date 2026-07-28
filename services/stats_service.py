# services/stats_service.py

from typing import Dict, List, Optional

from database.database import BaseRepository
from database.models import Tournament, User


class StatsService:
    """
    Сервис статистики турниров и игроков.
    """

    def __init__(
        self,
        repo: BaseRepository,
    ):
        self.repo = repo

    async def get_user_stats(self, user_id: int) -> Optional[Dict]:
        user: User | None = await self.repo.get_user(user_id)

        if user is None:
            return None

        winrate = 0

        if user.matches_played > 0:
            winrate = round(
                user.wins / user.matches_played * 100,
                2
            )

        return {
            "id": user.id,
            "username": user.username,
            "elo": user.elo,
            "peak_elo": user.peak_elo,
            "matches": user.matches_played,
            "wins": user.wins,
            "losses": user.losses,
            "draws": user.draws,
            "winrate": winrate,
            "tournaments_played": user.tournaments_played,
            "tournaments_won": user.tournaments_won,
        }

    async def get_tournament_stats(
        self,
        tournament_id: str
    ) -> Optional[Dict]:

        tournament: Tournament | None = await self.repo.get_tournament(
            tournament_id
        )

        if tournament is None:
            return None

        return {
            "id": tournament.id,
            "name": tournament.name,
            "format": tournament.format,
            "status": tournament.status,
            "players": len(tournament.participants),
            "matches": len(tournament.matches),
            "current_round": tournament.current_round,
        }

    async def get_top_elo(
        self,
        limit: int = 10
    ) -> List[Dict]:

        users = await self.repo.get_all_users()

        users = sorted(
            users,
            key=lambda u: u.elo,
            reverse=True
        )

        result = []

        for user in users[:limit]:
            result.append({
                "id": user.id,
                "username": user.username,
                "elo": user.elo
            })

        return result

    async def get_top_winners(
        self,
        limit: int = 10
    ) -> List[Dict]:

        users = await self.repo.get_all_users()

        users = sorted(
            users,
            key=lambda u: u.tournaments_won,
            reverse=True
        )

        result = []

        for user in users[:limit]:
            result.append({
                "id": user.id,
                "username": user.username,
                "tournaments_won": user.tournaments_won
            })

        return result

    async def get_total_statistics(self) -> Dict:

        users = await self.repo.get_all_users()
        tournaments = await self.repo.get_all_tournaments()

        matches = 0

        for tournament in tournaments:
            matches += len(tournament.matches)

        return {
            "users": len(users),
            "tournaments": len(tournaments),
            "matches": matches
        }
