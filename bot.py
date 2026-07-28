import asyncio
import signal
import sys

from telebot.async_telebot import AsyncTeleBot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import config

from utils.logger import (
    bot_logger,
    error_logger
)

from database.database import get_repository

from database.postgres import PostgresRepository

from redis.redis_storage import RedisStorage


# =====================================
# BOT INSTANCE
# =====================================

bot = AsyncTeleBot(
    config.BOT_TOKEN
)


# =====================================
# STORAGE
# =====================================

redis_storage = RedisStorage(
    host=config.REDIS_HOST,
    port=config.REDIS_PORT,
    db=config.REDIS_DB
)


# =====================================
# DATABASE
# =====================================

if config.DB_TYPE.lower() == "postgres":

    database = PostgresRepository(
        config.POSTGRES_URL
    )

else:

    database = get_repository(
        "json",
        config.JSON_DB_PATH
    )



# =====================================
# SCHEDULER
# =====================================

scheduler = AsyncIOScheduler()



# =====================================
# SERVICES CONTAINER
# =====================================

class Container:
    """
    Центральное хранилище зависимостей.
    Все handlers/services получают отсюда
    нужные объекты.
    """


    db = database

    redis = redis_storage

    scheduler = scheduler



container = Container()



# =====================================
# HANDLERS LOADER
# =====================================

def register_handlers():

    """
    Здесь подключаются все Telegram handlers.

    Когда создадим:
    handlers/admin.py
    handlers/tournaments.py
    handlers/matches.py

    просто добавим импорт сюда.
    """


    try:

        from handlers.admin import register_admin_handlers

        register_admin_handlers(
            bot,
            container
        )


    except ImportError:

        bot_logger.warning(
            "Admin handlers not found"
        )



    try:

        from handlers.players import register_player_handlers

        register_player_handlers(
            bot,
            container
        )


    except ImportError:

        bot_logger.warning(
            "Player handlers not found"
        )



    try:

        from handlers.tournaments import register_tournament_handlers

        register_tournament_handlers(
            bot,
            container
        )


    except ImportError:

        bot_logger.warning(
            "Tournament handlers not found"
        )



    try:

        from handlers.matches import register_match_handlers

        register_match_handlers(
            bot,
            container
        )


    except ImportError:

        bot_logger.warning(
            "Match handlers not found"
        )



# =====================================
# BASIC COMMANDS
# =====================================


@bot.message_handler(
    commands=["start"]
)
async def start(message):

    await bot.reply_to(
        message,
        (
            "🏆 Tournament Engine запущен\n\n"
            "Используйте /help"
        )
    )



@bot.message_handler(
    commands=["help"]
)
async def help_command(message):

    await bot.reply_to(
        message,
        (
            "🤖 Команды:\n\n"
            "/profile — профиль\n"
            "/rank — рейтинг\n"
            "/tournaments — турниры"
        )
    )



# =====================================
# STARTUP
# =====================================


async def startup():


    bot_logger.info(
        "Starting Tournament Engine..."
    )


    # PostgreSQL

    if isinstance(
        database,
        PostgresRepository
    ):

        await database.connect()

        bot_logger.info(
            "PostgreSQL connected"
        )


    else:

        bot_logger.info(
            "JSON Database enabled"
        )



    # Redis

    redis_ok = await redis_storage.ping()


    if redis_ok:

        bot_logger.info(
            "Redis connected"
        )

    else:

        error_logger.error(
            "Redis unavailable"
        )



    # Handlers

    register_handlers()


    # Scheduler

    scheduler.start()


    bot_logger.info(
        "Scheduler started"
    )



    bot_logger.info(
        "Bot initialization complete"
    )



# =====================================
# SHUTDOWN
# =====================================


async def shutdown():


    bot_logger.info(
        "Shutdown started..."
    )


    try:

        scheduler.shutdown()


    except Exception:
        pass



    try:

        await redis_storage.close()


    except Exception:
        pass



    if isinstance(
        database,
        PostgresRepository
    ):

        await database.disconnect()



    bot_logger.info(
        "Shutdown completed"
    )



# =====================================
# SIGNALS
# =====================================


def setup_signals(loop):


    async def stop():

        await shutdown()

        loop.stop()



    for sig in (
        signal.SIGINT,
        signal.SIGTERM
    ):

        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(stop())
        )



# =====================================
# MAIN
# =====================================


async def main():


    await startup()


    loop = asyncio.get_running_loop()


    setup_signals(
        loop
    )


    try:

        bot_logger.info(
            "Polling started"
        )


        await bot.infinity_polling(
            timeout=90,
            request_timeout=90
        )


    except Exception as e:


        error_logger.exception(
            f"Polling error: {e}"
        )


    finally:

        await shutdown()



if __name__ == "__main__":


    try:

        asyncio.run(
            main()
        )


    except KeyboardInterrupt:


        sys.exit(0)
