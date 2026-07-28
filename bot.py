import telebot
import logging
import os
import re
import json
import random
import math
import time
import tempfile
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# 1. Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =====================================================================
TOKEN = "8876079721:AAFMECzB5jkywB1J8ks66qgXg_YMzDMD6dU"
# =====================================================================

bot = telebot.TeleBot(TOKEN)
ADMINS = ['wonti9', 'avelon67', 'nupik91']

# Фиксированный путь к файлу базы данных в папке проекта
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.json")

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                tournaments = {}
                raw_tournaments = data.get("tournaments", {})
                
                # Миграция со старого формата, если был один активный турнир
                if not raw_tournaments and ("posts" in data or "active_tour" in data):
                    default_tid = "default"
                    tournaments[default_tid] = {
                        "posts": {str(k): list(v) for k, v in data.get("posts", {}).items()},
                        "active_tour": data.get("active_tour", {"teams": [], "matches": []}),
                        "registration_open": True,
                        "history": [],
                        "champion": None,
                        "stage": 1,
                        "recent_results": []
                    }
                else:
                    for tid, tdata in raw_tournaments.items():
                        tournaments[str(tid)] = {
                            "posts": {str(k): list(v) for k, v in tdata.get("posts", {}).items()},
                            "active_tour": tdata.get("active_tour", {"teams": [], "matches": []}),
                            "registration_open": tdata.get("registration_open", True),
                            "history": tdata.get("history", []),
                            "champion": tdata.get("champion", None),
                            "stage": tdata.get("stage", 1),
                            "recent_results": tdata.get("recent_results", [])
                        }

                return {
                    "tournaments": tournaments,
                    "stats": data.get("stats", {"players": {}, "teams": {}}),
                    "champions": data.get("champions", [])
                }
        except Exception as e:
            logging.error(f"Ошибка загрузки базы: {e}")
    return {
        "tournaments": {
            "default": {
                "posts": {},
                "active_tour": {"teams": [], "matches": []},
                "registration_open": True,
                "history": [],
                "champion": None,
                "stage": 1,
                "recent_results": []
            }
        },
        "stats": {"players": {}, "teams": {}},
        "champions": []
    }

def save_data():
    try:
        export_data = {
            "tournaments": db["tournaments"],
            "stats": db["stats"],
            "champions": db["champions"]
        }
        # Атомарное сохранение через временный файл для защиты от повреждений
        dir_name = os.path.dirname(DB_FILE)
        with tempfile.NamedTemporaryFile('w', dir=dir_name, delete=False, encoding="utf-8") as tf:
            json.dump(export_data, tf, ensure_ascii=False, indent=2)
            temp_name = tf.name
        os.replace(temp_name, DB_FILE)
    except Exception as e:
        logging.error(f"Ошибка атомарного сохранения: {e}")

db = load_data()
tournaments = db["tournaments"]
tour_stats = db["stats"]

def is_admin(message):
    if message.from_user and message.from_user.username:
        return message.from_user.username.lower() in ADMINS
    return False

def get_tournament_id(message):
    # Каждый пост регистрации или чат/тренд определяет уникальный турнир
    if message.reply_to_message:
        return str(message.reply_to_message.message_id)
    if message.message_thread_id:
        return str(message.message_thread_id)
    return str(message.chat.id)

def get_tournament_by_id(tid):
    tid_str = str(tid)
    if tid_str not in tournaments:
        tournaments[tid_str] = {
            "posts": {},
            "active_tour": {"teams": [], "matches": []},
            "registration_open": True,
            "history": [],
            "champion": None,
            "stage": 1,
            "recent_results": []
        }
    return tournaments[tid_str]

def get_tournament(message):
    return get_tournament_by_id(get_tournament_id(message))

def find_match_by_msg_id(msg_id):
    for tid, tour in tournaments.items():
        for m in tour["active_tour"].get("matches", []):
            if m.get("msg_id") == msg_id:
                return tour, m, tid
        for m in tour.get("history", []):
            if m.get("msg_id") == msg_id:
                return tour, m, tid
    return None, None, None

def calculate_elo(rating1, rating2, score1, score2):
    k = 32
    e1 = 1 / (1 + 10 ** ((rating2 - rating1) / 400))
    e2 = 1 / (1 + 10 ** ((rating1 - rating2) / 400))
    
    if score1 > score2: s1, s2 = 1, 0
    elif score1 < score2: s1, s2 = 0, 1
    else: s1, s2 = 0.5, 0.5
        
    return round(rating1 + k * (s1 - e1)), round(rating2 + k * (s2 - e2))

def init_player(username):
    clean_name = username.replace('@', '')
    if clean_name not in tour_stats["players"]:
        tour_stats["players"][clean_name] = {
            "elo": 1000, "goals_scored": 0, "goals_conceded": 0, "matches": 0,
            "wins": 0, "losses": 0, "draws": 0,
            "current_win_streak": 0, "max_win_streak": 0,
            "current_loss_streak": 0, "max_loss_streak": 0,
            "biggest_win": 0, "biggest_loss": 0,
            "last_opponent": None, "last_match_date": None,
            "championships": 0,
            "match_history": []
        }

def recalculate_all_stats():
    for p in tour_stats["players"]:
        tour_stats["players"][p]["elo"] = 1000
        tour_stats["players"][p]["wins"] = 0
        tour_stats["players"][p]["losses"] = 0
        tour_stats["players"][p]["draws"] = 0
        tour_stats["players"][p]["goals_scored"] = 0
        tour_stats["players"][p]["goals_conceded"] = 0
        tour_stats["players"][p]["matches"] = 0
        tour_stats["players"][p]["current_win_streak"] = 0
        tour_stats["players"][p]["max_win_streak"] = 0
        tour_stats["players"][p]["current_loss_streak"] = 0
        tour_stats["players"][p]["max_loss_streak"] = 0
        tour_stats["players"][p]["biggest_win"] = 0
        tour_stats["players"][p]["biggest_loss"] = 0
        tour_stats["players"][p]["match_history"] = []

    # Собираем все сыгранные матчи из истории и активных сеток всех турниров
    all_played = []
    for tid, t in tournaments.items():
        for hist in t.get("history", []):
            if hist.get("done"):
                all_played.append(hist)
        for m in t.get("active_tour", {}).get("matches", []):
            if m.get("done"):
                all_played.append(m)

    for m in all_played:
        p1, p2, s1, s2 = m["p1"], m["p2"], m["s1"], m["s2"]
        init_player(p1)
        init_player(p2)
        name1, name2 = p1.replace('@', ''), p2.replace('@', '')
        
        p1_s = tour_stats["players"][name1]
        p2_s = tour_stats["players"][name2]
        
        p1_s["goals_scored"] += s1
        p1_s["goals_conceded"] += s2
        p1_s["matches"] += 1
        
        p2_s["goals_scored"] += s2
        p2_s["goals_conceded"] += s1
        p2_s["matches"] += 1
        
        diff1 = s1 - s2
        diff2 = s2 - s1
        if diff1 > p1_s["biggest_win"]: p1_s["biggest_win"] = diff1
        if diff2 > p2_s["biggest_loss"]: p2_s["biggest_loss"] = diff2
        if diff2 > p2_s["biggest_win"]: p2_s["biggest_win"] = diff2
        if diff1 > p1_s["biggest_loss"]: p1_s["biggest_loss"] = diff1
        
        if s1 > s2:
            p1_s["wins"] += 1
            p2_s["losses"] += 1
            p1_s["current_win_streak"] += 1
            p1_s["current_loss_streak"] = 0
            if p1_s["current_win_streak"] > p1_s["max_win_streak"]: p1_s["max_win_streak"] = p1_s["current_win_streak"]
            
            p2_s["current_loss_streak"] += 1
            p2_s["current_win_streak"] = 0
            if p2_s["current_loss_streak"] > p2_s["max_loss_streak"]: p2_s["max_loss_streak"] = p2_s["current_loss_streak"]
        elif s1 < s2:
            p1_s["losses"] += 1
            p2_s["wins"] += 1
            p1_s["current_loss_streak"] += 1
            p1_s["current_win_streak"] = 0
            if p1_s["current_loss_streak"] > p1_s["max_loss_streak"]: p1_s["max_loss_streak"] = p1_s["current_loss_streak"]
            
            p2_s["current_win_streak"] += 1
            p2_s["current_loss_streak"] = 0
            if p2_s["current_win_streak"] > p2_s["max_win_streak"]: p2_s["max_win_streak"] = p2_s["current_win_streak"]
        else:
            p1_s["draws"] += 1
            p2_s["draws"] += 1
            p1_s["current_win_streak"] = 0
            p1_s["current_loss_streak"] = 0
            p2_s["current_win_streak"] = 0
            p2_s["current_loss_streak"] = 0
            
        old_r1 = p1_s["elo"]
        old_r2 = p2_s["elo"]
        p1_s["elo"], p2_s["elo"] = calculate_elo(old_r1, old_r2, s1, s2)
        
        p1_s["last_opponent"] = p2
        p2_s["last_opponent"] = p1
        p1_s["match_history"].append(dict(m))
        p2_s["match_history"].append(dict(m))

def process_match_result(tour, p1, p2, s1, s2, sender_username=None, message_id=None):
    active_tour = tour["active_tour"]
    for m in active_tour["matches"]:
        match_p1 = m["p1"].replace('@', '').lower()
        match_p2 = m["p2"].replace('@', '').lower()
        target_p1 = p1.replace('@', '').lower()
        target_p2 = p2.replace('@', '').lower()

        if (match_p1 == target_p1 and match_p2 == target_p2) or (match_p1 == target_p2 and match_p2 == target_p1):
            if match_p1 == target_p2:
                s1, s2 = s2, s1
            
            if m.get("done"):
                return False, "Матч уже завершен."

            m["s1"], m["s2"], m["done"] = s1, s2, True
            if sender_username:
                m["sender"] = sender_username
            if message_id:
                m["msg_id"] = message_id
            
            recalculate_all_stats()
            
            # Добавляем в последние результаты конкретного турнира и общие
            res_item = {
                "p1": m["p1"], "p2": m["p2"], "s1": s1, "s2": s2, "sender": sender_username
            }
            if "recent_results" not in tour:
                tour["recent_results"] = []
            tour["recent_results"].insert(0, res_item)
            if len(tour["recent_results"]) > 20:
                tour["recent_results"].pop()
                
            save_data()
            return True, m
    return False, "Матч не найден."

# ==================== УПРАВЛЕНИЕ РЕГИСТРАЦИЕЙ ====================

@bot.message_handler(commands=['open'])
def open_registration(message):
    try:
        if not is_admin(message): return
        tour = get_tournament(message)
        tour["registration_open"] = True
        save_data()
        bot.reply_to(message, "✅ Регистрация на турнир открыта!")
    except Exception as e:
        logging.error(f"Open reg error: {e}")

@bot.message_handler(commands=['close'])
def close_registration(message):
    try:
        if not is_admin(message): return
        tour = get_tournament(message)
        tour["registration_open"] = False
        save_data()
        bot.reply_to(message, "❌ Регистрация на турнир закрыта!")
    except Exception as e:
        logging.error(f"Close reg error: {e}")

@bot.message_handler(commands=['join'])
def player_join_tournament(message):
    try:
        if not message.from_user:
            return

        if not message.from_user.username:
            bot.reply_to(message, "⚠️ У вас не установлен username в Telegram. Пожалуйста, установите его в настройках профиля, чтобы зарегистрироваться.")
            return

        # 1. /join работает только ответом на пост регистрации.
        if not message.reply_to_message or not message.reply_to_message.text:
            bot.reply_to(message, "⚠️ Команда `/join` должна быть ответом на пост регистрации.")
            return

        target_text = message.reply_to_message.text.lower()
        # Пост регистрации обязан содержать ключевые слова
        if not any(kw in target_text for kw in ["registration", "регистрация", "рег"]):
            bot.reply_to(message, "⚠️ Это сообщение не является постом регистрации (нет слов registration / регистрация / рег).")
            return

        # Определяем турнир именно по ID поста регистрации, чтобы обеспечить независимость
        reg_post_id = str(message.reply_to_message.message_id)
        tour = get_tournament_by_id(reg_post_id)

        if not tour.get("registration_open", True):
            bot.reply_to(message, "❌ Регистрация на этот турнир закрыта.")
            return

        username = f"@{message.from_user.username}"

        # Проверка: игрок не может попасть сразу в несколько регистраций одного турнира / дублироваться
        for tid, t in tournaments.items():
            for post_id, plist in t.get("posts", {}).items():
                if username in plist:
                    # Если уже зарегистрирован в текущем турнире
                    if tid == reg_post_id:
                        bot.reply_to(message, f"ℹ️ Вы уже зарегистрированы в этом турнире!\n\n👥 Участников: {len(plist)}")
                        return
                    else:
                        bot.reply_to(message, "❌ Вы уже зарегистрированы в другом активном турнире.")
                        return

        if reg_post_id not in tour["posts"]:
            tour["posts"][reg_post_id] = []

        tour["posts"][reg_post_id].append(username)
        save_data()

        total = len(tour["posts"][reg_post_id])
        bot.reply_to(message, f"✅ @{message.from_user.username} успешно зарегистрирован!\n\n👥 Всего участников: {total}")
    except Exception as e:
        logging.error(f"Join error: {e}")
        bot.reply_to(message, "❌ Произошла ошибка при регистрации.")

@bot.message_handler(commands=['collect'])
def admin_collect_players(message):
    bot.reply_to(message, "⚠️ Команда больше не используется. Для регистрации игроки должны ответить `/join` на пост турнира.")

@bot.message_handler(commands=['add'])
def admin_add_player(message):
    try:
        if not is_admin(message): return
        args = message.text.split()
        if len(args) < 2:
            return bot.reply_to(message, "⚠️ Укажите никнейм. Пример: `/add @username`")
        
        username = args[1]
        if not username.startswith('@'): username = '@' + username

        tour = get_tournament(message)
        thread_id = get_tournament_id(message)
        if thread_id not in tour["posts"]: tour["posts"][thread_id] = []

        if username in tour["posts"][thread_id]:
            bot.reply_to(message, f"ℹ️ Игрок {username} уже есть в списке.")
        else:
            tour["posts"][thread_id].append(username)
            save_data()
            bot.reply_to(message, f"✅ Добавлен: {username}\n👥 Всего в списке: {len(tour['posts'][thread_id])}")
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['remove', 'del'])
def admin_remove_player(message):
    try:
        if not is_admin(message): return
        args = message.text.split()
        if len(args) < 2:
            return bot.reply_to(message, "⚠️ Укажите никнейм. Пример: `/remove @username`")
        
        username = args[1]
        if not username.startswith('@'): username = '@' + username

        tour = get_tournament(message)
        thread_id = get_tournament_id(message)
        if thread_id in tour["posts"] and username in tour["posts"][thread_id]:
            tour["posts"][thread_id].remove(username)
            save_data()
            bot.reply_to(message, f"🗑 Удален: {username}\n👥 Всего в списке: {len(tour['posts'][thread_id])}")
        else:
            bot.reply_to(message, f"❌ Игрок {username} не найден в списке.")
    except Exception as e:
        logging.error(e)

# ==================== ОСНОВНЫЕ КОМАНДЫ ====================

@bot.message_handler(commands=['list', 'players', 'участники'])
def show_collected_list(message):
    try:
        tour = get_tournament(message)
        thread_id = get_tournament_id(message)
        participants = list(tour["posts"].get(thread_id, []))
        
        if not participants:
            bot.reply_to(message, "📭 Под этим постом/веткой еще нет зарегистрированных участников.")
            return

        participants.sort()
        msg = f"📋 Список участников ({len(participants)} чел.):\n\n"
        for i, p in enumerate(participants, 1):
            msg += f"{i}. {p}\n"
        
        bot.reply_to(message, msg)
    except Exception as e:
        logging.error(f"List error: {e}")

@bot.message_handler(commands=['start'])
def send_welcome(message):
    try:
        bot.reply_to(
            message, 
            "✅ Бот запущен (Tournament System)\n\n"
            "👤 ИГРОКАМ:\n"
            "• `/join` (ответом на пост) — регистрация\n"
            "• `/profile [@user]` — турнирный паспорт\n"
            "• `/vs` — найти текущего соперника\n"
            "• `/bracket` — турнирная сетка\n"
            "• `/history [@user]` — история матчей\n"
            "• `/recent` — последние результаты\n"
            "• `/champions` — чемпионы турниров\n"
            "• `/active` — активные турниры\n"
            "• Напиши счет матча (например: `3:2`), чтобы бот засчитал его!\n\n"
            "👑 АДМИНАМ:\n"
            "• `/open` / `/close` — управление регистрацией\n"
            "• `/draw [режим] [лимит]` — жеребьевка (solo/duo/trio/4v4)\n"
            "• `/results [текст]` — прописать счета\n"
            "• `/next` — следующий этап\n"
            "• `/tp @username` — тех. поражение\n"
            "• `/top` и `/stats` — статистика\n"
        )
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['draw'])
def make_draw(message):
    try:
        if not is_admin(message): return
        
        tour = get_tournament(message)
        thread_id = get_tournament_id(message)
        collected = list(tour["posts"].get(thread_id, []))
        if not collected:
            bot.reply_to(message, "📭 Список участников пуст. Сначала игроки должны зарегистрироваться через /join.")
            return

        args = message.text.lower().split()[1:]
        mode, custom_limit = "solo", None

        for arg in args:
            if arg in ["solo", "соло", "1v1"]: mode = "solo"
            elif arg in ["duo", "дуо", "2v2"]: mode = "duo"
            elif arg in ["trio", "трио", "3v3"]: mode = "trio"
            elif arg in ["4v4", "4-4"]: mode = "4v4"
            elif arg.isdigit(): custom_limit = int(arg)

        team_sizes = {"solo": 1, "duo": 2, "trio": 3, "4v4": 4}
        team_size = team_sizes[mode]

        random.shuffle(collected)
        total_available = min(custom_limit, len(collected)) if custom_limit else len(collected)
        total_teams = total_available // team_size

        if total_teams < 2:
            bot.reply_to(message, f"⚠️ Недостаточно участников для режима {mode.upper()}. Нужно минимум {team_size * 2} чел., а найдено {len(collected)}.")
            return

        playoff_teams_count = 2 ** int(math.log2(total_teams))
        active_players = collected[:playoff_teams_count * team_size]
        reserve_players = collected[playoff_teams_count * team_size:]

        teams, team_names = [], []
        if mode == "solo":
            for p in active_players:
                teams.append([p])
                team_names.append(p)
                tour_stats["teams"][p] = [p]
        else:
            for i in range(0, len(active_players), team_size):
                teams.append(active_players[i:i+team_size])
                t_name = f"Команда {len(teams) + 1}"
                team_names.append(t_name)
                tour_stats["teams"][t_name] = teams[-1]

        tour["active_tour"]["teams"] = team_names
        tour["active_tour"]["matches"] = []
        tour["registration_open"] = False # Автоматически закрываем регистрацию при /draw
        tour["stage"] = 1
        
        msg = f"🏆 ТУРНИРНАЯ СЕТКА ({mode.upper()})\n\n"
        
        for i in range(0, len(team_names), 2):
            t1_name, t2_name = team_names[i], team_names[i+1]
            t1_members, t2_members = teams[i], teams[i+1]
            
            if mode != "solo": msg += f"⚔️ {t1_name} vs {t2_name}\n"

            random.shuffle(t1_members)
            random.shuffle(t2_members)
            
            for j in range(min(len(t1_members), len(t2_members))):
                tour["active_tour"]["matches"].append({
                    "p1": t1_members[j], "p2": t2_members[j],
                    "t1": t1_name, "t2": t2_name,
                    "s1": None, "s2": None, "done": False, "msg_id": None, "sender": None
                })
                if mode == "solo": msg += f"⚔️ {t1_members[j]} vs {t2_members[j]}\n"
                else: msg += f"• {t1_members[j]} vs {t2_members[j]}\n"
            if mode != "solo": msg += "\n"

        if reserve_players:
            msg += f"📌 Запасные игроки: {', '.join(reserve_players)}\n"

        save_data()
        bot.reply_to(message, msg)
    except Exception as e:
        logging.error(f"Draw error: {e}")

@bot.message_handler(commands=['results'])
def process_admin_results(message):
    try:
        if not is_admin(message): return
        text = message.text.replace('/results', '').strip()
        if not text:
            bot.reply_to(message, "⚠️ Введите результаты после команды /results\nПример:\n@player1 3:1 @player2")
            return

        matches_found = re.findall(r'(@[a-zA-Z0-9_]+)\s*(\d+)\s*:\s*(\d+)\s*(@[a-zA-Z0-9_]+)', text)
        if not matches_found:
            bot.reply_to(message, "❌ Не удалось распознать формат. Пример: @user1 3:1 @user2")
            return

        tour = get_tournament(message)
        success_count = 0
        for p1, s1, s2, p2 in matches_found:
            success, _ = process_match_result(tour, p1, p2, int(s1), int(s2), sender_username=message.from_user.username)
            if success:
                success_count += 1

        check_stage_completion(message, tour)
        bot.reply_to(message, f"✅ Успешно обновлено результатов матчей: {success_count}")
    except Exception as e:
        logging.error(f"Results error: {e}")
        bot.reply_to(message, "❌ Ошибка при обработке результатов.")

@bot.message_handler(commands=['next'])
def next_stage(message):
    try:
        if not is_admin(message): return
        tour = get_tournament(message)
        teams = tour["active_tour"].get("teams", [])
        if not teams:
            bot.reply_to(message, "📭 Сетка пуста. Нужен /draw.")
            return

        pending = sum(1 for m in tour["active_tour"]["matches"] if not m["done"])
        if pending > 0:
            bot.send_message(message.chat.id, f"⚠️ Не сыграно {pending} матчей! Считаем результаты без них...")

        advancing_teams = []
        for i in range(0, len(teams), 2):
            if i + 1 >= len(teams):
                advancing_teams.append(teams[i])
                break

            t1, t2 = teams[i], teams[i+1]
            t1_goals, t2_goals = 0, 0

            for m in tour["active_tour"]["matches"]:
                if m["done"] and m["t1"] == t1 and m["t2"] == t2:
                    t1_goals += m["s1"]
                    t2_goals += m["s2"]

            if t1_goals > t2_goals: advancing_teams.append(t1)
            elif t2_goals > t1_goals: advancing_teams.append(t2)
            else:
                winner = random.choice([t1, t2])
                advancing_teams.append(winner)
                bot.send_message(message.chat.id, f"⚖️ Ничья {t1} - {t2}. Проходит: {winner}")

        # Архивируем текущие матчи в историю турнира (независимые копии)
        for m in tour["active_tour"]["matches"]:
            if m not in tour["history"]:
                tour["history"].append(dict(m))

        tour["active_tour"]["teams"] = advancing_teams
        tour["active_tour"]["matches"] = []
        tour["stage"] += 1

        if len(advancing_teams) < 2:
            champion = advancing_teams[0] if advancing_teams else "Не определен"
            tour["champion"] = champion
            
            # Начисляем достижение чемпиону и открываем регистрацию снова
            if not champion.startswith("Команда"):
                init_player(champion)
                tour_stats["players"][champion.replace('@', '')]["championships"] += 1
            else:
                for member in tour_stats["teams"].get(champion, []):
                    init_player(member)
                    tour_stats["players"][member.replace('@', '')]["championships"] += 1
                    
            db["champions"].append({
                "tournament": get_tournament_id(message),
                "champion": champion,
                "date": time.strftime("%Y-%m-%d %H:%M")
            })
            
            tour["registration_open"] = True # Открываем регистрацию после завершения турнира
            save_data()
            bot.reply_to(message, f"🎉 ТУРНИР ЗАВЕРШЕН! Чемпион: {champion}\n\nРегистрация на следующий турнир автоматически открыта!")
            return

        msg = f"🏆 СЛЕДУЮЩИЙ ЭТАП ПЛЕЙ-ОФФ (Этап {tour['stage']})\n\n"
        for i in range(0, len(advancing_teams), 2):
            if i + 1 >= len(advancing_teams):
                 msg += f"🟢 {advancing_teams[i]} проходит без матча\n\n"
                 break

            tA, tB = advancing_teams[i], advancing_teams[i+1]
            if tA.startswith("Команда"): msg += f"⚔️ {tA} vs {tB}\n"

            rosterA = list(tour_stats["teams"].get(tA, [tA]))
            rosterB = list(tour_stats["teams"].get(tB, [tB]))

            random.shuffle(rosterA)
            random.shuffle(rosterB)

            for j in range(min(len(rosterA), len(rosterB))):
                tour["active_tour"]["matches"].append({
                    "p1": rosterA[j], "p2": rosterB[j],
                    "t1": tA, "t2": tB,
                    "s1": None, "s2": None, "done": False, "msg_id": None, "sender": None
                })
                if tA.startswith("Команда"): msg += f"• {rosterA[j]} vs {rosterB[j]}\n"
                else: msg += f"⚔️ {rosterA[j]} vs {rosterB[j]}\n"
            if tA.startswith("Команда"): msg += "\n"

        save_data()
        bot.reply_to(message, msg.strip())
    except Exception as e:
        logging.error(e)

def check_stage_completion(message, tour):
    matches = tour["active_tour"].get("matches", [])
    if matches and all(m["done"] for m in matches):
        bot.send_message(message.chat.id, "🏁 Все матчи этапа завершены.\nАдминистратор может использовать /next.")

def get_match_inline_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.row(
        InlineKeyboardButton("🔄 Изменить счет", callback_data="match_edit"),
        InlineKeyboardButton("❌ Отменить результат", callback_data="match_cancel")
    )
    keyboard.row(
        InlineKeyboardButton("🔨 ТП первому", callback_data="match_tp1"),
        InlineKeyboardButton("🔨 ТП второму", callback_data="match_tp2")
    )
    return keyboard

@bot.message_handler(func=lambda m: bool(re.search(r'\b(\d+)\s*:\s*(\d+)\b', str(m.text))))
def auto_score(message):
    try:
        if not message.from_user or not message.from_user.username: return
        if message.text.startswith('/'): return
        username = message.from_user.username.lower()

        score_match = re.search(r'\b(\d+)\s*:\s*(\d+)\b', message.text)
        if not score_match: return
        sc1, sc2 = int(score_match.group(1)), int(score_match.group(2))
        
        if sc1 > 30 or sc2 > 30: return

        tour = get_tournament(message)
        for m in tour["active_tour"]["matches"]:
            if not m["done"]:
                p1_clean = m["p1"].replace('@', '').lower()
                p2_clean = m["p2"].replace('@', '').lower()

                if p1_clean == username:
                    success, res_m = process_match_result(tour, m["p1"], m["p2"], sc1, sc2, sender_username=message.from_user.username, message_id=message.message_id)
                    if success:
                        sent_msg = bot.reply_to(
                            message,
                            f"✅ Результат зарегистрирован\n\n"
                            f"@{p1_clean} {sc1}:{sc2} @{p2_clean}\n\n"
                            f"👤 Отправил: @{message.from_user.username}",
                            reply_markup=get_match_inline_keyboard()
                        )
                        res_m["msg_id"] = sent_msg.message_id
                        save_data()
                        check_stage_completion(message, tour)
                    return
                elif p2_clean == username:
                    success, res_m = process_match_result(tour, m["p1"], m["p2"], sc2, sc1, sender_username=message.from_user.username, message_id=message.message_id)
                    if success:
                        sent_msg = bot.reply_to(
                            message,
                            f"✅ Результат зарегистрирован\n\n"
                            f"@{p1_clean} {sc2}:{sc1} @{p2_clean}\n\n"
                            f"👤 Отправил: @{message.from_user.username}",
                            reply_markup=get_match_inline_keyboard()
                        )
                        res_m["msg_id"] = sent_msg.message_id
                        save_data()
                        check_stage_completion(message, tour)
                    return
    except Exception as e:
        logging.error(e)

# Хранение состояния ожидания ввода нового счета от админа в оперативной памяти (только временный ввод)
admin_edit_sessions = {}

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    try:
        if not call.from_user or not call.from_user.username:
            return
        
        if call.from_user.username.lower() not in ADMINS:
            bot.answer_callback_query(call.id, "⛔️ Только для администраторов!", show_alert=True)
            return

        tour, target_match, tid = find_match_by_msg_id(call.message.message_id)

        if not target_match:
            bot.answer_callback_query(call.id, "❌ Матч не найден в базе данных.", show_alert=True)
            return

        data = call.data
        if data == "match_cancel":
            if not target_match["done"]:
                bot.answer_callback_query(call.id, "ℹ️ Матч уже не сыгран.")
                return
            target_match["done"] = False
            target_match["s1"] = None
            target_match["s2"] = None
            recalculate_all_stats()
            save_data()
            try:
                bot.edit_message_text(
                    f"❌ Результат отменен администратором @{call.from_user.username}.\nМатч снова доступен для отправки счета.",
                    call.message.chat.id,
                    call.message.message_id
                )
            except Exception:
                pass
            bot.answer_callback_query(call.id, "✅ Результат отменен.")

        elif data == "match_tp1":
            target_match["s1"], target_match["s2"], target_match["done"] = 6, 0, True
            target_match["msg_id"] = call.message.message_id
            recalculate_all_stats()
            save_data()
            try:
                bot.edit_message_text(
                    f"✅ Результат зарегистрирован (ТП)\n\n"
                    f"{target_match['p1']} 6:0 {target_match['p2']}\n\n"
                    f"👤 ТП назначен администратором @{call.from_user.username}",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=get_match_inline_keyboard()
                )
            except Exception:
                pass
            check_stage_completion(call.message, tour)
            bot.answer_callback_query(call.id, "✅ ТП первому игроку записано.")

        elif data == "match_tp2":
            target_match["s1"], target_match["s2"], target_match["done"] = 0, 6, True
            target_match["msg_id"] = call.message.message_id
            recalculate_all_stats()
            save_data()
            try:
                bot.edit_message_text(
                    f"✅ Результат зарегистрирован (ТП)\n\n"
                    f"{target_match['p1']} 0:6 {target_match['p2']}\n\n"
                    f"👤 ТП назначен администратором @{call.from_user.username}",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=get_match_inline_keyboard()
                )
            except Exception:
                pass
            check_stage_completion(call.message, tour)
            bot.answer_callback_query(call.id, "✅ ТП второму игроку записано.")

        elif data == "match_edit":
            admin_edit_sessions[call.from_user.id] = target_match
            bot.send_message(call.message.chat.id, f"✏️ Введите новый счет для матча {target_match['p1']} vs {target_match['p2']}\nНапример: `2:1`")
            bot.answer_callback_query(call.id, "Введите новый счет в чат.")

    except Exception as e:
        logging.error(f"Callback error: {e}")

@bot.message_handler(func=lambda m: m.from_user.id in admin_edit_sessions and bool(re.search(r'\b(\d+)\s*:\s*(\d+)\b', str(m.text))))
def admin_edit_score_handler(message):
    try:
        admin_id = message.from_user.id
        target_match = admin_edit_sessions.get(admin_id)
        if not target_match:
            return

        score_match = re.search(r'\b(\d+)\s*:\s*(\d+)\b', message.text)
        if not score_match: return
        sc1, sc2 = int(score_match.group(1)), int(score_match.group(2))

        target_match["s1"], target_match["s2"], target_match["done"] = sc1, sc2, True
        recalculate_all_stats()
        save_data()

        del admin_edit_sessions[admin_id]
        bot.reply_to(message, f"✅ Счет успешно изменен на {sc1}:{sc2} для матча {target_match['p1']} vs {target_match['p2']}")
        
        if target_match.get("msg_id"):
            try:
                bot.edit_message_text(
                    f"✅ Результат отредактирован\n\n"
                    f"{target_match['p1']} {sc1}:{sc2} {target_match['p2']}\n\n"
                    f"👤 Изменил админ: @{message.from_user.username}",
                    message.chat.id,
                    target_match["msg_id"],
                    reply_markup=get_match_inline_keyboard()
                )
            except Exception:
                pass
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['vs', 'opponent', 'соперник'])
def find_opponent(message):
    if not message.from_user or not message.from_user.username: return
    username = message.from_user.username.lower()

    tour = get_tournament(message)
    for m in tour["active_tour"]["matches"]:
        if not m["done"]:
            if m["p1"].replace('@', '').lower() == username:
                bot.reply_to(message, f"⚔️ Твой соперник: {m['p2']} (от {m['t2']})")
                return
            elif m["p2"].replace('@', '').lower() == username:
                bot.reply_to(message, f"⚔️ Твой соперник: {m['p1']} (от {m['t1']})")
                return
    bot.reply_to(message, "📭 У тебя нет активных матчей.")

@bot.message_handler(commands=['bracket'])
def show_bracket(message):
    try:
        tour = get_tournament(message)
        matches = tour["active_tour"].get("matches", [])
        if not matches:
            return bot.reply_to(message, "📭 Активная турнирная сетка отсутствует.")
        
        msg = f"🏆 ТУРНИРНАЯ СЕТКА (Этап {tour.get('stage', 1)})\n\n"
        for m in matches:
            status = "✅ Сыгран" if m["done"] else "⏳ Ожидает результат"
            score_str = f"{m['s1']}:{m['s2']}" if m["done"] else "—:—"
            winner = ""
            if m["done"]:
                if m["s1"] > m["s2"]: winner = f" 🏆 Победитель: {m['p1']}"
                elif m["s2"] > m["s1"]: winner = f" 🏆 Победитель: {m['p2']}"
                else: winner = " 🏆 Ничья"
            msg += f"• {m['p1']} {score_str} {m['p2']} [{status}]{winner}\n"
            
        bot.reply_to(message, msg)
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['history'])
def show_history(message):
    try:
        args = message.text.split()
        target = args[1] if len(args) > 1 else message.from_user.username
        if not target: return
        clean_name = target.replace('@', '').lower()

        init_player(target)
        p_data = tour_stats["players"].get(clean_name, {})
        history = p_data.get("match_history", [])

        if not history:
            return bot.reply_to(message, f"📭 У игрока @{clean_name} нет истории матчей.")

        msg = f"📜 История матчей @{clean_name}:\n\n"
        for m in history[-10:]:
            msg += f"• {m['p1']} {m['s1']}:{m['s2']} {m['p2']}\n"
        bot.reply_to(message, msg)
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['recent'])
def show_recent(message):
    try:
        tour = get_tournament(message)
        recent = tour.get("recent_results", [])
        if not recent:
            return bot.reply_to(message, "📭 Последние результаты отсутствуют в этом турнире.")

        msg = "⏱ Последние результаты:\n\n"
        for r in recent[:10]:
            sender_info = f" (от @{r['sender']})" if r.get("sender") else ""
            msg += f"• {r['p1']} {r['s1']}:{r['s2']} {r['p2']}{sender_info}\n"
        bot.reply_to(message, msg)
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['champions'])
def show_champions(message):
    try:
        champs = db.get("champions", [])
        if not champs:
            return bot.reply_to(message, "🏆 Список чемпионов пока пуст.")

        msg = "🏆 Зал славы (Чемпионы турниров):\n\n"
        for c in champs:
            msg += f"• Турнир ({c['date']}): 🏆 {c['champion']}\n"
        bot.reply_to(message, msg)
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['active'])
def show_active_tournaments(message):
    try:
        active_list = []
        for tid, t in tournaments.items():
            if not t.get("champion") and t.get("active_tour", {}).get("matches"):
                active_list.append(tid)

        if not active_list:
            return bot.reply_to(message, "📭 Нет активных турниров.")

        msg = f"🟢 Активные турниры ({len(active_list)}):\n\n"
        for tid in active_list:
            msg += f"• ID турнира/поста: {tid}\n"
        bot.reply_to(message, msg)
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['profile', 'профиль'])
def show_profile(message):
    try:
        args = message.text.split()
        target = args[1] if len(args) > 1 else message.from_user.username
        if not target: return
        clean_name = target.replace('@', '').lower()

        actual_name = None
        for name in tour_stats["players"]:
            if name.lower() == clean_name:
                actual_name = name
                break

        if not actual_name:
            bot.reply_to(message, "📭 Турнирный профиль не найден. Нужно сыграть хотя бы 1 матч.")
            return

        data = tour_stats["players"][actual_name]
        diff = data['goals_scored'] - data['goals_conceded']
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        
        matches = data['matches']
        wins = data['wins']
        losses = data['losses']
        draws = data['draws']
        winrate = round((wins / matches * 100), 1) if matches > 0 else 0.0

        # Подсчет общего количества завершенных турниров и чемпионств
        total_tournaments_count = len(tournaments)

        text = (f"🎟 ТУРНИРНЫЙ ПАСПОРТ\n\n"
                f"👤 Игрок: @{actual_name}\n"
                f"🏆 Рейтинг Эло: {data['elo']}\n"
                f"📊 Матчей: {matches} (П: {wins} | Н: {draws} | Пр: {losses})\n"
                f"📈 WinRate: {winrate}%\n"
                f"🔥 Серия побед: текущая {data['current_win_streak']} (макс. {data['max_win_streak']})\n"
                f"❄️ Серия поражений: текущая {data['current_loss_streak']} (макс. {data['max_loss_streak']})\n"
                f"⚽️ Забито: {data['goals_scored']} | 🧤 Пропущено: {data['goals_conceded']} (Разница: {diff_str})\n"
                f"💥 Самая крупная победа: +{data['biggest_win']}\n"
                f"💀 Самое крупное поражение: -{data['biggest_loss']}\n"
                f"👥 Последний соперник: {data['last_opponent'] or 'Нет'}\n"
                f"📌 Всего турниров: {total_tournaments_count}\n"
                f"🥇 Чемпионств: {data['championships']}")
        bot.reply_to(message, text)
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['tp'])
def tech_defeat(message):
    if not is_admin(message): return
    args = message.text.split()
    if len(args) < 2: return
    target = args[1].replace('@', '').lower()

    tour = get_tournament(message)
    for m in tour["active_tour"]["matches"]:
        if not m["done"]:
            if m["p1"].replace('@', '').lower() == target:
                success, _ = process_match_result(tour, m["p1"], m["p2"], 0, 6, sender_username=message.from_user.username)
                if success:
                    bot.reply_to(message, f"🔨 Тех. поражение. {m['p1']} 0:6 {m['p2']}")
                    check_stage_completion(message, tour)
                return
            elif m["p2"].replace('@', '').lower() == target:
                success, _ = process_match_result(tour, m["p1"], m["p2"], 6, 0, sender_username=message.from_user.username)
                if success:
                    bot.reply_to(message, f"🔨 Тех. поражение. {m['p1']} 6:0 {m['p2']}")
                    check_stage_completion(message, tour)
                return
    bot.reply_to(message, "📭 Активный матч для этого игрока не найден.")

@bot.message_handler(commands=['top'])
def show_top(message):
    try:
        players = tour_stats.get("players", {})
        if not players: return bot.reply_to(message, "📊 База пуста.")
        limit = int(message.text.split()[1]) if len(message.text.split()) > 1 and message.text.split()[1].isdigit() else 70
        sorted_players = sorted(players.items(), key=lambda x: x[1]["elo"], reverse=True)[:limit]
        bot.reply_to(message, "\n".join(["🏆 Mini Cup Elo Top"] + [f"{i}. @{n} ({d['elo']} Elo)" for i, (n, d) in enumerate(sorted_players, 1)]))
    except Exception as e: logging.error(e)

@bot.message_handler(commands=['stats'])
def show_stats(message):
    try:
        players = list(tour_stats.get("players", {}).items())
        if not players: return bot.reply_to(message, "📊 Статистика пуста.")
        
        best_elo = max(players, key=lambda x: x[1]["elo"]) if players else ("Нет", {"elo": 0})
        
        qualified_wr = [(n, d, (d["wins"]/d["matches"]*100) if d["matches"]>0 else 0) for n, d in players if d["matches"] >= 2]
        best_wr = max(qualified_wr, key=lambda x: x[2]) if qualified_wr else ("Нет", None, 0)
        
        best_scorer = max(players, key=lambda x: x[1]["goals_scored"]) if players else ("Нет", {"goals_scored": 0})
        
        qualified_def = [(n, d) for n, d in players if d["matches"] > 0]
        best_def = min(qualified_def, key=lambda x: x[1]["goals_conceded"]) if qualified_def else ("Нет", {"goals_conceded": 0})
        
        best_streak = max(players, key=lambda x: x[1]["max_win_streak"]) if players else ("Нет", {"max_win_streak": 0})
        
        most_active = max(players, key=lambda x: x[1]["matches"]) if players else ("Нет", {"matches": 0})
        
        total_tournaments = len(tournaments)
        total_matches = sum(d["matches"] for _, d in players) // 2
        total_goals = sum(d["goals_scored"] for _, d in players)
        avg_goals = round(total_goals / total_matches, 2) if total_matches > 0 else 0.0

        msg = (
            f"📊 ОБЩАЯ СТАТИСТИКА ТУРНИРА\n\n"
            f"🏆 Лучший Elo: @{best_elo[0]} ({best_elo[1]['elo']})\n"
            f"📈 Лучший WinRate: @{best_wr[0]} ({round(best_wr[2], 1)}%)\n"
            f"⚽️ Лучший бомбардир: @{best_scorer[0]} ({best_scorer[1]['goals_scored']} голов)\n"
            f"🛡 Лучшая защита: @{best_def[0]} ({best_def[1]['goals_conceded']} пропущено)\n"
            f"🔥 Самая длинная победная серия: @{best_streak[0]} ({best_streak[1]['max_win_streak']} побед)\n"
            f"⚡️ Самый активный игрок: @{most_active[0]} ({most_active[1]['matches']} матчей)\n\n"
            f"📌 Всего турниров: {total_tournaments}\n"
            f"📌 Всего матчей сыграно: {total_matches}\n"
            f"⚽️ Среднее количество голов за матч: {avg_goals}"
        )
        bot.reply_to(message, msg)
    except Exception as e: logging.error(e)

if __name__ == '__main__':
    logging.info("Старт бота (polling)...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            logging.error(f"Сбой polling: {e}. Перезапуск через 5 секунд...")
            time.sleep(5)
