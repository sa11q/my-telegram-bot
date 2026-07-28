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

# =====================================================================
#  БАЗА ДАННЫХ И МИГРАЦИЯ
# =====================================================================

def get_default_db():
    return {
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
        if os.path.exists(DB_FILE):
            try:
                with open(DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    default_db = get_default_db()
                    
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
            except Exception as e:
                logging.error(f"Ошибка загрузки БД: {e}")
        return get_default_db()

def save_data_internal(data):
    try:
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

# =====================================================================
#  ВСПАМОГАТЕЛЬНЫЕ ФУНКЦИИ И ПРОВЕРКИ
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
    # Сброс показателей
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

    # Сбор всех завершенных матчей
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

    # Пересчет
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
            if p2_s["current_win_streak"] > p2_s["max_win_streak"]:
                p2_s["max_win_streak"] = p2_s["current_win_streak"]
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
    # Если текущее время >= 22:00 или < 06:00
    if now.hour >= 22 or now.hour < 6:
        # 17:00 следующего дня (или того же дня, если сейчас между 00:00 и 06:00)
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
                
                # За 30 минут до дедлайна
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

# Запуск фонового потока проверки дедлайнов
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

    # Группировка матчей по командам
    team_pairs = {}
    for m in matches:
        pair_key = (m["t1"], m["t2"])
        if pair_key not in team_pairs:
            team_pairs[pair_key] = []
        team_pairs[pair_key].append(m)

    for (t1, t2), match_list in team_pairs.items():
        # Подсчет командных голов
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

    # Определяем победителей каждой пары команд
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
            # При равном счете — рандомный жребий
            winner = random.choice([t1, t2])
            advancing_teams.append(winner)
            if chat_id:
                try:
                    bot.send_message(chat_id, f"⚖️ Ничья в противостоянии {t1} - {t2}. По жребию проходит: {winner}")
                except Exception:
                    pass

    # Архивируем матчи текущего этапа
    for m in matches:
        active["history"].append(dict(m))

    active["stage"] += 1

    # Если осталась 1 команда — ФИНАЛ, есть победитель!
    if len(advancing_teams) <= 1:
        champion = advancing_teams[0] if advancing_teams else "Не определен"
        
        # Записываем чемпионство игроку(ам)
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

        # Архивируем турнир
        db["archived_tournaments"].append(dict(active))
        
        # Сброс активного турнира
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

    # Создаем следующий этап
    active["stage_name"] = get_stage_title(len(advancing_teams))
    new_teams_dict = {}
    new_matches = []

    # Формируем пары на следующий этап
    random.shuffle(advancing_teams)
    
    for i in range(0, len(advancing_teams), 2):
        if i + 1 >= len(advancing_teams):
            # Нечетное количество — проходимец без пары
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
            "Результат должен отправляться STRICTLY в формате:\n"
            "`@player1 2:3 @player2`\n"
            "*(Результаты без упоминаний двух игроков не учитываются)*.\n\n"
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
            return bot.reply_to(message, f"📭 Профиль для @{clean_name} не найден. Необходмо сыграть хотя бы 1 матч.")

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
#  ОБРАБОТКА РЕЗУЛЬТАТОВ МАТЧЕЙ (ТОЛЬКО КОРРЕКТНЫЙ ФОРМАТ)
# =====================================================================

@bot.message_handler(func=lambda m: is_group(m) and bool(re.search(r'@[a-zA-Z0-9_]+\s+\d+\s*[:\-]\s*\d+\s+@[a-zA-Z0-9_]+', str(m.text))))
def process_match_score(message):
    try:
        if not message.from_user or not message.from_user.username:
            return

        sender_username = normalize_username(message.from_user.username).lower()
        sender_is_admin = is_admin(message.from_user.username)

        # Строгий regex: @player1 2:3 @player2
        pattern = r'(@[a-zA-Z0-9_]+)\s+(\d+)\s*[:\-]\s*(\d+)\s+(@[a-zA-Z0-9_]+)'
        match = re.search(pattern, message.text)
        if not match:
            return

        p1_raw, s1_str, s2_str, p2_raw = match.groups()
        s1, s2 = int(s1_str), int(s2_str)

        # Ограничение адекватности счета
        if s1 > 50 or s2 > 50:
            return

        p1_norm = normalize_username(p1_raw).lower()
        p2_norm = normalize_username(p2_raw).lower()

        # Проверка отправки одним из участников или админом
        if not sender_is_admin and sender_username not in [p1_norm, p2_norm]:
            bot.reply_to(message, "❌ Вы не являетесь участником этого матча.")
            return

        active = db["active_tournament"]
        matches = active.get("matches", [])

        # Поиск матча
        target_match = None
        for m in matches:
            m_p1 = m["p1"].lower()
            m_p2 = m["p2"].lower()
            if (m_p1 == p1_norm and m_p2 == p2_norm) or (m_p1 == p2_norm and m_p2 == p1_norm):
                target_match = m
                break

        if not target_match:
            bot.reply_to(message, f"❌ Активный матч между {p1_raw} и {p2_raw} не найден в текущем этапе.")
            return

        if target_match["done"]:
            bot.reply_to(message, "❌ Этот матч уже был сыгран! Изменение счета доступно только администраторам через `/admin`.")
            return

        # Корректировка порядка голов если игроки указаны наоборот
        if target_match["p1"].lower() == p2_norm:
            s1, s2 = s2, s1

        # Фиксация результата
        target_match["s1"] = s1
        target_match["s2"] = s2
        target_match["done"] = True
        target_match["sender"] = sender_username

        recalculate_all_stats()
        save_data()

        bot.reply_to(
            message,
            f"✅ **РЕЗУЛЬТАТ ЗАРЕГИСТРИРОВАН!**\n\n"
            f"{target_match['p1']} **{s1}:{s2}** {target_match['p2']}\n"
            f"👤 Отправил: @{message.from_user.username}",
            parse_mode="Markdown"
        )

        # Проверка завершения всех матчей этапа
        if all(m["done"] for m in matches):
            if active.get("auto_next", True):
                advance_stage(message.chat.id)
            else:
                bot.send_message(message.chat.id, "🏁 Все матчи этапа завершены! Администратор может запустить следующий этап через `/admin`.")

    except Exception as e:
        logging.error(f"Error processing score: {e}")

# =====================================================================
#  ИНТЕРАКТИВНАЯ ИНЛАЙН АДМИН-ПАНЕЛЬ (/admin)
# =====================================================================

def build_admin_main_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🏆 Турниры", callback_data="adm_tour"),
        InlineKeyboardButton("👥 Игроки", callback_data="adm_players")
    )
    kb.add(
        InlineKeyboardButton("⚔ Матчи", callback_data="adm_matches"),
        InlineKeyboardButton("⏰ Дедлайн", callback_data="adm_deadline")
    )
    kb.add(
        InlineKeyboardButton("🏆 Этап", callback_data="adm_stage"),
        InlineKeyboardButton("📊 Статистика", callback_data="adm_stats")
    )
    kb.add(
        InlineKeyboardButton("⚙ Настройки", callback_data="adm_settings"),
        InlineKeyboardButton("❌ Закрыть", callback_data="adm_close")
    )
    return kb

@bot.message_handler(commands=['admin', 'админ'])
def open_admin_panel(message):
    try:
        if not is_admin(message.from_user.username):
            bot.reply_to(message, "⛔️ Доступ запрещен. Вы не являетесь администратором.")
            return

        bot.send_message(
            message.chat.id,
            "👑 **ИНТЕРАКТИВНАЯ АДМИН-ПАНЕЛЬ**\nВыберите нужный раздел управления:",
            reply_markup=build_admin_main_kb(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(e)

# === ОБРАБОТКА CALLBACK CALLBACK QUERY ДЛЯ АДМИНКИ ===

@bot.callback_query_handler(func=lambda call: call.data.startswith("adm_"))
def handle_admin_callbacks(call):
    try:
        if not is_admin(call.from_user.username):
            return bot.answer_callback_query(call.id, "⛔️ Вы не администратор!", show_alert=True)

        data = call.data
        chat_id = call.message.chat.id
        msg_id = call.message.message_id
        active = db["active_tournament"]

        # --- ГЛАВНОЕ МЕНЮ И НАВИГАЦИЯ ---
        if data == "adm_main":
            bot.edit_message_text("👑 **ИНТЕРАКТИВНАЯ АДМИН-ПАНЕЛЬ**\nВыберите нужный раздел управления:", chat_id, msg_id, reply_markup=build_admin_main_kb(), parse_mode="Markdown")

        elif data == "adm_close":
            bot.delete_message(chat_id, msg_id)

        # --- РАЗДЕЛ: ТУРНИРЫ ---
        elif data == "adm_tour":
            kb = InlineKeyboardMarkup(row_width=2)
            reg_status = "❌ Закрыть регистрацию" if active.get("registration_open") else "🟢 Открыть регистрацию"
            kb.add(
                InlineKeyboardButton(reg_status, callback_data="adm_tour_toggle_reg"),
                InlineKeyboardButton("🚀 Начать (Жеребьевка)", callback_data="adm_tour_draw")
            )
            kb.add(
                InlineKeyboardButton("🏁 Завершить турнир", callback_data="adm_tour_finish"),
                InlineKeyboardButton("🗑 Сбросить турнир", callback_data="adm_tour_reset")
            )
            kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="adm_main"))
            
            reg_str = "Открыта" if active.get("registration_open") else "Закрыта"
            p_count = len(active.get("registered_players", []))
            text = f"🏆 **УПРАВЛЕНИЕ ТУРНИРОМ**\n\nНазвание: **{active.get('title')}**\nСтатус регистрации: **{reg_str}**\nЗарегистрировано: **{p_count} чел.**"
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb, parse_mode="Markdown")

        elif data == "adm_tour_toggle_reg":
            active["registration_open"] = not active.get("registration_open", False)
            save_data()
            bot.answer_callback_query(call.id, "Статус регистрации изменен!")
            handle_admin_callbacks(type('obj', (object,), {'from_user': call.from_user, 'data': 'adm_tour', 'message': call.message}))

        elif data == "adm_tour_draw":
            registered = list(active.get("registered_players", []))
            mode = active.get("mode", "solo")
            team_sizes = {"solo": 1, "duo": 2, "trio": 3, "4v4": 4}
            team_size = team_sizes[mode]

            if len(registered) < team_size * 2:
                return bot.answer_callback_query(call.id, f"⚠️ Недостаточно игроков для режима {mode.upper()}! Нужно минимум {team_size * 2}.", show_alert=True)

            random.shuffle(registered)
            total_teams = len(registered) // team_size
            playoff_teams_count = 2 ** int(math.log2(total_teams))
            
            if playoff_teams_count < 2:
                return bot.answer_callback_query(call.id, "⚠️ Мало команд для сетки плей-офф.", show_alert=True)

            active_players = registered[:playoff_teams_count * team_size]
            
            teams_dict = {}
            team_names = []

            if mode == "solo":
                for p in active_players:
                    teams_dict[p] = [p]
                    team_names.append(p)
            else:
                for i in range(0, len(active_players), team_size):
                    t_name = f"Команда {len(team_names) + 1}"
                    team_names.append(t_name)
                    teams_dict[t_name] = active_players[i:i+team_size]

            active["teams"] = teams_dict
            active["matches"] = []
            active["history"] = []
            active["stage"] = 1
            active["stage_name"] = get_stage_title(len(team_names))
            active["registration_open"] = False
            active["chat_id"] = chat_id

            # Генерация матчей первого этапа
            for i in range(0, len(team_names), 2):
                t1_name, t2_name = team_names[i], team_names[i+1]
                t1_m, t2_m = teams_dict[t1_name], teams_dict[t2_name]
                
                r1, r2 = list(t1_m), list(t2_m)
                random.shuffle(r1)
                random.shuffle(r2)
                
                for j in range(min(len(r1), len(r2))):
                    active["matches"].append({
                        "id": f"m_1_{i}_{j}",
                        "t1": t1_name, "t2": t2_name,
                        "p1": r1[j], "p2": r2[j],
                        "s1": None, "s2": None, "done": False, "sender": None
                    })

            if active.get("auto_deadline", True):
                active["deadline"] = calculate_auto_deadline()
                active["reminder_sent"] = False

            save_data()
            bot.answer_callback_query(call.id, "Жеребьевка успешно проведена!")
            bot.send_message(chat_id, f"🏆 **ТУРНИР СТАРТОВАЛ!**\n\n{format_bracket_text()}")

        elif data == "adm_tour_finish":
            active["registration_open"] = False
            active["matches"] = []
            active["teams"] = {}
            active["deadline"] = None
            save_data()
            bot.answer_callback_query(call.id, "Турнир завершен.")

        elif data == "adm_tour_reset":
            active["registered_players"] = []
            active["matches"] = []
            active["teams"] = {}
            active["history"] = []
            active["stage"] = 1
            active["registration_open"] = False
            active["deadline"] = None
            save_data()
            bot.answer_callback_query(call.id, "Сброс проведен.")

        # --- РАЗДЕЛ: ИГРОКИ ---
        elif data == "adm_players":
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(
                InlineKeyboardButton("📋 Показать список участников", callback_data="adm_players_list"),
                InlineKeyboardButton("⬅️ Назад", callback_data="adm_main")
            )
            text = f"👥 **УПРАВЛЕНИЕ ИГРОКАМИ**\nЗарегистрировано: {len(active.get('registered_players', []))} чел."
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb, parse_mode="Markdown")

        elif data == "adm_players_list":
            plist = active.get("registered_players", [])
            if not plist:
                bot.answer_callback_query(call.id, "Список участников пуст.", show_alert=True)
            else:
                msg = "📋 **УЧАСТНИКИ:**\n\n" + "\n".join([f"{i}. {p}" for i, p in enumerate(plist, 1)])
                bot.send_message(chat_id, msg)

        # --- РАЗДЕЛ: МАТЧИ ---
        elif data == "adm_matches":
            matches = active.get("matches", [])
            kb = InlineKeyboardMarkup(row_width=1)
            
            if not matches:
                kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="adm_main"))
                return bot.edit_message_text("⚔ **УПРАВЛЕНИЕ МАТЧАМИ**\n\nНет активных матчей.", chat_id, msg_id, reply_markup=kb, parse_mode="Markdown")

            for idx, m in enumerate(matches[:10]):
                status = "✅" if m["done"] else "⏳"
                btn_text = f"{status} {m['p1']} vs {m['p2']} ({m['s1'] if m['s1'] is not None else '-'}:{m['s2'] if m['s2'] is not None else '-'})"
                kb.add(InlineKeyboardButton(btn_text, callback_data=f"adm_m_{idx}"))

            kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="adm_main"))
            bot.edit_message_text("⚔ **УПРАВЛЕНИЕ МАТЧАМИ**\nВыберите матч для редактирования:", chat_id, msg_id, reply_markup=kb, parse_mode="Markdown")

        elif data.startswith("adm_m_"):
            idx = int(data.split("_")[2])
            matches = active.get("matches", [])
            if idx >= len(matches):
                return bot.answer_callback_query(call.id, "Матч не найден.", show_alert=True)

            m = matches[idx]
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton("🔨 ТП первому (6:0)", callback_data=f"adm_tp1_{idx}"),
                InlineKeyboardButton("🔨 ТП второму (0:6)", callback_data=f"adm_tp2_{idx}")
            )
            kb.add(
                InlineKeyboardButton("❌ Отменить результат", callback_data=f"adm_mcancel_{idx}"),
                InlineKeyboardButton("⬅️ Назад", callback_data="adm_matches")
            )

            text = f"⚙ **Управление матчем:**\n{m['p1']} vs {m['p2']}\nТекущий счет: {m['s1']}:{m['s2']}"
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb, parse_mode="Markdown")

        elif data.startswith("adm_tp1_") or data.startswith("adm_tp2_"):
            parts = data.split("_")
            tp_type = parts[1]
            idx = int(parts[2])
            matches = active.get("matches", [])
            if idx < len(matches):
                m = matches[idx]
                m["s1"], m["s2"] = (6, 0) if tp_type == "tp1" else (0, 6)
                m["done"] = True
                recalculate_all_stats()
                save_data()
                bot.answer_callback_query(call.id, "Техническое поражение вынесено!")
                bot.send_message(chat_id, f"🔨 **Техническое поражение!**\n{m['p1']} {m['s1']}:{m['s2']} {m['p2']}")

        elif data.startswith("adm_mcancel_"):
            idx = int(data.split("_")[2])
            matches = active.get("matches", [])
            if idx < len(matches):
                m = matches[idx]
                m["s1"], m["s2"] = None, None
                m["done"] = False
                recalculate_all_stats()
                save_data()
                bot.answer_callback_query(call.id, "Результат отменен.")

        # --- РАЗДЕЛ: ДЕДЛАЙН ---
        elif data == "adm_deadline":
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton("➕ 30 мин", callback_data="adm_dl_add30"),
                InlineKeyboardButton("➖ 30 мин", callback_data="adm_dl_sub30")
            )
            kb.add(
                InlineKeyboardButton("🌅 Установить 17:00", callback_data="adm_dl_1700"),
                InlineKeyboardButton("⬅️ Назад", callback_data="adm_main")
            )
            dl = active.get("deadline", "Не установлен")
            bot.edit_message_text(f"⏰ **УПРАВЛЕНИЕ ДЕДЛАЙНОМ**\n\nТекущий дедлайн: **{dl}**", chat_id, msg_id, reply_markup=kb, parse_mode="Markdown")

        elif data in ["adm_dl_add30", "adm_dl_sub30", "adm_dl_1700"]:
            curr = active.get("deadline")
            base_dt = datetime.strptime(curr, "%Y-%m-%d %H:%M") if curr else datetime.now()
            
            if data == "adm_dl_add30":
                new_dt = base_dt + timedelta(minutes=30)
            elif data == "adm_dl_sub30":
                new_dt = base_dt - timedelta(minutes=30)
            else:
                next_day = datetime.now() + timedelta(days=1)
                new_dt = datetime(next_day.year, next_day.month, next_day.day, 17, 0)

            active["deadline"] = new_dt.strftime("%Y-%m-%d %H:%M")
            active["reminder_sent"] = False
            save_data()
            bot.answer_callback_query(call.id, "Дедлайн обновлен!")
            handle_admin_callbacks(type('obj', (object,), {'from_user': call.from_user, 'data': 'adm_deadline', 'message': call.message}))

        # --- РАЗДЕЛ: ЭТАП ---
        elif data == "adm_stage":
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(
                InlineKeyboardButton("▶️ Следующий этап (Принудительно)", callback_data="adm_stage_next"),
                InlineKeyboardButton("📢 Опубликовать сетку", callback_data="adm_stage_pub"),
                InlineKeyboardButton("⬅️ Назад", callback_data="adm_main")
            )
            bot.edit_message_text(f"🏆 **УПРАВЛЕНИЕ ЭТАПОМ**\n\nТекущий этап: **{active.get('stage_name')}**", chat_id, msg_id, reply_markup=kb, parse_mode="Markdown")

        elif data == "adm_stage_next":
            bot.answer_callback_query(call.id, "Переход на следующий этап...")
            advance_stage(chat_id)

        elif data == "adm_stage_pub":
            bot.answer_callback_query(call.id, "Опубликовано.")
            bot.send_message(chat_id, format_bracket_text())

        # --- РАЗДЕЛ: СТАТИСТИКА ---
        elif data == "adm_stats":
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(
                InlineKeyboardButton("🔄 Полный пересчет статистики", callback_data="adm_stats_recalc"),
                InlineKeyboardButton("⬅️ Назад", callback_data="adm_main")
            )
            bot.edit_message_text("📊 **УПРАВЛЕНИЕ СТАТИСТИКОЙ**", chat_id, msg_id, reply_markup=kb, parse_mode="Markdown")

        elif data == "adm_stats_recalc":
            recalculate_all_stats()
            save_data()
            bot.answer_callback_query(call.id, "Пересчет выполнен успешно!", show_alert=True)

        # --- РАЗДЕЛ: НАСТРОЙКИ ---
        elif data == "adm_settings":
            kb = InlineKeyboardMarkup(row_width=2)
            mode = active.get("mode", "solo")
            
            kb.add(
                InlineKeyboardButton(f"{'✅' if mode=='solo' else ''} Solo", callback_data="adm_set_solo"),
                InlineKeyboardButton(f"{'✅' if mode=='duo' else ''} Duo", callback_data="adm_set_duo")
            )
            kb.add(
                InlineKeyboardButton(f"{'✅' if mode=='trio' else ''} Trio", callback_data="adm_set_trio"),
                InlineKeyboardButton(f"{'✅' if mode=='4v4' else ''} 4v4", callback_data="adm_set_4v4")
            )
            
            auto_next = "🟢 Авто-этап: Вкл" if active.get("auto_next") else "🔴 Авто-этап: Выкл"
            kb.add(InlineKeyboardButton(auto_next, callback_data="adm_set_autonext"))
            kb.add(InlineKeyboardButton("⬅️ Назад", callback_data="adm_main"))

            text = f"⚙ **НАСТРОЙКИ ТУРНИРА**\n\nРежим: **{mode.upper()}**"
            bot.edit_message_text(text, chat_id, msg_id, reply_markup=kb, parse_mode="Markdown")

        elif data.startswith("adm_set_"):
            setting = data.split("_")[2]
            if setting in ["solo", "duo", "trio", "4v4"]:
                active["mode"] = setting
            elif setting == "autonext":
                active["auto_next"] = not active.get("auto_next", True)

            save_data()
            bot.answer_callback_query(call.id, "Настройки сохранены!")
            handle_admin_callbacks(type('obj', (object,), {'from_user': call.from_user, 'data': 'adm_settings', 'message': call.message}))

    except Exception as e:
        logging.error(f"Callback error: {e}")

# =====================================================================
#  ТОЧКА ВХОДА И ПУСК БОТА
# =====================================================================

if __name__ == '__main__':
    logging.info("Запуск турнирного бота (polling)...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            logging.error(f"Сбой polling: {e}. Перезапуск через 5 секунд...")
            time.sleep(5)
