import re
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

edit_states = {}

def register_result_handlers(bot, db, save_data, recalculate_all_stats, is_admin):
    
    @bot.message_handler(func=lambda m: m.chat.type in ['group', 'supergroup'] and m.text)
    def handle_match_score_message(message):
        text = message.text.strip()
        user_id = message.from_user.id
        
        if user_id in edit_states:
            if not is_admin(message.from_user.username):
                del edit_states[user_id]
                return
            
            match_id = edit_states[user_id]
            score_match = re.search(r'(\d+)\s*[:\-]\s*(\d+)', text)
            if score_match:
                s1 = int(score_match.group(1))
                s2 = int(score_match.group(2))
                
                active = db["active_tournament"]
                found_m = None
                for m in active.get("matches", []):
                    if m["id"] == match_id:
                        found_m = m
                        break
                
                if found_m:
                    found_m["s1"] = s1
                    found_m["s2"] = s2
                    found_m["done"] = True
                    found_m["sender"] = message.from_user.username
                    save_data()
                    recalculate_all_stats()
                    
                    del edit_states[user_id]
                    
                    kb = InlineKeyboardMarkup(row_width=2)
                    kb.add(
                        InlineKeyboardButton("✏️ Изменить", callback_data=f"res_edit_{match_id}"),
                        InlineKeyboardButton("❌ Отмена", callback_data=f"res_cancel_{match_id}")
                    )
                    kb.add(
                        InlineKeyboardButton("🔨 ТП 6:0", callback_data=f"res_tp1_{match_id}"),
                        InlineKeyboardButton("🔨 ТП 0:6", callback_data=f"res_tp2_{match_id}")
                    )
                    
                    try:
                        bot.reply_to(
                            message,
                            f"✅ Результат принят!\n⚔️ {found_m['p1']} {s1}:{s2} {found_m['p2']}",
                            reply_markup=kb,
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass
                    return
            else:
                bot.reply_to(message, "⚠️ Неверный формат счета. Введите счет в формате `3:2`", parse_mode="Markdown")
                return

        match_pattern = re.search(r'(@\w+)\s+(\d+)\s*[:\-]\s*(\d+)\s*(@\w+)', text)
        if match_pattern:
            p1_raw = match_pattern.group(1)
            s1 = int(match_pattern.group(2))
            s2 = int(match_pattern.group(3))
            p2_raw = match_pattern.group(4)
            
            active = db["active_tournament"]
            matches = active.get("matches", [])
            
            target_match = None
            for m in matches:
                if not m["done"]:
                    if (m["p1"].lower() == p1_raw.lower() and m["p2"].lower() == p2_raw.lower()) or \
                       (m["p1"].lower() == p2_raw.lower() and m["p2"].lower() == p1_raw.lower()):
                        target_match = m
                        break
            
            if target_match:
                if target_match["p1"].lower() == p2_raw.lower() and target_match["p2"].lower() == p1_raw.lower():
                    target_match["s1"] = s2
                    target_match["s2"] = s1
                else:
                    target_match["s1"] = s1
                    target_match["s2"] = s2
                
                target_match["done"] = True
                target_match["sender"] = message.from_user.username
                
                save_data()
                recalculate_all_stats()
                
                kb = InlineKeyboardMarkup(row_width=2)
                kb.add(
                    InlineKeyboardButton("✏️ Изменить", callback_data=f"res_edit_{target_match['id']}"),
                    InlineKeyboardButton("❌ Отмена", callback_data=f"res_cancel_{target_match['id']}"),
                )
                kb.add(
                    InlineKeyboardButton("🔨 ТП 6:0", callback_data=f"res_tp1_{target_match['id']}"),
                    InlineKeyboardButton("🔨 ТП 0:6", callback_data=f"res_tp2_{target_match['id']}"),
                )
                
                try:
                    bot.reply_to(
                        message,
                        f"✅ Результат принят!\n⚔️ {target_match['p1']} {target_match['s1']}:{target_match['s2']} {target_match['p2']}",
                        reply_markup=kb,
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

    @bot.callback_query_handler(func=lambda call: call.data and call.data.startswith('res_'))
    def handle_match_callbacks(call):
        data = call.data
        parts = data.split('_', 2)
        if len(parts) < 3:
            return
        action = parts[1]
        match_id = parts[2]
        
        active = db["active_tournament"]
        target_match = None
        for m in active.get("matches", []):
            if m["id"] == match_id:
                target_match = m
                break
        
        if not target_match:
            for m in active.get("history", []):
                if m["id"] == match_id:
                    target_match = m
                    break
        
        if not target_match:
            bot.answer_callback_query(call.id, "❌ Матч не найден.", show_alert=True)
            return
        
        user_username = call.from_user.username
        user_id = call.from_user.id
        
        is_match_participant = user_username and (
            user_username.lower() == target_match["p1"].replace('@', '').lower() or
            user_username.lower() == target_match["p2"].replace('@', '').lower()
        )
        
        if action == 'edit':
            if not is_admin(user_username) and not is_match_participant:
                bot.answer_callback_query(call.id, "⛔️ Только участник матча или админ может изменить счет.", show_alert=True)
                return
            
            edit_states[user_id] = match_id
            bot.answer_callback_query(call.id, "✏️ Отправьте новый счет в чат (например: 3:1)")
            try:
                bot.edit_message_text(
                    f"✏️ Ожидание нового счета для матча:\n{target_match['p1']} vs {target_match['p2']}\n\nОтправьте счет в чат (например `3:1`).",
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode="Markdown"
                )
            except Exception:
                pass
            return
        
        if not is_admin(user_username) and not is_match_participant:
            bot.answer_callback_query(call.id, "⛔️ Недостаточно прав.", show_alert=True)
            return
        
        if action == 'cancel':
            target_match["s1"] = None
            target_match["s2"] = None
            target_match["done"] = False
            target_match["sender"] = None
            bot.answer_callback_query(call.id, "❌ Результат отменен.")
            
        elif action == 'tp1':
            target_match["s1"] = 6
            target_match["s2"] = 0
            target_match["done"] = True
            bot.answer_callback_query(call.id, "🔨 Установлен ТП 6:0")
            
        elif action == 'tp2':
            target_match["s1"] = 0
            target_match["s2"] = 6
            target_match["done"] = True
            bot.answer_callback_query(call.id, "🔨 Установлен ТП 0:6")
        
        save_data()
        recalculate_all_stats()
        
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("✏️ Изменить", callback_data=f"res_edit_{match_id}"),
            InlineKeyboardButton("❌ Отмена", callback_data=f"res_cancel_{match_id}"),
        )
        kb.add(
            InlineKeyboardButton("🔨 ТП 6:0", callback_data=f"res_tp1_{match_id}"),
            InlineKeyboardButton("🔨 ТП 0:6", callback_data=f"res_tp2_{match_id}"),
        )
        
        status_text = f"⚔️ {target_match['p1']} {target_match['s1']}:{target_match['s2']} {target_match['p2']}" if target_match["done"] else f"⚔️ Матч не сыгран: {target_match['p1']} vs {target_match['p2']}"
        
        try:
            bot.edit_message_text(
                f"✅ Результат обновлен!\n{status_text}",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=kb,
                parse_mode="Markdown"
            )
        except Exception:
            pass
