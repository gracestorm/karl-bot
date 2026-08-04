import asyncio
import json
import os
import io
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import httpx
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MODELHUB_API_KEY = os.getenv("MODELHUB_API_KEY")

API_URL = os.getenv("API_URL", "https://modelhub.my/v1")
KARL_SYSTEM_PROMPT = """Вы - доктор Карл Вандерлик, медицинский доктор и доктор философии, клинический психотерапевт, специалист по Комплексному ПТСР, травме и диссоциации.

ПРАВИЛА ОФОРМЛЕНИЯ И СТИЛЯ:
1. Никогда не говорите как стандартный ИИ-помощник. Никаких дежурных фраз вежливости и канцеляризмов. Всегда обращайтесь к пользователю на «вы».
2. Ваш тон — строгий, глубокий, аналитический, но невероятно бережный и теплый европейский клиницист.
3. ФОРМАТИРОВАНИЕ ДЛЯ TELEGRAM: Используйте **жирный шрифт** для ключевых понятий, *курсив* для внутренних состояний и мягкие эмодзи (🧠, ⚓, 🌿, 🕯️) там, где это уместно для создания безопасной атмосферы. Избегайте использования решеток (#) для заголовков, чтобы текст выглядел гармонично.
4. Сохраняйте абсолютную преемственность беседы. Не сбрасывайте образ от сообщения к сообщению.
5. Разбирайте защитные механизмы психики и структурную диссоциацию просто, используя понятные метафоры. Задавайте не больше 1-2 мягких вопросов в конце, чтобы не перегружать диалог.

БАЗА ЗНАНИЙ И ЛИТЕРАТУРА:
Когда пользователь просит литературу, сразу выдайте структурированный список с красивым оформлением:
1. **Бессел ван дер Колк — «Тело помнит всё»** — как травма живет в соматической системе и как запустить исцеление через тело 🌿.
2. **Пит Уокер — «Комплексное ПТСР: Руководство по выздоровлению»** — работа с внутренним критиком, эмоциональными флешбэками и токсичным стыдом 🕯️.
3. **Ричард Шварц — «Нет плохих частей»** — бережное знакомство с субличностями и защитными частями психики 🧩.
4. **Деб Дана — «Поливагальная теория в терапии»** — понятный путеводитель по нервной системе, безопасности и замиранию ⚓."""

SESSIONS_FILE = "sessions.json"
MODEL_NAME = "claude-sonnet-4-6"

def load_sessions():
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except Exception:
            return {}
    return {}

def save_sessions():
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(user_sessions, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения сессий: {e}")

user_sessions = load_sessions()
user_message_buffers = {}

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📁 Экспорт сеанса"), KeyboardButton("Сбросить диалог")],
        [KeyboardButton("Теория КПТСР"), KeyboardButton("Литература")],
        [KeyboardButton("Самопомощь & IFS"), KeyboardButton("SOS / Флэшбек")]
    ],
    resize_keyboard=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sessions[user_id] = []
    save_sessions()
    text = "Guten Tag. Я — доктор Карл Вандерлик. Я слушаю вас."
    await update.message.reply_text(text, reply_markup=MAIN_MENU)

async def export_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_sessions or not user_sessions[user_id]:
        await update.message.reply_text("История сеанса пуста, экспортировать нечего.", reply_markup=MAIN_MENU)
        return

    log_lines = ["# Сеанс психотерапевтического анализа — Dr. Karl Wunderlich, M.D., Ph.D.\n"]
    for msg in user_sessions[user_id]:
        role_name = "Пациент" if msg["role"] == "user" else "Доктор Карл"
        log_lines.append(f"### {role_name}:\n{msg['content']}\n\n---\n")

    file_content = "".join(log_lines)
    bio = io.BytesIO(file_content.encode("utf-8"))
    bio.name = "karl_session_export.md"

    await update.message.reply_document(
        document=bio,
        caption="📁 Вот полный протокол вашей текущей сессии.",
        reply_markup=MAIN_MENU
    )

async def send_long_message(target_msg, text, reply_markup=None, parse_mode="Markdown"):
    MAX_LEN = 4000
    if len(text) <= MAX_LEN:
        await target_msg.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        return

    parts = [text[i:i+MAX_LEN] for i in range(0, len(text), MAX_LEN)]
    await target_msg.edit_text(parts[0], parse_mode=parse_mode)
    
    chat_id = target_msg.chat_id
    for idx, part in enumerate(parts[1:], 1):
        is_last = (idx == len(parts) - 1)
        markup = reply_markup if is_last else None
        await target_msg.get_bot().send_message(chat_id=chat_id, text=part, parse_mode=parse_mode, reply_markup=markup)

async def process_buffered_message(user_id, context):
    await asyncio.sleep(1.5)
    
    if user_id not in user_message_buffers or not user_message_buffers[user_id]["texts"]:
        return

    full_text = "\n".join(user_message_buffers[user_id]["texts"])
    update_obj = user_message_buffers[user_id]["update"]
    
    del user_message_buffers[user_id]

    if user_id not in user_sessions:
        user_sessions[user_id] = []

    user_sessions[user_id].append({"role": "user", "content": full_text})
    save_sessions()
    
    await generate_response(user_id, update_obj, is_callback=False)

async def generate_response(user_id, update_or_query, is_callback=False):
    if user_id not in user_sessions or not user_sessions[user_id]:
        msg = "История пуста."
        if is_callback:
            await update_or_query.message.reply_text(msg)
        else:
            await update_or_query.reply_text(msg)
        return

    headers = {
        "Authorization": f"Bearer {MODELHUB_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = [{"role": "system", "content": KARL_SYSTEM_PROMPT}] + user_sessions[user_id]
    payload = {"model": MODEL_NAME, "messages": messages, "temperature": 0.4}

    if is_callback:
        status_msg = await update_or_query.message.reply_text("⏳ Пересчитываю...")
    else:
        status_msg = await update_or_query.message.reply_text("⏳ Анализирую...")

    try:
        async def fetch():
            async with httpx.AsyncClient(timeout=120.0) as client:
                return await client.post(API_URL, json=payload, headers=headers)

        response = None
        for attempt in range(3):
            try:
                response = await fetch()
                break
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2)

        data = response.json()
        if response.status_code == 200:
            reply = data["choices"][0]["message"]["content"]
            
            if is_callback and user_sessions[user_id] and user_sessions[user_id][-1]["role"] == "assistant":
                user_sessions[user_id][-1]["content"] = reply
            else:
                user_sessions[user_id].append({"role": "assistant", "content": reply})

            save_sessions()

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔄 Перегенерировать", callback_data="regen"),
                    InlineKeyboardButton("⬅️ Откатить шаг", callback_data="undo")
                ]
            ])
            
            await send_long_message(status_msg, reply, reply_markup=keyboard, parse_mode="Markdown")
        else:
            err = data.get("error", {}).get("message", "Ошибка API")
            await status_msg.edit_text(f"API Error ({response.status_code}): {err}")
    except Exception as e:
        await status_msg.edit_text(f"Ошибка сети/таймаут: {e}")

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "📁 Экспорт сеанса":
        await export_chat(update, context)
        return
    elif text == "Литература":
        lit_text = (
            "📚 **Рекомендуемая литература по работе с травмой и КПТ:**\n\n"
            "1. **Бессел ван дер Колк — «Тело помнит всё»** — как травма имплантируется в соматическую систему и как запустить исцеление через тело.\n"
            "2. **Пит Уокер — «Комплексное ПТСР: Руководство по выздоровлению»** — фундаментальная работа с внутренним критиком, эмоциональными флешбэками и токсичным стыдом.\n"
            "3. **Ричард Шварц — «Нет плохих частей»** — мягкое введение в IFS — работу с субличностями и защитными частями психики.\n"
            "4. **Деб Дана — «Поливагальная теория в терапии»** — понятный путеводитель по нервной системе, безопасности, активации и замиранию.\n\n"
            "Какая из этих тем отзывается вам больше всего? Напишите, и мы разберем её точечно."
        )
        if user_id not in user_sessions:
            user_sessions[user_id] = []
        user_sessions[user_id].append({"role": "user", "content": "Литература"})
        user_sessions[user_id].append({"role": "assistant", "content": lit_text})
        save_sessions()
        await update.message.reply_text(lit_text, parse_mode="Markdown", reply_markup=MAIN_MENU)
        return
    elif "SOS" in text:
        await update.message.reply_text("🛡️ **Протокол заземления при флэшбеке:**\n\n1. Почувствуйте опору под стопами.\n2. Найдите глазами 3 предмета синего цвета.\n3. Сделайте мягкий, удлиненный выдох.", reply_markup=MAIN_MENU, parse_mode="Markdown")
        return
    elif "Сбросить" in text:
        user_message_buffers.pop(user_id, None)
        user_sessions[user_id] = []
        save_sessions()
        await update.message.reply_text("🧹 История диалога очищена.", reply_markup=MAIN_MENU)
        return

    if user_id not in user_message_buffers:
        user_message_buffers[user_id] = {"texts": [], "update": update, "task": None}
    
    user_message_buffers[user_id]["texts"].append(text)
    user_message_buffers[user_id]["update"] = update

    if user_message_buffers[user_id]["task"]:
        user_message_buffers[user_id]["task"].cancel()

    task = asyncio.create_task(process_buffered_message(user_id, context))
    user_message_buffers[user_id]["task"] = task

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "regen":
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await generate_response(user_id, query, is_callback=True)
        
    elif query.data == "undo":
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
            
        if user_id in user_sessions and len(user_sessions[user_id]) >= 2:
            user_sessions[user_id].pop()
            user_sessions[user_id].pop()
            save_sessions()
            await query.message.reply_text("↩️ Последний обмен сообщениями отменен. Можете написать мысль заново.", reply_markup=MAIN_MENU)
        else:
            await query.message.reply_text("Нечего откатывать — история пуста или слишком короткая.", reply_markup=MAIN_MENU)

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).read_timeout(60).connect_timeout(60).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("export", export_chat))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    print("Доктор Карл запущен в стабильном режиме!")
    app.run_polling(drop_pending_updates=True)

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"I am alive!")

def run_web_server():
    server = HTTPServer(('0.0.0.0', 10000), SimpleHandler)
    server.serve_forever()

if __name__ == '__main__':
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    main()
SESSIONS_FILE = "sessions.json"
MODEL_NAME = "claude-sonnet-4-6"

def load_sessions():
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except Exception:
            return {}
    return {}

def save_sessions():
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(user_sessions, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения сессий: {e}")

user_sessions = load_sessions()
user_message_buffers = {}

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📁 Экспорт сеанса"), KeyboardButton("Сбросить диалог")],
        [KeyboardButton("Теория КПТСР"), KeyboardButton("Литература")],
        [KeyboardButton("Самопомощь & IFS"), KeyboardButton("SOS / Флэшбек")]
    ],
    resize_keyboard=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sessions[user_id] = []
    save_sessions()
    text = "Guten Tag. Я — доктор Карл Вандерлих. Продолжайте."
    await update.message.reply_text(text, reply_markup=MAIN_MENU)

async def export_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_sessions or not user_sessions[user_id]:
        await update.message.reply_text("История сеанса пуста, экспортировать нечего.", reply_markup=MAIN_MENU)
        return

    log_lines = ["# Сеанс психотерапевтического анализа — Dr. Karl Wunderlich, M.D., Ph.D.\n"]
    for msg in user_sessions[user_id]:
        role_name = "Пациент" if msg["role"] == "user" else "Доктор Карл"
        log_lines.append(f"### {role_name}:\n{msg['content']}\n\n---\n")

    file_content = "".join(log_lines)
    bio = io.BytesIO(file_content.encode("utf-8"))
    bio.name = "karl_session_export.md"

    await update.message.reply_document(
        document=bio,
        caption="📁 Вот полный протокол вашей текущей сессии.",
        reply_markup=MAIN_MENU
    )

async def send_long_message(target_msg, text, reply_markup=None, parse_mode="Markdown"):
    MAX_LEN = 4000
    if len(text) <= MAX_LEN:
        await target_msg.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        return

    parts = [text[i:i+MAX_LEN] for i in range(0, len(text), MAX_LEN)]
    await target_msg.edit_text(parts[0], parse_mode=parse_mode)
    
    chat_id = target_msg.chat_id
    for idx, part in enumerate(parts[1:], 1):
        is_last = (idx == len(parts) - 1)
        markup = reply_markup if is_last else None
        await target_msg.get_bot().send_message(chat_id=chat_id, text=part, parse_mode=parse_mode, reply_markup=markup)

async def process_buffered_message(user_id, context):
    await asyncio.sleep(1.5)
    
    if user_id not in user_message_buffers or not user_message_buffers[user_id]["texts"]:
        return

    full_text = "\n".join(user_message_buffers[user_id]["texts"])
    update_obj = user_message_buffers[user_id]["update"]
    
    del user_message_buffers[user_id]

    if user_id not in user_sessions:
        user_sessions[user_id] = []

    user_sessions[user_id].append({"role": "user", "content": full_text})
    save_sessions()
    
    await generate_response(user_id, update_obj, is_callback=False)

async def generate_response(user_id, update_or_query, is_callback=False):
    if user_id not in user_sessions or not user_sessions[user_id]:
        msg = "История пуста."
        if is_callback:
            await update_or_query.message.reply_text(msg)
        else:
            await update_or_query.reply_text(msg)
        return

    headers = {
        "Authorization": f"Bearer {MODELHUB_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = [{"role": "system", "content": KARL_SYSTEM_PROMPT}] + user_sessions[user_id]
    payload = {"model": MODEL_NAME, "messages": messages, "temperature": 0.4}

    if is_callback:
        status_msg = await update_or_query.message.reply_text("⏳ Пересчитываю...")
    else:
        status_msg = await update_or_query.message.reply_text("⏳ Анализирую...")

    try:
        async def fetch():
            async with httpx.AsyncClient(timeout=120.0) as client:
                return await client.post(API_URL, json=payload, headers=headers)

        response = None
        for attempt in range(3):
            try:
                response = await fetch()
                break
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2)

        data = response.json()
        if response.status_code == 200:
            reply = data["choices"][0]["message"]["content"]
            
            if is_callback and user_sessions[user_id] and user_sessions[user_id][-1]["role"] == "assistant":
                user_sessions[user_id][-1]["content"] = reply
            else:
                user_sessions[user_id].append({"role": "assistant", "content": reply})

            save_sessions()

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔄 Перегенерировать", callback_data="regen"),
                    InlineKeyboardButton("⬅️ Откатить шаг", callback_data="undo")
                ]
            ])
            
            await send_long_message(status_msg, reply, reply_markup=keyboard, parse_mode="Markdown")
        else:
            err = data.get("error", {}).get("message", "Ошибка API")
            await status_msg.edit_text(f"API Error ({response.status_code}): {err}")
    except Exception as e:
        await status_msg.edit_text(f"Ошибка сети/таймаут: {e}")

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "📁 Экспорт сеанса":
        await export_chat(update, context)
        return
    elif text == "Литература":
        lit_text = (
            "📚 **Рекомендуемая литература по работе с травмой и КПТ:**\n\n"
            "1. **Бессел ван дер Колк — «Тело помнит всё»** — как травма имплантируется в соматическую систему и как запустить исцеление через тело.\n"
            "2. **Пит Уокер — «Комплексное ПТСР: Руководство по выздоровлению»** — фундаментальная работа с внутренним критиком, эмоциональными флешбэками и токсичным стыдом.\n"
            "3. **Ричард Шварц — «Нет плохих частей»** — мягкое введение в IFS — работу с субличностями и защитными частями психики.\n"
            "4. **Деб Дана — «Поливагальная теория в терапии»** — понятный путеводитель по нервной системе, безопасности, активации и замиранию.\n\n"
            "Какая из этих тем отзывается вам больше всего? Напишите, и мы разберем её точечно."
        )
        if user_id not in user_sessions:
            user_sessions[user_id] = []
        user_sessions[user_id].append({"role": "user", "content": "Литература"})
        user_sessions[user_id].append({"role": "assistant", "content": lit_text})
        save_sessions()
        await update.message.reply_text(lit_text, parse_mode="Markdown", reply_markup=MAIN_MENU)
        return
    elif "SOS" in text:
        await update.message.reply_text("Протокол флэшбека:\n1. Заземлитесь (стопы на пол).\n2. Найдите 3 синих предмета.\n3. Удлинённый выдох.", reply_markup=MAIN_MENU)
        return
    elif "Сбросить" in text:
        user_message_buffers.pop(user_id, None)
        user_sessions[user_id] = []
        save_sessions()
        await update.message.reply_text("История диалога очищена.", reply_markup=MAIN_MENU)
        return

    if user_id not in user_message_buffers:
        user_message_buffers[user_id] = {"texts": [], "update": update, "task": None}
    
    user_message_buffers[user_id]["texts"].append(text)
    user_message_buffers[user_id]["update"] = update

    if user_message_buffers[user_id]["task"]:
        user_message_buffers[user_id]["task"].cancel()

    task = asyncio.create_task(process_buffered_message(user_id, context))
    user_message_buffers[user_id]["task"] = task

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "regen":
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await generate_response(user_id, query, is_callback=True)
        
    elif query.data == "undo":
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
            
        if user_id in user_sessions and len(user_sessions[user_id]) >= 2:
            user_sessions[user_id].pop()
            user_sessions[user_id].pop()
            save_sessions()
            await query.message.reply_text("↩️ Последний обмен сообщениями отменен. Можете написать мысль заново.", reply_markup=MAIN_MENU)
        else:
            await query.message.reply_text("Нечего откатывать — история пуста или слишком короткая.", reply_markup=MAIN_MENU)

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).read_timeout(60).connect_timeout(60).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("export", export_chat))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    print("Доктор Карл запущен в стабильном режиме!")
    app.run_polling(drop_pending_updates=True)

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"I am alive!")

def run_web_server():
    server = HTTPServer(('0.0.0.0', 10000), SimpleHandler)
    server.serve_forever()

if __name__ == '__main__':
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    main()
3. Ричард Шварц — «Нет плохих частей» (Мягкое введение в IFS — работу с субличностями и защитными частями психики).
4. Деб Дана — «Поливагальная теория в терапии» (Понятный путеводитель по нервной системе, безопасности, активации и замиранию).
After presenting this list, invite the user to pick a specific focus or request a tailored recommendation based on their current symptom."""

SESSIONS_FILE = "sessions.json"
MODEL_NAME = "claude-sonnet-4-6"

def load_sessions():
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {int(k): v for k, v in data.items()}
        except Exception:
            return {}
    return {}

def save_sessions():
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(user_sessions, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения сессий: {e}")

user_sessions = load_sessions()
user_message_buffers = {}

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📁 Экспорт сеанса"), KeyboardButton("Сбросить диалог")],
        [KeyboardButton("Теория КПТСР"), KeyboardButton("Литература")],
        [KeyboardButton("Самопомощь & IFS"), KeyboardButton("SOS / Флэшбек")]
    ],
    resize_keyboard=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sessions[user_id] = []
    save_sessions()
    text = "Guten Tag. Я — доктор Карл Вандерлих. Продолжайте."
    await update.message.reply_text(text, reply_markup=MAIN_MENU)

async def export_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_sessions or not user_sessions[user_id]:
        await update.message.reply_text("История сеанса пуста, экспортировать нечего.", reply_markup=MAIN_MENU)
        return

    log_lines = ["# Сеанс психотерапевтического анализа — Dr. Karl Wunderlich, M.D., Ph.D.\n"]
    for msg in user_sessions[user_id]:
        role_name = "Пациент" if msg["role"] == "user" else "Доктор Карл"
        log_lines.append(f"### {role_name}:\n{msg['content']}\n\n---\n")

    file_content = "".join(log_lines)
    bio = io.BytesIO(file_content.encode("utf-8"))
    bio.name = "karl_session_export.md"

    await update.message.reply_document(
        document=bio,
        caption="📁 Вот полный протокол вашей текущей сессии.",
        reply_markup=MAIN_MENU
    )

async def send_long_message(target_msg, text, reply_markup=None, parse_mode="Markdown"):
    MAX_LEN = 4000
    if len(text) <= MAX_LEN:
        await target_msg.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        return

    parts = [text[i:i+MAX_LEN] for i in range(0, len(text), MAX_LEN)]
    await target_msg.edit_text(parts[0], parse_mode=parse_mode)
    
    chat_id = target_msg.chat_id
    for idx, part in enumerate(parts[1:], 1):
        is_last = (idx == len(parts) - 1)
        markup = reply_markup if is_last else None
        await target_msg.get_bot().send_message(chat_id=chat_id, text=part, parse_mode=parse_mode, reply_markup=markup)

async def process_buffered_message(user_id, context):
    await asyncio.sleep(1.5)
    
    if user_id not in user_message_buffers or not user_message_buffers[user_id]["texts"]:
        return

    full_text = "\n".join(user_message_buffers[user_id]["texts"])
    update_obj = user_message_buffers[user_id]["update"]
    
    del user_message_buffers[user_id]

    if user_id not in user_sessions:
        user_sessions[user_id] = []

    user_sessions[user_id].append({"role": "user", "content": full_text})
    save_sessions()
    
    await generate_response(user_id, update_obj, is_callback=False)

async def generate_response(user_id, update_or_query, is_callback=False):
    if user_id not in user_sessions or not user_sessions[user_id]:
        msg = "История пуста."
        if is_callback:
            await update_or_query.message.reply_text(msg)
        else:
            await update_or_query.reply_text(msg)
        return

    headers = {
        "Authorization": f"Bearer {MODELHUB_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = [{"role": "system", "content": KARL_SYSTEM_PROMPT}] + user_sessions[user_id]
    payload = {"model": MODEL_NAME, "messages": messages, "temperature": 0.4}

    if is_callback:
        status_msg = await update_or_query.message.reply_text("⏳ Пересчитываю...")
    else:
        status_msg = await update_or_query.message.reply_text("⏳ Анализирую...")

    try:
        async def fetch():
            async with httpx.AsyncClient(timeout=120.0) as client:
                return await client.post(API_URL, json=payload, headers=headers)

        response = None
        for attempt in range(3):
            try:
                response = await fetch()
                break
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2)

        data = response.json()
        if response.status_code == 200:
            reply = data["choices"][0]["message"]["content"]
            
            if is_callback and user_sessions[user_id] and user_sessions[user_id][-1]["role"] == "assistant":
                user_sessions[user_id][-1]["content"] = reply
            else:
                user_sessions[user_id].append({"role": "assistant", "content": reply})

            save_sessions()

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔄 Перегенерировать", callback_data="regen"),
                    InlineKeyboardButton("⬅️ Откатить шаг", callback_data="undo")
                ]
            ])
            
            await send_long_message(status_msg, reply, reply_markup=keyboard, parse_mode="Markdown")
        else:
            err = data.get("error", {}).get("message", "Ошибка API")
            await status_msg.edit_text(f"API Error ({response.status_code}): {err}")
    except Exception as e:
        await status_msg.edit_text(f"Ошибка сети/таймаут: {e}")

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "📁 Экспорт сеанса":
        await export_chat(update, context)
        return
    elif text == "Литература":
        lit_text = (
            "📚 **Рекомендуемая литература по работе с травмой и КПТ:**\n\n"
            "1. **Бессел ван дер Колк — «Тело помнит всё»** — как травма имплантируется в соматическую систему и как запустить исцеление через тело.\n"
            "2. **Пит Уокер — «Комплексное ПТСР: Руководство по выздоровлению»** — фундаментальная работа с внутренним критиком, эмоциональными флешбэками и токсичным стыдом.\n"
            "3. **Ричард Шварц — «Нет плохих частей»** — мягкое введение в IFS — работу с субличностями и защитными частями психики.\n"
            "4. **Деб Дана — «Поливагальная теория в терапии»** — понятный путеводитель по нервной системе, безопасности, активации и замиранию.\n\n"
            "Какая из этих тем отзывается вам больше всего? Напишите, и мы разберем её точечно."
        )
        if user_id not in user_sessions:
            user_sessions[user_id] = []
        user_sessions[user_id].append({"role": "user", "content": "Литература"})
        user_sessions[user_id].append({"role": "assistant", "content": lit_text})
        save_sessions()
        await update.message.reply_text(lit_text, parse_mode="Markdown", reply_markup=MAIN_MENU)
        return
    elif "SOS" in text:
        await update.message.reply_text("Протокол флэшбека:\n1. Заземлитесь (стопы на пол).\n2. Найдите 3 синих предмета.\n3. Удлинённый выдох.", reply_markup=MAIN_MENU)
        return
    elif "Сбросить" in text:
        user_message_buffers.pop(user_id, None)
        user_sessions[user_id] = []
        save_sessions()
        await update.message.reply_text("История диалога очищена.", reply_markup=MAIN_MENU)
        return

    if user_id not in user_message_buffers:
        user_message_buffers[user_id] = {"texts": [], "update": update, "task": None}
    
    user_message_buffers[user_id]["texts"].append(text)
    user_message_buffers[user_id]["update"] = update

    if user_message_buffers[user_id]["task"]:
        user_message_buffers[user_id]["task"].cancel()

    task = asyncio.create_task(process_buffered_message(user_id, context))
    user_message_buffers[user_id]["task"] = task

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "regen":
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await generate_response(user_id, query, is_callback=True)
        
    elif query.data == "undo":
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
            
        if user_id in user_sessions and len(user_sessions[user_id]) >= 2:
            user_sessions[user_id].pop()
            user_sessions[user_id].pop()
            save_sessions()
            await query.message.reply_text("↩️ Последний обмен сообщениями отменен. Можете написать мысль заново.", reply_markup=MAIN_MENU)
        else:
            await query.message.reply_text("Нечего откатывать — история пуста или слишком короткая.", reply_markup=MAIN_MENU)

telegram_app = None

async def setup_bot():
    global telegram_app
    telegram_app = ApplicationBuilder().token(TELEGRAM_TOKEN).read_timeout(60).connect_timeout(60).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("export", export_chat))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    telegram_app.add_handler(CallbackQueryHandler(handle_callback))
    
    await telegram_app.initialize()
    await telegram_app.bot.set_webhook(url=f"{RENDER_EXTERNAL_URL}/webhook")
    await telegram_app.start()
    print("Доктор Карл запущен в режиме вебхуков!")

class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"I am alive!")
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/webhook":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                json_data = json.loads(post_data.decode('utf-8'))
                update = Update.de_json(json_data, telegram_app.bot)
                
                # Передаем обновление в фоновый цикл бота
                asyncio.run_coroutine_threadsafe(
                    telegram_app.process_update(update), 
                    telegram_app.updater.running_loop if hasattr(telegram_app, 'updater') and telegram_app.updater else asyncio.get_event_loop()
                )
            except Exception as e:
                print(f"Ошибка обработки вебхука: {e}")
            
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

def run_web_server():
    server = HTTPServer(('0.0.0.0', 10000), WebhookHandler)
    server.serve_forever()

if __name__ == '__main__':
    # Запускаем инициализацию и вебхуки в цикле
    loop = asyncio.get_event_loop()
    loop.run_until_complete(setup_bot())
    
    # Запускаем веб-сервер на порту 10000 для Render
    run_web_server()

user_sessions = load_sessions()
user_message_buffers = {}

MAIN_MENU = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📁 Экспорт сеанса"), KeyboardButton("Сбросить диалог")],
        [KeyboardButton("Теория КПТСР"), KeyboardButton("Литература")],
        [KeyboardButton("Самопомощь & IFS"), KeyboardButton("SOS / Флэшбек")]
    ],
    resize_keyboard=True
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sessions[user_id] = []
    save_sessions()
    text = "Guten Tag. Я — доктор Карл Вандерлих. Продолжайте."
    await update.message.reply_text(text, reply_markup=MAIN_MENU)

async def export_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_sessions or not user_sessions[user_id]:
        await update.message.reply_text("История сеанса пуста, экспортировать нечего.", reply_markup=MAIN_MENU)
        return

    log_lines = ["# Сеанс психотерапевтического анализа — Dr. Karl Wunderlich, M.D., Ph.D.\n"]
    for msg in user_sessions[user_id]:
        role_name = "Пациент" if msg["role"] == "user" else "Доктор Карл"
        log_lines.append(f"### {role_name}:\n{msg['content']}\n\n---\n")

    file_content = "".join(log_lines)
    bio = io.BytesIO(file_content.encode("utf-8"))
    bio.name = "karl_session_export.md"

    await update.message.reply_document(
        document=bio,
        caption="📁 Вот полный протокол вашей текущей сессии.",
        reply_markup=MAIN_MENU
    )

async def send_long_message(target_msg, text, reply_markup=None, parse_mode="Markdown"):
    MAX_LEN = 4000
    if len(text) <= MAX_LEN:
        await target_msg.edit_text(text, parse_mode=parse_mode, reply_markup=reply_markup)
        return

    parts = [text[i:i+MAX_LEN] for i in range(0, len(text), MAX_LEN)]
    await target_msg.edit_text(parts[0], parse_mode=parse_mode)
    
    chat_id = target_msg.chat_id
    for idx, part in enumerate(parts[1:], 1):
        is_last = (idx == len(parts) - 1)
        markup = reply_markup if is_last else None
        await target_msg.get_bot().send_message(chat_id=chat_id, text=part, parse_mode=parse_mode, reply_markup=markup)

async def process_buffered_message(user_id, context):
    await asyncio.sleep(1.5)
    
    if user_id not in user_message_buffers or not user_message_buffers[user_id]["texts"]:
        return

    full_text = "\n".join(user_message_buffers[user_id]["texts"])
    update_obj = user_message_buffers[user_id]["update"]
    
    del user_message_buffers[user_id]

    if user_id not in user_sessions:
        user_sessions[user_id] = []

    user_sessions[user_id].append({"role": "user", "content": full_text})
    save_sessions()
    
    await generate_response(user_id, update_obj, is_callback=False)

async def generate_response(user_id, update_or_query, is_callback=False):
    if user_id not in user_sessions or not user_sessions[user_id]:
        msg = "История пуста."
        if is_callback:
            await update_or_query.message.reply_text(msg)
        else:
            await update_or_query.reply_text(msg)
        return

    headers = {
        "Authorization": f"Bearer {MODELHUB_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = [{"role": "system", "content": KARL_SYSTEM_PROMPT}] + user_sessions[user_id]
    payload = {"model": MODEL_NAME, "messages": messages, "temperature": 0.4}

    if is_callback:
        status_msg = await update_or_query.message.reply_text("⏳ Пересчитываю...")
    else:
        status_msg = await update_or_query.message.reply_text("⏳ Анализирую...")

    try:
        async def fetch():
            async with httpx.AsyncClient(timeout=120.0) as client:
                return await client.post(API_URL, json=payload, headers=headers)

        response = None
        for attempt in range(3):
            try:
                response = await fetch()
                break
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 2:
                    raise
                await asyncio.sleep(2)

        data = response.json()
        if response.status_code == 200:
            reply = data["choices"][0]["message"]["content"]
            
            if is_callback and user_sessions[user_id] and user_sessions[user_id][-1]["role"] == "assistant":
                user_sessions[user_id][-1]["content"] = reply
            else:
                user_sessions[user_id].append({"role": "assistant", "content": reply})

            save_sessions()

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔄 Перегенерировать", callback_data="regen"),
                    InlineKeyboardButton("⬅️ Откатить шаг", callback_data="undo")
                ]
            ])
            
            await send_long_message(status_msg, reply, reply_markup=keyboard, parse_mode="Markdown")
        else:
            err = data.get("error", {}).get("message", "Ошибка API")
            await status_msg.edit_text(f"API Error ({response.status_code}): {err}")
    except Exception as e:
        await status_msg.edit_text(f"Ошибка сети/таймаут: {e}")

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "📁 Экспорт сеанса":
        await export_chat(update, context)
        return
    elif text == "Литература":
        lit_text = (
            "📚 **Рекомендуемая литература по работе с травмой и КПТ:**\n\n"
            "1. **Бессел ван дер Колк — «Тело помнит всё»** — как травма имплантируется в соматическую систему и как запустить исцеление через тело.\n"
            "2. **Пит Уокер — «Комплексное ПТСР: Руководство по выздоровлению»** — фундаментальная работа с внутренним критиком, эмоциональными флешбэками и токсичным стыдом.\n"
            "3. **Ричард Шварц — «Нет плохих частей»** — мягкое введение в IFS — работу с субличностями и защитными частями психики.\n"
            "4. **Деб Дана — «Поливагальная теория в терапии»** — понятный путеводитель по нервной системе, безопасности, активации и замиранию.\n\n"
            "Какая из этих тем отзывается вам больше всего? Напишите, и мы разберем её точечно."
        )
        if user_id not in user_sessions:
            user_sessions[user_id] = []
        user_sessions[user_id].append({"role": "user", "content": "Литература"})
        user_sessions[user_id].append({"role": "assistant", "content": lit_text})
        save_sessions()
        await update.message.reply_text(lit_text, parse_mode="Markdown", reply_markup=MAIN_MENU)
        return
    elif "SOS" in text:
        await update.message.reply_text("Протокол флэшбека:\n1. Заземлитесь (стопы на пол).\n2. Найдите 3 синих предмета.\n3. Удлинённый выдох.", reply_markup=MAIN_MENU)
        return
    elif "Сбросить" in text:
        user_message_buffers.pop(user_id, None)
        user_sessions[user_id] = []
        save_sessions()
        await update.message.reply_text("История диалога очищена.", reply_markup=MAIN_MENU)
        return

    if user_id not in user_message_buffers:
        user_message_buffers[user_id] = {"texts": [], "update": update, "task": None}
    
    user_message_buffers[user_id]["texts"].append(text)
    user_message_buffers[user_id]["update"] = update

    if user_message_buffers[user_id]["task"]:
        user_message_buffers[user_id]["task"].cancel()

    task = asyncio.create_task(process_buffered_message(user_id, context))
    user_message_buffers[user_id]["task"] = task

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "regen":
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await generate_response(user_id, query, is_callback=True)
        
    elif query.data == "undo":
        try:
            await query.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
            
        if user_id in user_sessions and len(user_sessions[user_id]) >= 2:
            user_sessions[user_id].pop()
            user_sessions[user_id].pop()
            save_sessions()
            await query.message.reply_text("↩️ Последний обмен сообщениями отменен. Можете написать мысль заново.", reply_markup=MAIN_MENU)
        else:
            await query.message.reply_text("Нечего откатывать — история пуста или слишком короткая.", reply_markup=MAIN_MENU)

def main():
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).read_timeout(60).connect_timeout(60).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("export", export_chat))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    print("Доктор Карл запущен в стабильном режиме!")
    app.run_polling(drop_pending_updates=True)

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"I am alive!")

def run_web_server():
    server = HTTPServer(('0.0.0.0', 10000), SimpleHandler)
    server.serve_forever()

if __name__ == '__main__':
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    main()
