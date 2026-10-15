import asyncio, logging, os
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from google import genai
from google.genai import types

logging.basicConfig(level=logging.INFO)
log=logging.getLogger("homework-bot")
TG=os.getenv("TELEGRAM_BOT_TOKEN","").strip()
AI=os.getenv("GEMINI_API_KEY","").strip()
MODEL=os.getenv("GEMINI_MODEL","gemini-2.5-flash")
MAX_BYTES=10*1024*1024
INSTRUCTIONS="""Ты русскоязычный помощник по домашним заданиям школьников в России. Решай задание на фото, если оно читаемо. Если фото размыто или условие обрезано, попроси переснять, не выдумывай текст. Объясняй по шагам и перепроверяй вычисления. Оформи для тетради: математика/физика — Дано (если уместно), Решение, Ответ; языки — номер упражнения, выполненный текст и объяснение правила; другие предметы — ясные пункты, формулы и обоснования. Пиши на русском, без лишней воды. Укажи, если в условии есть неоднозначность."""
def keys():
 return InlineKeyboardMarkup([[InlineKeyboardButton("Объяснить подробнее",callback_data="detail")],[InlineKeyboardButton("Только краткий ответ",callback_data="short")],[InlineKeyboardButton("Оформить в тетради",callback_data="notebook")]])
async def start(u,c):
 await u.effective_message.reply_text("Привет! 📚 Пришли чёткое фото задания. В подписи можешь указать предмет и класс, например «Алгебра, 7 класс». Я разберу условие, объясню решение и оформлю ответ для тетради. Перепроверяй результат перед сдачей.")
async def help_cmd(u,c):
 await u.effective_message.reply_text("Отправь фото задания целиком без бликов. Можно указать предмет и класс в подписи. Если текст не читается, пришли снимок крупнее.")
async def solve(data,hint="",mode="normal"):
 client=genai.Client(api_key=AI)
 extra={"detail":"Объясни каждый шаг максимально подробно простыми словами.","short":"Дай краткий ответ и необходимые ключевые вычисления.","notebook":"Сделай аккуратное оформление, готовое для переписывания в тетрадь."}.get(mode,"")
 res=await asyncio.to_thread(client.models.generate_content,model=MODEL,contents=[types.Part.from_bytes(data=data,mime_type="image/jpeg"),INSTRUCTIONS+"\n"+extra+"\nПодпись пользователя: "+(hint or "нет")],config=types.GenerateContentConfig(temperature=0.2))
 return (res.text or "").strip() or "Не удалось прочитать ответ модели."
async def send_long(msg,text,markup=None):
 chunks=[text[i:i+3900] for i in range(0,len(text),3900)] or ["Нет ответа."]
 for i,chunk in enumerate(chunks): await msg.reply_text(chunk,reply_markup=markup if i==len(chunks)-1 else None)
async def photo(u,c):
 m=u.effective_message
 if not AI: await m.reply_text("ИИ не подключён. В секретах хостинга добавь GEMINI_API_KEY."); return
 status=await m.reply_text("📷 Читаю фото и решаю задание…")
 try:
  p=m.photo[-1]
  if p.file_size and p.file_size>MAX_BYTES: await status.edit_text("Фото больше 10 МБ. Отправь уменьшенный снимок."); return
  f=await c.bot.get_file(p.file_id); b=BytesIO(); await f.download_to_memory(out=b); data=b.getvalue()
  if len(data)>MAX_BYTES: await status.edit_text("Фото больше 10 МБ. Отправь уменьшенный снимок."); return
  hint=m.caption or ""; ans=await solve(data,hint)
  c.user_data["photo"]=data; c.user_data["hint"]=hint
  await status.delete(); await send_long(m,ans,keys())
 except Exception:
  log.exception("photo processing failed")
  await status.edit_text("Не удалось обработать фото. Проверь ключ ИИ и его квоту, затем попробуй ещё раз.")
async def mode(u,c):
 q=u.callback_query; await q.answer()
 data=c.user_data.get("photo")
 if not data: await q.message.reply_text("Сначала отправь фото задания."); return
 try:
  s=await q.message.reply_text("Готовлю ответ…")
  a=await solve(data,c.user_data.get("hint",""),q.data); await s.delete(); await send_long(q.message,a,keys())
 except Exception:
  log.exception("mode failed"); await q.message.reply_text("Не получилось изменить ответ. Проверь доступность ИИ.")
async def main_error(u,c): log.error("Telegram error: %s",c.error)
def main():
 if not TG: raise SystemExit("Set TELEGRAM_BOT_TOKEN secret")
 app=Application.builder().token(TG).build()
 app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("help",help_cmd))
 app.add_handler(MessageHandler(filters.PHOTO,photo))
 app.add_handler(CallbackQueryHandler(mode,pattern="^(detail|short|notebook)$"))
 app.add_error_handler(main_error)
 log.info("Starting polling; model=%s",MODEL); app.run_polling()
if __name__=="__main__": main()
