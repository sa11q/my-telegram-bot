import time
import logging
import telebot
from telebot.types import Message, User, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from typing import Optional, Dict, Any

from database.database import db, save_data

# =====================================================================
# КОНФИГУРАЦИЯ ЛОГИРОВАНИЯ
# =====================================================================
logger = logging.getLogger("handlers.players")

# =====================================================================
# КОНСТАНТЫ
# =====================================================================
DEFAULT_LANG = "ru"
SUPPORTED_LANGS = ["ru", "kk", "uz", "en"]

# =====================================================================
# СЛОВАРЬ ПЕРЕВОДОВ (МУЛЬТИЯЗЫЧНОСТЬ)
# =====================================================================
TEXT: Dict[str, Dict[str, str]] = {
    "ru": {
        "choose_lang": "🌍 Выберите ваш язык / Тілді таңдаңыз / Tilni tanlang / Choose your language:",
        "lang_set": "✅ Язык успешно изменен на Русский!",
        "start": "👋 *Привет! Я турнирный бот.*\n\nЯ помогаю организовывать лиги и кубки, регистрировать игроков, собирать статистику и генерировать матчи.\n\nВведите /help, чтобы увидеть список доступных команд.",
        "help": "📜 *Список команд для игрока:*\n\n🔸 /join или `●` — Зарегистрироваться на турнир\n🔸 /unjoin — Отменить свою регистрацию\n🔸 /rules — Правила турнира\n🔸 /vs — Узнать своего текущего соперника\n🔸 /profile — Посмотреть свой профиль\n🔸 /language — Изменить язык интерфейса",
        "rules": "⚖️ *Правила наших турниров:*\n\n1. Соблюдайте уважение к соперникам в чате.\n2. Результаты матчей подтверждаются скриншотами.\n3. При отсутствии игрока более 15 минут после дедлайна — техническое поражение (ТП).\n4. Формат и количество участников регулируются администрацией.\n\n_Незнание правил не освобождает от ответственности._",
        "only_group": "⚠️ Эта команда доступна только в главном турнирном чате.",
        "no_username": "⚠️ Для участия в турнире и сохранения настроек у вас должен быть установлен @username в Telegram.",
        "reg_closed": "🛑 Регистрация на турнир в данный момент закрыта.",
        "banned": "⛔️ Доступ к турнирам ограничен (Вы находитесь в черном списке).",
        "already_reg": "✅ Вы уже зарегистрированы на текущий турнир!",
        "not_reg": "⚠️ Вы не зарегистрированы на текущий турнир.",
        "vs_plug": "⏳ Турнирная сетка еще формируется или матчи не сгенерированы.\nСледите за анонсами в группе!",
        "join_success": "✅ Игрок {username} успешно зарегистрирован!\n👥 Всего участников: *{count}*",
        "unjoin_success": "🚪 Игрок {username} отменил регистрацию.\n👥 Осталось участников: *{count}*"
    },
    "kk": {
        "choose_lang": "🌍 Тілді таңдаңыз:",
        "lang_set": "✅ Тіл сәтті Қазақша болып өзгертілді!",
        "start": "👋 *Сәлем! Мен турнир ботымын.*\n\nМен лигалар мен кубоктарды ұйымдастыруға, ойыншыларды тіркеуге және матчтарды құруға көмектесемін.\n\nҚолжетімді командаларды көру үшін /help енгізіңіз.",
        "help": "📜 *Ойыншыларға арналған командалар:*\n\n🔸 /join немесе `●` — Турнирге тіркелу\n🔸 /unjoin — Тіркелуден бас тарту\n🔸 /rules — Турнир ережелері\n🔸 /vs — Қарсыласыңызды білу\n🔸 /profile — Профиліңізді көру\n🔸 /language — Тілді өзгерту",
        "rules": "⚖️ *Біздің турнир ережелері:*\n\n1. Чатта қарсыластарды құрметтеңіз.\n2. Матч нәтижелері скриншоттармен расталады.\n3. Дедлайннан кейін 15 минут жоқ болсаңыз — техникалық жеңіліс (ТП).\n4. Қатысушылар саны әкімшілікпен реттеледі.\n\n_Ережелерді білмеу жауапкершіліктен босатпайды._",
        "only_group": "⚠️ Бұл команда тек негізгі турнир чатында қолжетімді.",
        "no_username": "⚠️ Турнирге қатысу және баптауларды сақтау үшін Telegram-да @username орнатылуы керек.",
        "reg_closed": "🛑 Қазіргі уақытта турнирге тіркелу жабық.",
        "banned": "⛔️ Турнирлерге қатысу шектелген (Сіз қара тізімдесіз).",
        "already_reg": "✅ Сіз ағымдағы турнирге тіркеліп қойғансыз!",
        "not_reg": "⚠️ Сіз ағымдағы турнирге тіркелмегенсіз.",
        "vs_plug": "⏳ Турнир кестесі әлі құрылуда немесе матчтар жасалмаған.\nТоптағы хабарландыруларды қадағалаңыз!",
        "join_success": "✅ {username} ойыншысы сәтті тіркелді!\n👥 Барлық қатысушылар: *{count}*",
        "unjoin_success": "🚪 {username} ойыншысы тіркелуден бас тартты.\n👥 Қалған қатысушылар: *{count}*"
    },
    "uz": {
        "choose_lang": "🌍 Tilni tanlang:",
        "lang_set": "✅ Til muvaffaqiyatli O'zbekcha qilib o'zgartirildi!",
        "start": "👋 *Salom! Men turnir botiman.*\n\nMen ligalar va kuboklarni tashkil etish, o'yinchilarni ro'yxatdan o'tkazish, statistika yig'ish va o'yinlarni yaratishda yordam beraman.\n\nMavjud buyruqlarni ko'rish uchun /help ni bosing.",
        "help": "📜 *O'yinchilar uchun buyruqlar:*\n\n🔸 /join yoki `●` — Turnirga ro'yxatdan o'tish\n🔸 /unjoin — Ro'yxatdan o'tishni bekor qilish\n🔸 /rules — Turnir qoidalari\n🔸 /vs — Raqibingizni bilish\n🔸 /profile — Profilni ko'rish\n🔸 /language — Tilni o'zgartirish",
        "rules": "⚖️ *Bizning turnir qoidalari:*\n\n1. Chatda raqiblarni hurmat qiling.\n2. O'yin natijalari skrinshotlar bilan tasdiqlanadi.\n3. Dedlayndan keyin 15 daqiqa yo'q bo'lsangiz — texnik mag'lubiyat (TM).\n4. Ishtirokchilar soni ma'muriyat tomonidan tartibga solinadi.\n\n_Qoidalarni bilmaslik javobgarlikdan ozod etmaydi._",
        "only_group": "⚠️ Bu buyruq faqat asosiy turnir chatida ishlaydi.",
        "no_username": "⚠️ Turnirda qatnashish va sozlamalarni saqlash uchun Telegram'da @username o'rnatilgan bo'lishi kerak.",
        "reg_closed": "🛑 Hozirgi vaqtda turnirga ro'yxatdan o'tish yopiq.",
        "banned": "⛔️ Turnirlarga kirish cheklangan (Siz qora ro'yxatdasiz).",
        "already_reg": "✅ Siz joriy turnirga ro'yxatdan o'tgansiz!",
        "not_reg": "⚠️ Siz joriy turnirga ro'yxatdan o'tmagansiz.",
        "vs_plug": "⏳ Turnir jadvali hali shakllanmoqda yoki o'yinlar yaratilmagan.\nChatdagi e'lonlarni kuzatib boring!",
        "join_success": "✅ {username} o'yinchisi muvaffaqiyatli ro'yxatdan o'tdi!\n👥 Jami ishtirokchilar: *{count}*",
        "unjoin_success": "🚪 {username} o'yinchisi ro'yxatdan o'tishni bekor qildi.\n👥 Qolgan ishtirokchilar: *{count}*"
    },
    "en": {
        "choose_lang": "🌍 Choose your language:",
        "lang_set": "✅ Language successfully changed to English!",
        "start": "👋 *Hello! I am a tournament bot.*\n\nI help organize leagues and cups, register players, collect statistics, and generate matches.\n\nType /help to see the list of available commands.",
        "help": "📜 *List of commands for player:*\n\n🔸 /join or `●` — Register for the tournament\n🔸 /unjoin — Cancel your registration\n🔸 /rules — Tournament rules\n🔸 /vs — Find out your current opponent\n🔸 /profile — View your profile\n🔸 /language — Change interface language",
        "rules": "⚖️ *Our tournament rules:*\n\n1. Respect your opponents in the chat.\n2. Match results are confirmed by screenshots.\n3. Absence for more than 15 minutes after the deadline — technical defeat (TD).\n4. The format and number of participants are regulated by administration.\n\n_Ignorance of the rules does not excuse you from responsibility._",
        "only_group": "⚠️ This command is only available in the main tournament chat.",
        "no_username": "⚠️ You must have a @username in Telegram to participate and save settings.",
        "reg_closed": "🛑 Registration for the tournament is currently closed.",
        "banned": "⛔️ Access to tournaments is restricted (You are blacklisted).",
        "already_reg": "✅ You are already registered for the current tournament!",
        "not_reg": "⚠️ You are not registered for the current tournament.",
        "vs_plug": "⏳ The tournament bracket is still being formed or matches are not generated.\nFollow the announcements in the group!",
        "join_success": "✅ Player {username} successfully registered!\n👥 Total participants: *{count}*",
        "unjoin_success": "🚪 Player {username} canceled registration.\n👥 Participants left: *{count}*"
    }
}

# =====================================================================
# РАБОТА С БАЗОЙ ДАННЫХ И СТРУКТУРОЙ ПОЛЬЗОВАТЕЛЕЙ
# =====================================================================
def ensure_db_structure() -> None:
    """Гарантирует наличие всех необходимых веток в структуре базы данных."""
    if "users" not in db:
        db["users"] = {}
    
    if "active_tournament" not in db:
        db["active_tournament"] = {}
    
    tour = db["active_tournament"]
    if "registered_players" not in tour:
        tour["registered_players"] = []
    if "banned_players" not in tour:
        tour["banned_players"] = []
    if "registration_time" not in tour:
        tour["registration_time"] = {}

def ensure_user_node(username: str) -> None:
    """Создает расширяемую ветку пользователя, если её еще нет."""
    ensure_db_structure()
    if username not in db["users"]:
        db["users"][username] = {
            "language": DEFAULT_LANG,
            "notifications": True,
            "rating": 1200,
            "last_active": int(time.time())
        }

def get_user_language(username: Optional[str]) -> str:
    """Возвращает текущий язык игрока из базы данных."""
    if not username:
        return DEFAULT_LANG
    ensure_db_structure()
    if username in db["users"] and "language" in db["users"][username]:
        lang = db["users"][username]["language"]
        if lang in SUPPORTED_LANGS:
            return lang
    return DEFAULT_LANG

def set_user_language(username: str, language: str) -> None:
    """Устанавливает и сохраняет новый язык для пользователя."""
    if not username or language not in SUPPORTED_LANGS:
        return
    ensure_user_node(username)
    db["users"][username]["language"] = language
    save_data()
    logger.info(f"Игрок {username} сменил язык на: {language.upper()}")

def get_text(username: Optional[str], key: str, **kwargs: Any) -> str:
    """
    Централизованная функция получения перевода текста для пользователя.
    Доступна для использования из любых других модулей проекта.
    """
    lang = get_user_language(username)
    text_template = TEXT.get(lang, TEXT[DEFAULT_LANG]).get(key, TEXT[DEFAULT_LANG].get(key, "TEXT_NOT_FOUND"))
    
    if kwargs:
        return text_template.format(**kwargs)
    return text_template

# =====================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И ПРОВЕРКИ
# =====================================================================
def is_group(message: Message) -> bool:
    """Проверяет, отправлено ли сообщение в групповом чате."""
    return message.chat.type in ['group', 'supergroup']

def normalize_username(user: User) -> Optional[str]:
    """Возвращает отформатированный @username или None при его отсутствии."""
    if user.username:
        return f"@{user.username}"
    return None

def registration_open() -> bool:
    """Проверяет статус открытой регистрации на активный турнир."""
    ensure_db_structure()
    return db["active_tournament"].get("registration_open", False)

def player_banned(username: str) -> bool:
    """Проверяет, находится ли игрок в черном списке."""
    if not username:
        return False
    ensure_db_structure()
    return username in db["active_tournament"]["banned_players"]

def player_registered(username: str) -> bool:
    """Проверяет, зарегистрирован ли пользователь в текущем турнире."""
    if not username:
        return False
    ensure_db_structure()
    return username in db["active_tournament"]["registered_players"]

def get_lang_keyboard() -> InlineKeyboardMarkup:
    """Генерирует мультиязычную Inline-клавиатуру для выбора языка."""
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
        InlineKeyboardButton("🇰🇿 Қазақша", callback_data="lang_kk")
    )
    markup.row(
        InlineKeyboardButton("🇺🇿 O’zbekcha", callback_data="lang_uz"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
    )
    return markup

# =====================================================================
# ОБРАБОТЧИКИ (HANDLERS)
# =====================================================================
def register_players_handlers(bot: telebot.TeleBot) -> None:
    """Регистрирует все хендлеры игроков и системы локализации."""
    logger.info("Регистрация мультиязычных обработчиков модуля players...")

    @bot.message_handler(commands=['start'])
    def cmd_start(message: Message):
        """Обработчик команды /start с первичным выбором языка при необходимости."""
        username = normalize_username(message.from_user)
        ensure_db_structure()

        if not username:
            bot.reply_to(message, TEXT[DEFAULT_LANG]["no_username"])
            return

        ensure_user_node(username)
        
        # Если язык еще не зафиксирован или пользователь новый — принудительно запрашиваем язык
        if username not in db["users"] or "language" not in db["users"][username]:
            bot.reply_to(message, TEXT[DEFAULT_LANG]["choose_lang"], reply_markup=get_lang_keyboard())
            return

        bot.reply_to(message, get_text(username, "start"), parse_mode="Markdown")

    @bot.message_handler(commands=['language', 'lang'])
    def cmd_language(message: Message):
        """Команда для смены языка интерфейса на лету."""
        username = normalize_username(message.from_user)
        if not username:
            bot.reply_to(message, TEXT[DEFAULT_LANG]["no_username"])
            return
            
        ensure_user_node(username)
        bot.reply_to(message, get_text(username, "choose_lang"), reply_markup=get_lang_keyboard())
        logger.debug(f"Игрок {username} открыл меню смены языка.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('lang_'))
    def callback_lang(call: CallbackQuery):
        """Обработка нажатия на инлайн-кнопки выбора языка."""
        username = normalize_username(call.from_user)
        if not username:
            bot.answer_callback_query(call.id, TEXT[DEFAULT_LANG]["no_username"], show_alert=True)
            return

        selected_lang = call.data.split('_')[1]
        if selected_lang in SUPPORTED_LANGS:
            set_user_language(username, selected_lang)
            
            try:
                # Удаляем инлайн-клавиатуру и отправляем приветствие на новом языке
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=get_text(username, "lang_set") + "\n\n" + get_text(username, "start"),
                    parse_mode="Markdown"
                )
            except Exception:
                # Если сообщение старое или не может быть отредактировано, отправляем новым
                bot.send_message(
                    call.message.chat.id,
                    get_text(username, "lang_set") + "\n\n" + get_text(username, "start"),
                    parse_mode="Markdown"
                )
                
            bot.answer_callback_query(call.id, get_text(username, "lang_set"))
            logger.info(f"Пользователь {username} успешно выбрал язык: {selected_lang}")

    @bot.message_handler(commands=['help'])
    def cmd_help(message: Message):
        """Вывод справки по командам на языке пользователя."""
        username = normalize_username(message.from_user)
        bot.reply_to(message, get_text(username, "help"), parse_mode="Markdown")

    @bot.message_handler(commands=['rules'])
    def cmd_rules(message: Message):
        """Вывод правил турнира на языке пользователя."""
        username = normalize_username(message.from_user)
        bot.reply_to(message, get_text(username, "rules"), parse_mode="Markdown")

    @bot.message_handler(commands=['vs'])
    def cmd_vs(message: Message):
        """Заглушка команды /vs с мультиязычными проверками."""
        username = normalize_username(message.from_user)
        if not username:
            bot.reply_to(message, get_text(None, "no_username"))
            return
            
        if not player_registered(username):
            bot.reply_to(message, get_text(username, "not_reg"))
            return

        bot.reply_to(message, get_text(username, "vs_plug"), parse_mode="Markdown")

    @bot.message_handler(commands=['join'])
    @bot.message_handler(func=lambda msg: msg.text and msg.text.strip() == '●')
    def cmd_join(message: Message):
        """Регистрация игрока в турнире с комплексными проверками и мультиязычностью."""
        username = normalize_username(message.from_user)
        
        if not is_group(message):
            bot.reply_to(message, get_text(username, "only_group"))
            return
            
        if not username:
            bot.reply_to(message, get_text(None, "no_username"))
            return
            
        if not registration_open():
            bot.reply_to(message, get_text(username, "reg_closed"))
            return
            
        if player_banned(username):
            bot.reply_to(message, get_text(username, "banned"))
            logger.warning(f"Забаненный игрок {username} попытался зарегистрироваться.")
            return
            
        if player_registered(username):
            bot.reply_to(message, get_text(username, "already_reg"))
            return

        try:
            ensure_db_structure()
            ensure_user_node(username)
            
            tour = db["active_tournament"]
            tour["registered_players"].append(username)
            tour["chat_id"] = message.chat.id
            tour["registration_time"][username] = int(time.time())
            
            save_data()
            
            players_count = len(tour["registered_players"])
            success_msg = get_text(username, "join_success", username=username, count=players_count)
            
            bot.reply_to(message, success_msg, parse_mode="Markdown")
            logger.info(f"Игрок {username} успешно зарегистрирован. Всего участников: {players_count}")
            
        except Exception as e:
            logger.error(f"Ошибка при регистрации игрока {username}: {e}", exc_info=True)
            bot.reply_to(message, "❌ Internal database error.")

    @bot.message_handler(commands=['unjoin'])
    def cmd_unjoin(message: Message):
        """Отмена регистрации участника с мультиязычным откликом."""
        username = normalize_username(message.from_user)
        
        if not is_group(message):
            bot.reply_to(message, get_text(username, "only_group"))
            return
            
        if not username:
            bot.reply_to(message, get_text(None, "no_username"))
            return
            
        if not registration_open():
            bot.reply_to(message, get_text(username, "reg_closed"))
            return
            
        if not player_registered(username):
            bot.reply_to(message, get_text(username, "not_reg"))
            return

        try:
            ensure_db_structure()
            tour = db["active_tournament"]
            tour["registered_players"].remove(username)
            
            if username in tour["registration_time"]:
                del tour["registration_time"][username]
                
            save_data()
            
            players_count = len(tour["registered_players"])
            unjoin_msg = get_text(username, "unjoin_success", username=username, count=players_count)
            
            bot.reply_to(message, unjoin_msg, parse_mode="Markdown")
            logger.info(f"Игрок {username} отменил регистрацию. Осталось участников: {players_count}")
            
        except ValueError:
            logger.error(f"Попытка удаления отсутствующего игрока {username} из списка.")
        except Exception as e:
            logger.error(f"Ошибка при отмене регистрации игрока {username}: {e}", exc_info=True)
            bot.reply_to(message, "❌ Internal database error.")

