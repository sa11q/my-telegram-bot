import telebot
import logging
import os
import re
import json
import threading
import time
import random
import math
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

# 1. Логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =====================================================================
TOKEN = "8876079721:AAEh9mZcoNmMXPqC9txDKMB-9RHd3lQPqGk"
# =====================================================================

bot = telebot.TeleBot(TOKEN)
ADMINS = ['wonti9', 'avelon67', 'nupik91']
DB_FILE = "database.json"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "posts": {int(k): set(v) for k, v in data.get("posts", {}).items()},
                    "stats": data.get("stats", {"players": {}, "teams": {}}),
                    "active_tour": data.get("active_tour", {"teams": [], "matches": [], "stage": "Отборочные", "deadline_str": "Не установлен"})
                }
        except Exception as e:
            logging.error(f"Ошибка загрузки базы: {e}")
    return {"posts": {}, "stats": {"players": {}, "teams": {}}, "active_tour": {"teams": [], "matches": [], "stage": "Отборочные", "deadline_str": "Не установлен"}}

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
            "elo": 1000, "goals_scored": 0, "goals_conceded": 0, "matches": 0, "history": []
        }
    if "history" not in tour_stats["players"][clean_name]:
        tour_stats["players"][clean_name]["history"] = []

def process_match_result(m, s1, s2):
    """Принимает словарь матча и окончательный счет, обновляет статистику"""
    name1 = m["p1"].replace('@', '').lower()
    name2 = m["p2"].replace('@', '').lower()
    init_player(name1)
    init_player(name2)
    
    # Сохраняем предыдущий Elo для возможности отката
    old_r1 = tour_stats["players"][name1]["elo"]
    old_r2 = tour_stats["players"][name2]["elo"]
    m["old_elo1"] = old_r1
    m["old_elo2"] = old_r2
    
    m["s1"], m["s2"] = s1, s2
    m["done"] = True
    m["pending"] = None
    
    tour_stats["players"][name1]["goals_scored"] += s1
    tour_stats["players"][name1]["goals_conceded"] += s2
    tour_stats["players"][name1]["matches"] += 1
    
    tour_stats["players"][name2]["goals_scored"] += s2
    tour_stats["players"][name2]["goals_conceded"] += s1
    tour_stats["players"][name2]["matches"] += 1
    
    new_r1, new_r2 = calculate_elo(old_r1, old_r2, s1, s2)
    tour_stats["players"][name1]["elo"] = new_r1
    tour_stats["players"][name2]["elo"] = new_r2

    # Запись в историю (максимум 5 последних)
    res1 = "✅ W" if s1 > s2 else ("❌ L" if s1 < s2 else "🤝 D")
    res2 = "✅ W" if s2 > s1 else ("❌ L" if s2 < s1 else "🤝 D")
    
    tour_stats["players"][name1]["history"].insert(0, f"{res1} {s1}:{s2} vs {m['p2']}")
    tour_stats["players"][name2]["history"].insert(0, f"{res2} {s2}:{s1} vs {m['p1']}")
    
    tour_stats["players"][name1]["history"] = tour_stats["players"][name1]["history"][:5]
    tour_stats["players"][name2]["history"] = tour_stats["players"][name2]["history"][:5]
    
    save_data()

def revert_match(m):
    """Откат статистики матча, если админ перезаписывает результат"""
    if not m.get("done"): return
    name1 = m["p1"].replace('@', '').lower()
    name2 = m["p2"].replace('@', '').lower()
    s1, s2 = m["s1"], m["s2"]
    
    tour_stats["players"][name1]["goals_scored"] -= s1
    tour_stats["players"][name1]["goals_conceded"] -= s2
    tour_stats["players"][name1]["matches"] -= 1
    
    tour_stats["players"][name2]["goals_scored"] -= s2
    tour_stats["players"][name2]["goals_conceded"] -= s1
    tour_stats["players"][name2]["matches"] -= 1
    
    tour_stats["players"][name1]["elo"] = m.get("old_elo1", tour_stats["players"][name1]["elo"])
    tour_stats["players"][name2]["elo"] = m.get("old_elo2", tour_stats["players"][name2]["elo"])
    
    if tour_stats["players"][name1]["history"]: tour_stats["players"][name1]["history"].pop(0)
    if tour_stats["players"][name2]["history"]: tour_stats["players"][name2]["history"].pop(0)
    
    m["done"] = False
    m["s1"], m["s2"] = None, None

# ================= АДМИНСКИЙ СБОР ЧЕРЕЗ /collect =================

@bot.message_handler(commands=['collect'])
def admin_collect_players(message):
    if not is_admin(message): return
    if not message.reply_to_message:
        bot.reply_to(message, "⚠️ Эту команду нужно отправлять **в ответ (реплаем)** на пост-анонс турнира!")
        return

    thread_id = get_thread_id(message)
    if thread_id not in posts_data: posts_data[thread_id] = set()

    target_msg = message.reply_to_message
    collected = set()

    if target_msg.text:
        collected.update(re.findall(r'(@[a-zA-Z0-9_]+)', target_msg.text))
    if target_msg.from_user and target_msg.from_user.username:
        collected.add(f"@{target_msg.from_user.username}")

    added = 0
    for u in collected:
        if u not in posts_data[thread_id]:
            posts_data[thread_id].add(u)
            added += 1

    save_data()
    bot.reply_to(message, f"✅ Сбор завершен!\n➕ Новых: {added}\n👥 Всего: {len(posts_data[thread_id])}")

@bot.message_handler(commands=['list', 'players'])
def show_collected_list(message):
    thread_id = get_thread_id(message)
    participants = sorted(list(posts_data.get(thread_id, set())))
    if not participants:
        bot.reply_to(message, "📭 Под этим постом/веткой еще нет участников.")
        return
    bot.reply_to(message, f"📋 Участники ({len(participants)}):\n\n" + "\n".join([f"{i}. {p}" for i, p in enumerate(participants, 1)]))

# ================= ДЕДЛАЙНЫ И ЖЕРЕБЬЕВКА =================

@bot.message_handler(commands=['setdeadline'])
def set_deadline(message):
    if not is_admin(message): return
    args = message.text.replace('/setdeadline', '').strip()
    if not args:
        bot.reply_to(message, "⚠️ Формат: `/setdeadline 29.07 22:00`")
        return
        
    try:
        current_year = datetime.now().year
        dt_obj = datetime.strptime(f"{current_year}.{args}", "%Y.%d.%m %H:%M")
        
        active_tour["deadline_str"] = args
        active_tour["deadline_ts"] = dt_obj.timestamp()
        active_tour["warning_sent"] = False
        active_tour["chat_id"] = message.chat.id
        save_data()
        bot.reply_to(message, f"⏰ Дедлайн стадии установлен на: **{args}**")
    except Exception as e:
        bot.reply_to(message, "❌ Ошибка формата. Используй ДД.ММ ЧЧ:ММ (Пример: 29.07 22:00)")

@bot.message_handler(commands=['draw'])
def make_draw(message):
    if not is_admin(message): return
    thread_id = get_thread_id(message)
    collected = list(posts_data.get(thread_id, set()))
    if not collected:
        bot.reply_to(message, "📭 Список пуст. Нужен `/collect`.")
        return

    args = message.text.lower().split()[1:]
    mode, custom_limit = "solo", None
    for arg in args:
        if arg in ["solo", "1v1"]: mode = "solo"
        elif arg in ["duo", "2v2"]: mode = "duo"
        elif arg in ["trio", "3v3"]: mode = "trio"
        elif arg in ["4v4", "4-4"]: mode = "4v4"
        elif arg.isdigit(): custom_limit = int(arg)

    team_size = {"solo": 1, "duo": 2, "trio": 3, "4v4": 4}[mode]
    random.shuffle(collected)
    total_available = min(custom_limit, len(collected)) if custom_limit else len(collected)
    total_teams = total_available // team_size

    if total_teams < 2:
         return bot.reply_to(message, "⚠️ Недостаточно участников.")

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
    active_tour["stage"] = f"Турнир ({mode.upper()})"
    active_tour["deadline_str"] = "Не установлен"
    active_tour["deadline_ts"] = None
    active_tour["chat_id"] = message.chat.id
    
    msg = f"🏆 ТУРНИРНАЯ СЕТКА ({mode.upper()})\n\n"
    for i in range(0, len(team_names), 2):
        t1_name, t2_name = team_names[i], team_names[i+1]
        t1_members, t2_members = teams[i], teams[i+1]
        
        if mode != "solo": msg += f"⚔️ {t1_name} vs {t2_name}\n"
        for j in range(min(len(t1_members), len(t2_members))):
            active_tour["matches"].append({
                "p1": t1_members[j], "p2": t2_members[j],
                "t1": t1_name, "t2": t2_name,
                "s1": None, "s2": None, "done": False, "pending": None
            })
            prefix = "⚔️ " if mode == "solo" else "• "
            msg += f"{prefix}{t1_members[j]} vs {t2_members[j]}\n"
        if mode != "solo": msg += "\n"

    save_data()
    bot.reply_to(message, msg)

@bot.message_handler(commands=['next'])
def next_stage(message):
    if not is_admin(message): return
    teams = active_tour.get("teams", [])
    if not teams: return bot.reply_to(message, "📭 Сетка пуста.")

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
        else: advancing_teams.append(random.choice([t1, t2]))

    active_tour["teams"] = advancing_teams
    active_tour["matches"] = []
    active_tour["stage"] = "Плей-офф (Следующий раунд)"
    active_tour["deadline_str"] = "Не установлен"
    active_tour["deadline_ts"] = None

    if len(advancing_teams) < 2:
        bot.reply_to(message, f"🎉 ТУРНИР ЗАВЕРШЕН! Чемпион: {advancing_teams[0]}")
        return save_data()

    msg = "🏆 СЛЕДУЮЩИЙ ЭТАП\n\n"
    for i in range(0, len(advancing_teams), 2):
        if i + 1 >= len(advancing_teams): break
        tA, tB = advancing_teams[i], advancing_teams[i+1]
        if tA.startswith("Команда"): msg += f"⚔️ {tA} vs {tB}\n"
        rosterA = list(tour_stats["teams"].get(tA, [tA]))
        rosterB = list(tour_stats["teams"].get(tB, [tB]))

        for j in range(min(len(rosterA), len(rosterB))):
            active_tour["matches"].append({
                "p1": rosterA[j], "p2": rosterB[j], "t1": tA, "t2": tB,
                "s1": None, "s2": None, "done": False, "pending": None
            })
            msg += f"⚔️ {rosterA[j]} vs {rosterB[j]}\n"

    save_data()
    bot.reply_to(message, msg)

# ================= РЕГИСТРАЦИЯ И ПРОВЕРКА СЧЕТА =================

@bot.message_handler(func=lambda m: bool(re.search(r'@[a-zA-Z0-9_]+\s+\d+\s*:\s*\d+\s+@[a-zA-Z0-9_]+', str(m.text))))
def propose_score(message):
    """Игрок отправляет счет строго по шаблону @user1 2:3 @user2"""
    text = message.text
    if text.startswith('/setscore') or text.startswith('/results'): return
    
    matches_found = re.findall(r'(@[a-zA-Z0-9_]+)\s+(\d+)\s*:\s*(\d+)\s+(@[a-zA-Z0-9_]+)', text)
    if not matches_found: return
    
    p1, s1, s2, p2 = matches_found[0]
    p1_clean, p2_clean = p1.replace('@', '').lower(), p2.replace('@', '').lower()
    username = message.from_user.username.lower() if message.from_user else ""
    s1, s2 = int(s1), int(s2)
    
    is_admin_user = username in ADMINS
    if not is_admin_user and username not in [p1_clean, p2_clean]:
        return # Отправляет не участник матча
        
    for m in active_tour["matches"]:
        m_p1, m_p2 = m["p1"].replace('@', '').lower(), m["p2"].replace('@', '').lower()
        if (m_p1 == p1_clean and m_p2 == p2_clean) or (m_p1 == p2_clean and m_p2 == p1_clean):
            if m.get("done"):
                bot.reply_to(message, "⚠️ Этот матч уже сыгран. Если есть ошибка, админ может изменить счет через /setscore.")
                return
                
            if m_p1 == p2_clean: s1, s2 = s2, s1 # Выравниваем счет относительно m["p1"]
                
            m["pending"] = {"s1": s1, "s2": s2, "by": username}
            save_data()
            bot.reply_to(message, f"⏳ Результат **{m['p1']} {s1}:{s2} {m['p2']}** ожидает подтверждения.\nСоперник или админ, напишите `/confirm` для подтверждения.")
            return

@bot.message_handler(commands=['confirm'])
def confirm_score(message):
    username = message.from_user.username.lower() if message.from_user else ""
    is_admin_user = username in ADMINS
    confirmed = 0
    
    for m in active_tour["matches"]:
        if not m.get("done") and m.get("pending"):
            p1, p2 = m["p1"].replace('@', '').lower(), m["p2"].replace('@', '').lower()
            reporter = m["pending"]["by"]
            
            # Подтвердить может соперник (не репортер) или админ
            if (username in [p1, p2] and username != reporter) or is_admin_user:
                process_match_result(m, m["pending"]["s1"], m["pending"]["s2"])
                bot.send_message(message.chat.id, f"✅ Результат подтвержден: **{m['p1']} {m['s1']}:{m['s2']} {m['p2']}**")
                confirmed += 1
                
    if confirmed == 0:
        bot.reply_to(message, "📭 Нет результатов, ожидающих твоего подтверждения.")

@bot.message_handler(commands=['setscore', 'results'])
def admin_setscore(message):
    if not is_admin(message): return
    text = message.text.replace('/setscore', '').replace('/results', '').strip()
    
    matches_found = re.findall(r'(@[a-zA-Z0-9_]+)\s+(\d+)\s*:\s*(\d+)\s+(@[a-zA-Z0-9_]+)', text)
    if not matches_found:
        bot.reply_to(message, "❌ Неверный формат. Нужно строго: `/setscore @user1 2:3 @user2`")
        return
        
    p1, s1, s2, p2 = matches_found[0]
    p1_c, p2_c = p1.replace('@', '').lower(), p2.replace('@', '').lower()
    s1, s2 = int(s1), int(s2)
    
    for m in active_tour["matches"]:
        m_p1, m_p2 = m["p1"].replace('@', '').lower(), m["p2"].replace('@', '').lower()
        if (m_p1 == p1_c and m_p2 == p2_c) or (m_p1 == p2_c and m_p2 == p1_c):
            if m_p1 == p2_c: s1, s2 = s2, s1
            
            if m.get("done"):
                revert_match(m) # Откат старых стат, если переписываем
                
            process_match_result(m, s1, s2)
            bot.reply_to(message, f"🛠 **Админ-вмешательство!** Счет установлен: {m['p1']} {s1}:{s2} {m['p2']}")
            return
            
    bot.reply_to(message, "📭 Этот матч не найден в текущей сетке.")

# ================= ИНФО КОМАНДЫ =================

@bot.message_handler(commands=['vs'])
def find_opponent(message):
    username = message.from_user.username.lower() if message.from_user else ""
    for m in active_tour["matches"]:
        if not m.get("done"):
            opp, team = None, None
            if m["p1"].replace('@', '').lower() == username: opp, team = m['p2'], m['t2']
            elif m["p2"].replace('@', '').lower() == username: opp, team = m['p1'], m['t1']
            
            if opp:
                stage = active_tour.get("stage", "Турнир")
                deadline = active_tour.get("deadline_str", "Не установлен")
                bot.reply_to(message, f"📌 **Стадия:** {stage}\n⏰ **Дедлайн:** {deadline}\n\n⚔️ Твой соперник: **{opp}** (от {team})")
                return
    bot.reply_to(message, "📭 У тебя нет активных матчей.")

@bot.message_handler(commands=['profile'])
def show_profile(message):
    target = message.text.split()[1] if len(message.text.split()) > 1 else message.from_user.username
    if not target: return
    clean_name = target.replace('@', '').lower()
    actual_name = next((n for n in tour_stats["players"] if n.lower() == clean_name), None)

    if not actual_name:
         return bot.reply_to(message, "📭 Турнирный профиль не найден.")

    data = tour_stats["players"][actual_name]
    diff = data['goals_scored'] - data['goals_conceded']
    
    hist = data.get("history", [])
    hist_text = "\n".join(hist) if hist else "Нет сыгранных матчей"

    text = (f"🎟 ТУРНИРНЫЙ ПАСПОРТ: @{actual_name}\n\n"
            f"🏆 Рейтинг Эло: {data['elo']}\n"
            f"📊 Матчей: {data['matches']} (Разница мячей: {'+' if diff>0 else ''}{diff})\n"
            f"⚽️ Забито: {data['goals_scored']} | 🧤 Пропущено: {data['goals_conceded']}\n\n"
            f"📖 **Последние 5 матчей:**\n{hist_text}")
    bot.reply_to(message, text)

@bot.message_handler(commands=['tp'])
def tech_defeat(message):
    if not is_admin(message): return
    args = message.text.split()
    if len(args) < 2: return
    target = args[1].replace('@', '').lower()

    for m in active_tour["matches"]:
        if not m.get("done"):
            if m["p1"].replace('@', '').lower() == target:
                process_match_result(m, 0, 6)
                bot.reply_to(message, f"🔨 Тех. поражение. {m['p1']} 0:6 {m['p2']}")
                return
            elif m["p2"].replace('@', '').lower() == target:
                process_match_result(m, 6, 0)
                bot.reply_to(message, f"🔨 Тех. поражение. {m['p1']} 6:0 {m['p2']}")
                return

@bot.message_handler(commands=['top', 'stats'])
def show_top(message):
    players = tour_stats.get("players", {})
    if not players: return bot.reply_to(message, "📊 База пуста.")
    sorted_players = sorted(players.items(), key=lambda x: x[1]["elo"], reverse=True)[:30]
    bot.reply_to(message, "\n".join(["🏆 Топ Игроков (Elo)"] + [f"{i}. {n} ({d['elo']})" for i, (n, d) in enumerate(sorted_players, 1)]))

# ================= ПОТОК ПРОВЕРКИ ДЕДЛАЙНОВ =================

def check_deadlines():
    while True:
        time.sleep(60)
        try:
            dt_ts = active_tour.get("deadline_ts")
            if dt_ts and not active_tour.get("warning_sent"):
                now = time.time()
                # Если до дедлайна осталось менее 20 минут (1200 сек) и мы еще не уведомляли
                if dt_ts - 1200 <= now < dt_ts:
                    chat_id = active_tour.get("chat_id")
                    if chat_id:
                        pending_matches = [m for m in active_tour.get("matches", []) if not m.get("done")]
                        if pending_matches:
                            msg = "⚠️ **ВНИМАНИЕ! ДО ДЕДЛАЙНА ОСТАЛОСЬ 20 МИНУТ!**\n\nНе сыграны:\n"
                            for m in pending_matches:
                                msg += f"⚔️ {m['p1']} vs {m['p2']}\n"
                            bot.send_message(chat_id, msg)
                    active_tour["warning_sent"] = True
                    save_data()
        except Exception as e:
            logging.error(f"Deadline thread error: {e}")

# ================= СЕРВЕР RENDER =================

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args): pass

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

if __name__ == '__main__':
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=check_deadlines, daemon=True).start()
    logging.info("Старт бота...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            logging.error(e)
            time.sleep(5)
