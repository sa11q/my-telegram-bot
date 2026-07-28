from database.models import Tournament, TournamentFormat, Match
from database.database import BaseRepository

class TournamentService:
    def __init__(self, repo: BaseRepository):
        self.repo = repo

    async def create_tournament(self, name: str, fmt: TournamentFormat) -> Tournament:
        t = Tournament(name=name, format=fmt)
        await self.repo.save_tournament(t)
        return t

    async def join_tournament(self, t_id: str, user_id: int) -> bool:
        t = await self.repo.get_tournament(t_id)
        if not t or not t.is_active:
            return False
        if user_id not in t.participants:
            t.participants.append(user_id)
            await self.repo.save_tournament(t)
        return True

    async def generate_bracket(self, t_id: str):
        t = await self.repo.get_tournament(t_id)
        if not t or len(t.participants) < 2:
            return
        
        if t.format == TournamentFormat.SINGLE_ELIMINATION:
            import math
            import random
            participants = t.participants.copy()
            random.shuffle(participants)
            
            # Simple bracket generation
            for i in range(0, len(participants), 2):
                p1 = participants[i]
                p2 = participants[i+1] if i+1 < len(participants) else None
                m = Match(
                    tournament_id=t.id,
                    player1_id=p1,
                    player2_id=p2,
                    stage="ROUND_1"
                )
                t.matches.append(m.id)
            await self.repo.save_tournament(t)

