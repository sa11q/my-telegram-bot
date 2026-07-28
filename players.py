import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart, Command

from database import pool
from tournament_service import TournamentService

logger = logging.getLogger(__name__)
players_router = Router()

# ==========================================
# КЛАВИАТУРЫ И ПАНЕЛИ
# ==========================================

def get_main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Главная панель игрока в зависимости от языка"""
    buttons = {
        "ru": [
            [InlineKeyboardButton(text="👤 Профиль", callback_data="pl_profile"), InlineKeyboardButton(text="🏆 Топ игроков", callback_data="pl_top")],
            [InlineKeyboardButton(text="✍️ Записать матч", callback_data="pl_help_score"), InlineKeyboardButton(text="🌐 Язык / Тіл", callback_data="pl_lang")]
        ],
        "kz": [
            [InlineKeyboardButton(text="👤 Профиль", callback_data="pl_profile"), InlineKeyboardButton(text="🏆 Үздіктер", callback_data="pl_top")],
            [InlineKeyboardButton(text="✍️ Матч жазу", callback_data="pl_help_score"), InlineKeyboardButton(text="🌐 Тіл / Язык", callback_data="pl_lang")]
        ],
        "uz": [
            [InlineKeyboardButton(text="👤 Profil", callback_data="pl_profile"), InlineKeyboardButton(text="🏆 Reyting", callback_data="pl_top")],
            [InlineKeyboardButton(text="✍️ O'yinni kiritish", callback_data="pl_help_score"), InlineKeyboardButton(text="🌐 Til / Язык", callback_data="pl_lang")]
        ],
        "en": [
            [InlineKeyboardButton(text="👤 Profile", callback_data="pl_profile"), InlineKeyboardButton(text="🏆 Leaderboard", callback_data="pl_top")],
            [InlineKeyboardButton(text="✍️ Submit Match", callback_data="pl_help_score"), InlineKeyboardButton(text="🌐 Language", callback_data="pl_lang")]
        ]
    }
    return InlineKeyboardMarkup(inline_keyboard=buttons.get(lang, buttons["ru"]))

def get_languages_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора из 4 языков"""
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
# СТАРТ И РЕГИСТРАЦИЯ / ВЫБОР ЯЗЫКА
# ==========================================

@players_router.message(CommandStart())
async def cmd_start(message: Message):
    """Приветствие, автоматическая регистрация игрока и главное меню"""
    user = message.from_user
    if not pool:
        await message.answer("Database error.")
        return

    async with pool.acquire() as conn:
        # Автоматический апсерт игрока в базу
        clean_username = (user.username or f"user_{user.id}").lower().replace("@", "")
        await conn.execute("""
            INSERT INTO players (tg_id, username) 
            VALUES ($1, $2)
            ON CONFLICT (tg_id) DO UPDATE SET username = EXCLUDED.username;
        """, user.id, clean_username)

        # Получаем язык игрока
        row = await conn.fetchrow("SELECT language FROM players WHERE tg_id = $1;", user.id)
        lang = row["language"] if row and row["language"] in ["ru", "kz", "uz", "en"] else "ru"

    welcome_texts = {
        "ru": f"👋 Привет, <b>{user.first_name}</b>!\nДобро пожаловать в официальную систему турниров FC Mobile.\n\nИспользуй панель управления ниже:",
        "kz": f"👋 Сәлем, <b>{user.first_name}</b>!\nFC Mobile ресми турнир жүйесіне қош келдіңіз.\n\nТөмендегі басқару панелін пайдаланыңыз:",
        "uz": f"👋 Salom, <b>{user.first_name}</b>!\nRasmiy FC Mobile turnir tizimiga xush kelibsiz.\n\nQuyidagi boshqaruv panelidan foydalaning:",
        "en": f"👋 Hello, <b>{user.first_name}</b>!\nWelcome to the official FC Mobile tournament system.\n\nUse the control panel below:"
    }

    await message.answer(
        welcome_texts.get(lang, welcome_texts["ru"]),
        reply_markup=get_main_menu_keyboard(lang)
    )

@players_router.callback_query(F.data == "pl_lang")
async def cb_open_language(callback: CallbackQuery):
    """Открытие меню смены языка"""
    langs_text = {
        "ru": "🌐 Выберите язык интерфейса:",
        "kz": "🌐 Интерфейс тілін таңдаңыз:",
        "uz": "🌐 Interfeys tilini tanlang:",
        "en": "🌐 Select interface language:"
    }
    lang = await TournamentService.get_player_language(callback.from_user.id)
    await callback.message.edit_text(langs_text.get(lang, langs_text["ru"]), reply_markup=get_languages_keyboard())
    await callback.answer()

@players_router.callback_query(F.data.startswith("set_lang_"))
async def cb_set_language(callback: CallbackQuery):
    """Сохранение выбранного языка"""
    new_lang = callback.data.split("_")[2]
    if new_lang not in ["ru", "kz", "uz", "en"]:
        return

    async with pool.acquire() as conn:
        await conn.execute("UPDATE players SET language = $1 WHERE tg_id = $2;", new_lang, callback.from_user.id)

    success_texts = {
        "ru": "✅ Язык успешно изменен на русский!",
        "kz": "✅ Тіл қазақ тіліне сәтті өзгертілді!",
        "uz": "✅ Til o'zbek tiliga o'zgartirildi!",
        "en": "✅ Language successfully changed to English!"
    }

    await callback.message.edit_text(success_texts.get(new_lang, success_texts["ru"]), reply_markup=get_main_menu_keyboard(new_lang))
    await callback.answer()

# ==========================================
# ПРОФИЛЬ И СТАТИСТИКА
# ==========================================

@players_router.callback_query(F.data == "pl_profile")
async def cb_profile(callback: CallbackQuery):
    """Просмотр личного профиля игрока"""
    user_id = callback.from_user.id
    lang = await TournamentService.get_player_language(user_id)

    async with pool.acquire() as conn:
        player = await conn.fetchrow("SELECT * FROM players WHERE tg_id = $1;", user_id)

    if not player:
        await callback.answer("Profile not found.", show_alert=True)
        return

    total = player["matches_played"]
    wins = player["wins"]
    losses = player["losses"]
    draws = player["draws"]
    elo = player["elo"]
    username = player["username"]

    profile_templates = {
        "ru": f"👤 <b>Ваш профиль:</b>\n\n• Ник: <code>@{username}</code>\n• Рейтинг Elo: <b>{elo}</b>\n• Матчи: {total}\n• Победы: <b>{wins}</b> | Поражения: <b>{losses}</b> | Ничьи: <b>{draws}</b>",
        "kz": f"👤 <b>Сіздің профиліңіз:</b>\n\n• Ник: <code>@{username}</code>\n• Elo рейтингі: <b>{elo}</b>\n• Матчтар: {total}\n• Жеңістер: <b>{wins}</b> | Жеңілістер: <b>{losses}</b> | Тең: <b>{draws}</b>",
        "uz": f"👤 <b>Sizning profilingiz:</b>\n\n• Nik: <code>@{username}</code>\n• Elo reytingi: <b>{elo}</b>\n• O'yinlar: {total}\n• G'alaba: <b>{wins}</b> | Mag'lubiyat: <b>{losses}</b> | Durang: <b>{draws}</b>",
        "en": f"👤 <b>Your profile:</b>\n\n• Username: <code>@{username}</code>\n• Elo Rating: <b>{elo}</b>\n• Matches: {total}\n• Wins: <b>{wins}</b> | Losses: <b>{losses}</b> | Draws: <b>{draws}</b>"
    }

    back_btn = {
        "ru": "◀️ Назад", "kz": "◀️ Артқа", "uz": "◀️ Orqaga", "en": "◀️ Back"
    }

    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=back_btn.get(lang, "◀️ Back"), callback_data="pl_back_menu")]
    ])

    await callback.message.edit_text(profile_templates.get(lang, profile_templates["ru"]), reply_markup=markup)
    await callback.answer()

@players_router.callback_query(F.data == "pl_back_menu")
async def cb_back_menu(callback: CallbackQuery):
    """Возврат в главное меню из разделов"""
    lang = await TournamentService.get_player_language(callback.from_user.id)
    menu_texts = {
        "ru": "🏠 Главное меню турнира:",
        "kz": "🏠 Турнирдің бас мәзірі:",
        "uz": "🏠 Turnir bosh menyusi:",
        "en": "🏠 Tournament main menu:"
    }
    await callback.message.edit_text(menu_texts.get(lang, menu_texts["ru"]), reply_markup=get_main_menu_keyboard(lang))
    await callback.answer()

@players_router.callback_query(F.data == "pl_top")
async def cb_leaderboard(callback: CallbackQuery):
    """Таблица лидеров по Elo"""
    lang = await TournamentService.get_player_language(callback.from_user.id)
    async with pool.acquire() as conn:
        top_players = await conn.fetch("SELECT username, elo, wins FROM players ORDER BY elo DESC LIMIT 10;")

    title = {
        "ru": "🏆 <b>Топ-10 игроков по Elo:</b>\n\n",
        "kz": "🏆 <b>Elo бойынша үздік 10 ойыншы:</b>\n\n",
        "uz": "🏆 <b>Elo bo'yicha top 10 o'yinchi:</b>\n\n",
        "en": "🏆 <b>Top 10 players by Elo:</b>\n\n"
    }[lang]

    text = title
    for i, p in enumerate(top_players, 1medal := ["🥇", "🥈", "🥉"]):
        medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"<b>{i}.</b>"
        text += f"{medal} @{p['username']} — <b>{p['elo']}</b> Elo (Поб: {p['wins']})\n"

    back_btn = {"ru": "◀️ Назад", "kz": "◀️ Артқа", "uz": "◀️ Orqaga", "en": "◀️ Back"}[lang]
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=back_btn, callback_data="pl_back_menu")]])

    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()

@players_router.callback_query(F.data == "pl_help_score")
async def cb_help_score(callback: CallbackQuery):
    """Инструкция, как отправлять результат матча"""
    lang = await TournamentService.get_player_language(callback.from_user.id)
    help_texts = {
        "ru": "✍️ <b>Как записать результат матча?</b>\n\nПросто отправь в этот чат сообщение в таком формате:\n<code>@player1 3:1 @player2</code>\n\nБот автоматически проверит активный матч, запишет счет и обновит ваш рейтинг Elo!",
        "kz": "✍️ <b>Матч нәтижесін қалай жазуға болады?</b>\n\nБұл чатқа мына форматта хабарлама жіберіңіз:\n<code>@player1 3:1 @player2</code>\n\nБот белсенді матчты тексеріп, есепті жазады және Elo рейтингін жаңартады!",
        "uz": "✍️ <b>O'yin natijasini qanday kiritish mumkin?</b>\n\nShunchaki ushbu chatga quyidagi formatda yuboring:\n<code>@player1 3:1 @player2</code>\n\nBot faol o'yinni tekshiradi, hisobni yozadi va Elo reytingini yangilaydi!",
        "en": "✍️ <b>How to submit a match result?</b>\n\nSimply send a message to this chat in the following format:\n<code>@player1 3:1 @player2</code>\n\nBot will automatically check the active match, save the score, and update your Elo rating!"
    }
    back_btn = {"ru": "◀️ Назад", "kz": "◀️ Артқа", "uz": "◀️ Orqaga", "en": "◀️ Back"}[lang]
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=back_btn, callback_data="pl_back_menu")]])

    await callback.message.edit_text(help_texts.get(lang, help_texts["ru"]), reply_markup=markup)
    await callback.answer()

# ==========================================
# ОБРАБОТКА РЕЗУЛЬТАТОВ МАТЧЕЙ (ТЕКСТОВЫЙ ПАРСИНГ)
# ==========================================

@players_router.message(F.text.regexp(r"^@?([\w\d_]+)\s+(\d+)\s*[:\-\/]\s*(\d+)\s+@?([\w\d_]+)$"))
async def handle_match_score_input(message: Message, regexp_match):
    """
    Перехватывает сообщения формата: @player1 3:2 @player2
    и передает их в бизнес-логику турнир сервиса.
    """
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

