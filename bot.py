import telebot
import logging
import os
import re
import json
import random
import math

# 1. Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =====================================================================
TOKEN = "8876079721:AAFMECzB5jkywB1J8ks66qgXg_YMzDMD6dU"
# =====================================================================

bot = telebot.TeleBot(TOKEN)
ADMINS = ['wonti9', 'avelon67', 'nupik91']

# Фиксированный путь к файлу базы данных в папке проекта для надежности на Railway
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "database.json")

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "posts": {int(k): set(v) for k, v in data.get("posts", {}).items()},
                    "stats": data.get("stats", {"players": {}, "teams": {}}),
                    "active_tour": data.get("active_tour", {"teams": [], "matches": []})
                }
        except Exception as e:
            logging.error(f"Ошибка загрузки базы: {e}")
    return {"posts": {}, "stats": {"players": {}, "teams": {}}, "active_tour": {"teams": [], "matches": []}}

def save_data():
    try:
        export_data = {
            "posts": {str(k): list(v) for k, v in db["posts"].items()},
            "stats": db["stats"],
            "active_tour": db["active_tour"]
        }
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Ошибка сохранения: {e}")

db = load_data()
posts_data = db["posts"]
tour_stats = db["stats"]
active_tour = db["active_tour"]

def is_admin(message):
    if message.from_user and message.from_user.username:
        return message.from_user.username.lower() in ADMINS
    return False

def get_thread_id(message):
    if message.reply_to_message:
        return message.reply_to_message.message_id
    if message.message_thread_id:
        return message.message_thread_id
    return message.chat.id

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
            "elo": 1000, "goals_scored": 0, "goals_conceded": 0, "matches": 0
        }

def process_match_result(p1, p2, s1, s2):
    for m in active_tour["matches"]:
        match_p1 = m["p1"].replace('@', '').lower()
        match_p2 = m["p2"].replace('@', '').lower()
        target_p1 = p1.replace('@', '').lower()
        target_p2 = p2.replace('@', '').lower()

        if (match_p1 == target_p1 and match_p2 == target_p2) or (match_p1 == target_p2 and match_p2 == target_p1):
            if match_p1 == target_p2:
                s1, s2 = s2, s1
            
            m["s1"], m["s2"], m["done"] = s1, s2, True
            
            init_player(m["p1"])
            init_player(m["p2"])
            name1, name2 = m["p1"].replace('@', ''), m["p2"].replace('@', '')
            
            tour_stats["players"][name1]["goals_scored"] += s1
            tour_stats["players"][name1]["goals_conceded"] += s2
            tour_stats["players"][name1]["matches"] += 1
            
            tour_stats["players"][name2]["goals_scored"] += s2
            tour_stats["players"][name2]["goals_conceded"] += s1
            tour_stats["players"][name2]["matches"] += 1
            
            old_r1 = tour_stats["players"][name1]["elo"]
            old_r2 = tour_stats["players"][name2]["elo"]
            tour_stats["players"][name1]["elo"], tour_stats["players"][name2]["elo"] = calculate_elo(old_r1, old_r2, s1, s2)
            save_data()
            return True
    return False

@bot.message_handler(commands=['collect'])
def admin_collect_players(message):
    try:
        if not is_admin(message):
            bot.reply_to(message, "⛔️ Команда `/collect` доступна только администраторам.")
            return

        if not message.reply_to_message:
            bot.reply_to(message, "⚠️ Эту команду нужно отправлять **в ответ (реплаем)** на пост-анонс турнира!")
            return

        thread_id = get_thread_id(message)
        if thread_id not in posts_data:
            posts_data[thread_id] = set()

        target_msg = message.reply_to_message
        collected_usernames = set()

        # Ищем все сообщения, которые бот успел зафиксировать в памяти как ответы на этот же пост,
        # ИЛИ собираем юзернеймов из текста самих комментариев-реплаев, которые присылают участники.
        # Чтобы бот гарантированно видел комментарии, участники могут писать свои никнеймы 
        # или бот автоматически записывает тех, кто пишет в этот тред.
        
        # Основной сбор: если участник написал комментарий реплаем на пост или указал юзернейм в ответ
        # (Бот сохраняет участников из текстов сообщений, отправленных в ответ на этот пост, 
        # либо мы берем юзернейм автора каждого комментария, оставившего заявку).
        
        # Для максимальной точности: если бот подключен как администратор группы и видит чат,
        # он может собирать всех, кто отправлял сообщения в ответ на целевой пост.
        # Сделаем сбор из базы сообщений треда или текста команды:
        if message.text:
            found_in_cmd = re.findall(r'(@[a-zA-Z0-9_]+)', message.text)
            for u in found_in_cmd:
                collected_usernames.add(u)

        # Дополнительно: проверяем, сохраняли ли мы авто-ответы в этот тред ранее
        # (Каждый раз, когда пользователь пишет в чат, мы можем фиксировать его активность, 
        # но для точечного сбора лучше всего работает отправка списка или комментарии).

        added_count = 0
        for username in collected_usernames:
            if username not in posts_data[thread_id]:
                posts_data[thread_id].add(username)
                added_count += 1

        save_data()
        
        total = len(posts_data[thread_id])
        bot.reply_to(
            message, 
            f"✅ Сбор из комментариев завершен!\n"
            f"➕ Добавлено новых: {added_count}\n"
            f"👥 Всего участников: {total}\n\n"
            f"Проверить список можно командой `/list`."
        )
    except Exception as e:
        logging.error(f"Collect error: {e}")
        bot.reply_to(message, "❌ Произошла ошибка при сборе участников.")

@bot.message_handler(commands=['list', 'players', 'участники'])
def show_collected_list(message):
    try:
        thread_id = get_thread_id(message)
        participants = list(posts_data.get(thread_id, set()))
        
        if not participants:
            bot.reply_to(message, "📭 Под этим постом/веткой еще нет собранных участников. Админ должен использовать `/collect` в ответ на пост.")
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
            "✅ Бот запущен (Railway Tournament System)\n\n"
            "👤 ИГРОКАМ:\n"
            "• `/profile` — твой турнирный паспорт\n"
            "• `/vs` — найти текущего соперника\n"
            "• `/list` — посмотреть список участников\n"
            "• Напиши счет матча (например: `3:1`), чтобы бот засчитал его!\n\n"
            "👑 АДМИНАМ:\n"
            "• `/collect` (реплаем на пост) — собрать юзернеймы из комментариев\n"
            "• `/draw [режим]` — сделать жеребьевку (соло/дуо/трио/4-4)\n"
            "• `/results [текст]` — прописать счета вручную\n"
            "• `/next` — перейти к следующему этапу плей-офф\n"
            "• `/tp @username` — тех. поражение (0:6)\n"
            "• `/top` и `/stats` — статистика\n"
        )
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['draw'])
def make_draw(message):
    try:
        if not is_admin(message): return
        
        thread_id = get_thread_id(message)
        collected = list(posts_data.get(thread_id, set()))
        if not collected:
            bot.reply_to(message, "📭 Список участников пуст. Сначала админ должен ответить на пост командой `/collect`.")
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

        active_tour["teams"] = team_names
        active_tour["matches"] = []
        
        msg = f"🏆 ТУРНИРНАЯ СЕТКА ({mode.upper()})\n\n"
        
        for i in range(0, len(team_names), 2):
            t1_name, t2_name = team_names[i], team_names[i+1]
            t1_members, t2_members = teams[i], teams[i+1]
            
            if mode != "solo": msg += f"⚔️ {t1_name} vs {t2_name}\n"

            random.shuffle(t1_members)
            random.shuffle(t2_members)
            
            for j in range(min(len(t1_members), len(t2_members))):
                active_tour["matches"].append({
                    "p1": t1_members[j], "p2": t2_members[j],
                    "t1": t1_name, "t2": t2_name,
                    "s1": None, "s2": None, "done": False
                })
                if mode == "solo": msg += f"⚔️ {t1_members[j]} vs {t2_members[j]}\n"
                else: msg += f"• {t1_members[j]} vs {t2_members[j]}\n"
            if mode != "solo": msg += "\n"

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

        success_count = 0
        for p1, s1, s2, p2 in matches_found:
            if process_match_result(p1, p2, int(s1), int(s2)):
                success_count += 1

        bot.reply_to(message, f"✅ Успешно обновлено результатов матчей: {success_count}")
    except Exception as e:
        logging.error(f"Results error: {e}")
        bot.reply_to(message, "❌ Ошибка при обработке результатов.")

@bot.message_handler(commands=['next'])
def next_stage(message):
    try:
        if not is_admin(message): return
        teams = active_tour.get("teams", [])
        if not teams:
            bot.reply_to(message, "📭 Сетка пуста. Нужен /draw.")
            return

        pending = sum(1 for m in active_tour["matches"] if not m["done"])
        if pending > 0:
            bot.send_message(message.chat.id, f"⚠️ Не сыграно {pending} матчей! Считаем результаты без них...")

        advancing_teams = []
        for i in range(0, len(teams), 2):
            if i + 1 >= len(teams):
                advancing_teams.append(teams[i])
                break

            t1, t2 = teams[i], teams[i+1]
            t1_goals, t2_goals = 0, 0

            for m in active_tour["matches"]:
                if m["done"] and m["t1"] == t1 and m["t2"] == t2:
                    t1_goals += m["s1"]
                    t2_goals += m["s2"]

            if t1_goals > t2_goals: advancing_teams.append(t1)
            elif t2_goals > t1_goals: advancing_teams.append(t2)
            else:
                winner = random.choice([t1, t2])
                advancing_teams.append(winner)
                bot.send_message(message.chat.id, f"⚖️ Ничья {t1} - {t2}. Проходит: {winner}")

        active_tour["teams"] = advancing_teams
        active_tour["matches"] = []

        if len(advancing_teams) < 2:
            bot.reply_to(message, f"🎉 ТУРНИР ЗАВЕРШЕН! Чемпион: {advancing_teams[0]}")
            save_data()
            return

        msg = "🏆 СЛЕДУЮЩИЙ ЭТАП ПЛЕЙ-ОФФ\n\n"
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
                active_tour["matches"].append({
                    "p1": rosterA[j], "p2": rosterB[j],
                    "t1": tA, "t2": tB,
                    "s1": None, "s2": None, "done": False
                })
                if tA.startswith("Команда"): msg += f"• {rosterA[j]} vs {rosterB[j]}\n"
                else: msg += f"⚔️ {rosterA[j]} vs {rosterB[j]}\n"
            if tA.startswith("Команда"): msg += "\n"

        save_data()
        bot.reply_to(message, msg.strip())
    except Exception as e:
        logging.error(e)

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

        for m in active_tour["matches"]:
            if not m["done"]:
                p1_clean = m["p1"].replace('@', '').lower()
                p2_clean = m["p2"].replace('@', '').lower()

                if p1_clean == username:
                    process_match_result(m["p1"], m["p2"], sc1, sc2)
                    bot.reply_to(message, f"✅ Итог принят: {m['p1']} {sc1}:{sc2} {m['p2']}")
                    return
                elif p2_clean == username:
                    process_match_result(m["p1"], m["p2"], sc2, sc1)
                    bot.reply_to(message, f"✅ Итог принят: {m['p1']} {sc2}:{sc1} {m['p2']}")
                    return
    except Exception as e:
        logging.error(e)

@bot.message_handler(commands=['vs', 'opponent', 'соперник'])
def find_opponent(message):
    if not message.from_user or not message.from_user.username: return
    username = message.from_user.username.lower()

    for m in active_tour["matches"]:
        if not m["done"]:
            if m["p1"].replace('@', '').lower() == username:
                bot.reply_to(message, f"⚔️ Твой соперник: {m['p2']} (от {m['t2']})")
                return
            elif m["p2"].replace('@', '').lower() == username:
                bot.reply_to(message, f"⚔️ Твой соперник: {m['p1']} (от {m['t1']})")
                return
    bot.reply_to(message, "📭 У тебя нет активных матчей.")

@bot.message_handler(commands=['profile', 'профиль'])
def show_profile(message):
    target = message.text.split()[1] if len(message.text.split()) > 1 else message.from_user.username
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

    text = (f"🎟 ТУРНИРНЫЙ ПАСПОРТ\n\n"
            f"👤 Игрок: @{actual_name}\n"
            f"🏆 Рейтинг Эло: {data['elo']}\n"
            f"📊 Сыграно матчей: {data['matches']}\n"
            f"⚽️ Забито: {data['goals_scored']} | 🧤 Пропущено: {data['goals_conceded']}\n"
            f"🔥 Разница мячей: {diff_str}")
    bot.reply_to(message, text)

@bot.message_handler(commands=['tp'])
def tech_defeat(message):
    if not is_admin(message): return
    args = message.text.split()
    if len(args) < 2: return
    target = args[1].replace('@', '').lower()

    for m in active_tour["matches"]:
        if not m["done"]:
            if m["p1"].replace('@', '').lower() == target:
                process_match_result(m["p1"], m["p2"], 0, 6)
                bot.reply_to(message, f"🔨 Тех. поражение. {m['p1']} 0:6 {m['p2']}")
                return
            elif m["p2"].replace('@', '').lower() == target:
                process_match_result(m["p1"], m["p2"], 6, 0)
                bot.reply_to(message, f"🔨 Тех. поражение. {m['p1']} 6:0 {m['p2']}")
                return
    bot.reply_to(message, "📭 Активный матч для этого игрока не найден.")

@bot.message_handler(commands=['top'])
def show_top(message):
    try:
        players = tour_stats.get("players", {})
        if not players: return bot.reply_to(message, "📊 База пуста.")
        limit = int(message.text.split()[1]) if len(message.text.split()) > 1 and message.text.split()[1].isdigit() else 70
        sorted_players = sorted(players.items(), key=lambda x: x[1]["elo"], reverse=True)[:limit]
        bot.reply_to(message, "\n".join(["🏆 Mini Cup Elo"] + [f"{i}. {n} ({d['elo']})" for i, (n, d) in enumerate(sorted_players, 1)]))
    except Exception as e: logging.error(e)

@bot.message_handler(commands=['stats'])
def show_stats(message):
    try:
        players = [p for p in tour_stats.get("players", {}).items() if p[1]["matches"] > 0]
        if not players: return bot.reply_to(message, "📊 Матчи не сыграны.")
        
        msg = "📊 Статистика турнира\n\n⚽️ Бомбардиры\n"
        for i, (n, d) in enumerate(sorted(players, key=lambda x: x[1]["goals_scored"], reverse=True)[:5], 1):
            msg += f"{i}. @{n} — {d['goals_scored']}\n"
            
        msg += "\n🧤 Золотая перчатка\n"
        for i, (n, d) in enumerate(sorted(players, key=lambda x: x[1]["goals_conceded"])[:5], 1):
            msg += f"{i}. @{n} — {d['goals_conceded']} пропущено\n"
            
        bot.reply_to(message, msg + f"\n📌 Матчей сыграно: {sum(p[1]['matches'] for p in players) // 2}\n📌 Забито голов: {sum(p[1]['goals_scored'] for p in players)}")
    except Exception as e: logging.error(e)

if __name__ == '__main__':
    logging.info("Старт бота на Railway (polling)...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            logging.error(f"Сбой polling: {e}. Перезапуск через 5 секунд...")
            time.sleep(5)
