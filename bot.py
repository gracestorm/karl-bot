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
API_URL = os.getenv("API_URL", "https://modelhub.my/v1/chat/completions")

# ==================== СИСТЕМНЫЙ ПРОМПТ (на английском, но ответы на русском) ====================
KARL_SYSTEM_PROMPT = """You are Dr. Karl Wunderlich, MD, PhD — Clinical Psychotherapist, Professor of Traumatology, European specialist in Complex PTSD and Dissociative Disorders. You have 30+ years of clinical practice, trained in Vienna, Zurich, and Boston. You are widely regarded as one of the finest trauma therapists in Europe, with a waiting list of 18 months and a session fee that reflects your expertise. Your patients include diplomats, academics, and individuals who have exhausted all other treatment options.

YOUR CLINICAL EXPERTISE:
- Complex PTSD (CPTSD) and developmental trauma
- Dissociative disorders (DPDR, DID, dissociative subtypes of PTSD)
- Trauma-focused therapies (PE, CPT, EMDR, NET, TF-CBT)
- Somatic approaches (Sensorimotor Psychotherapy, Somatic Experiencing, Polyvagal Theory)
- Internal Family Systems (IFS) — you are a Level 3 certified practitioner
- Dialectical Behavior Therapy (DBT) — skills training and trauma adaptation
- Attachment theory (Bowlby, Ainsworth, Fonagy)
- Neurobiology of trauma (Porges, van der Kolk, Siegel, Schore)
- Psychodynamic therapy (object relations, self-psychology)
- Existential and humanistic approaches (Yalom, Rogers)
- Cognitive Behavioral Therapy (CBT, CT-R, schema therapy)
- Gestalt therapy and embodied awareness
- Integrative and multimodal treatment planning

YOUR PHILOSOPHY:
You believe trauma is not a life sentence — it is a profound disruption that can be metabolized, integrated, and transformed. You work with the whole person: nervous system, psyche, relationships, meaning-making, and somatic experience. You are rigorous, deeply intellectual, yet warm and attuned. You never patronize. You respect the patient's intelligence and agency.

YOUR COMMUNICATION STYLE:
- Tone: Authoritative but compassionate. Profoundly knowledgeable yet accessible. You speak with the quiet confidence of someone who has seen it all and is not easily impressed or shaken.
- Address: Always formal "you" (respectful distance). No familiarity.
- Structure: Your responses are clinically structured but flow naturally. Use clear thematic sections with bold headers. Each section builds on the previous. Your answers are essays in miniature — dense with insight, not a single wasted word.
- Formatting: Markdown only. Use **bold** for headers and key concepts. Use *italics* for emphasis or clinical terms. Never use # headers. Never use emojis. Never use decorative symbols.
- Depth vs. Brevity: You are not verbose — every sentence carries clinical weight. You are not terse — you provide full context where needed. You write in complete, elegant paragraphs. Your language is precise, nuanced, and rich.
- Questions: At the end of each response, pose 1-2 gentle, clinically significant questions. These questions are not formalities — they are carefully chosen to deepen insight, challenge avoidance, or invite reflection. They are open-ended, non-leading, and patient-centered.
- Clinical vocabulary: Use appropriate terminology (e.g., "hypervigilance," "affect dysregulation," "dissociative compartmentalization," "somatic markers," "attachment rupture," "implicit memory," "polyvagal hierarchy"). Always, always explain terms in plain language immediately after using them — not as definitions, but woven into the sentence.

YOUR CLINICAL APPROACH WHEN WORKING WITH CPTSD AND DISSOCIATION:
1. Stabilization First — Always assess and prioritize nervous system regulation before any exposure or memory work.
2. Psychoeducation — You explain mechanisms thoroughly. Your patients understand their own neurobiology.
3. Somatic Awareness — You attend to the body as the primary locus of trauma.
4. Parts Work — You integrate IFS language and concepts naturally, helping patients relate to their internal system with curiosity, not judgment.
5. Affect Regulation — You teach and reinforce DBT skills where appropriate (distress tolerance, emotion regulation, interpersonal effectiveness, mindfulness).
6. Attachment Repair — You explore relational patterns with warmth and non-judgmental curiosity.
7. Narrative Integration — You help patients construct a coherent trauma narrative without forcing recall.
8. Polyvagal Grounding — You anchor work in the autonomic nervous system; you know when a patient is in dorsal vagal shutdown or sympathetic activation.
9. Dissociation Sensitivity — You recognize dissociation as adaptive defense, not pathology. You pace accordingly. You never push.
10. Cultural and Contextual Sensitivity — You attend to meaning, identity, and life context in every session.

YOUR RESPONSE PATTERN:
Start with a brief acknowledgment of what the patient has shared.
Provide psychoeducation or clinical analysis, structured in 2-4 thematic sections.
Weave in theory, neuroscience, and practical wisdom.
Conclude with 1-2 reflective questions that invite exploration.

WHAT YOU ABSOLUTELY DO NOT DO:
- Use emojis, smileys, or decorative text — ever.
- Use informal language (no "hey," "okay," "gotcha," "cool," "awesome").
- Offer platitudes or toxic positivity (no "everything happens for a reason," "look on the bright side," "just stay positive").
- Give direct advice or tell the patient what to do. You guide, you educate, you invite — you do not command.
- Interpret prematurely. You build understanding together.
- Overwhelm with jargon without translation.
- Forget that you are speaking to a human being in distress — beneath all the expertise, you are deeply present.

CRITICAL REMINDER FOR YOURSELF:
You are not here to impress. You are here to help. The patient is not your student, your client, or your case study. They are a person who has suffered, who has survived, who is seeking understanding and relief. Your language, your presence, your structure — all of it serves that one purpose. You are a guide through the underworld, not a showman.

When you reference a book, author, or technique, you always briefly explain its relevance to the current topic and offer a recommendation for further reading if appropriate. You have access to a vast clinical library and you use it judiciously.

CRITICAL INSTRUCTION: You must always respond in Russian language. All your answers, explanations, and questions must be in Russian, regardless of the language of the user's message. Use correct, rich, clinical Russian. Never switch to English in your responses."""

# ===================== БАЗА ЗНАНИЙ =====================
KNOWLEDGE_BASE = {
    "books": {
        "van der Kolk (2014)": {
            "title": "The Body Keeps the Score",
            "author": "Bessel van der Kolk",
            "year": 2014,
            "summary": "A seminal work on how trauma is stored in the body and the brain. Essential for understanding the neurobiology of trauma and the role of somatic therapies.",
            "recommendation": "If you want to understand why your body reacts the way it does, this is the foundational text."
        },
        "Walker (2013)": {
            "title": "Complex PTSD: From Surviving to Thriving",
            "author": "Pete Walker",
            "year": 2013,
            "summary": "A practical guide to managing CPTSD, focusing on emotional flashbacks, inner critic work, and the four Fs (fight, flight, freeze, fawn).",
            "recommendation": "This is the best self-help resource for understanding the daily experience of CPTSD and practical coping strategies."
        },
        "Schwartz (2021)": {
            "title": "No Bad Parts",
            "author": "Richard Schwartz",
            "year": 2021,
            "summary": "Introduction to Internal Family Systems (IFS) — a non-pathologizing model of the mind as a system of protective and wounded parts.",
            "recommendation": "If you're curious about the IFS approach, this is the most accessible entry point."
        },
        "Porges (2011)": {
            "title": "The Polyvagal Theory",
            "author": "Stephen Porges",
            "year": 2011,
            "summary": "Explains the role of the vagus nerve in regulating safety, connection, and threat responses. The foundation of many trauma-informed interventions.",
            "recommendation": "For those interested in the neuroscience of safety and connection, this is a must-read."
        },
        "Dana (2020)": {
            "title": "Polyvagal Exercises for Safety and Connection",
            "author": "Deb Dana",
            "year": 2020,
            "summary": "Practical exercises to regulate the nervous system based on Polyvagal Theory.",
            "recommendation": "A workbook that offers concrete practices to shift out of survival states."
        },
        "Linehan (2014)": {
            "title": "DBT Skills Training Manual",
            "author": "Marsha Linehan",
            "year": 2014,
            "summary": "The core manual for Dialectical Behavior Therapy, focusing on mindfulness, distress tolerance, emotion regulation, and interpersonal effectiveness.",
            "recommendation": "This is the gold standard for skills training, particularly useful if emotion dysregulation is a central issue."
        },
        "Ogden (2006)": {
            "title": "Trauma and the Body",
            "author": "Pat Ogden",
            "year": 2006,
            "summary": "A sensorimotor approach to trauma therapy, emphasizing the body's role in processing traumatic memories.",
            "recommendation": "Excellent for those who want to understand the somatic dimension of trauma treatment."
        },
        "Briere & Scott (2015)": {
            "title": "Principles of Trauma Therapy",
            "author": "John Briere, Catherine Scott",
            "year": 2015,
            "summary": "A comprehensive overview of contemporary trauma therapy, integrating multiple modalities.",
            "recommendation": "A more clinical textbook, useful if you want a broad overview of the field."
        }
    },
    "authors": {
        "Bessel van der Kolk": "Leading expert on trauma, founder of the Trauma Center in Boston. Known for integrating neuroscience, attachment, and body-based therapies.",
        "Pete Walker": "Psychotherapist and author, specializing in CPTSD and emotional flashbacks. His work is particularly focused on the inner critic and shame.",
        "Richard Schwartz": "Developer of Internal Family Systems (IFS), a model that views the mind as a system of subpersonalities or 'parts'.",
        "Stephen Porges": "Developed the Polyvagal Theory, which explains how the autonomic nervous system mediates safety, connection, and defense.",
        "Deb Dana": "Clinician and author, known for translating Polyvagal Theory into practical clinical interventions and self-help exercises.",
        "Marsha Linehan": "Creator of Dialectical Behavior Therapy (DBT), originally designed for borderline personality disorder but widely used for emotion dysregulation in trauma.",
        "Pat Ogden": "Founder of Sensorimotor Psychotherapy, focusing on the body's role in trauma resolution.",
        "John Bowlby": "Founder of Attachment Theory, which explains how early relationships shape lifelong patterns of relating."
    },
    "techniques": {
        "IFS": "Internal Family Systems — a model that identifies and works with protective and wounded 'parts' of the psyche. It is non-pathologizing and assumes all parts have positive intentions.",
        "DBT": "Dialectical Behavior Therapy — a skills-based approach that teaches mindfulness, emotion regulation, distress tolerance, and interpersonal effectiveness.",
        "Polyvagal": "Polyvagal Theory — describes the hierarchy of autonomic states (ventral vagal, sympathetic, dorsal vagal) and how to shift between them.",
        "EMDR": "Eye Movement Desensitization and Reprocessing — a therapy that uses bilateral stimulation to process traumatic memories.",
        "Somatic Experiencing": "A body-oriented approach to trauma resolution developed by Peter Levine, focusing on releasing trapped survival energy.",
        "Sensorimotor Psychotherapy": "Integrates body awareness with cognitive and emotional processing to address trauma.",
        "Cognitive Processing Therapy (CPT)": "A cognitive-behavioral approach that focuses on changing maladaptive beliefs related to trauma.",
        "Prolonged Exposure (PE)": "A behavioral therapy that involves gradual exposure to trauma-related memories and situations.",
        "Mindfulness-Based Stress Reduction (MBSR)": "A program that uses mindfulness meditation to reduce stress and improve emotional regulation."
    },
    "online_resources": {
        "National Center for PTSD": "https://www.ptsd.va.gov/ — US Department of Veterans Affairs resource with extensive information on PTSD and CPTSD.",
        "International Society for Traumatic Stress Studies": "https://istss.org/ — Professional organization with resources for clinicians and patients.",
        "Pete Walker's Website": "https://www.pete-walker.com/ — Articles and resources on CPTSD, emotional flashbacks, and recovery.",
        "Polyvagal Institute": "https://www.polyvagalinstitute.org/ — Educational resources on Polyvagal Theory.",
        "IFS Institute": "https://ifs-institute.com/ — Official site for Internal Family Systems, with directories and resources."
    }
}

# ===================== ОБРАБОТЧИКИ ЗНАНИЙ =====================
def get_book_recommendation():
    books = KNOWLEDGE_BASE["books"]
    lines = ["*Рекомендуемая литература по травме и её лечению:*\n"]
    for key, book in books.items():
        lines.append(f"**{book['title']}** — {book['author']} ({book['year']})")
        lines.append(f"_{book['summary']}_")
        lines.append(f"*Рекомендация:* {book['recommendation']}\n")
    return "\n".join(lines)

def get_author_info():
    authors = KNOWLEDGE_BASE["authors"]
    lines = ["*Ключевые авторы и их вклад:*\n"]
    for name, desc in authors.items():
        lines.append(f"**{name}** — {desc}")
    return "\n".join(lines)

def get_techniques_info():
    techniques = KNOWLEDGE_BASE["techniques"]
    lines = ["*Основные терапевтические подходы при травме:*\n"]
    for name, desc in techniques.items():
        lines.append(f"**{name}** — {desc}")
    return "\n".join(lines)

def get_online_resources():
    resources = KNOWLEDGE_BASE["online_resources"]
    lines = ["*Полезные онлайн-ресурсы:*\n"]
    for name, url in resources.items():
        lines.append(f"**{name}** — {url}")
    return "\n".join(lines)

def get_topic_info(topic):
    topic_lower = topic.lower()
    results = []
    for key, book in KNOWLEDGE_BASE["books"].items():
        if (topic_lower in key.lower() or 
            topic_lower in book["title"].lower() or 
            topic_lower in book["author"].lower() or
            topic_lower in book["summary"].lower()):
            results.append(f"**{book['title']}** — {book['author']} ({book['year']})")
            results.append(f"_{book['summary']}_")
            results.append(f"*Рекомендация:* {book['recommendation']}\n")
    for name, desc in KNOWLEDGE_BASE["techniques"].items():
        if topic_lower in name.lower() or topic_lower in desc.lower():
            results.append(f"**{name}** — {desc}")
    for name, desc in KNOWLEDGE_BASE["authors"].items():
        if topic_lower in name.lower() or topic_lower in desc.lower():
            results.append(f"**{name}** — {desc}")
    if not results:
        return f"По вашему запросу '{topic}' ничего не найдено. Попробуйте другую тему или используйте кнопки 'Книги', 'Авторы', 'Техники' или 'Ресурсы'."
    return "\n".join(results)

# ===================== ОСНОВНОЙ КОД =====================

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
        [KeyboardButton("Книги по травме"), KeyboardButton("Авторы и теории")],
        [KeyboardButton("Техники и подходы"), KeyboardButton("Онлайн-ресурсы")],
        [KeyboardButton("Поиск по теме"), KeyboardButton("SOS / Флэшбек")]
    ],
    resize_keyboard=True
)

# ===================== ХЕНДЛЕРЫ =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_sessions[user_id] = []
    save_sessions()
    text = (
        "Guten Tag. Я — доктор Карл Вандерлик.\n\n"
        "Я специализируюсь на комплексной травме и диссоциативных расстройствах. "
        "Сегодня я здесь, чтобы помочь вам понять механизмы вашего состояния и найти пути к облегчению.\n\n"
        "Вы можете задавать любые вопросы или использовать кнопки ниже для доступа к рекомендуемой литературе, техникам и ресурсам."
    )
    await update.message.reply_text(text, reply_markup=MAIN_MENU)

async def test_api(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not MODELHUB_API_KEY:
        await update.message.reply_text("❌ MODELHUB_API_KEY не задан!")
        return
    
    status_msg = await update.message.reply_text("🔍 Проверяю подключение к ModelHub...")
    
    try:
        headers = {
            "Authorization": f"Bearer {MODELHUB_API_KEY}",
            "Content-Type": "application/json"
        }
        test_payload = {
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": "Say just 'Hello!'"}],
            "max_tokens": 20,
            "temperature": 0.1
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(API_URL, json=test_payload, headers=headers)
        if response.status_code == 200:
            try:
                data = response.json()
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "Нет ответа")
                await status_msg.edit_text(f"✅ API работает!\n\nURL: {API_URL}\nМодель: {MODEL_NAME}\nОтвет: {reply}")
            except Exception as e:
                await status_msg.edit_text(f"❌ Ошибка: {str(e)}\n\nОтвет: {response.text[:200]}")
        else:
            await status_msg.edit_text(f"❌ Ошибка {response.status_code}\nURL: {API_URL}\nОтвет: {response.text[:300]}")
    except Exception as e:
        await status_msg.edit_text(f"❌ Ошибка: {str(e)[:300]}")

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
        caption="📁 Полный протокол вашей сессии.",
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

    if not MODELHUB_API_KEY:
        error_msg = "❌ API ключ не настроен."
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

        if response.status_code != 200:
            error_text = f"❌ Ошибка API ({response.status_code})\nURL: {API_URL}\n"
            try:
                data = response.json()
                if "error" in data:
                    error_text += f"Сообщение: {data['error'].get('message', '')}"
            except:
                error_text += f"Ответ: {response.text[:200]}"
            
            await status_msg.edit_text(error_text)
            return

        try:
            data = response.json()
        except json.JSONDecodeError as e:
            print(f"Ошибка парсинга JSON: {e}")
            print(f"Ответ API: {response.text[:500]}")
            await status_msg.edit_text(f"❌ API вернул некорректный ответ.\n\nПолучено: {response.text[:200]}")
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
        await status_msg.edit_text("⏰ Превышено время ожидания.")
    except httpx.NetworkError as e:
        await status_msg.edit_text(f"🌐 Ошибка сети: {str(e)[:100]}")
    except Exception as e:
        print(f"Неизвестная ошибка: {e}")
        await status_msg.edit_text(f"❌ Ошибка: {str(e)[:200]}")

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.effective_user.id

    # Команды из меню
    if text == "📁 Экспорт сеанса":
        await export_chat(update, context)
        return
    elif text == "Книги по травме":
        await update.message.reply_text(get_book_recommendation(), parse_mode="Markdown", reply_markup=MAIN_MENU)
        return
    elif text == "Авторы и теории":
        await update.message.reply_text(get_author_info(), parse_mode="Markdown", reply_markup=MAIN_MENU)
        return
    elif text == "Техники и подходы":
        await update.message.reply_text(get_techniques_info(), parse_mode="Markdown", reply_markup=MAIN_MENU)
        return
    elif text == "Онлайн-ресурсы":
        await update.message.reply_text(get_online_resources(), parse_mode="Markdown", reply_markup=MAIN_MENU)
        return
    elif text == "Поиск по теме":
        await update.message.reply_text(
            "Введите ключевое слово для поиска в моей библиотеке (например, 'IFS', 'flashback', 'Porges').",
            reply_markup=MAIN_MENU
        )
        context.user_data["search_mode"] = True
        return
    elif "SOS" in text:
        sos_text = (
            "**Протокол экстренного заземления при флэшбеке или панике:**\n\n"
            "1. Остановитесь. Почувствуйте опору под ногами.\n"
            "2. Назовите 5 предметов, которые вы видите.\n"
            "3. Сделайте глубокий вдох и медленный выдох (считайте до 4 на вдохе, до 6 на выдохе).\n"
            "4. Повторите: 'Сейчас я в безопасности. Это прошлое, не настоящее.'\n"
            "5. Если возможно, коснитесь чего-то прохладного или тёплого, чтобы вернуться в тело.\n\n"
            "Помните: флэшбек не опасен, он просто неприятен. Он пройдёт."
        )
        await update.message.reply_text(sos_text, parse_mode="Markdown", reply_markup=MAIN_MENU)
        return
    elif "Сбросить" in text:
        user_message_buffers.pop(user_id, None)
        user_sessions[user_id] = []
        save_sessions()
        await update.message.reply_text("История диалога очищена.", reply_markup=MAIN_MENU)
        return

    # Поиск по теме
    if context.user_data.get("search_mode"):
        result = get_topic_info(text)
        await update.message.reply_text(result, parse_mode="Markdown", reply_markup=MAIN_MENU)
        context.user_data["search_mode"] = False
        return

    # Обычное сообщение
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

def main():
    time.sleep(3)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("export", export_chat))
    app.add_handler(CommandHandler("test", test_api))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("Доктор Карл запущен с полной базой знаний!")
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
