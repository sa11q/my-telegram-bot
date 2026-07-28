import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

# Импорты из наших будущих модулей
from config import BOT_TOKEN, ADMIN_IDS
from database import init_db, close_db
from players import players_router
from admin import admin_router
from scheduler import start_scheduler, stop_scheduler

# ==========================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ==========================================
def setup_logging():
    """Создает папку логов и настраивает ротацию файлов (максимум 5 файлов по 5 МБ)"""
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
            logging.StreamHandler() # Вывод логов в консоль
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
    
    # Уведомление админов о запуске (опционально)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, "✅ Система турниров успешно запущена и готова к работе!")
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление админу {admin_id}: {e}")

async def on_shutdown(bot: Bot):
    """Выполняется перед выключением бота (graceful shutdown)"""
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
    
    # Инициализация бота и диспетчера
    # parse_mode="HTML" позволяет использовать <b>, <i> и <code> в текстах
    bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
    
    # MemoryStorage используется для хранения состояний (FSM) в оперативной памяти
    dp = Dispatcher(storage=MemoryStorage())
    
    # Регистрация роутеров (разделение команд админа и игроков)
    dp.include_router(admin_router)
    dp.include_router(players_router)
    
    # Регистрация хуков жизненного цикла
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # Сбрасываем накопившиеся апдейты, чтобы бот не обрабатывал 
    # старые сообщения после перезапуска/обновления
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
