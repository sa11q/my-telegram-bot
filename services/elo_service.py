# services/elo_service.py

from typing import Tuple
from database.models import User


class EloService:
    """
    Elo/MMR система турнира.

    Используется после завершения матча:
    - получает рейтинг игроков;
    - рассчитывает новый рейтинг;
    - возвращает новые значения.
    """

    def __init__(self, default_rating: int = 1200, k_factor: int = 32):
        self.default_rating = default_rating
        self.k_factor = k_factor


    def get_rating(self, user: User | None) -> int:
        """
        Получение рейтинга игрока.
        Если игрок отсутствует — возвращает стандартный рейтинг.
        """

        if not user:
            return self.default_rating

        return user.elo



    def expected_score(
        self,
        player_rating: int,
        opponent_rating: int
    ) -> float:
        """
        Вероятность победы игрока.

        Формула Elo:
        E = 1 / (1 + 10^((Rb - Ra)/400))
        """

        return 1 / (
            1 + 10 ** (
                (opponent_rating - player_rating) / 400
            )
        )



    def calculate_rating_change(
        self,
        player_rating: int,
        opponent_rating: int,
        actual_score: float
    ) -> int:
        """
        Расчёт изменения рейтинга.

        actual_score:
        1   - победа
        0.5 - ничья
        0   - поражение
        """

        expected = self.expected_score(
            player_rating,
            opponent_rating
        )

        change = self.k_factor * (
            actual_score - expected
        )

        return round(change)



    def calculate_new_ratings(
        self,
        player1_rating: int,
        player2_rating: int,
        player1_score: float
    ) -> Tuple[int, int]:
        """
        Возвращает новые рейтинги двух игроков.
        """

        player2_score = 1 - player1_score


        change1 = self.calculate_rating_change(
            player1_rating,
            player2_rating,
            player1_score
        )

        change2 = self.calculate_rating_change(
            player2_rating,
            player1_rating,
            player2_score
        )


        new_player1 = max(
            0,
            player1_rating + change1
        )

        new_player2 = max(
            0,
            player2_rating + change2
        )


        return new_player1, new_player2



    def result_to_score(
        self,
        winner_id: int | None,
        player1_id: int,
        player2_id: int
    ) -> Tuple[float, float]:
        """
        Перевод результата матча в Elo формат.
        """

        if winner_id is None:
            return 0.5, 0.5


        if winner_id == player1_id:
            return 1.0, 0.0


        if winner_id == player2_id:
            return 0.0, 1.0


        return 0.5, 0.5



    def update_users_rating(
        self,
        player1: User,
        player2: User,
        winner_id: int | None
    ) -> Tuple[User, User]:
        """
        Полное обновление Elo игроков.

        Будет использоваться в match_service/result_service.
        """

        score1, _ = self.result_to_score(
            winner_id,
            player1.id,
            player2.id
        )


        new_rating1, new_rating2 = self.calculate_new_ratings(
            player1.elo,
            player2.elo,
            score1
        )


        player1.elo = new_rating1
        player2.elo = new_rating2


        if player1.elo > player1.max_elo:
            player1.max_elo = player1.elo

        if player2.elo > player2.max_elo:
            player2.max_elo = player2.elo


        return player1, player2



# Глобальный экземпляр сервиса
elo_service = EloService()
