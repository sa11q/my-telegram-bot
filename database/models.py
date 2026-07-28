import logging
import asyncpg

logger = logging.getLogger(__name__)

async def init_db(pool: asyncpg.Pool):
    """
    Инициализация схемы базы данных. 
    Создает все необходимые таблицы, индексы и триггеры для турнирной системы.
    """
    async with pool.acquire() as conn:
        # 1. Таблица участников (игроков)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS players (
                tg_id BIGINT PRIMARY KEY,
                username VARCHAR(64) UNIQUE NOT NULL,
                elo INT DEFAULT 1200,
                wins INT DEFAULT 0,
                losses INT DEFAULT 0,
                draws INT DEFAULT 0,
                matches_played INT DEFAULT 0,
                language VARCHAR(10) DEFAULT 'ru',
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 2. Таблица турниров
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tournaments (
                id SERIAL PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                mode VARCHAR(32) DEFAULT 'swiss', -- swiss или knockout
                status VARCHAR(32) DEFAULT 'active', -- active, archived, finished
                is_active BOOLEAN DEFAULT TRUE,
                current_stage INT DEFAULT 1,
                stage_deadline TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 3. Таблица матчей
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS matches (
                id SERIAL PRIMARY KEY,
                tour_id INT REFERENCES tournaments(id) ON DELETE CASCADE,
                stage INT DEFAULT 1,
                p1_id BIGINT REFERENCES players(tg_id) ON DELETE CASCADE,
                p2_id BIGINT REFERENCES players(tg_id) ON DELETE CASCADE,
                p1_score INT DEFAULT 0,
                p2_score INT DEFAULT 0,
                status VARCHAR(32) DEFAULT 'pending', -- pending, finished
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # 4. Создание индексов для молниеносного поиска и производительности
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_players_elo ON players(elo DESC);
            CREATE INDEX IF NOT EXISTS idx_players_username ON players(LOWER(username));
            CREATE INDEX IF NOT EXISTS idx_matches_tour ON matches(tour_id);
            CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
        """)

    logger.info("✅ Все таблицы и индексы в базе данных успешно инициализированы!")
