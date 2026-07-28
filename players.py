import logging
import math
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command

from database import pool
from tournament_service import TournamentService

logger = logging.getLogger(__name__)
players_router = Router()

# ==========================================
# ВИЗУАЛЬНЫЕ РАНГИ И ГЕЙМИФИКАЦИЯ
# ==========================================

def get_player_rank(elo: int, lang: str = "ru") -> str:
    """Эксклюзивная система званий на основе Elo-рейтинга"""
    ranks = {
        "ru": [
            (2000, "👑 GOAT / Легенда киберспорта"),
            (1800, "💎 Элита мирового топ-100"),
            (1650, "🏆 Мастер спорта FC Mobile"),
            (1500, "⭐ Эксперт дивизиона"),
            (1350, "🔥 Профессионал"),
            (1200, "⚽ Игрок основы"),
            (0,    "🌱 Новичок академии")
        ],
        "kz": [
            (2000, "👑 GOAT / Киберспорт аңызы"),
            (1800, "💎 Әлемдік топ-100 элитасы"),
            (1650, "🏆 FC Mobile спорт шебері"),
            (1500, "⭐ Дивизион сарапшысы"),
            (1350, "🔥 Кәсіпқой"),
            (1200, "⚽ Негізгі құрам ойыншысы"),
            (0,    "🌱 Академия жаңадан келгені")
        ],
        "uz": [
            (2000, "👑 GOAT / Kibersport afsonasi"),
            (1800, "💎 Jahon top-100 elitasi"),
            (1650, "🏆 FC Mobile sport ustasi"),
            (1500, "⭐ Divizion eksperti"),
            (1350, "🔥 Professional"),
            (1200, "⚽ Asosiy tarkib o'yinchisi"),
            (0,    "🌱 Akademiya yangi o'yinchisi")
        ],
        "en": [
            (2000, "👑 GOAT / Cyber Esports Legend"),
            (1800, "💎 World Top-100 Elite"),
            (1650, "🏆 FC Mobile Master"),
            (1500, "⭐ Division Expert"),
            (1350, "🔥 Professional Player"),
            (1200, "⚽ Core Squad Member"),
            (0,    "🌱 Academy Newbie")
        ]
    }
    lang_ranks = ranks.get(lang, ranks["ru"])
    for threshold, title in lang_ranks:
        if elo >= threshold:
            return title
    return lang_ranks[-1][1]

# ==========================================
# УНИКАЛЬНЫЕ ИНТЕРАКТИВНЫЕ ПАНЕЛИ
# ==========================================

def get_main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Глубокая премиальная панель управления игрока"""
    buttons = {
        "ru": [
            [InlineKeyboardButton(text="👤 Мой кибер-профиль", callback_data="pl_profile"), InlineKeyboardButton(text="⚔️ Мои матчи", callback_data="pl_my_matches")],
            [InlineKeyboardButton(text="🏆 Зал славы (Топ)", callback_data="pl_top"), InlineKeyboardButton(text="📊 Статистика", callback_data="pl_stats")],
            [InlineKeyboardButton(text="✍️ Как отправить счет", callback_data="pl_help_score"), InlineKeyboardButton(text="🌐 Язык / Language", callback_data="pl_lang")]
        ],
        "kz": [
            [InlineKeyboardButton(text="👤 Менің профилім", callback_data="pl_profile"), InlineKeyboardButton(text="⚔️ Менің матчтарым", callback_data="pl_my_matches")],
            [InlineKeyboardButton(text="🏆 Даңқ залы (Топ)", callback_data="pl_top"), InlineKeyboardButton(text="📊 Статистика", callback_data="pl_stats")],
            [InlineKeyboardButton(text="✍️ Есепті қалай жіберу", callback_data="pl_help_score"), InlineKeyboardButton(text="🌐 Тіл / Тіл", callback_data="pl_lang")]
        ],
        "uz": [
            [InlineKeyboardButton(text="👤 Mening profilim", callback_data="pl_profile"), InlineKeyboardButton(text="⚔️ Mening o'yinlarim", callback_data="pl_my_matches")],
            [InlineKeyboardButton(text="🏆 Shon-sharaf zali (Top)", callback_data="pl_top"), InlineKeyboardButton(text="📊 Statistika", callback_data="pl_stats")],
            [InlineKeyboardButton(text="✍️ Hisobni kiritish", callback_data="pl_help_score"), InlineKeyboardButton(text="🌐 Til / Language", callback_data="pl_lang")]
        ],
        "en": [
            [InlineKeyboardButton(text="👤 Cyber Profile", callback_data="pl_profile"), InlineKeyboardButton(text="⚔️ My Matches", callback_data="pl_my_matches")],
            [InlineKeyboardButton(text="🏆 Hall of Fame (Top)", callback_data="pl_top"), InlineKeyboardButton(text="📊 Performance", callback_data="pl_stats")],
            [InlineKeyboardButton(text="✍️ How to Submit Score", callback_data="pl_help_score"), InlineKeyboardButton(text="🌐 Language", callback_data="pl_lang")]
        ]
    }
    return InlineKeyboardMarkup(inline_keyboard=buttons.get(lang, buttons["ru"]))

def get_languages_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru"),
            InlineKeyboardButton(text="🇰🇿 Қазақша", callback_data="set_lang_kz")
        ],
        [
            InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="set_lang_uz"),
            InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")
        ]
    ])

# ==========================================
# СТАРТ И АВТОМАТИЧЕСКАЯ ИДЕНТИФИКАЦИЯ
# ==========================================

@players_router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    if not pool:
        return

    async with pool.acquire() as conn:
        clean_username = (user.username or f"player_{user.id}").lower().replace("@", "")
        # Upsert с фиксацией первого визита
        await conn.execute("""
            INSERT INTO players (tg_id, username) 
            VALUES ($1, $2)
            ON CONFLICT (tg_id) DO UPDATE SET username = EXCLUDED.username;
        """, user.id, clean_username)

        row = await conn.fetchrow("SELECT language FROM players WHERE tg_id = $1;", user.id)
        lang = row["language"] if row and row["language"] in ["ru", "kz", "uz", "en"] else "ru"

    greetings = {
        "ru": f"🎮 <b>Добро пожаловать в киберспортивную экосистему FC Mobile, {user.first_name}!</b>\n\nТвоя учетная запись успешно синхронизирована с базой данных.\nВыбери нужный раздел в панели ниже:",
        "kz": f"🎮 <b>FC Mobile киберспорт жүйесіне қош келдіңіз, {user.first_name}!</b>\n\nТіркелгіңіз деректер қорымен сәтті синхрондалды.\nТөменгі панельден қажетті бөлімді таңдаңыз:",
        "uz": f"🎮 <b>FC Mobile kibersport tizimiga xush kelibsiz, {user.first_name}!</b>\n\nHisobingiz ma'lumotlar bazasi bilan muvaffaqiyatli sinxronlandi.\nQuyidagi panel kerakli bo'limni tanlang:",
        "en": f"🎮 <b>Welcome to the FC Mobile esports ecosystem, {user.first_name}!</b>\n\nYour account has been successfully synchronized.\nChoose an option from the control panel below:"
    }

    await message.answer(greetings.get(lang, greetings["ru"]), reply_markup=get_main_menu_keyboard(lang))

@players_router.callback_query(F.data == "pl_lang")
async def cb_open_language(callback: CallbackQuery):
    lang = await TournamentService.get_player_language(callback.from_user.id)
    texts = {
        "ru": "🌐 <b>Выбор языка системы:</b>\nВыберите удобный для вас язык интерфейса:",
        "kz": "🌐 <b>Жүйе тілін таңдау:</b>\nӨзіңізге ыңғайлы тілді таңдаңыз:",
        "uz": "🌐 <b>Tizim tilini tanlash:</b>\nO'zingizga qulay tilni tanlang:",
        "en": "🌐 <b>System Language Selection:</b>\nChoose your preferred interface language:"
    }
    await callback.message.edit_text(texts.get(lang, texts["ru"]), reply_markup=get_languages_keyboard())
    await callback.answer()

@players_router.callback_query(F.data.startswith("set_lang_"))
async def cb_set_language(callback: CallbackQuery):
    new_lang = callback.data.split("_")[2]
    if new_lang not in ["ru", "kz", "uz", "en"]:
        return

    async with pool.acquire() as conn:
        await conn.execute("UPDATE players SET language = $1 WHERE tg_id = $2;", new_lang, callback.from_user.id)

    success_texts = {
        "ru": "✅ Язык успешно изменен!",
        "kz": "✅ Тіл сәтті өзгертілді!",
        "uz": "✅ Til muvaffaqiyatli o'zgartirildi!",
        "en": "✅ Language successfully updated!"
    }
    await callback.answer(success_texts.get(new_lang, success_texts["ru"]), show_alert=True)
    
    # Возвращаем в обновленное меню
    menu_headers = {
        "ru": "🏠 Главное меню киберспортивной системы:",
        "kz": "🏠 Киберспорт жүйесінің бас мәзірі:",
        "uz": "🏠 Kibersport tizimining bosh menyusi:",
        "en": "🏠 Esports system main menu:"
    }
    await callback.message.edit_text(menu_headers.get(new_lang, menu_headers["ru"]), reply_markup=get_main_menu_keyboard(new_lang))

# ==========================================
# ИНТЕРАКТИВНЫЙ ПРОФИЛЬ С РАНГОМ
# ==========================================

@players_router.callback_query(F.data == "pl_profile")
async def cb_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = await TournamentService.get_player_language(user_id)

    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT * FROM players WHERE tg_id = $1;", user_id)

    if not p:
        await callback.answer("Profile sync error.", show_alert=True)
        return

    total = p["matches_played"]
    wins = p["wins"]
    losses = p["losses"]
    draws = p["draws"]
    elo = p["elo"]
    rank_title = get_player_rank(elo, lang)
    winrate = round((wins / total * 100) if total > 0 else 0.0, 1)

    cards = {
        "ru": (
            f"👤 <b>ЭЛЕКТРОННЫЙ ПАСПОРТ КИБЕРСПОРТСМЕНА</b>\n"
            f"──────────────────────────────\n"
            f"• Никнейм: <code>@{p['username']}</code>\n"
            f"• Текущий ранг: <b>{rank_title}</b>\n"
            f"• Рейтинг Elo: <b>{elo} PTS</b>\n"
            f"──────────────────────────────\n"
            f"📈 <b>Боевая статистика:</b>\n"
            f"• Всего матчей: <b>{total}</b>\n"
            f"• Победы / Поражения / Ничьи: <b>{wins} / {losses} / {draws}</b>\n"
            f"• Винрейт (Winrate): <b>{winrate}%</b>"
        ),
        "kz": (
            f"👤 <b>КИБЕРСПОРТШЫНЫҢ ЭЛЕКТРОНДЫҚ ПАСПОРТЫ</b>\n"
            f"──────────────────────────────\n"
            f"• Никнейм: <code>@{p['username']}</code>\n"
            f"• Ағымдағы ранг: <b>{rank_title}</b>\n"
            f"• Elo рейтингі: <b>{elo} PTS</b>\n"
            f"──────────────────────────────\n"
            f"📈 <b>Жекпе-жек статистикасы:</b>\n"
            f"• Барлық матчтар: <b>{total}</b>\n"
            f"• Жеңіс / Жеңіліс / Тең: <b>{wins} / {losses} / {draws}</b>\n"
            f"• Жеңіс пайызы (Winrate): <b>{winrate}%</b>"
        ),
        "uz": (
            f"👤 <b>KIBERSPORTCHI ELEKTRON PASPORTI</b>\n"
            f"──────────────────────────────\n"
            f"• Nikeym: <code>@{p['username']}</code>\n"
            f"• Hozirgi daraja: <b>{rank_title}</b>\n"
            f"• Elo reytingi: <b>{elo} PTS</b>\n"
            f"──────────────────────────────\n"
            f"📈 <b>Jangovar statistika:</b>\n"
            f"• Jami o'yinlar: <b>{total}</b>\n"
            f"• G'alaba / Mag'lubiyat / Durang: <b>{wins} / {losses} / {draws}</b>\n"
            f"• G'alabalar foizi (Winrate): <b>{winrate}%</b>"
        ),
        "en": (
            f"👤 <b>ESPORTS ATHLETE DIGITAL PASSPORT</b>\n"
            f"──────────────────────────────\n"
            f"• Username: <code>@{p['username']}</code>\n"
            f"• Current Rank: <b>{rank_title}</b>\n"
            f"• Elo Rating: <b>{elo} PTS</b>\n"
            f"──────────────────────────────\n"
            f"📈 <b>Combat Statistics:</b>\n"
            f"• Total Matches: <b>{total}</b>\n"
            f"• Wins / Losses / Draws: <b>{wins} / {losses} / {draws}</b>\n"
            f"• Winrate: <b>{winrate}%</b>"
        )
    }

    back_btn = {"ru": "◀️ В главное меню", "kz": "◀️ Бас мәзірге", "uz": "◀️ Bosh menyuga", "en": "◀️ Main Menu"}[lang]
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=back_btn, callback_data="pl_back_menu")]])

    await callback.message.edit_text(cards.get(lang, cards["ru"]), reply_markup=markup)
    await callback.answer()

@players_router.callback_query(F.data == "pl_back_menu")
async def cb_back_menu(callback: CallbackQuery):
    lang = await TournamentService.get_player_language(callback.from_user.id)
    menu_headers = {
        "ru": "🏠 Главное меню киберспортивной системы:",
        "kz": "🏠 Киберспорт жүйесінің бас мәзірі:",
        "uz": "🏠 Kibersport tizimining bosh menyusi:",
        "en": "🏠 Esports system main menu:"
    }
    await callback.message.edit_text(menu_headers.get(lang, menu_headers["ru"]), reply_markup=get_main_menu_keyboard(lang))
    await callback.answer()

# ==========================================
# МОИ МАТЧИ (ИНТЕРАКТИВНЫЙ ТРЕКЕР)
# ==========================================

@players_router.callback_query(F.data == "pl_my_matches")
async def cb_my_matches(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = await TournamentService.get_player_language(user_id)

    if not pool:
        return

    async with pool.acquire() as conn:
        tour = await conn.fetchrow("SELECT id, name FROM tournaments WHERE is_active = TRUE LIMIT 1;")
        if not tour:
            not_active = {
                "ru": "ℹ️ В данный момент активный турнир не проводится.",
                "kz": "ℹ️ Қазіргі уақытта белсенді турнир өткізіліп жатқан жоқ.",
                "uz": "ℹ️ Hozirda faol turnir o'tkazilmayapti.",
                "en": "ℹ️ There is no active tournament right now."
            }[lang]
            await callback.answer(not_active, show_alert=True)
            return

        # Ищем матчи текущего игрока
        matches = await conn.fetch("""
            SELECT m.*, u1.username as u1_name, u2.username as u2_name 
            FROM matches m
            JOIN players u1 ON m.p1_id = u1.tg_id
            JOIN players u2 ON m.p2_id = u2.tg_id
            WHERE m.tour_id = $1 AND (m.p1_id = $2 OR m.p2_id = $2)
            ORDER BY m.id DESC;
        """, tour["id"], user_id)

    header = {
        "ru": f"⚔️ <b>Ваши матчи в турнире «{tour['name']}»:</b>\n\n",
        "kz": f"⚔️ <b>«{tour['name']}» турниріндегі матчтарыңыз:</b>\n\n",
        "uz": f"⚔️ <b>«{tour['name']}» turniridagi o'yinlaringiz:</b>\n\n",
        "en": f"⚔️ <b>Your matches in «{tour['name']}»:</b>\n\n"
    }[lang]

    if not matches:
        text = header + {"ru": "У вас пока нет назначенных матчей.", "kz": "Әзірге тағайынген матчтарыңыз жоқ.", "uz": "Hozircha tayinlangan o'yinlaringiz yo'q.", "en": "You have no assigned matches yet."}[lang]
    else:
        text = header
        for m in matches:
            status_symbol = "🟢 Завершен" if m["status"] == "finished" else "⏳ Ожидает игры"
            text += f"• <b>Матч #{m['id']}</b>: @{m['u1_name']} vs @{m['u2_name']}\n  Счет: <code>{m['p1_score']} : {m['p2_score']}</code> | Статус: {status_symbol}\n\n"

    back_btn = {"ru": "◀️ Назад", "kz": "◀️ Артқа", "uz": "◀️ Orqaga", "en": "◀️ Back"}[lang]
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=back_btn, callback_data="pl_back_menu")]])

    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()

# ==========================================
# ТОП ЛИДЕРОВ И ЗАЛ СЛАВЫ
# ==========================================

@players_router.callback_query(F.data == "pl_top")
async def cb_leaderboard(callback: CallbackQuery):
    lang = await TournamentService.get_player_language(callback.from_user.id)
    async with pool.acquire() as conn:
        top_players = await conn.fetch("SELECT username, elo, wins, losses FROM players ORDER BY elo DESC LIMIT 10;")

    title = {
        "ru": "🏆 <b>ЭЛИТНЫЙ ЗАЛ СЛАВЫ (ТОП-10 ELO):</b>\n\n",
        "kz": "🏆 <b>ЭЛИТАЛЫҚ ДАҢҚ ЗАЛЫ (ТОП-10 ELO):</b>\n\n",
        "uz": "🏆 <b>SHON-SHARAF ZALI (TOP-10 ELO):</b>\n\n",
        "en": "🏆 <b>ELITE HALL OF FAME (TOP-10 ELO):</b>\n\n"
    }[lang]

    text = title
    for i, p in enumerate(top_players, 1):
        medal = ["👑", "🥈", "🥉"][i-1] if i <= 3 else f"<b>{i}.</b>"
        text += f"{medal} <code>@{p['username']}</code> — <b>{p['elo']} PTS</b> (Поб: {p['wins']})\n"

    back_btn = {"ru": "◀️ Назад", "kz": "◀️ Артқа", "uz": "◀️ Orqaga", "en": "◀️ Back"}[lang]
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=back_btn, callback_data="pl_back_menu")]])

    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()

# ==========================================
# ОБЩАЯ СТАТИСТИКА СИСТЕМЫ
# ==========================================

@players_router.callback_query(F.data == "pl_stats")
async def cb_global_stats(callback: CallbackQuery):
    lang = await TournamentService.get_player_language(callback.from_user.id)
    if not pool:
        return

    async with pool.acquire() as conn:
        total_players = await conn.fetchval("SELECT COUNT(*) FROM players;")
        total_matches = await conn.fetchval("SELECT COUNT(*) FROM matches;")
        finished_matches = await conn.fetchval("SELECT COUNT(*) FROM matches WHERE status = 'finished';")

    stats_text = {
        "ru": (
            f"📊 <b>ГЛОБАЛЬНАЯ СТАТИСТИКА ЭКОСИСТЕМЫ</b>\n"
            f"──────────────────────────────\n"
            f"• Зарегистрировано бойцов: <b>{total_players}</b>\n"
            f"• Всего создано матчей: <b>{total_matches}</b>\n"
            f"• Успешно сыграно матчей: <b>{finished_matches}</b>\n"
            f"• Статус ядра: 🟢 <b>Работает стабильно</b>"
        ),
        "kz": (
            f"📊 <b>ЭКОСИ ЖҮЙЕНІҢ ЖАЛПЫ СТАТИСТИКАСЫ</b>\n"
            f"──────────────────────────────\n"
            f"• Тіркелген ойыншылар: <b>{total_players}</b>\n"
            f"• Барлық матчтар саны: <b>{total_matches}</b>\n"
            f"• Аяқталған матчтар: <b>{finished_matches}</b>\n"
            f"• Жүйе күйі: 🟢 <b>Қалыпты жұмыс істеуде</b>"
        ),
        "uz": (
            f"📊 <b>TIZIMNING GLOBAL STATISTIKASI</b>\n"
            f"──────────────────────────────\n"
            f"• Ro'yxatdan o'tgan o'yinchilar: <b>{total_players}</b>\n"
            f"• Jami yaratilgan o'yinlar: <b>{total_matches}</b>\n"
            f"• Muvaffaqiyatli yakunlangan: <b>{finished_matches}</b>\n"
            f"• Tizim holati: 🟢 <b>Barqaror ishlamqda</b>"
        ),
        "en": (
            f"📊 <b>GLOBAL ECOSYSTEM PERFORMANCE</b>\n"
            f"──────────────────────────────\n"
            f"• Registered Players: <b>{total_players}</b>\n"
            f"• Total Matches Created: <b>{total_matches}</b>\n"
            f"• Successfully Played: <b>{finished_matches}</b>\n"
            f"• Core Status: 🟢 <b>Online & Stable</b>"
        )
    }

    back_btn = {"ru": "◀️ Назад", "kz": "◀️ Артқа", "uz": "◀️ Orqaga", "en": "◀️ Back"}[lang]
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=back_btn, callback_data="pl_back_menu")]])

    await callback.message.edit_text(stats_text.get(lang, stats_text["ru"]), reply_markup=markup)
    await callback.answer()

# ==========================================
# ИНСТРУКЦИЯ ПО ОТПРАВКЕ СЧЕТА
# ==========================================

@players_router.callback_query(F.data == "pl_help_score")
async def cb_help_score(callback: CallbackQuery):
    lang = await TournamentService.get_player_language(callback.from_user.id)
    help_texts = {
        "ru": (
            "✍️ <b>ПРАВИЛА ОТПРАВКИ РЕЗУЛЬТАТОВ МАТЧА</b>\n\n"
            "Чтобы бот автоматически зафиксировал результат и пересчитал твой Elo-рейтинг, отправь сообщение в чат строго в таком синтаксисе:\n\n"
            "<code>@player1 3:1 @player2</code>\n\n"
            "💡 <i>Система сама распознает участников, проверит наличие активного матча и мгновенно обновит таблицы.</i>"
        ),
        "kz": (
            "✍️ <b>МАТЧ НӘТИЖЕЛЕРІН ЖІБЕРУ ЕРЕЖЕЛЕРІ</b>\n\n"
            "Бот нәтижені автоматты түрде тіркеп, Elo рейтингіңізді қайта есептеуі үшін чатқа мына синтаксиспен хабарлама жіберіңіз:\n\n"
            "<code>@player1 3:1 @player2</code>\n\n"
            "💡 <i>Жүйе қатысушыларды өзі таниды, белсенді матчты тексеріп, кестелерді дереу жаңартады.</i>"
        ),
        "uz": (
            "✍️ <b>O'YIN NATIJALARINI YUBORISH QOIDALARI</b>\n\n"
            "Bot natijani avtomatik qayd etishi va Elo reytingini hisoblashi uchun chatga quyidagi formatda yuboring:\n\n"
            "<code>@player1 3:1 @player2</code>\n\n"
            "💡 <i>Tizim ishtirokchilarni o'zi tanidi, faol o'yinni tekshiradi va jadvalni darhol yangilaydi.</i>"
        ),
        "en": (
            "✍️ <b>MATCH RESULT SUBMISSION GUIDE</b>\n\n"
            "For the bot to automatically record the result and update your Elo rating, send a message to the chat using this exact syntax:\n\n"
            "<code>@player1 3:1 @player2</code>\n\n"
            "💡 <i>The system automatically recognizes participants, verifies active matches, and updates leaderboards instantly.</i>"
        )
    }
    back_btn = {"ru": "◀️ Назад", "kz": "◀️ Артқа", "uz": "◀️ Orqaga", "en": "◀️ Back"}[lang]
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=back_btn, callback_data="pl_back_menu")]])

    await callback.message.edit_text(help_texts.get(lang, help_texts["ru"]), reply_markup=markup)
    await callback.answer()

# ==========================================
# ПАРСИНГ ТЕКСТОВЫХ РЕЗУЛЬТАТОВ МАТЧЕЙ
# ==========================================

@players_router.message(F.text.regexp(r"^@?([\w\d_]+)\s+(\d+)\s*[:\-\/]\s*(\d+)\s+@?([\w\d_]+)$"))
async def handle_match_score_input(message: Message, regexp_match):
    p1_nick = regexp_match.group(1)
    score1 = int(regexp_match.group(2))
    score2 = int(regexp_match.group(3))
    p2_nick = regexp_match.group(4)

    response_text = await TournamentService.process_match_input(
        chat_id=message.chat.id,
        sender_id=message.from_user.id,
        sender_username=message.from_user.username or "",
        p1_nick=p1_nick,
        p2_nick=p2_nick,
        score1=score1,
        score2=score2
    )

    await message.reply(response_text)
