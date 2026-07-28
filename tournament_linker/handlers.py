import sqlite3
import os

DB_NAME = "tournament_linker/tournament.db"

def init_db():
    os.makedirs("tournament_linker", exist_ok=True)
    conn = sqlite3.connect(DB_NAME)
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
    conn.close()

init_db()

# Функция для регистрации обработчиков в ваш основной telebot-скрипт
def register_tournament_handlers(bot):

    # Автоматический перехват новых постов в канале
    @bot.channel_post_handler(func=lambda message: True)
    fname = lambda message: auto_link(message)
    def auto_link(message):
        channel_id = message.chat.id
        current_post_id = message.message_id

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Получаем ID предыдущего поста
        cursor.execute('SELECT last_post_id FROM last_channel_posts WHERE channel_id = ?', (channel_id,))
        row = cursor.fetchone()
        
        if row:
            previous_post_id = row[0]
            # Автоматически связываем предыдущий пост (регистрация) и текущий (матчи)
            cursor.execute('''
                INSERT OR REPLACE INTO tournaments (channel_id, reg_post_id, match_post_id, status)
                VALUES (?, ?, ?, 'active')
            ''', (channel_id, previous_post_id, current_post_id))
        
        # Обновляем последний пост в канале
        cursor.execute('''
            INSERT OR REPLACE INTO last_channel_posts (channel_id, last_post_id)
            VALUES (?, ?)
        ''', (channel_id, current_post_id))
        
        conn.commit()
        conn.close()

    # Перехват команды /results в комментариях под постом матчей
    @bot.message_handler(commands=['results'])
    def handle_results(message):
        if not message.reply_to_message:
            return

        match_post_id = message.reply_to_message.message_id
        channel_id = message.chat.id # Или message.forward_from_chat.id в зависимости от структуры комментариев

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT reg_post_id FROM tournaments 
            WHERE match_post_id = ? AND status = 'active'
        ''', (match_post_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return

        reg_post_id = row[0]
        results_text = message.text.replace("/results", "").strip()
        
        if not results_text:
            bot.reply_to(message, "❌ Укажите счет матча после /results")
            return

        bot.reply_to(
            message,
            f"✅ Результат принят!\n"
            f"🔗 Автоматически привязан к посту регистрации: #{reg_post_id}\n"
            f"📊 Счёт: {results_text}"
        )
