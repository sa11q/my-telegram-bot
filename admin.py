import logging
import math
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from database import pool
from tournament_service import TournamentService

logger = logging.getLogger(__name__)
admin_router = Router()

ADMIN_IDS = [123456789]  # Твой ID администратора

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ==========================================
# ГЛАВНОЕ МЕНЮ АДМИНИСТРАТОРА
# ==========================================

async def get_admin_dashboard_text() -> str:
    """Генерирует сводку системной статистики"""
    if not pool:
        return "🛠 <b>Панель управления системой (Офлайн)</b>"
        
    async with pool.acquire() as conn:
        players_count = await conn.fetchval("SELECT COUNT(*) FROM players;")
        tour = await conn.fetchrow("SELECT * FROM tournaments WHERE is_active = TRUE LIMIT 1;")
        
        matches_total = 0
        matches_pending = 0
        if tour:
            matches_total = await conn.fetchval("SELECT COUNT(*) FROM matches WHERE tour_id = $1;", tour["id"])
            matches_pending = await conn.fetchval("SELECT COUNT(*) FROM matches WHERE tour_id = $1 AND status = 'pending';", tour["id"])

    tour_info = f"🏆 <b>{tour['name']}</b> (Этап: {tour['current_stage']})" if tour else "❌ Нет активного"
    
    return (
        "🛠 <b>ABSOLUTE ADMIN PANEL (System Core)</b>\n"
        "──────────────────────────────\n"
        f"👥 Всего игроков в базе: <b>{players_count}</b>\n"
        f"📌 Активный турнир: {tour_info}\n"
        f"⚔️ Матчи: Всего <b>{matches_total}</b> | Ожидают <b>{matches_pending}</b>\n"
        "──────────────────────────────\n"
        "Выберите раздел управления:"
    )

def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏆 Турнир", callback_data="adm_sec_tour"),
            InlineKeyboardButton(text="⚔️ Матчи и Сетка", callback_data="adm_sec_matches:0")
        ],
        [
            InlineKeyboardButton(text="👥 Участники", callback_data="adm_sec_players:0"),
            InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_broadcast_menu")
        ],
        [
            InlineKeyboardButton(text="🔄 Сброс базы / Системы", callback_data="adm_system_reset"),
            InlineKeyboardButton(text="❌ Закрыть", callback_data="adm_close")
        ]
    ])

@admin_router.message(Command("admin"))
async def cmd_admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    text = await get_admin_dashboard_text()
    await message.answer(text, reply_markup=get_admin_main_keyboard())

@admin_router.callback_query(F.data == "adm_main")
async def cb_admin_main(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    text = await get_admin_dashboard_text()
    await callback.message.edit_text(text, reply_markup=get_admin_main_keyboard())
    await callback.answer()

@admin_router.callback_query(F.data == "adm_close")
async def cb_close_admin(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text("✅ Панель администратора скрыта.")
    await callback.answer()


# ==========================================
# 1. УПРАВЛЕНИЕ ТУРНИРОМ
# ==========================================

@admin_router.callback_query(F.data == "adm_sec_tour")
async def cb_sec_tournament(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать турнир", callback_data="adm_tour_create_info")],
        [InlineKeyboardButton(text="🛑 Остановить текущий", callback_data="adm_tour_stop")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🏆 <b>Управление турниром:</b>\n\nВыберите действие:", reply_markup=markup)
    await callback.answer()

@admin_router.callback_query(F.data == "adm_tour_create_info")
async def cb_tour_create_info(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    text = (
        "➕ <b>Создание турнира</b>\n\n"
        "Отправьте в чат команду в формате:\n"
        "<code>/newtour [Название] [режим: swiss/knockout]</code>\n\n"
        "Пример:\n<code>/newtour FC Mobile Pro 2026 swiss</code>"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_sec_tour")]])
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()

@admin_router.message(Command("newtour"))
async def cmd_new_tour(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.reply("❌ Формат: <code>/newtour [Название] [режим]</code>")
        return

    name = parts[1]
    mode = parts[2] if len(parts) > 2 else "swiss"
    deadline = TournamentService.calculate_deadline()

    if not pool:
        return

    async with pool.acquire() as conn:
        await conn.execute("UPDATE tournaments SET is_active = FALSE;")
        tour_id = await conn.fetchval("""
            INSERT INTO tournaments (name, is_active, status, mode, current_stage, stage_deadline)
            VALUES ($1, TRUE, 'active', $2, 1, $3)
            RETURNING id;
        """, name, mode, deadline)

    await message.reply(f"✅ Турнир <b>{name}</b> (ID: {tour_id}, Режим: {mode}) успешно запущен!")

@admin_router.callback_query(F.data == "adm_tour_stop")
async def cb_tour_stop(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    if not pool:
        return
    async with pool.acquire() as conn:
        await conn.execute("UPDATE tournaments SET is_active = FALSE, status = 'archived' WHERE is_active = TRUE;")
    await callback.message.edit_text("🛑 Активный турнир переведен в архив.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_sec_tour")]]))
    await callback.answer()


# ==========================================
# 2. УПРАВЛЕНИЕ МАТЧАМИ С ПАГИНАЦИЕЙ (СТРАНИЦЫ)
# ==========================================

@admin_router.callback_query(F.data.startswith("adm_sec_matches:"))
async def cb_sec_matches(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    
    page = int(callback.data.split(":")[1])
    limit = 5  # Количество матчей на одной странице
    offset = page * limit

    if not pool:
        return

    async with pool.acquire() as conn:
        tour = await conn.fetchrow("SELECT id, name FROM tournaments WHERE is_active = TRUE LIMIT 1;")
        if not tour:
            await callback.answer("ℹ️ Нет активного турнира.", show_alert=True)
            return

        total_matches = await conn.fetchval("SELECT COUNT(*) FROM matches WHERE tour_id = $1;", tour["id"])
        
        query = """
            SELECT m.*, u1.username as u1_name, u2.username as u2_name 
            FROM matches m
            JOIN players u1 ON m.p1_id = u1.tg_id
            JOIN players u2 ON m.p2_id = u2.tg_id
            WHERE m.tour_id = $1
            ORDER BY m.id ASC
            LIMIT $2 OFFSET $3;
        """
        matches = await conn.fetch(query, tour["id"], limit, offset)

    if not matches and total_matches == 0:
        text = f"⚔️ <b>Матчи турнира: {tour['name']}</b>\n\nВ турнире пока нет матчей."
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_main")]])
        await callback.message.edit_text(text, reply_markup=markup)
        await callback.answer()
        return

    text = f"⚔️ <b>Матчи турнира: {tour['name']}</b> (Всего: {total_matches})\nСтраница {page + 1} из {max(1, math.ceil(total_matches / limit))}:\n\n"
    
    buttons = []
    for m in matches:
        status_icon = "✅" if m["status"] == "finished" else "⏳"
        text += f"{status_icon} <b>#{m['id']}</b> | @{m['u1_name']} {m['p1_score']}:{m['p2_score']} @{m['u2_name']} ({m['status']})\n"
        # Кнопка для ручного изменения счета конкретного матча
        buttons.append([InlineKeyboardButton(text=f"✏️ Изменить матч #{m['id']}", callback_data=f"adm_edit_match:{m['id']}:{page}")])

    # Навигация пагинации (Страницы)
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"adm_sec_matches:{page - 1}"))
    if offset + limit < total_matches:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"adm_sec_matches:{page + 1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)
        
    buttons.append([InlineKeyboardButton(text="◀️ В главное меню", callback_data="adm_main")])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@admin_router.callback_query(F.data.startswith("adm_edit_match:"))
async def cb_edit_match_prompt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    _, match_id, page = callback.data.split(":")
    
    text = (
        f"✏️ <b>Редактирование матча #{match_id}</b>\n\n"
        f"Чтобы принудительно изменить счет, отправьте в чат команду:\n"
        f"<code>/setscore {match_id} [счет_1] [счет_2]</code>\n\n"
        f"Пример: <code>/setscore {match_id} 3 1</code>"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ К списку матчей", callback_data=f"adm_sec_matches:{page}")]
    ])
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()

@admin_router.message(Command("setscore"))
async def cmd_admin_set_score(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 4:
        await message.reply("❌ Формат: <code>/setscore [match_id] [s1] [s2]</code>")
        return

    try:
        match_id = int(parts[1])
        s1 = int(parts[2])
        s2 = int(parts[3])
    except ValueError:
        await message.reply("❌ ID матча и счета должны быть числами.")
        return

    if not pool:
        return

    async with pool.acquire() as conn:
        match = await conn.fetchrow("SELECT * FROM matches WHERE id = $1;", match_id)
        if not match:
            await message.reply(f"❌ Матч #{match_id} не найден.")
            return

        # Принудительно обновляем счет и переводим в finished
        await conn.execute("""
            UPDATE matches SET p1_score = $1, p2_score = $2, status = 'finished' WHERE id = $3;
        """, s1, s2, match_id)

    await message.reply(f"✅ Счет матча #{match_id} успешно изменен на <b>{s1}:{s2}</b> администратором!")


# ==========================================
# 3. УПРАВЛЕНИЕ УЧАСТНИКАМИ (ИГРОКАМИ)
# ==========================================

@admin_router.callback_query(F.data.startswith("adm_sec_players:"))
async def cb_sec_players(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    page = int(callback.data.split(":")[1])
    limit = 8
    offset = page * limit

    if not pool:
        return

    async with pool.acquire() as conn:
        total_players = await conn.fetchval("SELECT COUNT(*) FROM players;")
        players = await conn.fetch("SELECT tg_id, username, elo, wins, losses FROM players ORDER BY elo DESC LIMIT $1 OFFSET $2;", limit, offset)

    text = f"👥 <b>База участников (Всего: {total_players})</b>\nСтраница {page + 1}:\n\n"
    buttons = []

    for p in players:
        text += f"• @{p['username']} — <b>{p['elo']} Elo</b> (Поб: {p['wins']} / Пор: {p['losses']})\n"
        buttons.append([InlineKeyboardButton(text=f"🗑 Удалить @{p['username']}", callback_data=f"adm_del_p:{p['tg_id']}:{page}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"adm_sec_players:{page - 1}"))
    if offset + limit < total_players:
        nav_buttons.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"adm_sec_players:{page + 1}"))
    
    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([
        InlineKeyboardButton(text="➕ Добавить игрока", callback_data="adm_add_player_info"),
        InlineKeyboardButton(text="◀️ В меню", callback_data="adm_main")
    ])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@admin_router.callback_query(F.data.startswith("adm_del_p:"))
async def cb_delete_player_btn(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    _, tg_id_str, page = callback.data.split(":")
    tg_id = int(tg_id_str)

    if not pool:
        return

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM players WHERE tg_id = $1;", tg_id)

    await callback.answer("✅ Игрок удален из базы!", show_alert=True)
    # Обновляем страницу участников
    callback.data = f"adm_sec_players:{page}"
    await cb_sec_players(callback)

@admin_router.callback_query(F.data == "adm_add_player_info")
async def cb_add_player_info(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    text = (
        "➕ <b>Ручное добавление игрока</b>\n\n"
        "Отправьте команду в чат:\n"
        "<code>/addplayer [username]</code>\n\n"
        "Пример: <code>/addplayer ssshhym</code>"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад к участникам", callback_data="adm_sec_players:0")]])
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()

@admin_router.message(Command("addplayer"))
async def cmd_add_player(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("❌ Формат: <code>/addplayer [username]</code>")
        return

    username = parts[1].strip().lower().replace("@", "")
    import time
    fake_tg_id = -int(time.time())

    if not pool:
        return

    async with pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT tg_id FROM players WHERE LOWER(username) = $1;", username)
        if existing:
            await message.reply(f"ℹ️ Игрок @{username} уже в базе!")
            return
        await conn.execute("INSERT INTO players (tg_id, username, elo) VALUES ($1, $2, 1200);", fake_tg_id, username)

    await message.reply(f"✅ Участник <b>@{username}</b> успешно добавлен в систему!")


# ==========================================
# 4. МАССОВАЯ РАССЫЛКА
# ==========================================

@admin_router.callback_query(F.data == "adm_broadcast_menu")
async def cb_broadcast_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    text = (
        "📢 <b>Массовая рассылка</b>\n\n"
        "Отправьте в чат команду:\n"
        "<code>/broadcast [Ваш текст уведомления]</code>\n\n"
        "Сообщение будет отправлено всем игрокам."
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="adm_main")]])
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()

@admin_router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if not is_admin(message.from_user.id):
        return
    text_to_send = message.text.replace("/broadcast", "").strip()
    if not text_to_send:
        await message.reply("❌ Введите текст после команды.")
        return

    if not pool:
        return

    async with pool.acquire() as conn:
        players = await conn.fetch("SELECT tg_id FROM players WHERE tg_id > 0;")

    success, fail = 0, 0
    for p in players:
        try:
            await message.bot.send_message(p["tg_id"], f"📢 <b>Объявление организатора:</b>\n\n{text_to_send}")
            success += 1
        except Exception:
            fail += 1

    await message.reply(f"📊 Рассылка завершена!\n• Успешно: <b>{success}</b>\n• Ошибок: <b>{fail}</b>")


# ==========================================
# 5. СИСТЕМНОЕ ОБСЛУЖИВАНИЕ И СБРОС
# ==========================================

@admin_router.callback_query(F.data == "adm_system_reset")
async def cb_system_reset(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚠️ УДАЛИТЬ ВСЕ МАТЧИ И ТУРНИРЫ", callback_data="adm_confirm_reset")],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data="adm_main")]
    ])
    await callback.message.edit_text("⚠️ <b>Опасная зона!</b>\n\nВы можете очистить всю историю матчей и турниров (профили игроков и их Elo сохранятся).", reply_markup=markup)
    await callback.answer()

@admin_router.callback_query(F.data == "adm_confirm_reset")
async def cb_confirm_reset(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    if not pool:
        return
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM matches;")
        await conn.execute("DELETE FROM tournaments;")
    await callback.message.edit_text("🧹 Все турниры и матчи успешно очищены из системы.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ В меню", callback_data="adm_main")]]))
    await callback.answer()
