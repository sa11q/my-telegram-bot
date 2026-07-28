import sqlite3
from aiogram import Router, types, F
from aiogram.filters import Command

router = Router()
DB_NAME = "tournament_linker/tournament.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tournaments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                reg_post_id INTEGER,
                match_post_id INTEGER,
                status TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS last_channel_posts (
                channel_id INTEGER PRIMARY KEY,
                last_post_id INTEGER
            )
        ''')
        conn.commit()

init_db()

# Автоматически ловит новый пост в канале и связывает с предыдущим
@router.channel_post()
async def auto_link_posts(message: types.Message):
    channel_id = message.chat.id
    current_post_id = message.message_id

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        
        # Получаем ID предыдущего поста в этом канале
        cursor.execute('SELECT last_post_id FROM last_channel_posts WHERE channel_id = ?', (channel_id,))
        row = cursor.fetchone()
        
        if row:
            previous_post_id = row[0]
            # Автоматически связываем предыдущий пост (регистрация) и текущий (матчи/сетка)
            cursor.execute('''
                INSERT OR REPLACE INTO tournaments (channel_id, reg_post_id, match_post_id, status)
                VALUES (?, ?, ?, 'active')
            ''', (channel_id, previous_post_id, current_post_id))
        
        # Сохраняем текущий пост как последний
        cursor.execute('''
            INSERT OR REPLACE INTO last_channel_posts (channel_id, last_post_id)
            VALUES (?, ?)
        ''', (channel_id, current_post_id))
        
        conn.commit()

# Обработка результатов под постом матчей
@router.message(Command("results"))
async def handle_results(message: types.Message):
    if not message.reply_to_message:
        return

    match_post_id = message.reply_to_message.message_id
    channel_id = message.chat.id

    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT reg_post_id FROM tournaments 
            WHERE channel_id = ? AND match_post_id = ? AND status = 'active'
        ''', (channel_id, match_post_id))
        row = cursor.fetchone()

    if not row:
        return

    reg_post_id = row[0]
    results_text = message.text.replace("/results", "").strip()
    
    if not results_text:
        await message.reply("❌ Укажите счет матча после /results")
        return

    await message.reply(
        f"✅ Результат принят!\n"
        f"🔗 Автоматически привязан к посту регистрации: #{reg_post_id}\n"
        f"📊 Счёт: {results_text}"
    )
