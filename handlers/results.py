import re
import logging
from telebot import types


def register_result_handlers(bot, db, save_data, recalculate_stats, is_admin):

    RESULT_REGEX = re.compile(
        r"(@?[a-zA-Z0-9_]+)\s+(\d+)\s*[:\-]\s*(\d+)\s+(@?[a-zA-Z0-9_]+)",
        re.UNICODE
    )


    # ===============================
    # ПРИЕМ РЕЗУЛЬТАТА (ТЕКСТ + ФОТО)
    # ===============================

    @bot.message_handler(
        content_types=["text", "photo"],
        func=lambda m: m.chat.type in ["group", "supergroup"]
    )
    def process_result(message):

        try:

            # Берем текст либо подпись фото
            text = message.text or message.caption

            if not text:
                return


            match = RESULT_REGEX.search(text)

            if not match:
                return


            p1, s1, s2, p2 = match.groups()

            s1 = int(s1)
            s2 = int(s2)


            if s1 > 50 or s2 > 50:
                return


            active = db["active_tournament"]

            matches = active.get("matches", [])


            p1 = p1.lower()
            p2 = p2.lower()


            target = None


            # ищем существующий матч
            for m in matches:

                m1 = m["p1"].lower()
                m2 = m["p2"].lower()


                if (m1 == p1 and m2 == p2) or (m1 == p2 and m2 == p1):
                    target = m
                    break



            if not target:
                bot.reply_to(
                    message,
                    "❌ Такой матч не найден в текущем этапе."
                )
                return



            # проверяем участника
            sender = (
                "@" + message.from_user.username
                if message.from_user.username
                else ""
            ).lower()


            if not is_admin(sender):

                if sender not in [
                    target["p1"].lower(),
                    target["p2"].lower()
                ]:
                    bot.reply_to(
                        message,
                        "❌ Вы не участник этого матча."
                    )
                    return



            if target["done"]:

                bot.reply_to(
                    message,
                    "❌ Этот матч уже завершен."
                )
                return



            # если игроки написаны наоборот
            if target["p1"].lower() == p2:
                s1, s2 = s2, s1



            target["s1"] = s1
            target["s2"] = s2
            target["done"] = True


            save_data()

            recalculate_stats()



            kb = types.InlineKeyboardMarkup(row_width=2)

            kb.add(
                types.InlineKeyboardButton(
                    "✏️ Изменить счет",
                    callback_data=f"result_edit_{target['id']}"
                ),

                types.InlineKeyboardButton(
                    "❌ Отменить",
                    callback_data=f"result_cancel_{target['id']}"
                )
            )

            kb.add(
                types.InlineKeyboardButton(
                    "🔨 ТП первому (6:0)",
                    callback_data=f"result_tp1_{target['id']}"
                ),

                types.InlineKeyboardButton(
                    "🔨 ТП второму (0:6)",
                    callback_data=f"result_tp2_{target['id']}"
                )
            )


            bot.reply_to(
                message,
                f"✅ <b>Результат принят!</b>\n\n"
                f"{target['p1']} <b>{s1}:{s2}</b> {target['p2']}",
                parse_mode="HTML",
                reply_markup=kb
            )



        except Exception as e:
            logging.error(
                f"Result error: {e}"
            )



    # ===============================
    # КНОПКИ АДМИНА
    # ===============================

    @bot.callback_query_handler(
        func=lambda c: c.data.startswith("result_")
    )
    def result_actions(call):

        try:

            if not is_admin(call.from_user.username):
                return bot.answer_callback_query(
                    call.id,
                    "Нет прав",
                    show_alert=True
                )


            action, match_id = call.data.split("_")[1:]


            active = db["active_tournament"]


            match = None

            for m in active["matches"]:
                if m["id"] == match_id:
                    match = m
                    break


            if not match:
                return


            if action == "cancel":

                match["done"] = False
                match["s1"] = None
                match["s2"] = None


            elif action == "tp1":

                match["s1"] = 6
                match["s2"] = 0
                match["done"] = True


            elif action == "tp2":

                match["s1"] = 0
                match["s2"] = 6
                match["done"] = True


            elif action == "edit":

                bot.answer_callback_query(
                    call.id,
                    "Отправьте новый счет в чат.",
                    show_alert=True
                )
                return



            save_data()
            recalculate_stats()


            bot.answer_callback_query(
                call.id,
                "Готово"
            )


        except Exception as e:
            logging.error(
                f"Callback result error: {e}"
            )
