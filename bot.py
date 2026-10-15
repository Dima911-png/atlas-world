
import asyncio
import base64
import logging
import os
from io import BytesIO

from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("homework-bot")

TG = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
AI = os.getenv("GROQ_API_KEY", "").strip()
MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b").strip()
MAX_BYTES = 10 * 1024 * 1024

INSTRUCTIONS = """
Ты русскоязычный помощник по домашним заданиям школьников в России.

Решай задания с фотографии. Сначала внимательно прочитай условие.
Не выдумывай нечитаемые числа, слова и условия. Если фотография размыта
или задание обрезано, попроси прислать более чёткий снимок.
Проверяй вычисления и отвечай по-русски.

КРИТИЧЕСКИ ВАЖНО ДЛЯ TELEGRAM:
- Никогда не используй LaTeX: запрещены $, \\( \\), \\frac, \\sqrt,
  \\sin, \\cos, \\alpha и подобные команды. Telegram показывает их как сырой текст.
- Пиши формулы обычными символами Unicode и простым текстом:
  sin(α), cos(α), √(9/25) = 3/5, x², 1/2, а не LaTeX.
- Не используй Markdown-заголовки с # и не оборачивай формулы в $.
- Делай короткие абзацы и отдельные строки для вычислений.
- Не выводи необработанный код разметки. Ответ должен сразу хорошо выглядеть в обычном сообщении Telegram.

ОФОРМЛЕНИЕ В ТЕТРАДИ:
Для математической задачи используй формат:
№ задания (если номер виден)
Решение.
1) ...
2) ...
Вычисления — каждое на отдельной строке.
Ответ: ...

Добавляй «Дано», «Найти» и формулы, когда это уместно для физики и геометрии.
Не добавляй выдуманное условие, которого нет на фото.
Для русского и иностранных языков укажи номер упражнения, выполни задание и коротко поясни правило.
Для остальных предметов дай понятный, структурированный ответ, который удобно переписать в тетрадь.
"""


def keys():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "Объяснить подробнее", callback_data="detail"
        )],
        [InlineKeyboardButton(
            "Только краткий ответ", callback_data="short"
        )],
        [InlineKeyboardButton(
            "Оформить в тетради", callback_data="notebook"
        )],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Привет! 📚 Я помогу с домашними заданиями.\n\n"
        "Пришли фотографию задания целиком. "
        "В подписи можешь написать предмет и класс, например "
        "«Алгебра, 7 класс».\n\n"
        "Я объясню решение по шагам и оформлю ответ для тетради."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "Отправь чёткое фото задания без бликов. "
        "Можно указать предмет и класс в подписи. "
        "Если текст не читается, пришли снимок крупнее."
    )


async def solve(data: bytes, hint: str = "", mode: str = "normal"):
    extra = {
        "detail": "Объясни каждый шаг особенно подробно и простыми словами.",
        "short": "Дай краткий ответ и необходимые вычисления.",
        "notebook": (
            "Оформи строго для переписывания в школьную тетрадь: заголовок «Решение», "
            "нумерованные шаги, отдельная строка для каждого вычисления и строка «Ответ: ...». "
            "Используй только обычные символы, без LaTeX, знаков $ и команд вроде \\frac или \\sqrt."
        ),
    }.get(mode, "")

    encoded = base64.b64encode(data).decode("ascii")
    prompt = (
        INSTRUCTIONS
        + "\nДополнительная просьба: " + extra
        + "\nПредмет и класс от пользователя: " + (hint or "не указаны")
    )

    def request():
        client = Groq(api_key=AI)
        return client.chat.completions.create(
            model=MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/jpeg;base64," + encoded
                        },
                    },
                ],
            }],
            temperature=0.2,
            max_completion_tokens=4096,
        )

    result = await asyncio.to_thread(request)
    answer = result.choices[0].message.content
    return (answer or "").strip() or "Не удалось получить ответ модели."


async def send_long(message, text: str, markup=None):
    chunks = [
        text[i:i + 3900]
        for i in range(0, len(text), 3900)
    ] or ["Ответ пуст."]

    for i, chunk in enumerate(chunks):
        await message.reply_text(
            chunk,
            reply_markup=markup if i == len(chunks) - 1 else None,
        )


async def photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message

    if not AI:
        await message.reply_text(
            "ИИ не подключён. Проверь секрет GROQ_API_KEY в GitHub."
        )
        return

    status = await message.reply_text("📷 Читаю фотографию и решаю задание…")

    try:
        photo_file = message.photo[-1]

        if photo_file.file_size and photo_file.file_size > MAX_BYTES:
            await status.edit_text(
                "Фото больше 10 МБ. Отправь уменьшенный снимок."
            )
            return

        file = await context.bot.get_file(photo_file.file_id)
        buffer = BytesIO()
        await file.download_to_memory(out=buffer)
        data = buffer.getvalue()

        if len(data) > MAX_BYTES:
            await status.edit_text(
                "Фото больше 10 МБ. Отправь уменьшенный снимок."
            )
            return

        hint = message.caption or ""
        answer = await solve(data, hint)

        context.user_data["photo"] = data
        context.user_data["hint"] = hint

        await status.delete()
        await send_long(message, answer, keys())

    except Exception:
        log.exception("Photo processing failed")
        await status.edit_text(
            "Не удалось обработать фото. Проверь ключ Groq, "
            "доступность модели и лимиты API, затем попробуй ещё раз."
        )


async def mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = context.user_data.get("photo")
    if not data:
        await query.message.reply_text("Сначала отправь фото задания.")
        return

    try:
        status = await query.message.reply_text("Готовлю ответ…")
        answer = await solve(
            data,
            context.user_data.get("hint", ""),
            query.data,
        )
        await status.delete()
        await send_long(query.message, answer, keys())

    except Exception:
        log.exception("Mode change failed")
        await query.message.reply_text(
            "Не удалось подготовить ответ. Проверь доступность Groq "
            "и лимиты API."
        )


async def main_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Telegram error: %s", context.error)


def main():
    if not TG:
        raise SystemExit("Не найден секрет TELEGRAM_BOT_TOKEN")

    app = Application.builder().token(TG).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, photo))
    app.add_handler(
        CallbackQueryHandler(
            mode,
            pattern="^(detail|short|notebook)$",
        )
    )
    app.add_error_handler(main_error)

    log.info("Starting bot; model=%s", MODEL)
    app.run_polling()


if __name__ == "__main__":
    main()
