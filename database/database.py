import logging
import math
from typing import Optional, Dict, Any, List
from datetime import datetime

import asyncpg

logger = logging.getLogger(__name__)

# Глобальный пул соединений
pool: Optional[asyncpg.Pool] = None

# DSN по умолчанию (настрой под свою БД или читай из env)
DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/tournaments_db"


# ==========================================
# ИНИЦИАЛИЗАЦИЯ И ЗАКРЫТИЕ ПУЛА БД
# ==========================================

async def init_db(dsn: str = DEFAULT_DSN):
    """
    Создает пул соединений PostgreSQL и авто-создает таблицы при запуске.
    """
    global pool
    try:
        pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=5,
            max_size=20,
            command_timeout=60
        )
        
        async with pool.acquire() as conn:
            # Игроки (BIGINT критически важен для Telegram user_id!)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS players (
                    tg_id BIGINT PRIMARY KEY,
                    username VARCHAR(64) UNIQUE NOT NULL,
                    elo INT DEFAULT 1200,
                    matches_played INT DEFAULT 0,
                    wins INT DEFAULT 0,
                    losses INT DEFAULT 0,
                    draws INT DEFAULT 0,
                    language VARCHAR(10) DEFAULT 'ru'
                );
                
                CREATE INDEX IF NOT EXISTS idx_players_username_lower 
                ON players (LOWER(username));
            """)

            # Турниры
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS tournaments (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    is_active BOOLEAN DEFAULT FALSE,
                    status VARCHAR(32) DEFAULT 'registration',
                    mode VARCHAR(32),
                    current_stage INT DEFAULT 1,
                    stage_deadline TIMESTAMP WITH TIME ZONE
                );
            """)

            # Матчи
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS matches (
                    id SERIAL PRIMARY KEY,
                    tour_id INT REFERENCES tournaments(id) ON DELETE CASCADE,
                    stage INT,
                    p1_id BIGINT REFERENCES players(tg_id),
                    p2_id BIGINT REFERENCES players(tg_id),
                    p1_score INT DEFAULT 0,
                    p2_score INT DEFAULT 0,
                    status VARCHAR(32) DEFAULT 'pending'
                );
            """)

        logger.info("✅ База данных PostgreSQL (asyncpg pool) успешно инициализирована.")
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к PostgreSQL: {e}")
        raise e


async def close_db():
    """Корректное закрытие пула соединений при выключении бота."""
    global pool
    if pool:
        await pool.close()
        logger.info("Пул соединений PostgreSQL закрыт.")


# ==========================================
# РАБОТА С ИГРОКАМИ
# ==========================================

async def upsert_player(tg_id: int, username: str) -> None:
    """Добавляет игрока или обновляет username при совпадении tg_id."""
    if not username or not pool:
        return

    clean_username = username.lower().replace("@", "")
    query = """
        INSERT INTO players (tg_id, username)
        VALUES ($1, $2)
        ON CONFLICT (tg_id) DO UPDATE SET username = EXCLUDED.username;
    """
    async with pool.acquire() as conn:
        await conn.execute(query, tg_id, clean_username)


async def get_player_language(tg_id: int) -> str:
    """Получает язык интерфейса игрока."""
    if not pool:
        return "ru"
        
    query = "SELECT language FROM players WHERE tg_id = $1;"
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, tg_id)
        return row["language"] if row else "ru"


async def set_player_language(tg_id: int, lang_code: str) -> None:
    """Обновляет язык игрока."""
    if not pool:
        return
        
    query = "UPDATE players SET language = $1 WHERE tg_id = $2;"
    async with pool.acquire() as conn:
        await conn.execute(query, lang_code, tg_id)


async def get_player_by_username(username: str) -> Optional[asyncpg.Record]:
    """Быстрый поиск игрока без учета регистра."""
    if not pool:
        return None
        
    clean_username = username.lower().replace("@", "")
    query = "SELECT * FROM players WHERE LOWER(username) = $1;"
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, clean_username)


# ==========================================
# РАБОТА С ТУРНИРАМИ
# ==========================================

async def get_active_tournament() -> Optional[asyncpg.Record]:
    """Возвращает текущий активный турнир."""
    if not pool:
        return None
        
    query = "SELECT * FROM tournaments WHERE is_active = TRUE AND status != 'archived' LIMIT 1;"
    async with pool.acquire() as conn:
        return await conn.fetchrow(query)


# ==========================================
# РАБОТА С МАТЧАМИ И РЕЗУЛЬТАТАМИ
# ==========================================

async def find_pending_match(tour_id: int, p1_username: str, p2_username: str) -> Optional[asyncpg.Record]:
    """
    Ищет несыгранный матч между двумя игроками в текущем турнире.
    Автоматически перекрещивает проверку (кто P1, а кто P2 в базе).
    """
    if not pool:
        return None

    p1 = p1_username.lower().replace("@", "")
    p2 = p2_username.lower().replace("@", "")

    query = """
        SELECT m.*, u1.username as u1_name, u2.username as u2_name 
        FROM matches m
        JOIN players u1 ON m.p1_id = u1.tg_id
        JOIN players u2 ON m.p2_id = u2.tg_id
        WHERE m.tour_id = $1 AND m.status = 'pending'
        AND (
            (LOWER(u1.username) = $2 AND LOWER(u2.username) = $3) 
            OR 
            (LOWER(u1.username) = $3 AND LOWER(u2.username) = $2)
        )
        LIMIT 1;
    """
    async with pool.acquire() as conn:
        return await conn.fetchrow(query, tour_id, p1, p2)


async def _update_elo_and_stats(conn: asyncpg.Connection, p1_id: int, p2_id: int, s1: int, s2: int):
    """
    Внутренний пересчет Эло и статистики в рамках существующей транзакции.
    """
    p1 = await conn.fetchrow("SELECT elo FROM players WHERE tg_id = $1;", p1_id)
    p2 = await conn.fetchrow("SELECT elo FROM players WHERE tg_id = $1;", p2_id)

    if not p1 or not p2:
        return

    r1, r2 = p1["elo"], p2["elo"]

    expected_1 = 1 / (1 + math.pow(10, (r2 - r1) / 400))
    expected_2 = 1 / (1 + math.pow(10, (r1 - r2) / 400))

    actual_1 = 1.0 if s1 > s2 else (0.0 if s1 < s2 else 0.5)
    actual_2 = 1.0 - actual_1

    k = 32
    new_r1 = round(r1 + k * (actual_1 - expected_1))
    new_r2 = round(r2 + k * (actual_2 - expected_2))

    # Обновление первого игрока
    await conn.execute("""
        UPDATE players SET 
            elo = $1, 
            matches_played = matches_played + 1,
            wins = wins + $2, 
            losses = losses + $3, 
            draws = draws + $4
        WHERE tg_id = $5;
    """, new_r1, 1 if actual_1 == 1 else 0, 1 if actual_1 == 0 else 0, 1 if actual_1 == 0.5 else 0, p1_id)

    # Обновление второго игрока
    await conn.execute("""
        UPDATE players SET 
            elo = $1, 
            matches_played = matches_played + 1,
            wins = wins + $2, 
            losses = losses + $3, 
            draws = draws + $4
        WHERE tg_id = $5;
    """, new_r2, 1 if actual_2 == 1 else 0, 1 if actual_2 == 0 else 0, 1 if actual_2 == 0.5 else 0, p2_id)


async def register_match_result(match_id: int, p1_username_input: str, s1: int, s2: int) -> bool:
    """
    Транзакционная запись результата и пересчет рейтинга.
    В asyncpg изоляция транзакций отрабатывает мгновенно.
    """
    if not pool:
        return False

    clean_p1 = p1_username_input.lower().replace("@", "")

    async with pool.acquire() as conn:
        async with conn.transaction():
            query = """
                SELECT m.*, u1.username as u1_name, u2.username as u2_name 
                FROM matches m
                JOIN players u1 ON m.p1_id = u1.tg_id
                JOIN players u2 ON m.p2_id = u2.tg_id
                WHERE m.id = $1 FOR UPDATE;
            """
            match = await conn.fetchrow(query, match_id)

            if not match or match["status"] != "pending":
                return False

            # Распределение счета относительно записей p1/p2 в базе
            if match["u1_name"].lower() == clean_p1:
                final_s1, final_s2 = s1, s2
            else:
                final_s1, final_s2 = s2, s1

            # 1. Запись счета
            await conn.execute("""
                UPDATE matches 
                SET p1_score = $1, p2_score = $2, status = 'finished'
                WHERE id = $3;
            """, final_s1, final_s2, match_id)

            # 2. Обновление Elo и статистики
            await _update_elo_and_stats(conn, match["p1_id"], match["p2_id"], final_s1, final_s2)

            return True
