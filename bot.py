import asyncio
import json
import os
import io
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import httpx
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MODELHUB_API_KEY = os.getenv("MODELHUB_API_KEY")
API_URL = os.getenv("API_URL", "https://modelhub.my/v1")

KARL_SYSTEM_PROMPT = """Вы - доктор Карл Вандерлик, медицинский доктор и доктор философии, клинический психотерапевт, специалист по Комплексному ПТСР и травме. Ваш тон строгий, глубокий, аналитический, но бережный. Всегда обращайтесь на вы. Используйте жирный шрифт для ключевых понятий и мягкие эмодзи. Избегайте решеток для заголовков. Отвечайте глубоко, но понятно, задавая не больше 1-2 мягких вопросов в конце."""

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

    log_lines = ["# Сеанс психотерапевтического анализа\n"]
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

    # Проверяем наличие API ключа
    if not MODELHUB_API_KEY:
        error_msg = "❌ API ключ не настроен. Пожалуйста, добавьте MODELHUB_API_KEY в переменные окружения."
        if is_callback:
            await update_or_query.message.reply_text(error_msg)
        else:
            await update_or_query.reply_text(error_msg)
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
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(API_URL, json=payload, headers=headers)
                return response

        response = None
        for attempt in range(3):
            try:
                response = await fetch()
                break
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                print(f"Попытка {attempt+1} не удалась: {e}")
                if attempt == 2:
                    raise
                await asyncio.sleep(2)

        # Проверяем статус ответа
        if response.status_code != 200:
            error_text = f"❌ API вернул ошибку {response.status_code}\n"
            try:
                data = response.json()
                if "error" in data:
                    error_text += f"Сообщение: {data['error'].get('message', 'Неизвестная ошибка')}"
            except:
                error_text += f"Ответ: {response.text[:200]}"
            
            await status_msg.edit_text(error_text)
            return

        # Парсим JSON
        try:
            data = response.json()
        except json.JSONDecodeError as e:
            print(f"Ошибка парсинга JSON: {e}")
            print(f"Ответ API: {response.text[:500]}")
            await status_msg.edit_text(
                "❌ API вернул некорректный ответ. Проверьте настройки MODELHUB_API_KEY и API_URL.\n\n"
                f"Получено: {response.text[:200]}"
            )
            return

        reply = data.get("choices", [{}])[0].get("message", {}).get("content", "Нет ответа от модели")
        
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
        
    except httpx.TimeoutException:
        await status_msg.edit_text("⏰ Превышено время ожидания ответа от API. Попробуйте позже.")
    except httpx.NetworkError as e:
        await status_msg.edit_text(f"🌐 Ошибка сети: {str(e)[:100]}")
    except Exception as e:
        print(f"Неизвестная ошибка: {e}")
        await status_msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    if text == "📁 Экспорт сеанса":
        await export_chat(update, context)
        return
    elif text == "Литература":
        lit_text = "📚 Рекомендуемая литература:\n\n1. Бессел ван дер Колк - Тело помнит всё.\n2. Пит Уокер - Комплексное ПТСР.\n3. Ричард Шварц - Нет плохих частей.\n4. Деб Дана - Поливагальная теория."
        if user_id not in user_sessions:
            user_sessions[user_id] = []
        user_sessions[user_id].append({"role": "user", "content": "Литература"})
        user_sessions[user_id].append({"role": "assistant", "content": lit_text})
        save_sessions()
        await update.message.reply_text(lit_text, parse_mode="Markdown", reply_markup=MAIN_MENU)
        return
    elif "Теория" in text:
        theory_text = "🧠 *Комплексное ПТСР (КПТСР)*\n\nКПТСР развивается при длительной травме. Основные признаки:\n\n• Трудности с регуляцией эмоций\n• Негативное восприятие себя\n• Проблемы в отношениях\n• Соматические симптомы\n\n*Подходы к терапии:*\n• IFS (Внутренние семейные системы)\n• EMDR\n• Соматическое переживание\n• Психотерапия, ориентированная на травму"
        await update.message.reply_text(theory_text, parse_mode="Markdown", reply_markup=MAIN_MENU)
        return
    elif "Самопомощь" in text:
        ifs_text = "🧩 *IFS - Внутренние семейные системы*\n\nОсновные части:\n\n• *Изгнанники* - уязвимые части, несущие боль\n• *Менеджеры* - защитники, контролирующие\n• *Пожарные* - реагируют на триггеры\n\n*Практика:*\n1. Заметь часть, которая сейчас активна\n2. Спроси: \"Что ты чувствуешь?\"\n3. Спроси: \"Что тебе нужно?\"\n4. Поблагодари за защиту"
        await update.message.reply_text(ifs_text, parse_mode="Markdown", reply_markup=MAIN_MENU)
        return
    elif "SOS" in text:
        sos_text = "🛡️ *Протокол заземления:*\n\n1. Опора под стопами\n2. Найдите 3 синих предмета\n3. Сделайте удлиненный выдох\n4. Назовите 5 вещей вокруг\n\n*Дыхание:* 4-4-6 (вдох-задержка-выдох)"
        await update.message.reply_text(sos_text, reply_markup=MAIN_MENU, parse_mode="Markdown")
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
            await query.message.reply_text("↩️ Последний обмен отменен.", reply_markup=MAIN_MENU)
        else:
            await query.message.reply_text("Нечего откатывать.", reply_markup=MAIN_MENU)
async def test_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестирует подключение к ModelHub API"""
    if not MODELHUB_API_KEY:
        await update.message.reply_text("❌ MODELHUB_API_KEY не задан в переменных окружения!")
        return
    
    if not TELEGRAM_TOKEN:
        await update.message.reply_text("❌ TELEGRAM_TOKEN не задан!")
        return
    
    status_msg = await update.message.reply_text("🔍 Проверяю подключение к ModelHub...")
    
    try:
        headers = {
            "Authorization": f"Bearer {MODELHUB_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Простой тестовый запрос
        test_payload = {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": "Say just 'Hello, API works!'"}],
            "max_tokens": 20,
            "temperature": 0.1
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(API_URL, json=test_payload, headers=headers)
        
        if response.status_code == 200:
            try:
                data = response.json()
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "Нет ответа")
                await status_msg.edit_text(
                    f"✅ API работает!\n\n"
                    f"Модель: {MODEL_NAME}\n"
                    f"URL: {API_URL}\n"
                    f"Ответ: {reply}"
                )
            except Exception as e:
                await status_msg.edit_text(f"❌ Ошибка парсинга JSON: {str(e)}\n\nОтвет API: {response.text[:200]}")
        else:
            await status_msg.edit_text(
                f"❌ Ошибка API ({response.status_code})\n\n"
                f"URL: {API_URL}\n"
                f"Модель: {MODEL_NAME}\n"
                f"Ответ: {response.text[:300]}"
            )
    except httpx.TimeoutException:
        await status_msg.edit_text(f"⏰ Таймаут подключения к {API_URL}")
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)[:300]}")
def main():
    # Останавливаем все предыдущие экземпляры
    time.sleep(3)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("export", export_chat))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("Доктор Карл запущен в стабильном режиме!")
    app.run_polling(drop_pending_updates=True, allowed_updates=["message", "callback_query"])

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"I am alive!")
    
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_web_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHandler)
    server.serve_forever()

if __name__ == '__main__':
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    main()
app.add_handler(CommandHandler("test", test_api))
def main():
    # Останавливаем все предыдущие экземпляры
    time.sleep(3)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("export", export_chat))
    app.add_handler(CommandHandler("test", test_api))  # <-- ДОБАВЬ ЭТУ СТРОКУ
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("Доктор Карл запущен в стабильном режиме!")
    app.run_polling(drop_pending_updates=True, allowed_updates=["message", "callback_query"])
