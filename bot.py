import telebot
import logging
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

TOKEN = "8876079721:AAH8dJTuvKNVHuMNzdG_M79Xp5vkAZ5wO_I"
bot = telebot.TeleBot(TOKEN)

# Список админов
ADMINS = ['wonti9', 'avelon67', 'nupik91']

# Хранилище собранных юзернеймов: { thread_id: set("@user1", "@user2") }
posts_data = {}

def is_admin(message):
    username = message.from_user.username
    if username:
        return username.lower() in ADMINS
    return False

def get_thread_id(message):
    # Определяем ID ветки/поста
    if message.message_thread_id:
        return message.message_thread_id
    if message.reply_to_message:
        return message.reply_to_message.message_id
    return message.chat.id

# 1. АВТОМАТИЧЕСКИЙ СБОР ЮЗЕРНЕЙМОВ ИЗ ВСЕХ СООБЩЕНИЙ И КОММЕНТАРИЕВ
@bot.message_handler(func=lambda message: True, content_types=['text', 'caption'])
def catch_usernames(message):
    try:
        text = message.text or message.caption or ""
        
        # Находим все юзернеймы формата @username (автоматически отсекает точки и запятые)
        found_usernames = re.findall(r'@[a-zA-Z0-9_]+', text)
        
        if found_usernames:
            thread_id = get_thread_id(message)
            if thread_id not in posts_data:
                posts_data[thread_id] = set()
            
            for tag in found_usernames:
                posts_data[thread_id].add(tag) # set исключает дубликаты
            
            logging.info(f"Собрано {len(found_usernames)} юзернеймов под постом/веткой {thread_id}")
    except Exception as e:
        logging.error(f"Ошибка при сборе юзернеймов: {e}")

# 2. КОМАНДА /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        if not is_admin(message):
            bot.reply_to(message, "⛔ Доступ запрещен. Бот только для администрации.")
            return
        bot.reply_to(message, "✅ Бот готов к работе! Добавьте меня в чат/канал с комментариями. Для сбора списка отправьте /collect под нужным постом.")
    except Exception as e:
        logging.error(f"Ошибка в /start: {e}")

# 3. КОМАНДА /collect — ВЫВОД ОЧИЩЕННОГО СПИСКА
@bot.message_handler(commands=['collect'])
def collect_comments(message):
    try:
        if not is_admin(message):
            bot.reply_to(message, "⛔ У вас нет прав для этой команды.")
            return
        
        thread_id = get_thread_id(message)
        collected = posts_data.get(thread_id, set())
        
        if not collected:
            bot.reply_to(message, "📭 Под этим постом/в этой ветке пока не найдено ни одного юзернейма с `@`.")
            return
        
        # Сортируем список по алфавиту
        sorted_list = sorted(list(collected))
        
        response_text = f"📋 **Собранные юзернеймы ({len(sorted_list)} шт.):**\n\n"
        response_text += "\n".join(f"{i+1}. {tag}" for i, tag in enumerate(sorted_list))
        
        # Если список очень длинный (больше 4000 символов), отправляем файлом
        if len(response_text) > 4000:
            filename = f"usernames_{thread_id}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write("\n".join(sorted_list))
            with open(filename, "rb") as f:
                bot.send_document(message.chat.id, f, caption=f"✅ Список юзернеймов ({len(sorted_list)} шт.)")
            os.remove(filename)
        else:
            bot.reply_to(message, response_text, parse_mode="Markdown")
            
        logging.info(f"Админ @{message.from_user.username} выгрузил {len(sorted_list)} юзернеймов.")
    except Exception as e:
        logging.error(f"Ошибка в /collect: {e}")

# 4. ФЕЙКОВЫЙ ВЕБ-СЕРВЕР ДЛЯ RENDER
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")
        
    def log_message(self, format, *args):
        pass

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

if __name__ == '__main__':
    server_thread = threading.Thread(target=run_dummy_server, daemon=True)
    server_thread.start()
    
    logging.info("Бот со сбором юзернеймов запущен!")
    
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            logging.error(f"Критическая ошибка опроса: {e}. Перезапуск через 5 секунд...")
            time.sleep(5)
