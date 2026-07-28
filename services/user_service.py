from typing import Optional, List

from database.database import BaseRepository
from database.models import User, Role
from utils.logger import admin_logger, error_logger


class UserService:
    """
    Центральная система управления пользователями.
    Работает с любым Repository:
    JSON / PostgreSQL.
    """

    def __init__(self, repo: BaseRepository):
        self.repo = repo


    async def get_user(self, user_id: int) -> Optional[User]:
        """
        Получить профиль игрока.
        """
        try:
            return await self.repo.get_user(user_id)

        except Exception as e:
            error_logger.error(
                f"Get user error {user_id}: {e}"
            )
            return None


    async def create_user(
        self,
        user_id: int,
        username: Optional[str] = None
    ) -> User:
        """
        Создание нового пользователя.
        """

        existing = await self.get_user(user_id)

        if existing:
            return existing


        user = User(
            id=user_id,
            username=username,
            role=Role.USER,
            elo=1200,
            max_elo=1200
        )


        await self.repo.save_user(user)

        admin_logger.info(
            f"Created user {user_id} @{username}"
        )

        return user



    async def get_or_create_user(
        self,
        user_id: int,
        username: Optional[str] = None
    ) -> User:
        """
        Основная функция для middleware.
        Каждый входящий пользователь проходит здесь.
        """

        user = await self.get_user(user_id)

        if user:
            return user


        return await self.create_user(
            user_id,
            username
        )



    async def update_username(
        self,
        user_id: int,
        username: str
    ) -> bool:
        """
        Обновление username Telegram.
        """

        user = await self.get_user(user_id)

        if not user:
            return False


        user.username = username

        await self.repo.save_user(user)

        return True



    async def change_role(
        self,
        target_id: int,
        new_role: Role,
        admin_id: int
    ) -> bool:
        """
        Выдать роль игроку.
        OWNER нельзя снять.
        """

        target = await self.get_user(target_id)

        if not target:
            return False


        if target.role == Role.OWNER:
            return False


        target.role = new_role

        await self.repo.save_user(target)


        admin_logger.info(
            f"Admin {admin_id} changed "
            f"{target_id} role to {new_role}"
        )


        return True



    async def ban_user(
        self,
        user_id: int,
        reason: str,
        admin_id: int
    ) -> bool:
        """
        Бан игрока.
        """

        user = await self.get_user(user_id)

        if not user:
            return False


        if user.role == Role.OWNER:
            return False


        user.is_banned = True
        user.ban_reason = reason


        await self.repo.save_user(user)


        admin_logger.info(
            f"Admin {admin_id} banned {user_id}: {reason}"
        )

        return True



    async def unban_user(
        self,
        user_id: int,
        admin_id: int
    ) -> bool:
        """
        Разбан игрока.
        """

        user = await self.get_user(user_id)

        if not user:
            return False


        user.is_banned = False
        user.ban_reason = None


        await self.repo.save_user(user)


        admin_logger.info(
            f"Admin {admin_id} unbanned {user_id}"
        )

        return True



    async def add_match_result(
        self,
        winner_id: int,
        loser_id: int
    ):
        """
        Обновление статистики после матча.
        Elo будет отдельно в elo_service.py.
        """

        winner = await self.get_user(winner_id)
        loser = await self.get_user(loser_id)


        if not winner or not loser:
            return False


        winner.wins += 1
        winner.matches_played += 1


        loser.losses += 1
        loser.matches_played += 1


        await self.repo.save_user(winner)
        await self.repo.save_user(loser)


        return True



    async def get_top_players(
        self,
        limit: int = 10
    ) -> List[User]:
        """
        Топ игроков по Elo.
        """

        # Универсально для JSON.
        # В PostgreSQL потом можно заменить SQL сортировкой.

        if not hasattr(self.repo, "_read_db"):
            return []


        data = await self.repo._read_db()

        users = [
            User(**u)
            for u in data.get("users", {}).values()
        ]


        users.sort(
            key=lambda x: x.elo,
            reverse=True
        )


        return users[:limit]
