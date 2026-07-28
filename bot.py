import telebot
import logging
import os
import re
import json
import random
import math
import time
import tempfile
import threading
import shutil
from datetime import datetime, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# 1. Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# =====================================================================
TOKEN = "8876079721:AAFMECzB5jkywB1J8ks66qgXg_YMzDMD6dU"
# =====================================================================

bot = telebot.TeleBot(TOKEN, parse_mode=None)

# Системная блокировка для безопасной многопоточной работы с данными
db_lock = threading.Lock()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.json")
DB_BACKUP_FILE = os.path.join(BASE_DIR, "database_backup.json")

# =====================================================================
#  БАЗА ДАННЫХ И МИГРАЦИЯ
# =====================================================================

def get_default_db():
    return {
        "database_version": 1,
        "active_tournament": {
            "title": "Mini Cup",
            "mode": "solo",  # solo, duo, trio, 4v4
            "registration_open": False,
            "registered_players": [],
            "banned_players": [],
            "stage": 1,
            "stage_name": "1/8 Финала",
            "deadline": None,
            "reminder_sent": False,
            "chat_id": None,
            "teams": {},       # {"Команда 1": ["@user1", ...]}
            "matches": [],     # [{"id": "m1", "t1": "...", "t2": "...", "p1": "...", "p2": "...", "s1": None, "s2": None, "done": False}]
            "history": [],     # Сыгранные матчи прошлых этапов
            "auto_next": True,
            "auto_deadline": True
        },
        "archived_tournaments": [],
        "champions": [],
        "stats": {
            "players": {}
        },
        "settings": {
            "admins": ['wonti9', 'avelon67', 'nupik91']
        }
    }

def load_data():
    with db_lock:
        data = None
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logging.error(f"Ошибка чтения database.json: {e}")
                data = None

        if data is None and os.path.exists(DB_BACKUP_FILE):
            try:
                logging.info("Попытка загрузки из database_backup.json...")
                with open(DB_BACKUP_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logging.error(f"Ошибка чтения database_backup.json: {e}")
                data = None

        if data is None:
            return get_default_db()

        default_db = get_default_db()
        
        # Проверка и добавление версии базы данных
        if "database_version" not in data:
            data["database_version"] = 1

        # Структурная валидация ключей
        if "active_tournament" not in data:
            data["active_tournament"] = default_db["active_tournament"]
        else:
            for k, v in default_db["active_tournament"].items():
                if k not in data["active_tournament"]:
                    data["active_tournament"][k] = v

        if "stats" not in data or "players" not in data["stats"]:
            data["stats"] = {"players": {}}
        if "champions" not in data:
            data["champions"] = []
        if "archived_tournaments" not in data:
            data["archived_tournaments"] = []
        if "settings" not in data:
            data["settings"] = default_db["settings"]
            
        return data

def save_data_internal(data):
    try:
        if os.path.exists(DB_FILE):
            try:
                shutil.copy2(DB_FILE, DB_BACKUP_FILE)
            except Exception as e:
                logging.error(f"Ошибка создания бэкапа БД: {e}")

        dir_name = os.path.dirname(DB_FILE)
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding="utf-8") as tf:
            json.dump(data, tf, ensure_ascii=False, indent=2)
            temp_name = tf.name
        os.replace(temp_name, DB_FILE)
    except Exception as e:
        logging.error(f"Ошибка сохранения БД: {e}")

def save_data():
    with db_lock:
        save_data_internal(db)

db = load_data()

# Автоматическое создание/дополнение базы, если отсутствуют ключевые поля
default_template = get_default_db()
data_changed = False
for key in ["active_tournament", "stats", "champions", "archived_tournaments", "settings"]:
    if key not in db:
        db[key] = default_template[key]
        data_changed = True

if data_changed:
    save_data()

# =====================================================================
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И ПРОВЕРКИ
# =====================================================================

def is_group(message):
    return message.chat.type in ['group', 'supergroup']

def is_admin(user_id_or_username):
    if not user_id_or_username:
        return False
    clean_name = str(user_id_or_username).replace('@', '').lower()
    admins = [a.lower() for a in db["settings"]["admins"]]
    return clean_name in admins

def normalize_username(username):
    if not username:
        return ""
    clean = username.strip()
    if not clean.startswith('@'):
        clean = '@' + clean
    return clean

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
        
    return round(rating1 + k * (s1 - e1)), round(rating2 + k * (s2 - e2))

def init_player(username):
    clean = username.replace('@', '')
    players = db["stats"]["players"]
    if clean not in players:
        players[clean] = {
            "elo": 1000,
            "goals_scored": 0,
            "goals_conceded": 0,
            "matches": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "current_win_streak": 0,
            "max_win_streak": 0,
            "current_loss_streak": 0,
            "max_loss_streak": 0,
            "biggest_win": 0,
            "biggest_loss": 0,
            "last_opponent": None,
            "championships": 0,
            "match_history": []
        }

def recalculate_all_stats():
    players = db["stats"]["players"]
    for p in players:
        players[p]["elo"] = 1000
        players[p]["wins"] = 0
        players[p]["losses"] = 0
        players[p]["draws"] = 0
        players[p]["goals_scored"] = 0
        players[p]["goals_conceded"] = 0
        players[p]["matches"] = 0
        players[p]["current_win_streak"] = 0
        players[p]["max_win_streak"] = 0
        players[p]["current_loss_streak"] = 0
        players[p]["max_loss_streak"] = 0
        players[p]["biggest_win"] = 0
        players[p]["biggest_loss"] = 0
        players[p]["match_history"] = []

    all_matches = []
    
    for arch in db.get("archived_tournaments", []):
        for m in arch.get("history", []):
            if m.get("done"):
                all_matches.append(m)
                
    active_tour = db["active_tournament"]
    for m in active_tour.get("history", []):
        if m.get("done"):
            all_matches.append(m)
    for m in active_tour.get("matches", []):
        if m.get("done"):
            all_matches.append(m)

    for m in all_matches:
        p1, p2, s1, s2 = m["p1"], m["p2"], m["s1"], m["s2"]
        init_player(p1)
        init_player(p2)
        n1, n2 = p1.replace('@', ''), p2.replace('@', '')
        
        p1_s = players[n1]
        p2_s = players[n2]
        
        p1_s["goals_scored"] += s1
        p1_s["goals_conceded"] += s2
        p1_s["matches"] += 1
        
        p2_s["goals_scored"] += s2
        p2_s["goals_conceded"] += s1
        p2_s["matches"] += 1
        
        diff1 = s1 - s2
        diff2 = s2 - s1
        
        if diff1 > p1_s["biggest_win"]: p1_s["biggest_win"] = diff1
        if diff1 < 0 and abs(diff1) > p1_s["biggest_loss"]: p1_s["biggest_loss"] = abs(diff1)
        
        if diff2 > p2_s["biggest_win"]: p2_s["biggest_win"] = diff2
        if diff2 < 0 and abs(diff2) > p2_s["biggest_loss"]: p2_s["biggest_loss"] = abs(diff2)
        
        if s1 > s2:
            p1_s["wins"] += 1
            p2_s["losses"] += 1
            p1_s["current_win_streak"] += 1
            p1_s["current_loss_streak"] = 0
            if p1_s["current_win_streak"] > p1_s["max_win_streak"]:
                p1_s["max_win_streak"] = p1_s["current_win_streak"]
            
            p2_s["current_loss_streak"] += 1
            p2_s["current_win_streak"] = 0
            if p2_s["current_loss_streak"] > p2_s["max_loss_streak"]:
                p2_s["max_loss_streak"] = p2_s["current_loss_streak"]
        elif s1 < s2:
            p1_s["losses"] += 1
            p2_s["wins"] += 1
            p1_s["current_loss_streak"] += 1
            p1_s["current_win_streak"] = 0
            if p1_s["current_loss_streak"] > p1_s["max_loss_streak"]:
                p1_s["max_loss_streak"] = p1_s["current_loss_streak"]
            
            p2_s["current_win_streak"] += 1
            p2_s["current_loss_streak"] = 0
            if p2_s["current_win_streak"] > p1_s["max_win_streak"]:
                p1_s["max_win_streak"] = p1_s["current_win_streak"]
        else:
            p1_s["draws"] += 1
            p2_s["draws"] += 1
            p1_s["current_win_streak"] = 0
            p1_s["current_loss_streak"] = 0
            p2_s["current_win_streak"] = 0
            p2_s["current_loss_streak"] = 0
            
        old_r1, old_r2 = p1_s["elo"], p2_s["elo"]
        p1_s["elo"], p2_s["elo"] = calculate_elo(old_r1, old_r2, s1, s2)
        
        p1_s["last_opponent"] = p2
        p2_s["last_opponent"] = p1
        
        m_record = {"p1": p1, "p2": p2, "s1": s1, "s2": s2}
        p1_s["match_history"].append(m_record)
        p2_s["match_history"].append(m_record)

# =====================================================================
#  ЛОГИКА ДЕДЛАЙНОВ И ТАЙМЕРОВ
# =====================================================================

def calculate_auto_deadline():
    now = datetime.now()
    if now.hour >= 22 or now.hour < 6:
        target_date = now if now.hour < 6 else now + timedelta(days=1)
        deadline_dt = datetime(target_date.year, target_date.month, target_date.day, 17, 0, 0)
    else:
        deadline_dt = now + timedelta(hours=1, minutes=30)
    return deadline_dt.strftime("%Y-%m-%d %H:%M")

def deadline_reminder_thread():
    while True:
        try:
            time.sleep(30)
            active = db["active_tournament"]
            if active.get("deadline") and not active.get("reminder_sent", False):
                deadline_dt = datetime.strptime(active["deadline"], "%Y-%m-%d %H:%M")
                now = datetime.now()
                time_left = (deadline_dt - now).total_seconds()
                
                if 0 < time_left <= 1800:
                    chat_id = active.get("chat_id")
                    if chat_id:
                        unplayed = [m for m in active["matches"] if not m["done"]]
                        if unplayed:
                            players_list = []
                            for m in unplayed:
                                players_list.extend([m["p1"], m["p2"]])
                            
                            p_str = " ".join(set(players_list))
                            msg = (
                                f"⏰ **ВНИМАНИЕ! ДО ДЕДЛАЙНА ОСТАЛОСЬ 30 МИНУТ!**\n\n"
                                f"Несыгранные матчи:\n"
                            )
                            for m in unplayed:
                                msg += f"• {m['p1']} vs {m['p2']}\n"
                            msg += f"\nИгроки: {p_str}\nПожалуйста, доиграйте свои матчи!"
                            
                            try:
                                bot.send_message(chat_id, msg)
                            except Exception as ex:
                                logging.error(f"Ошибка отправки напоминания: {ex}")
                    
                    active["reminder_sent"] = True
                    save_data()
        except Exception as e:
            logging.error(f"Ошибка в фоновом потоке дедлайнов: {e}")

threading.Thread(target=deadline_reminder_thread, daemon=True).start()

# =====================================================================
#  ГЕНЕРАЦИЯ И ОФОРМЛЕНИЕ СЕТКИ
# =====================================================================

def get_stage_title(teams_count):
    if teams_count == 2:
        return "🏆 ФИНАЛ"
    elif teams_count == 4:
        return "🏆 1/2 ФИНАЛА"
    elif teams_count == 8:
        return "🏆 1/4 ФИНАЛА"
    elif teams_count == 16:
        return "🏆 1/8 ФИНАЛА"
    elif teams_count == 32:
        return "🏆 1/16 ФИНАЛА"
    else:
        return f"🏆 ЭТАП ({teams_count} команд)"

def format_bracket_text():
    active = db["active_tournament"]
    matches = active.get("matches", [])
    teams = active.get("teams", {})
    mode = active.get("mode", "solo")
    
    if not matches:
        return "📭 Активная турнирная сетка отсутствует."

    title = active.get("stage_name", "Турнирный этап")
    tour_title = active.get("title", "Mini Cup")
    
    msg = f"{title} — {tour_title}\n\n"

    team_pairs = {}
    for m in matches:
        pair_key = (m["t1"], m["t2"])
        if pair_key not in team_pairs:
            team_pairs[pair_key] = []
        team_pairs[pair_key].append(m)

    for (t1, t2), match_list in team_pairs.items():
        t1_goals = sum(m["s1"] for m in match_list if m["done"] and m["s1"] is not None)
        t2_goals = sum(m["s2"] for m in match_list if m["done"] and m["s2"] is not None)
        
        if mode != "solo":
            msg += f"⚔️ {t1} [{t1_goals}] vs [{t2_goals}] {t2}\n"

        for m in match_list:
            if m["done"]:
                score_str = f"{m['s1']}:{m['s2']}"
                status = "✅"
            else:
                score_str = "vs"
                status = "⏳"
            
            msg += f"• {m['p1']} {score_str} {m['p2']} {status}\n"

        msg += "────────────\n"

    dl = active.get("deadline")
    if dl:
        try:
            dl_dt = datetime.strptime(dl, "%Y-%m-%d %H:%M")
            msg += f"\n🔴 Дедлайн → {dl_dt.strftime('%H:%M (%d.%m)')}\n"
        except Exception:
            msg += f"\n🔴 Дедлайн → {dl}\n"

    return msg.strip()

# =====================================================================
#  АВТОМАТИЧЕСКИЙ И РУЧНОЙ ПЕРЕХОД ЭТАПОВ
# =====================================================================

def advance_stage(chat_id=None):
    active = db["active_tournament"]
    matches = active.get("matches", [])
    teams_dict = active.get("teams", {})
    mode = active.get("mode", "solo")

    if not matches:
        return False, "Сетка пуста."

    team_pairs = {}
    for m in matches:
        pair_key = (m["t1"], m["t2"])
        if pair_key not in team_pairs:
            team_pairs[pair_key] = []
        team_pairs[pair_key].append(m)

    advancing_teams = []

    for (t1, t2), match_list in team_pairs.items():
        t1_goals = sum(m["s1"] for m in match_list if m["done"] and m["s1"] is not None)
        t2_goals = sum(m["s2"] for m in match_list if m["done"] and m["s2"] is not None)

        if t1_goals > t2_goals:
            advancing_teams.append(t1)
        elif t2_goals > t1_goals:
            advancing_teams.append(t2)
        else:
            winner = random.choice([t1, t2])
            advancing_teams.append(winner)
            if chat_id:
                try:
                    bot.send_message(chat_id, f"⚖️ Ничья в противостоянии {t1} - {t2}. По жребию проходит: {winner}")
                except Exception:
                    pass

    for m in matches:
        active["history"].append(dict(m))

    active["stage"] += 1

    if len(advancing_teams) <= 1:
        champion = advancing_teams[0] if advancing_teams else "Не определен"
        
        if mode == "solo":
            clean_champ = champion.replace('@', '')
            init_player(champion)
            db["stats"]["players"][clean_champ]["championships"] += 1
        else:
            roster = teams_dict.get(champion, [])
            for member in roster:
                clean_m = member.replace('@', '')
                init_player(member)
                db["stats"]["players"][clean_m]["championships"] += 1

        champ_record = {
            "tournament": active.get("title", "Mini Cup"),
            "champion": champion,
            "date": time.strftime("%Y-%m-%d %H:%M")
        }
        db["champions"].append(champ_record)

        db["archived_tournaments"].append(dict(active))
        
        active["registration_open"] = False
        active["registered_players"] = []
        active["matches"] = []
        active["teams"] = {}
        active["stage"] = 1
        active["stage_name"] = "Завершен"
        active["deadline"] = None

        save_data()
        
        final_msg = f"🎉 **ТУРНИР ЗАВЕРШЕН!**\n\n🏆 Победитель турнира: **{champion}**!"
        if chat_id:
            bot.send_message(chat_id, final_msg)
        return True, final_msg

    active["stage_name"] = get_stage_title(len(advancing_teams))
    new_teams_dict = {}
    new_matches = []

    random.shuffle(advancing_teams)
    
    for i in range(0, len(advancing_teams), 2):
        if i + 1 >= len(advancing_teams):
            pass
        
        tA = advancing_teams[i]
        tB = advancing_teams[i+1]
        
        rosterA = teams_dict.get(tA, [tA])
        rosterB = teams_dict.get(tB, [tB])
        
        new_teams_dict[tA] = rosterA
        new_teams_dict[tB] = rosterB
        
        rA_copy = list(rosterA)
        rB_copy = list(rosterB)
        random.shuffle(rA_copy)
        random.shuffle(rB_copy)

        for j in range(min(len(rA_copy), len(rB_copy))):
            match_id = f"m_{active['stage']}_{i}_{j}"
            new_matches.append({
                "id": match_id,
                "t1": tA, "t2": tB,
                "p1": rA_copy[j], "p2": rB_copy[j],
                "s1": None, "s2": None, "done": False, "sender": None
            })

    active["teams"] = new_teams_dict
    active["matches"] = new_matches
    
    if active.get("auto_deadline", True):
        active["deadline"] = calculate_auto_deadline()
        active["reminder_sent"] = False

    save_data()

    bracket_msg = format_bracket_text()
    if chat_id:
        bot.send_message(chat_id, f"🔄 **АВТОМАТИЧЕСКИЙ ПЕРЕХОД НА СЛЕДУЮЩИЙ ЭТАП!**\n\n{bracket_msg}")

    return True, bracket_msg

# =====================================================================
#  КОМАНДЫ ДЛЯ ВСЕХ ИГРОКОВ (ГРУППОВОЙ ЧАТ)
# =====================================================================

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        text = (
            "🤖 **БОТ УПРАВЛЕНИЯ ФУТБОЛЬНЫМИ ТУРНИРАМИ**\n\n"
            "📌 Основные команды:\n"
            "• `/join` или `●` — Зарегистрироваться на турнир\n"
            "• `@player1 2:3 @player2` — Отправить результат матча\n"
            "• `/bracket` — Актуальная турнирная сетка\n"
            "• `/profile [@user]` — Турнирный паспорт игрока\n"
            "• `/stats` — Общая статистика\n"
            "• `/top` — Топ игроков по Elo\n"
            "• `/champions` — Зал славы (Чемпионы)\n"
            "• `/vs` — Узнать текущего соперника\n"
            "• `/recent` — Последние результаты\n"
            "• `/rules` — Правила и формат ввода результатов\n"
            "• `/admin` — Панель администратора (Inline)"
        )
        bot.reply_to(message, text, parse_mode="Markdown")
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['rules'])
def send_rules(message):
    try:
        rules_text = (
            "📜 **ПРАВИЛА И ИНСТРУКЦИЯ**\n\n"
            "1️⃣ **Регистрация**:\n"
            "Когда администратор открывает регистрацию, просто отправьте в чат `/join` или символ `●`.\n\n"
            "2️⃣ **Отправка результатов**:\n"
            "Результат должен отправляться в формате:\n"
            "`@player1 2:3 @player2`\n\n"
            "3️⃣ **Подтверждение**:\n"
            "Сообщение с результатом должен написать один из участников данного матча.\n\n"
            "4️⃣ **Дедлайны**:\n"
            "Каждый этап имеет ограничение по времени. За 30 минут приходит предупреждение."
        )
        bot.reply_to(message, rules_text, parse_mode="Markdown")
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['join'], func=is_group)
@bot.message_handler(func=lambda m: is_group(m) and m.text and m.text.strip() == "●")
def register_player(message):
    try:
        if not message.from_user or not message.from_user.username:
            bot.reply_to(message, "⚠️ У вас нет username в Telegram. Установите его в настройках профиля.")
            return

        username = normalize_username(message.from_user.username)
        active = db["active_tournament"]

        if not active.get("registration_open", False):
            bot.reply_to(message, "❌ Регистрация на турнир сейчас закрыта.")
            return

        banned = [b.lower() for b in active.get("banned_players", [])]
        if username.lower() in banned:
            bot.reply_to(message, "⛔️ Вы заблокированы для участия в турнирах.")
            return

        registered = active.get("registered_players", [])
        if username in registered:
            bot.reply_to(message, f"ℹ️ {username}, вы уже зарегистрированы!\n👥 Всего участников: {len(registered)}")
            return

        registered.append(username)
        active["chat_id"] = message.chat.id
        save_data()

        bot.reply_to(message, f"✅ {username} успешно зарегистрирован!\n👥 Всего участников: {len(registered)}")
    except Exception as e:
        logging.error(f"Join error: {e}")

@bot.message_handler(commands=['bracket', 'сетка'], func=is_group)
def show_bracket_cmd(message):
    try:
        text = format_bracket_text()
        bot.reply_to(message, text)
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['vs', 'соперник'], func=is_group)
def show_vs(message):
    try:
        if not message.from_user or not message.from_user.username:
            return
        username = normalize_username(message.from_user.username).lower()

        active = db["active_tournament"]
        for m in active.get("matches", []):
            if not m["done"]:
                p1_clean = m["p1"].lower()
                p2_clean = m["p2"].lower()
                if p1_clean == username:
                    return bot.reply_to(message, f"⚔️ Твой текущий соперник: **{m['p2']}** (Команда {m['t2']})", parse_mode="Markdown")
                elif p2_clean == username:
                    return bot.reply_to(message, f"⚔️ Твой текущий соперник: **{m['p1']}** (Команда {m['t1']})", parse_mode="Markdown")

        bot.reply_to(message, "📭 У вас нет активных несыгранных матчей на данном этапе.")
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['profile', 'профиль'])
def show_profile(message):
    try:
        args = message.text.split()
        if len(args) > 1:
            target = args[1]
        else:
            target = message.from_user.username if message.from_user else None

        if not target:
            return bot.reply_to(message, "⚠️ Укажите пользователя. Пример: `/profile @username`", parse_mode="Markdown")

        clean_name = target.replace('@', '').lower()
        players = db["stats"]["players"]

        actual_name = None
        for p in players:
            if p.lower() == clean_name:
                actual_name = p
                break

        if not actual_name:
            return bot.reply_to(message, f"📭 Профиль для @{clean_name} не найден. Необходимо сыграть хотя бы 1 матч.")

        data = players[actual_name]
        diff = data['goals_scored'] - data['goals_conceded']
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        
        matches = data['matches']
        wins = data['wins']
        losses = data['losses']
        draws = data['draws']
        winrate = round((wins / matches * 100), 1) if matches > 0 else 0.0

        text = (
            f"🎟 **ТУРНИРНЫЙ ПАСПОРТ**\n\n"
            f"👤 Игрок: @{actual_name}\n"
            f"🏆 Рейтинг Elo: **{data['elo']}**\n"
            f"📊 Матчей: {matches} (П: {wins} | Н: {draws} | Пр: {losses})\n"
            f"📈 WinRate: {winrate}%\n"
            f"🔥 Серия побед: текущая {data['current_win_streak']} (макс. {data['max_win_streak']})\n"
            f"❄️ Серия поражений: текущая {data['current_loss_streak']} (макс. {data['max_loss_streak']})\n"
            f"⚽️ Забито: {data['goals_scored']} | 🧤 Пропущено: {data['goals_conceded']} (Разница: {diff_str})\n"
            f"💥 Самая крупная победа: +{data['biggest_win']}\n"
            f"💀 Самое крупное поражение: -{data['biggest_loss']}\n"
            f"👥 Последний соперник: {data['last_opponent'] or 'Нет'}\n"
            f"🥇 Чемпионств: {data['championships']}"
        )
        bot.reply_to(message, text, parse_mode="Markdown")
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['stats', 'статистика'])
def show_stats(message):
    try:
        players = list(db["stats"]["players"].items())
        if not players:
            return bot.reply_to(message, "📊 Статистика пуста.")

        best_elo = max(players, key=lambda x: x[1]["elo"])
        
        qualified_wr = [(n, d, (d["wins"]/d["matches"]*100) if d["matches"]>0 else 0) for n, d in players if d["matches"] >= 2]
        best_wr = max(qualified_wr, key=lambda x: x[2]) if qualified_wr else ("Нет", None, 0)

        best_scorer = max(players, key=lambda x: x[1]["goals_scored"])
        
        qualified_def = [(n, d) for n, d in players if d["matches"] > 0]
        best_def = min(qualified_def, key=lambda x: x[1]["goals_conceded"]) if qualified_def else ("Нет", {"goals_conceded": 0})
        
        best_streak = max(players, key=lambda x: x[1]["max_win_streak"])

        total_matches = sum(d["matches"] for _, d in players) // 2
        total_goals = sum(d["goals_scored"] for _, d in players)
        avg_goals = round(total_goals / total_matches, 2) if total_matches > 0 else 0.0

        msg = (
            f"📊 **ОБЩАЯ СТАТИСТИКА**\n\n"
            f"🏆 Лучший Elo: @{best_elo[0]} ({best_elo[1]['elo']})\n"
            f"📈 Лучший WinRate: @{best_wr[0]} ({round(best_wr[2], 1)}%)\n"
            f"⚽️ Бомбардир: @{best_scorer[0]} ({best_scorer[1]['goals_scored']} голов)\n"
            f"🛡 Защита: @{best_def[0]} ({best_def[1]['goals_conceded']} проп.)\n"
            f"🔥 Рекорд побед подряд: @{best_streak[0]} ({best_streak[1]['max_win_streak']})\n\n"
            f"📌 Всего сыграно матчей: {total_matches}\n"
            f"⚽️ Среднее число голов за матч: {avg_goals}"
        )
        bot.reply_to(message, msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['top', 'топ'])
def show_top(message):
    try:
        players = db["stats"]["players"]
        if not players:
            return bot.reply_to(message, "📊 База игроков пуста.")

        sorted_players = sorted(players.items(), key=lambda x: x[1]["elo"], reverse=True)[:50]
        
        msg = "🏆 **ТОП ИГРОКОВ ПО ELO**\n\n"
        for i, (name, data) in enumerate(sorted_players, 1):
            msg += f"{i}. @{name} — {data['elo']} Elo ({data['wins']}В/{data['draws']}Н/{data['losses']}П)\n"

        bot.reply_to(message, msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['champions', 'чемпионы'])
def show_champions(message):
    try:
        champs = db.get("champions", [])
        if not champs:
            return bot.reply_to(message, "🏆 Зал славы пока пуст.")

        msg = "🏆 **ЗАЛ СЛАВЫ (ЧЕМПИОНЫ)**\n\n"
        for c in champs:
            msg += f"• {c['tournament']} ({c['date']}): 🏆 **{c['champion']}**\n"

        bot.reply_to(message, msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['recent'])
def show_recent(message):
    try:
        active = db["active_tournament"]
        history = active.get("history", []) + [m for m in active.get("matches", []) if m["done"]]
        if not history:
            return bot.reply_to(message, "📭 Сыгранные матчи отсутствуют.")

        msg = "⏱ **ПОСЛЕДНИЕ РЕЗУЛЬТАТЫ**\n\n"
        for m in history[-10:]:
            msg += f"• {m['p1']} {m['s1']}:{m['s2']} {m['p2']}\n"

        bot.reply_to(message, msg, parse_mode="Markdown")
    except Exception as e:
        logging.error(e)

# =====================================================================
#  ИНТЕРАКТИВНАЯ ИНЛАЙН АДМИН-ПАНЕЛЬ (/admin)
# =====================================================================

def build_admin_main_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🏆 Турнир", callback_data="adm_tour"),
        InlineKeyboardButton("👥 Игроки", callback_data="adm_players")
    )
    kb.add(
        InlineKeyboardButton("⚔️ Матчи", callback_data="adm_matches"),
        InlineKeyboardButton("⏰ Дедлайн", callback_data="adm_deadline")
    )
    kb.add(
        InlineKeyboardButton("📊 Статистика", callback_data="adm_stats"),
        InlineKeyboardButton("⚙️ Настройки", callback_data="adm_settings")
    )
    kb.add(
        InlineKeyboardButton("❌ Закрыть", callback_data="adm_close")
    )
    return kb

def build_admin_back_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="adm_main"))
    return kb

@bot.message_handler(commands=['admin', 'админ'])
def open_admin_panel(message):
    try:
        if not is_admin(message.from_user.username):
            bot.reply_to(message, "⛔️ Доступ запрещен. Вы не являетесь администратором.")
            return

        bot.send_message(
            message.chat.id,
            "👑 **АДМИН-ПАНЕЛЬ**\nВыберите нужный раздел:",
            reply_markup=build_admin_main_kb(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(e)

@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith('adm_'))
def handle_admin_callbacks(call):
    if not is_admin(call.from_user.username):
        bot.answer_callback_query(call.id, "⛔️ Доступ запрещен.", show_alert=True)
        return

    data = call.data
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    try:
        if data == "adm_main":
            bot.edit_message_text(
                "👑 **АДМИН-ПАНЕЛЬ**\nВыберите нужный раздел:",
                chat_id,
                message_id,
                reply_markup=build_admin_main_kb(),
                parse_mode="Markdown"
            )
        elif data == "adm_tour":
            active = db["active_tournament"]
            reg_status = "Открыта" if active.get("registration_open") else "Закрыта"
            text = (
                f"🏆 **ТУРНИР**\n\n"
                f"• Название: {active.get('title')}\n"
                f"• Режим: {active.get('mode')}\n"
                f"• Регистрация: {reg_status}\n"
                f"• Участников: {len(active.get('registered_players', []))}\n"
                f"• Этап: {active.get('stage_name')}"
            )
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(
                InlineKeyboardButton("🟢 Открыть регистрацию", callback_data="adm_tour_open"),
                InlineKeyboardButton("🔴 Закрыть регистрацию", callback_data="adm_tour_close"),
                InlineKeyboardButton("🔄 Переключить этап", callback_data="adm_tour_next_stage"),
                InlineKeyboardButton("⬅️ Назад", callback_data="adm_main")
            )
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="Markdown")

        elif data == "adm_tour_open":
            db["active_tournament"]["registration_open"] = True
            save_data()
            bot.answer_callback_query(call.id, "🟢 Регистрация открыта!")
            call.data = "adm_tour"
            handle_admin_callbacks(call)

        elif data == "adm_tour_close":
            db["active_tournament"]["registration_open"] = False
            save_data()
            bot.answer_callback_query(call.id, "🔴 Регистрация закрыта!")
            call.data = "adm_tour"
            handle_admin_callbacks(call)

        elif data == "adm_tour_next_stage":
            success, msg = advance_stage(chat_id)
            bot.answer_callback_query(call.id, "🔄 Этап обновлен!")
            bot.edit_message_text(f"🔄 **Результат перехода этапа:**\n\n{msg}", chat_id, message_id, reply_markup=build_admin_back_kb(), parse_mode="Markdown")

        elif data == "adm_players":
            players = db["stats"]["players"]
            text = f"👥 **ИГРОКИ**\n\nВсего в базе: {len(players)} игроков."
            bot.edit_message_text(text, chat_id, message_id, reply_markup=build_admin_back_kb(), parse_mode="Markdown")

        elif data == "adm_matches":
            active = db["active_tournament"]
            matches = active.get("matches", [])
            text = f"⚔️ **МАТЧИ**\n\nАктивных матчей: {len(matches)}"
            bot.edit_message_text(text, chat_id, message_id, reply_markup=build_admin_back_kb(), parse_mode="Markdown")

        elif data == "adm_deadline":
            active = db["active_tournament"]
            dl = active.get("deadline") or "Не установлен"
            text = f"⏰ **ДЕДЛАЙН**\n\nТекущий дедлайн: {dl}"
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(
                InlineKeyboardButton("🕒 Установить авто-дедлайн (+1.5ч)", callback_data="adm_dl_auto"),
                InlineKeyboardButton("❌ Сбросить дедлайн", callback_data="adm_dl_clear"),
                InlineKeyboardButton("⬅️ Назад", callback_data="adm_main")
            )
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="Markdown")

        elif data == "adm_dl_auto":
            db["active_tournament"]["deadline"] = calculate_auto_deadline()
            db["active_tournament"]["reminder_sent"] = False
            save_data()
            bot.answer_callback_query(call.id, "⏰ Авто-дедлайн установлен!")
            call.data = "adm_deadline"
            handle_admin_callbacks(call)

        elif data == "adm_dl_clear":
            db["active_tournament"]["deadline"] = None
            save_data()
            bot.answer_callback_query(call.id, "❌ Дедлайн сброшен!")
            call.data = "adm_deadline"
            handle_admin_callbacks(call)

        elif data == "adm_stats":
            players = db["stats"]["players"]
            text = f"📊 **СТАТИСТИКА**\n\nЗаписано игроков: {len(players)}\nВсего турниров в архиве: {len(db.get('archived_tournaments', []))}"
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(
                InlineKeyboardButton("🔄 Пересчитать всю статистику", callback_data="adm_recalc"),
                InlineKeyboardButton("⬅️ Назад", callback_data="adm_main")
            )
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="Markdown")

        elif data == "adm_recalc":
            recalculate_all_stats()
            save_data()
            bot.answer_callback_query(call.id, "🔄 Статистика пересчитана!")
            call.data = "adm_stats"
            handle_admin_callbacks(call)

        elif data == "adm_settings":
            admins = db["settings"]["admins"]
            text = f"⚙️ **НАСТРОЙКИ**\n\nАдминистраторы: {', '.join(admins)}"
            bot.edit_message_text(text, chat_id, message_id, reply_markup=build_admin_back_kb(), parse_mode="Markdown")

        elif data == "adm_close":
            bot.delete_message(chat_id, message_id)
    except Exception as e:
        logging.error(f"Admin callback error: {e}")

# =====================================================================
#  ПОДКЛЮЧЕНИЕ ВНЕШНИХ МОДУЛЕЙ И ТОЧКА ВХОДА
# =====================================================================

from handlers.results import register_result_handlers

register_result_handlers(
    bot,
    db,
    save_data,
    recalculate_all_stats,
    is_admin
)

if __name__ == '__main__':
    logging.info("Запуск турнирного бота (polling)...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            logging.error(f"Сбой polling: {e}. Перезапуск через 5 секунд...")
            time.sleep(5)
