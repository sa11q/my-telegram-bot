import os
import json
import logging
import shutil
import tempfile
import threading
from copy import deepcopy
from typing import Dict, Any, Tuple, Optional

# =====================================================================
# КОНФИГУРАЦИЯ ЛОГИРОВАНИЯ
# =====================================================================
logger = logging.getLogger("database")

# =====================================================================
# КОНФИГУРАЦИЯ ПУТЕЙ И КОНСТАНТ
# =====================================================================
# Вычисляем абсолютные пути относительно текущего файла (database.py)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.json")
DB_BACKUP_FILE = os.path.join(BASE_DIR, "database_backup.json")

CURRENT_DB_VERSION = 1
JSON_INDENT = 4

# =====================================================================
# ПОТОКОБЕЗОПАСНОСТЬ
# =====================================================================
db_lock = threading.Lock()


# =====================================================================
# СТРУКТУРА БАЗЫ ПО УМОЛЧАНИЮ
# =====================================================================
def get_default_db() -> Dict[str, Any]:
    """
    Возвращает эталонную структуру базы данных.
    Рассчитана на масштабирование (турниры, статистика, ELO, админка и т.д.).
    """
    return {
        "database_version": CURRENT_DB_VERSION,
        "active_tournament": {
            "title": "Новый турнир",
            "mode": "solo",
            "registration_open": False,
            "registered_players": [],
            "banned_players": [],
            "stage": 1,
            "stage_name": "Не начат",
            "deadline": None,
            "reminder_sent": False,
            "chat_id": None,
            "teams": {},
            "matches": [],
            "history": [],
            "auto_next": True,
            "auto_deadline": True
        },
        "archived_tournaments": [],
        "champions": [],
        "stats": {
            "players": {}
        },
        "settings": {
            "admins": []
        }
    }


# =====================================================================
# ВАЛИДАЦИЯ И МИГРАЦИИ
# =====================================================================
def _update_dict_recursively(base: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """
    Рекурсивно обновляет target-словарь недостающими ключами из base.
    Возвращает True, если были внесены изменения.
    """
    changed = False
    for key, value in base.items():
        if key not in target:
            target[key] = deepcopy(value)
            changed = True
            logger.info(f"Миграция: Добавлен новый ключ '{key}' в базу данных.")
        elif isinstance(value, dict) and isinstance(target[key], dict):
            if _update_dict_recursively(value, target[key]):
                changed = True
    return changed


def validate_database(data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """
    Проверяет целостность базы данных и автоматически добавляет новые поля.
    """
    logger.info("Начало валидации базы данных...")
    default_schema = get_default_db()
    is_changed = False

    # 1. Проверка и обновление версии базы данных
    if data.get("database_version", 0) < CURRENT_DB_VERSION:
        logger.info(f"Обновление версии БД: {data.get('database_version')} -> {CURRENT_DB_VERSION}")
        data["database_version"] = CURRENT_DB_VERSION
        is_changed = True

    # 2. Рекурсивное восстановление недостающих ключей
    if _update_dict_recursively(default_schema, data):
        is_changed = True

    if is_changed:
        logger.info("Валидация выявила изменения структуры (проведена автоматическая миграция).")
    else:
        logger.info("Структура базы данных актуальна.")

    return data, is_changed


# =====================================================================
# РЕЗЕРВНОЕ КОПИРОВАНИЕ И ВОССТАНОВЛЕНИЕ
# =====================================================================
def backup_database() -> bool:
    """
    Создает резервную копию основной базы данных перед перезаписью.
    """
    if not os.path.exists(DB_FILE):
        return False
        
    try:
        shutil.copy2(DB_FILE, DB_BACKUP_FILE)
        logger.debug("Резервная копия базы данных успешно создана.")
        return True
    except Exception as e:
        logger.error(f"Критическая ошибка при создании резервной копии: {e}", exc_info=True)
        return False


def restore_backup() -> Optional[Dict[str, Any]]:
    """
    Пытается загрузить данные из резервной копии при повреждении основной базы.
    """
    if not os.path.exists(DB_BACKUP_FILE):
        logger.warning("Файл резервной копии отсутствует. Восстановление невозможно.")
        return None

    logger.info("Попытка восстановления из database_backup.json...")
    try:
        with open(DB_BACKUP_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info("База данных успешно восстановлена из резервной копии.")
        return data
    except Exception as e:
        logger.error(f"Не удалось восстановить базу из backup. Файл поврежден: {e}", exc_info=True)
        return None


# =====================================================================
# ИНИЦИАЛИЗАЦИЯ ФАЙЛОВ
# =====================================================================
def ensure_database_exists() -> None:
    """
    Проверяет наличие файлов базы и бекапа. Если их нет — создает эталонные.
    """
    if not os.path.exists(DB_FILE):
        logger.warning("database.json не найден. Создание новой чистой базы...")
        save_data_internal(get_default_db())

    if not os.path.exists(DB_BACKUP_FILE) and os.path.exists(DB_FILE):
        logger.info("database_backup.json не найден. Первичное создание бекапа...")
        backup_database()


# =====================================================================
# ЧТЕНИЕ И ЗАПИСЬ (CORE LOGIC)
# =====================================================================
def save_data_internal(data: Dict[str, Any]) -> None:
    """
    Атомарное сохранение данных. Исключает повреждение файла при сбоях питания.
    Не использует блокировки (вызывается из обертки).
    """
    try:
        # Создаем временный файл в той же директории
        fd, temp_path = tempfile.mkstemp(dir=BASE_DIR, suffix=".tmp", text=True)
        with os.fdopen(fd, 'w', encoding="utf-8") as tf:
            json.dump(data, tf, ensure_ascii=False, indent=JSON_INDENT)
        
        # Атомарная замена (переименование)
        os.replace(temp_path, DB_FILE)
        logger.debug("Изменения успешно записаны в database.json (атомарно).")
    except Exception as e:
        logger.error(f"Критическая ошибка файловой системы при сохранении: {e}", exc_info=True)
        # Очистка временного файла в случае ошибки
        if 'temp_path' in locals() and os.path.exists(temp_path):
            os.remove(temp_path)


def save_data() -> None:
    """
    Безопасное сохранение текущего состояния в файл.
    Включает потоковую блокировку и предварительный бекап.
    """
    global db
    with db_lock:
        logger.debug("Запрошено сохранение базы данных...")
        backup_database()
        save_data_internal(db)


def load_data() -> Dict[str, Any]:
    """
    Загружает базу данных в память. При необходимости выполняет восстановление,
    создание с нуля и миграцию структуры.
    """
    with db_lock:
        ensure_database_exists()
        data = None

        # 1. Попытка загрузить основную базу
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info("database.json успешно загружен в память.")
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON в основной базе: {e}")
        except Exception as e:
            logger.error(f"Непредвиденная ошибка чтения базы: {e}", exc_info=True)

        # 2. Если основная повреждена — загружаем backup
        if data is None:
            logger.warning("Основная база недоступна. Запуск процедуры восстановления...")
            data = restore_backup()

        # 3. Если backup тоже мертв — создаем с нуля
        if data is None:
            logger.critical("Обе базы (основная и backup) повреждены! Инициализация чистой БД.")
            data = get_default_db()

        # 4. Проверяем целостность структуры и обновляем при необходимости
        data, is_changed = validate_database(data)
        
        # Если были изменения структуры или восстановление — фиксируем на диск
        if is_changed or not os.path.exists(DB_FILE):
            logger.info("Сохранение обновленной/восстановленной базы на диск...")
            backup_database()
            save_data_internal(data)

        return data


# =====================================================================
# ИНИЦИАЛИЗАЦИЯ СОСТОЯНИЯ ПРИ ИМПОРТЕ
# =====================================================================
# Переменная db становится доступной сразу после `import database.database`
logger.info("Инициализация модуля database...")
db: Dict[str, Any] = load_data()

