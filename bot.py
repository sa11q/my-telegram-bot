import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

# Импорты из наших будущих модулей
from database import init_db, close_db
from players import players_router
from admin import admin_router
from scheduler import start_scheduler, stop_scheduler

# Импорт Middleware для мультиязычности (RU, KZ, UZ, EN)
from middlewares.i18n import I18nMiddleware

# ==========================================
# ОСНОВНЫЕ НАСТРОЙКИ
# ==========================================
# Твой рабочий токен
BOT_TOKEN = "8876079721:AAHWW6G5nTcbk06C_sN5P-OzqkWpqlx5PBI"

# Впиши сюда свой ID (можно узнать через @userinfobot)
ADMIN_IDS = [123456789] 

# ==========================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ==========================================
def setup_logging():
    """Создает папку логов и настраивает ротацию файлов"""
    if not os.path.exists("logs"):
        os.makedirs("logs")
        
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RotatingFileHandler(
                "logs/bot.log", 
                maxBytes=5_000_000, 
                backupCount=5, 
                encoding="utf-8"
            ),
            logging.StreamHandler()
        ]
    )

logger = logging.getLogger(__name__)

# ==========================================
# ЖИЗНЕННЫЙ ЦИКЛ БОТА
# ==========================================
async def on_startup(bot: Bot):
    """Выполняется при запуске бота"""
    logger.info("Инициализация базы данных SQLite...")
    await init_db()
    
    logger.info("Запуск фонового планировщика (дедлайны)...")
    await start_scheduler(bot)
    
    logger.info("Бот успешно запущен!")
    
    # Уведомление админов о запуске
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, "✅ Система турниров успешно запущена!")
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление админу {admin_id}: {e}")

async def on_shutdown(bot: Bot):
    """Выполняется перед выключением бота"""
    logger.info("Остановка планировщика дедлайнов...")
    await stop_scheduler()
    
    logger.info("Закрытие соединений с базой данных...")
    await close_db()
    
    logger.info("Бот корректно остановлен.")

# ==========================================
# ГЛАВНАЯ ФУНКЦИЯ ЗАПУСКА
# ==========================================
async def main():
    setup_logging()
    
    bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
    dp = Dispatcher(storage=MemoryStorage())
    
    # РЕГИСТРАЦИЯ ПЕРЕВОДЧИКА (i18n)
    dp.update.middleware(I18nMiddleware())
    
    # Регистрация роутеров 
    dp.include_router(admin_router)
    dp.include_router(players_router)
    
    # Регистрация хуков жизненного цикла
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    await bot.delete_webhook(drop_pending_updates=True)
    
    logger.info("Запуск polling...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановка программы вручную (Ctrl+C).")
