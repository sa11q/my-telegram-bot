import math
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

import asyncpg
from database import pool

logger = logging.getLogger(__name__)

# Часовой пояс (UTC+5) для точного соблюдения дедлайнов
KZ_TZ = timezone(timedelta(hours=5))

# Словари локализации прямо в сервисе для мгновенной генерации текстов
LOCALES: Dict[str, Dict[str, str]] = {
    "ru": {
        "score_accepted": "✅ <b>Результат принят!</b>\n@{p1} {s1}:{s2} @{p2}\n📈 Рейтинг Elo обновлен.",
        "negative_score": "❌ Счёт не может быть отрицательным.",
        "not_active_tour": "ℹ️ Сейчас нет активного турнира или регистрация закрыта.",
        "not_participant": "🚨 <b>Ошибка:</b> Ты не являешься участником этого матча.",
        "match_not_found": "❌ Активный матч между вами не найден, либо результат уже записан.",
        "db_error": "🛠 Произошла ошибка базы данных при сохранении."
    },
    "kz": {
        "score_accepted": "✅ <b>Нәтиже қабылданды!</b>\n@{p1} {s1}:{s2} @{p2}\n📈 Elo рейтингі жаңартылды.",
        "negative_score": "❌ Есеп теріс болуы мүмкін емес.",
        "not_active_tour": "ℹ️ Қазір белсенді турнир жоқ немесе тіркеу жабық.",
        "not_participant": "🚨 <b>Қате:</b> Сіз бұл матчтың қатысушысы емессіз.",
        "match_not_found": "❌ Араларыңыздағы белсенді матч табылмады немесе нәтиже бұрын жазылған.",
        "db_error": "🛠 Сақтау кезінде деректер қорының қатесі орын алды."
    },
    "uz": {
        "score_accepted": "✅ <b>Natija qabul qilindi!</b>\n@{p1} {s1}:{s2} @{p2}\n📈 Elo reytingi yangilandi.",
        "negative_score": "❌ Hisob manfiy bo'lishi mumkin emas.",
        "not_active_tour": "ℹ️ Hozirda faol turnir yo'q yoki ro'yxatdan o'tish yopilgan.",
        "not_participant": "🚨 <b>Xato:</b> Siz bu o'yinning ishtirokchisi emassiz.",
        "match_not_found": "❌ Orangizdagi faol o'yin topilmadi yoki natija allaqachon yozilgan.",
        "db_error": "🛠 Saqlash vaqtida ma'lumotlar bazasida xatolik yuz berdi."
    },
    "en": {
        "score_accepted": "✅ <b>Result accepted!</b>\n@{p1} {s1}:{s2} @{p2}\n📈 Elo rating updated.",
        "negative_score": "❌ Score cannot be negative.",
        "not_active_tour": "ℹ️ There is no active tournament or registration is closed.",
        "not_participant": "🚨 <b>Error:</b> You are not a participant in this match.",
        "match_not_found": "❌ Active match between you was not found or already recorded.",
        "db_error": "🛠 Database error occurred while saving."
    }
}

class TournamentService:
    
    @staticmethod
    def get_text(lang: str, key: str, **kwargs) -> str:
        """Возвращает переведенный текст с подстановкой переменных."""
        lang_dict = LOCALES.get(lang, LOCALES["ru"])
        text = lang_dict.get(key, LOCALES["ru"].get(key, key))
        return text.format(**kwargs)

    @staticmethod
    def calculate_deadline() -> datetime:
        """
        Автоматический дедлайн: +1.5 часа. 
        НО если этап выпадает после 22:00 -> дедлайн становится 17:00 следующего дня.
        """
        now = datetime.now(KZ_TZ)
        deadline = now + timedelta(hours=1, minutes=30)
        
        if now.hour >= 22 or deadline.hour >= 22 or now.hour < 8:
            next_day = now + timedelta(days=1) if now.hour >= 8 else now
            deadline = next_day.replace(hour=17, minute=0, second=0, microsecond=0)
            
        return deadline

    @staticmethod
    async def get_player_language(tg_id: int) -> str:
        """Получает язык игрока из базы данных."""
        if not pool:
            return "ru"
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT language FROM players WHERE tg_id = $1;", tg_id)
            return row["language"] if row and row["language"] in LOCALES else "ru"

    @classmethod
    async def process_match_input(
        cls, 
        chat_id: int, 
        sender_id: int, 
        sender_username: str, 
        p1_nick: str, 
        p2_nick: str, 
        score1: int, 
        score2: int
    ) -> str:
        """
        Главный пайплайн обработки счета от игрока:
        1. Проверка валидности счетов.
        2. Получение языка пользователя для ответа.
        3. Проверка активного турнира.
        4. Защита от спуфинга (отправитель — участник матча).
        5. Поиск матча в базе.
        6. Атомарная транзакция записи счета и обновления Elo.
        """
        if score1 < 0 or score2 < 0:
            lang = await cls.get_player_language(sender_id)
            return cls.get_text(lang, "negative_score")

        if not pool:
            return "Database pool is not initialized."

        async with pool.acquire() as conn:
            # Получаем язык отправителя
            player_row = await conn.fetchrow("SELECT language FROM players WHERE tg_id = $1;", sender_id)
            lang = player_row["language"] if player_row and player_row["language"] in LOCALES else "ru"

            # Проверяем активный турнир
            tour = await conn.fetchrow("SELECT * FROM tournaments WHERE is_active = TRUE AND status = 'active' LIMIT 1;")
            if not tour:
                return cls.get_text(lang, "not_active_tour")

            # Ищем игроков в базе
            p1_clean = p1_nick.lower().replace("@", "")
            p2_clean = p2_nick.lower().replace("@", "")
            
            p1 = await conn.fetchrow("SELECT * FROM players WHERE LOWER(username) = $1;", p1_clean)
            p2 = await conn.fetchrow("SELECT * FROM players WHERE LOWER(username) = $2;", p2_clean)

            if not p1 or not p2:
                return cls.get_text(lang, "match_not_found")

            # Проверка безопасности: отправитель должен быть участником матча
            if sender_id not in (p1["tg_id"], p2["tg_id"]):
                return cls.get_text(lang, "not_participant")

            # Ищем активный несыгранный матч между ними в текущем турнире
            match_query = """
                SELECT m.*, u1.username as u1_name, u2.username as u2_name 
                FROM matches m
                JOIN players u1 ON m.p1_id = u1.tg_id
                JOIN players u2 ON m.p2_id = u2.tg_id
                WHERE m.tour_id = $1 AND m.status = 'pending'
                AND (
                    (u1.tg_id = $2 AND u2.tg_id = $3) 
                    OR 
                    (u1.tg_id = $3 AND u2.tg_id = $2)
                )
                LIMIT 1;
            """
            match = await conn.fetchrow(match_query, tour["id"], p1["tg_id"], p2["tg_id"])
            if not match:
                return cls.get_text(lang, "match_not_found")

            # Распределяем счет в зависимости от того, как игроки записаны в таблице матчей
            if match["u1_name"].lower() == p1_clean:
                final_s1, final_s2 = score1, score2
            else:
                final_s1, final_s2 = score2, score1

            # Запуск транзакции записи результата и пересчета Elo
            try:
                async with conn.transaction():
                    # 1. Обновляем статус и счет матча
                    await conn.execute("""
                        UPDATE matches 
                        SET p1_score = $1, p2_score = $2, status = 'finished'
                        WHERE id = $3;
                    """, final_s1, final_s2, match["id"])

                    # 2. Пересчет Elo для обоих игроков
                    await cls._apply_elo(conn, match["p1_id"], match["p2_id"], final_s1, final_s2)

                return cls.get_text(lang, "score_accepted", p1=p1_clean, s1=final_s1, s2=final_s2, p2=p2_clean)

            except Exception as e:
                logger.error(f"Transaction failed while saving match: {e}")
                return cls.get_text(lang, "db_error")

    @staticmethod
    async def _apply_elo(conn: asyncpg.Connection, p1_id: int, p2_id: int, s1: int, s2: int):
        """Внутренний математический расчет Elo-рейтинга (K=32)."""
        p1 = await conn.fetchrow("SELECT elo FROM players WHERE tg_id = $1;", p1_id)
        p2 = await conn.fetchrow("SELECT elo FROM players WHERE tg_id = $1;", p2_id)
        if not p1 or not p2:
            return

        r1, r2 = p1["elo"], p2["elo"]
        exp_1 = 1 / (1 + math.pow(10, (r2 - r1) / 400))
        exp_2 = 1 / (1 + math.pow(10, (r1 - r2) / 400))

        act_1 = 1.0 if s1 > s2 else (0.0 if s1 < s2 else 0.5)
        act_2 = 1.0 - act_1

        k = 32
        new_r1 = round(r1 + k * (act_1 - exp_1))
        new_r2 = round(r2 + k * (act_2 - exp_2))

        # Обновление игрока 1
        await conn.execute("""
            UPDATE players SET 
                elo = $1, matches_played = matches_played + 1,
                wins = wins + $2, losses = losses + $3, draws = draws + $4
            WHERE tg_id = $5;
        """, new_r1, 1 if act_1 == 1 else 0, 1 if act_1 == 0 else 0, 1 if act_1 == 0.5 else 0, p1_id)

        # Обновление игрока 2
        await conn.execute("""
            UPDATE players SET 
                elo = $1, matches_played = matches_played + 1,
                wins = wins + $2, losses = losses + $3, draws = draws + $4
            WHERE tg_id = $5;
        """, new_r2, 1 if act_2 == 1 else 0, 1 if act_2 == 0 else 0, 1 if act_2 == 0.5 else 0, p2_id)

