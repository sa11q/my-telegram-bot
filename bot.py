import telebot
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# 1. Настройка правильного логирования (логи будут появляться в Render моментально)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Твой рабочий токен
TOKEN = "8876079721:AAGrdHpZdta93TRUQBwLgcJLmIsCwiAfUKE"
bot = telebot.TeleBot(TOKEN)

# Список админов (строго в нижнем регистре)
ADMINS = ['wonti9', 'avelon67', 'nupik91']

# 2. Надежная проверка прав (учитывает отсутствие юзернейма)
def is_admin(message):
    username = message.from_user.username
    if username:
        return username.lower() in ADMINS
    return False

# 3. Обработка команд с защитой от падений
@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        if not is_admin(message):
            bot.reply_to(message, "⛔ Доступ запрещен. Бот только для администрации.")
            logging.warning(f"Несанкционированный доступ от пользователя ID: {message.from_user.id}")
            return
        
        bot.reply_to(message, "✅ Привет! Бот успешно запущен, защищен и готов к работе.")
        logging.info(f"Админ @{message.from_user.username} запустил бота.")
    except Exception as e:
        logging.error(f"Ошибка в команде /start: {e}")

@bot.message_handler(commands=['collect'])
def collect_comments(message):
    try:
        if not is_admin(message):
            bot.reply_to(message, "⛔ У вас нет прав для этой команды.")
            return
        
        bot.reply_to(message, "⚙️ Команда /collect принята. Начинаю работу...")
        logging.info(f"Админ @{message.from_user.username} вызвал /collect.")
        
        # Тут в будущем будет логика сбора комментариев
        
    except Exception as e:
        logging.error(f"Ошибка в команде /collect: {e}")

# 4. ФЕЙКОВЫЙ ВЕБ-СЕРВЕР ДЛЯ RENDER (Чтобы Render не убивал бота)
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"Bot is alive and running!")
        
    # Отключаем лишний спам в логах от пингов Render'а
    def log_message(self, format, *args):
        pass

def run_dummy_server():
    # Render сам выдает нужный порт через переменную окружения PORT
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    logging.info(f"Запущен веб-сервер для Render на порту {port}")
    server.serve_forever()

# 5. Главный блок запуска
if __name__ == '__main__':
    # Запускаем фейковый сервер в параллельном потоке
    server_thread = threading.Thread(target=run_dummy_server, daemon=True)
    server_thread.start()
    
    logging.info("Бот успешно стартовал и подключился к Telegram API!")
    
    # Запускаем самого бота с параметрами для поддержания стабильного соединения
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            logging.error(f"Критическая ошибка опроса: {e}. Перезапуск через 5 секунд...")
            import time
            time.sleep(5)
