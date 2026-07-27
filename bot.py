import telebot

TOKEN = '8876079721:AAEsmS1IbFBtp-t-OCMu8Q7LwapolDOviVk'
bot = telebot.TeleBot(TOKEN)

# Формат: { thread_id: set("@user1", "@user2") }
posts_data = {}


@bot.message_handler(func=lambda message: True)
def track_comments(message):
    thread_id = message.message_thread_id or (message.reply_to_message.message_id if message.reply_to_message else None)
    
    if thread_id and message.text:
        if thread_id not in posts_data:
            posts_data[thread_id] = set()
            
        words = message.text.split()
        for word in words:
            if '@' in word:
                clean_username = word.strip(".,!?:;()[]{}")
                if clean_username.startswith('@') and len(clean_username) > 1:
                    posts_data[thread_id].add(clean_username)


@bot.message_handler(commands=['collect'])
def collect_for_post(message):
    thread_id = message.message_thread_id or (message.reply_to_message.message_id if message.reply_to_message else None)
    
    if not thread_id:
        bot.reply_to(message, "⚠️ Напишите эту команду в комментариях под конкретным постом (или ответом на пост)!")
        return

    collected = posts_data.get(thread_id, set())
    
    if collected:
        text = f"📋 **Собранные юзернеймы под этим постом ({len(collected)} шт.):**\n\n" + "\n".join(collected)
        
        if len(text) > 4000:
            filename = f"users_post_{thread_id}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write("\n".join(collected))
            with open(filename, "rb") as f:
                bot.send_document(message.chat.id, f, caption="✅ Файл со всеми собранными юзернеймами под этим постом:")
        else:
            bot.reply_to(message, text)
    else:
        bot.reply_to(message, "Под этим постом пока не найдено ни одного сообщения с `@`!")


print("Бот успешно запущен и готов собирать комментарии по постам!")
bot.infinity_polling()
