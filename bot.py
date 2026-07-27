import telebot
import logging
import os
import re
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# 1. Настройка логирования для отслеживания работы на Render
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =====================================================================
TOKEN = "8876079721:AAEh9mZcoNmMXPqC9txDKMB-9RHd3lQPqGk"
# =====================================================================

bot = telebot.TeleBot(TOKEN)

# Список админов (в нижнем регистре)
ADMINS = ['wonti9', 'avelon67', 'nupik91']

# Файл базы данных для сохранения юзернеймов между перезапусками Render
DB_FILE = "database.json"

def load_data():
    """Загрузка сохраненных данных из файла."""
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): set(v) for k, v in data.items()}
        except Exception as e:
            logging.error(f"Ошибка загрузки базы данных: {e}")
    return {}

def save_data():
    """Сохранение данных в файл."""
    try:
        export_data = {str(k): list(v) for k, v in posts_data.items()}
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения базы данных: {e}")

# Инициализация хранилища
posts_data = load_data()

def is_admin(message):
    """Проверка прав администратора."""
    if message.from_user and message.from_user.username:
        return message.from_user.username.lower() in ADMINS
    return False

def get_thread_id(message):
    """Определение ID ветки, комментария или чата."""
    if message.message_thread_id:
        return message.message_thread_id
    if message.reply_to_message:
        return message.reply_to_message.message_id
    return message.chat.id

# ================= КОМАНДЫ БОТА =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        if not is_admin(message):
            bot.reply_to(message, "⛔ Доступ запрещен. Бот работает только для администрации.")
            return
        bot.reply_to(
            message, 
            "✅ **Бот полностью запущен и готов к работе!**\n\n"
            "• Добавьте бота в чат или канал с комментариями.\n"
            "• Бот автоматически собирает все теги `@username` из сообщений.\n"
            "• Для получения очищенного списка напишите `/collect` в ответе на пост или ветку."
        )
    except Exception as e:
        logging.error(f"Ошибка в команде /start: {e}")

@bot.message_handler(commands=['collect'])
def collect_comments(message):
    try:
        if not is_admin(message):
            bot.reply_to(message, "⛔ У вас нет прав для выполнения этой команды.")
            return
        
        thread_id = get_thread_id(message)
        collected = posts_data.get(thread_id, set())
        
        if not collected:
            bot.reply_to(message, "📭 Под этим постом/в этой ветке пока не найдено ни одного юзернейма.")
            return
        
        sorted_list = sorted(list(collected))
        
        response_text = f"📋 **Собранные юзернеймы ({len(sorted_list)} шт.):**\n\n"
        response_text += "\n".join(f"{i+1}. {tag}" for i, tag in enumerate(sorted_list))
        
        if len(response_text) > 4000:
            filename = f"usernames_{thread_id}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write("\n".join(sorted_list))
            with open(filename, "rb") as f:
                bot.send_document(message.chat.id, f, caption=f"✅ Полный список юзернеймов ({len(sorted_list)} шт.)")
            os.remove(filename)
        else:
            bot.reply_to(message, response_text, parse_mode="Markdown")
            
        logging.info(f"Админ @{message.from_user.username} выгрузил {len(sorted_list)} юзернеймов.")
    except Exception as e:
        logging.error(f"Ошибка в команде /collect: {e}")

# ================= АВТОМАТИЧЕСКИЙ СБОР ЮЗЕРНЕЙМОВ =================

@bot.message_handler(func=lambda message: True, content_types=['text', 'caption'])
def catch_usernames(message):
    try:
        text = message.text or message.caption or ""
        
        if text.startswith('/'):
            return

        found_usernames = re.findall(r'@[a-zA-Z0-9_]+', text)
        
        if found_usernames:
            thread_id = get_thread_id(message)
            if thread_id not in posts_data:
                posts_data[thread_id] = set()
            
            initial_count = len(posts_data[thread_id])
            for tag in found_usernames:
                posts_data[thread_id].add(tag)
            
            if len(posts_data[thread_id]) > initial_count:
                save_data()
                logging.info(f"Добавлено новых юзернеймов: {len(found_usernames)}. Всего в ветке {thread_id}: {len(posts_data[thread_id])}")
    except Exception as e:
        logging.error(f"Ошибка при обработке сообщения: {e}")

# ================= ВЕБ-СЕРВЕР ДЛЯ РЕНДЕРА И POLLING =================

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot status: OK")
        
    def log_message(self, format, *args):
        pass

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

if __name__ == '__main__':
    server_thread = threading.Thread(target=run_dummy_server, daemon=True)
    server_thread.start()
    
    logging.info("Веб-сервер успешно запущен. Старт опроса Telegram API...")
    
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            logging.error(f"Сбой соединения ({e}). Повторная попытка через 5 секунд...")
            time.sleep(5)
