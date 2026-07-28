import asyncio
import signal

from telebot.async_telebot import AsyncTeleBot
from telebot import asyncio_filters
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import config

from database.database import get_repository
from database.postgres import PostgresRepository

from redis.redis_storage import RedisStorage

from services.elo_service import EloService
from services.user_service import UserService
from services.ranking_service import RankingService
from services.tournament_service import TournamentService
from services.bracket_service import BracketService
from services.swiss_service import SwissService
from services.match_service import MatchService
from services.result_service import ResultService
from services.dispute_service import DisputeService
from services.reminder_service import ReminderService

from utils.logger import bot_logger, error_logger
from utils.error_handler import GlobalErrorHandler
from utils.middlewares import AuthMiddleware


# ==================================================
# BOT CORE
# ==================================================

bot = AsyncTeleBot(
    config.BOT_TOKEN,
    parse_mode="HTML"
)


scheduler = AsyncIOScheduler()


# ==================================================
# DEPENDENCY CONTAINER
# ==================================================

class Container:

    database = None
    redis = None

    users = None
    tournament = None
    bracket = None
    swiss = None
    matches = None
    results = None
    disputes = None
    ranking = None
    elo = None
    reminders = None


services = Container()



# ==================================================
# DATABASE
# ==================================================

async def setup_database():

    if config.DB_TYPE.lower() == "postgres":

        services.database = PostgresRepository(
            config.POSTGRES_URL
        )

        await services.database.connect()

        bot_logger.info(
            "PostgreSQL connected"
        )


    else:

        services.database = get_repository(
            "json",
            config.JSON_DB_PATH
        )

        bot_logger.info(
            "JSON database enabled"
        )



# ==================================================
# REDIS
# ==================================================

async def setup_redis():

    services.redis = RedisStorage(
        config.REDIS_HOST,
        config.REDIS_PORT,
        config.REDIS_DB
    )

    bot_logger.info(
        "Redis initialized"
    )



# ==================================================
# SERVICES
# ==================================================

def setup_services():

    services.elo = EloService()


    services.users = UserService(
        services.database
    )


    services.ranking = RankingService(
        services.database,
        services.elo
    )


    services.bracket = BracketService(
        services.database
    )


    services.swiss = SwissService(
        services.database
    )


    services.tournament = TournamentService(
        services.database,
        services.bracket,
        services.swiss
    )


    services.matches = MatchService(
        services.database,
        services.ranking,
        services.bracket
    )


    services.results = ResultService(
        services.matches
    )


    services.disputes = DisputeService(
        services.database
    )


    services.reminders = ReminderService(
        bot,
        services.database
    )


    bot_logger.info(
        "Services initialized"
    )



# ==================================================
# HANDLERS
# ==================================================

def setup_handlers():

    from handlers.admin import register_admin_handlers
    from handlers.players import register_player_handlers
    from handlers.tournaments import register_tournament_handlers
    from handlers.matches import register_match_handlers
    from handlers.callbacks import register_callback_handlers
    from handlers.disputes import register_dispute_handlers
    from handlers.rankings import register_ranking_handlers


    register_admin_handlers(
        bot,
        services
    )


    register_player_handlers(
        bot,
        services
    )


    register_tournament_handlers(
        bot,
        services
    )


    register_match_handlers(
        bot,
        services
    )


    register_callback_handlers(
        bot,
        services
    )


    register_dispute_handlers(
        bot,
        services
    )


    register_ranking_handlers(
        bot,
        services
    )


    bot_logger.info(
        "Handlers loaded"
    )



# ==================================================
# MIDDLEWARE + FILTERS
# ==================================================

def setup_middlewares():


    bot.setup_middleware(
        AuthMiddleware()
    )


    bot.add_custom_filter(
        asyncio_filters.StateFilter(bot)
    )


    bot_logger.info(
        "Middlewares loaded"
    )



# ==================================================
# TASKS
# ==================================================

def setup_scheduler():

    scheduler.add_job(
        services.reminders.check_deadlines,
        "interval",
        seconds=60
    )


    scheduler.start()


    bot_logger.info(
        "Scheduler started"
    )



# ==================================================
# STARTUP
# ==================================================

async def startup():

    bot.exception_handler = GlobalErrorHandler(
        bot
    )


    await setup_database()

    await setup_redis()

    setup_services()

    setup_middlewares()

    setup_handlers()

    setup_scheduler()


    bot_logger.info(
        "🔥 Tournament Engine ONLINE"
    )



# ==================================================
# SHUTDOWN
# ==================================================

async def shutdown():

    bot_logger.info(
        "Shutdown started"
    )


    scheduler.shutdown(
        wait=False
    )


    if services.redis:

        await services.redis.close()


    if isinstance(
        services.database,
        PostgresRepository
    ):

        await services.database.disconnect()


    bot_logger.info(
        "Shutdown completed"
    )



# ==================================================
# MAIN
# ==================================================

async def main():

    await startup()


    try:

        await bot.polling(
            non_stop=True,
            request_timeout=120
        )


    except Exception as error:

        error_logger.exception(
            error
        )


    finally:

        await shutdown()



if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        pass
