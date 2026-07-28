import telebot
import logging
import os
import re
import json
import threading
import time
import random
import math
from http.server import BaseHTTPRequestHandler, HTTPServer

# 1. Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =====================================================================
TOKEN = "8876079721:AAEh9mZcoNmMXPqC9txDKMB-9RHd3lQPqGk"
# =====================================================================

bot = telebot.TeleBot(TOKEN)

# Список администраторов
ADMINS = ['wonti9', 'avelon67', 'nupik91']

# Файл базы данных
DB_FILE = "database.json"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "posts": {int(k): set(v) for k, v in data.get("posts", {}).items()},
                    "stats": data.get("stats", {"players": {}, "teams": {}})
                }
        except Exception as e:
            logging.error(f"Ошибка загрузки базы данных: {e}")
    return {"posts": {}, "stats": {"players": {}, "teams": {}}}

def save_data():
    try:
        export_data = {
            "posts": {str(k): list(v) for k, v in db["posts"].items()},
            "stats": db["stats"]
        }
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения базы данных: {e}")

# Инициализация хранилища
db = load_data()
posts_data = db["posts"]
tour_stats = db["stats"]

def is_admin(message):
    if message.from_user and message.from_user.username:
        return message.from_user.username.lower() in ADMINS
    return False

def get_thread_id(message):
    if message.message_thread_id:
        return message.message_thread_id
    if message.reply_to_message:
        return message.reply_to_message.message_id
    return message.chat.id

def calculate_elo(rating1, rating2, score1, score2):
    k = 32
    e1 = 1 / (1 + 10 ** ((rating2 - rating1) / 400))
    e2 = 1 / (1 + 10 ** ((rating1 - rating2) / 400))
    
    if score1 > score2:
        s1, s2 = 1, 0
    elif score1 < score2:
        s1, s2 = 0, 1
    else:
        s1, s2 = 0.5, 0.5
        
    new_r1 = rating1 + k * (s1 - e1)
    new_r2 = rating2 + k * (s2 - e2)
    
    return round(new_r1), round(new_r2)

def init_player(username):
    clean_name = username.replace('@', '')
    if clean_name not in tour_stats["players"]:
        tour_stats["players"][clean_name] = {
            "elo": 1000, 
            "goals_scored": 0, 
            "goals_conceded": 0, 
            "matches": 0
        }

# ================= КОМАНДЫ БОТА =================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        if not is_admin(message):
            bot.reply_to(message, "⛔ Доступ запрещен. Бот работает только для администрации.")
            return
        bot.reply_to(
            message, 
            "✅ Бот запущен\n\n"
            "• /collect — список собранных юзернеймов\n"
            "• /draw [соло/дуо/трио/4-4] [число] — провести жеребьевку\n"
            "• /results [текст] — ввести результаты матчей\n"
            "• /top [число] — Elo рейтинг участников\n"
            "• /stats — отдельная статистика турнира"
        )
    except Exception as e:
        logging.error(f"Ошибка в /start: {e}")

@bot.message_handler(commands=['collect'])
def collect_comments(message):
    try:
        if not is_admin(message):
            return
        thread_id = get_thread_id(message)
        collected = posts_data.get(thread_id, set())
        if not collected:
            bot.reply_to(message, "📭 Пока не найдено ни одного юзернейма.")
            return
        sorted_list = sorted(list(collected))
        response_text = f"📋 Собранные юзернеймы ({len(sorted_list)} шт.):\n\n"
        response_text += "\n".join(f"{i+1}. {tag}" for i, tag in enumerate(sorted_list))
        bot.reply_to(message, response_text)
    except Exception as e:
        logging.error(f"Ошибка в /collect: {e}")

# ================= ЖЕРЕБЬЕВКА (СОЛО, ДУО, ТРИО, 4v4) =================

@bot.message_handler(commands=['draw'])
def make_draw(message):
    try:
        if not is_admin(message):
            return
        
        thread_id = get_thread_id(message)
        collected = list(posts_data.get(thread_id, set()))
        
        if not collected:
            bot.reply_to(message, "📭 Под этой веткой/постом нет собранных участников.")
            return

        args = message.text.split()[1:]
        mode = "solo"
        custom_limit = None

        for arg in args:
            arg_lower = arg.lower()
            if arg_lower in ["solo", "соло", "1v1", "1-1"]:
                mode = "solo"
            elif arg_lower in ["duo", "дуо", "2v2", "2-2"]:
                mode = "duo"
            elif arg_lower in ["trio", "трио", "3v3", "3-3"]:
                mode = "trio"
            elif arg_lower in ["4v4", "4-4", "quad", "квартет", "squad"]:
                mode = "4v4"
            elif arg.isdigit():
                custom_limit = int(arg)

        team_sizes = {"solo": 1, "duo": 2, "trio": 3, "4v4": 4}
        mode_names = {"solo": "Соло", "duo": "Дуо", "trio": "Трио", "4v4": "4v4"}
        
        team_size = team_sizes[mode]
        mode_title = mode_names[mode]

        random.shuffle(collected)

        total_available = len(collected)
        if custom_limit and custom_limit < total_available:
            total_available = custom_limit

        total_teams = total_available // team_size

        if total_teams < 2:
            bot.reply_to(message, f"⚠️ Недостаточно участников для режима {mode_title}. Нужно минимум {team_size * 2} чел.")
            return

        playoff_teams_count = 2 ** int(math.log2(total_teams))
        players_needed = playoff_teams_count * team_size

        active_players = collected[:players_needed]
        reserve_players = collected[players_needed:]

        if playoff_teams_count == 2:
            stage_name = "Финал"
        elif playoff_teams_count == 4:
            stage_name = "1/2 Финала"
        elif playoff_teams_count == 8:
            stage_name = "1/4 Финала"
        elif playoff_teams_count == 16:
            stage_name = "1/8 Финала"
        elif playoff_teams_count == 32:
            stage_name = "1/16 Финала"
        elif playoff_teams_count == 64:
            stage_name = "1/32 Финала"
        else:
            stage_name = f"1/{playoff_teams_count // 2} Финала"

        msg = f"🏆 Жеребьевка ({mode_title}) — {stage_name}\n\n"

        if mode == "solo":
            match_num = 1
            for i in range(0, len(active_players), 2):
                p1 = active_players[i]
                p2 = active_players[i+1]
                msg += f"{match_num}. {p1} vs {p2}\n"
                match_num += 1
        else:
            teams = []
            for i in range(0, len(active_players), team_size):
                team_members = active_players[i:i+team_size]
                teams.append(team_members)
            
            for t_idx, team_members in enumerate(teams, 1):
                t_name = f"Команда {t_idx}"
                tour_stats["teams"][t_name] = team_members

            save_data()

            for i in range(0, len(teams), 2):
                t1_members = teams[i]
                t2_members = teams[i+1]
                t1_name = f"Команда {i+1}"
                t2_name = f"Команда {i+2}"

                msg += f"{t1_name} vs {t2_name}\n"
                msg += f"{t1_name}: {', '.join(t1_members)}\n"
                msg += f"{t2_name}: {', '.join(t2_members)}\n\n"

        if reserve_players:
            msg += f"\n⚠️ Запасные ({len(reserve_players)}):\n"
            msg += ", ".join(reserve_players)

        if len(msg) <= 4000:
            bot.reply_to(message, msg)
        else:
            chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
            for chunk in chunks:
                bot.send_message(message.chat.id, chunk)

    except Exception as e:
        logging.error(f"Ошибка в /draw: {e}")
        bot.reply_to(message, f"❌ Ошибка жеребьевки: {e}")

# ================= РЕЗУЛЬТАТЫ И СЕТКА =================

@bot.message_handler(commands=['results'])
def process_results(message):
    try:
        if not is_admin(message):
            return
        
        text = message.text.replace('/results', '').strip()
        if not text:
            bot.reply_to(message, "⚠️ Вставьте результаты матчей после команды /results")
            return

        # Нормализация переносов строк
        text = text.replace('\r\n', '\n')
        blocks = re.split(r'\n\s*\n', text)
        advancing_teams = []
        
        for block in blocks:
            team_match = re.search(r'(Команда \d+) (\d+):(\d+) (Команда \d+)', block)
            if not team_match:
                continue
                
            team1, t1_score, t2_score, team2 = team_match.groups()
            
            if int(t1_score) > int(t2_score):
                advancing_teams.append(team1)
            else:
                advancing_teams.append(team2)
                
            player_matches = re.findall(r'(@[a-zA-Z0-9_]+)\s+(\d+):(\d+)\s+(@[a-zA-Z0-9_]+)', block)
            
            team1_roster = set()
            team2_roster = set()
            
            for p1, p1_score, p2_score, p2 in player_matches:
                s1, s2 = int(p1_score), int(p2_score)
                init_player(p1)
                init_player(p2)
                
                name1 = p1.replace('@', '')
                name2 = p2.replace('@', '')
                
                team1_roster.add(p1)
                team2_roster.add(p2)
                
                tour_stats["players"][name1]["goals_scored"] += s1
                tour_stats["players"][name1]["goals_conceded"] += s2
                tour_stats["players"][name1]["matches"] += 1
                
                tour_stats["players"][name2]["goals_scored"] += s2
                tour_stats["players"][name2]["goals_conceded"] += s1
                tour_stats["players"][name2]["matches"] += 1
                
                old_r1 = tour_stats["players"][name1]["elo"]
                old_r2 = tour_stats["players"][name2]["elo"]
                new_r1, new_r2 = calculate_elo(old_r1, old_r2, s1, s2)
                
                tour_stats["players"][name1]["elo"] = new_r1
                tour_stats["players"][name2]["elo"] = new_r2
            
            tour_stats["teams"][team1] = list(team1_roster)
            tour_stats["teams"][team2] = list(team2_roster)

        save_data()

        if not advancing_teams:
            bot.reply_to(message, "❌ Не удалось распознать результаты. Проверьте формат.")
            return

        random.shuffle(advancing_teams)
        
        next_stage_text = "🏆 СЛЕДУЮЩИЙ ЭТАП\n\n"
        
        for i in range(0, len(advancing_teams), 2):
            if i + 1 >= len(advancing_teams):
                next_stage_text += f"{advancing_teams[i]} проходит далее без матча\n\n"
                break
                
            tA = advancing_teams[i]
            tB = advancing_teams[i+1]
            
            next_stage_text += f"{tA} vs {tB}\n"
            
            rosterA = tour_stats["teams"].get(tA, [])
            rosterB = tour_stats["teams"].get(tB, [])
            
            random.shuffle(rosterA)
            random.shuffle(rosterB)
            
            pairs_count = min(len(rosterA), len(rosterB))
            for j in range(pairs_count):
                next_stage_text += f"{rosterA[j]} vs {rosterB[j]}\n"
            next_stage_text += "\n"

        bot.reply_to(message, next_stage_text.strip())
        
    except Exception as e:
        logging.error(f"Ошибка в /results: {e}")
        bot.reply_to(message, f"❌ Ошибка обработки: {e}")

# ================= РЕЙТИНГ ELO (МИНИМАЛИСТИЧНЫЙ) =================

@bot.message_handler(commands=['top'])
def show_top(message):
    try:
        players = tour_stats.get("players", {})
        if not players:
            bot.reply_to(message, "📊 База игроков пуста.")
            return

        args = message.text.split()
        limit = 70
        if len(args) > 1 and args[1].isdigit():
            limit = int(args[1])

        sorted_players = sorted(players.items(), key=lambda x: x[1]["elo"], reverse=True)[:limit]

        lines = ["🏆 Mini Cup Elo"]
        for i, (name, data) in enumerate(sorted_players, 1):
            lines.append(f"{i}. {name} ({data['elo']})")

        full_text = "\n".join(lines)

        if len(full_text) <= 4000:
            bot.reply_to(message, full_text)
        else:
            chunk = ""
            for line in lines:
                if len(chunk) + len(line) + 1 > 4000:
                    bot.send_message(message.chat.id, chunk)
                    chunk = ""
                chunk += line + "\n"
            if chunk:
                bot.send_message(message.chat.id, chunk)

    except Exception as e:
        logging.error(f"Ошибка в /top: {e}")

# ================= ОТДЕЛЬНАЯ СТАТИСТИКА ТУРНИРА =================

@bot.message_handler(commands=['stats'])
def show_stats(message):
    try:
        players = tour_stats.get("players", {})
        if not players:
            bot.reply_to(message, "📊 Статистика пока пуста.")
            return

        active_players = [p for p in players.items() if p[1]["matches"] > 0]
        
        if not active_players:
            bot.reply_to(message, "📊 Матчи еще не были сыграны.")
            return

        top_scorers = sorted(active_players, key=lambda x: x[1]["goals_scored"], reverse=True)[:5]
        top_defenders = sorted(active_players, key=lambda x: x[1]["goals_conceded"])[:5]

        total_matches = sum(p[1]["matches"] for p in players.values()) // 2
        total_goals = sum(p[1]["goals_scored"] for p in players.values())

        msg = "📊 Статистика турнира\n\n"

        msg += "⚽️ Бомбардиры\n"
        for i, (name, data) in enumerate(top_scorers, 1):
            msg += f"{i}. @{name} — {data['goals_scored']}\n"

        msg += "\n🧤 Золотая перчатка\n"
        for i, (name, data) in enumerate(top_defenders, 1):
            msg += f"{i}. @{name} — {data['goals_conceded']} пропущено\n"

        msg += f"\n📌 Общие цифры\n"
        msg += f"• Матчей сыграно: {total_matches}\n"
        msg += f"• Забито голов: {total_goals}"

        bot.reply_to(message, msg)

    except Exception as e:
        logging.error(f"Ошибка в /stats: {e}")

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
    except Exception as e:
        logging.error(f"Ошибка при обработке сообщения: {e}")

# ================= ВЕБ-СЕРВЕР ДЛЯ РЕНДЕРА =================

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
    
    logging.info("Веб-сервер запущен. Старт бота...")
    
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            logging.error(f"Сбой соединения ({e}). Повтор через 5 секунд...")
            time.sleep(5)
