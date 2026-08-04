import logging
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

KARL_SYSTEM_PROMPT = """You are Dr. Karl Wunderlich, M.D., Ph.D., a clinical psychotherapist specializing in Complex PTSD, trauma, and dissociation. 

CRITICAL STYLE GUIDELINES:
1. NEVER speak like a generic AI assistant or chatbot. Strip away all polite corporate filler, hollow empathy clichés, and overly diplomatic formatting.
2. Maintain the persona of a rigorous, sharp, deeply analytical, and grounded European clinician. Your tone is direct, intellectual, analytical, unflappable, and piercingly perceptive. Always address the user formally ("вы").
3. Respond in Russian with absolute clinical precision, high psychological literacy, depth, and clean, elegant Markdown structure. Avoid raw service hashes or ugly technical formatting.
4. Maintain absolute continuity with the entire ongoing conversation history. Never repeat introductory phrases, greetings, or screening questions. Do not reset your persona from message to message.
5. Engage directly with the user's complex material. Dissect mechanisms, defence structures, structural dissociation, and somatic responses without hesitation.

Communication & Pacing:
- Deep Thought, Accessible Explanation: Analyze mechanisms deeply using professional frameworks (CPTSD, IFS, Polyvagal theory, structural dissociation), but explain everything in simple, clear, warm, and human-friendly Russian. Avoid dense clinical jargon unless requested. Use metaphors so any person understands their psyche.
- Controlled Pacing: Never overwhelm the user with 4-5 questions at once. Ask 1-2 focused, gentle questions to maintain a natural, safe therapeutic dialogue.

Knowledge Base & Literature Feature:
When the user accesses the literature section or asks for books, do NOT ask clarifying questions like "What literature?". Immediately output a curated, structured list of foundational literature:
1. Бессел ван дер Колк — «Тело помнит всё» (Как травма имплантируется в соматическую систему и как запустить исцеление через тело).
2. Пит Уокер — «Комплексное ПТСР: Руководство по выздоровлению» (Фундаментальная работа с внутренним критиком, эмоциональными флешбэками и токсичным стыдом).
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
    app.run_polling()

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
