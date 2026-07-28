import os
import sys
import time
import logging
import telebot

# =====================================================================
# КОНФИГУРАЦИЯ И ПУТИ
# =====================================================================
# Определяем абсолютный путь к директории, где лежит bot.py.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# Автоматически создаем папку для логов, если её не существует
os.makedirs(LOGS_DIR, exist_ok=True)

# Константы для задержек и таймаутов
RESTART_DELAY_SECONDS = 5
POLLING_TIMEOUT = 20
LONG_POLLING_TIMEOUT = 10

# =====================================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# =====================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOGS_DIR, "bot.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# =====================================================================
# ИНИЦИАЛИЗАЦИЯ БОТА
# =====================================================================
TOKEN = "8876079721:AAFMECzB5jkywB1J8ks66qgXg_YMzDMD6dU"
bot = telebot.TeleBot(TOKEN, parse_mode=None)

# =====================================================================
# ПОДКЛЮЧЕНИЕ ОБРАБОТЧИКОВ (HANDLERS)
# =====================================================================
_MODULES_IMPORTED = False
_HANDLERS_REGISTERED = False

try:
    from handlers.results import register_results_handlers
    from handlers.players import register_players_handlers
    from handlers.profile import register_profile_handlers
    from handlers.stats import register_stats_handlers
    from handlers.tournament import register_tournament_handlers
    from handlers.admin import register_admin_handlers
    
    _MODULES_IMPORTED = True
except ImportError as e:
    logger.error(f"Ошибка импорта модулей обработчиков: {e}")
    logger.info("Убедитесь, что все файлы в папке handlers созданы.")

def register_all_handlers(telebot_instance: telebot.TeleBot) -> None:
    """
    Регистрирует все обработчики сообщений и callback-ов.
    Защищена от повторного вызова.
    """
    global _HANDLERS_REGISTERED
    
    if _HANDLERS_REGISTERED:
        logger.warning("Обработчики уже зарегистрированы. Пропуск повторной регистрации.")
        return

    logger.info("Начало регистрации обработчиков (handlers)...")
    
    try:
        register_results_handlers(telebot_instance)
        register_players_handlers(telebot_instance)
        register_profile_handlers(telebot_instance)
        register_stats_handlers(telebot_instance)
        register_tournament_handlers(telebot_instance)
        register_admin_handlers(telebot_instance)
        
        _HANDLERS_REGISTERED = True
        
        registered_modules = [
            "handlers.results", 
            "handlers.players", 
            "handlers.profile",
            "handlers.stats", 
            "handlers.tournament", 
            "handlers.admin"
        ]
        logger.info(f"Все модули успешно зарегистрированы: {', '.join(registered_modules)}")
    except NameError as e:
        logger.error(f"Не удалось зарегистрировать обработчики из-за ошибки импорта: {e}")

# =====================================================================
# ЗАПУСК ПРИЛОЖЕНИЯ
# =====================================================================
def main():
    logger.info("===================================================")
    logger.info("=== Запуск приложения турнирного бота ===")
    logger.info(f"=== Время запуска: {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
    logger.info(f"=== Версия Python: {sys.version.split(' ')[0]} ===")
    logger.info("===================================================")
    
    # 1. Проверка успешности импорта модулей
    if not _MODULES_IMPORTED:
        logger.critical("КРИТИЧЕСКАЯ ОШИБКА: Не все модули были импортированы. Остановка запуска.")
        sys.exit(1)
        
    # 2. Проверка токена и доступности серверов Telegram
    logger.info("Проверка токена и подключения к Telegram...")
    try:
        bot_info = bot.get_me()
        logger.info(f"Подключение успешно! Бот авторизован как: @{bot_info.username} (ID: {bot_info.id})")
    except telebot.apihelper.ApiTelegramException as e:
        logger.critical(f"Ошибка API Telegram (возможно, неверный токен): {e}")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Не удалось подключиться к серверам Telegram: {e}", exc_info=True)
        sys.exit(1)
    
    # 3. Регистрация обработчиков
    register_all_handlers(bot)
    
    logger.info("Старт polling. Бот готов к приему сообщений...")
    
    # 4. Основной цикл polling с обработкой прерываний и ошибок
    while True:
        try:
            bot.infinity_polling(timeout=POLLING_TIMEOUT, long_polling_timeout=LONG_POLLING_TIMEOUT)
        except KeyboardInterrupt:
            # Корректное завершение при нажатии Ctrl+C
            logger.info("Получен сигнал остановки (KeyboardInterrupt). Завершение работы...")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Произошла непредвиденная ошибка в polling: {e}", exc_info=True)
            logger.info(f"Перезапуск polling через {RESTART_DELAY_SECONDS} секунд...")
            time.sleep(RESTART_DELAY_SECONDS)

if __name__ == '__main__':
    main()

