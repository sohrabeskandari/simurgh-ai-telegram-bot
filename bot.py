import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# -----------------------
# تنظیمات لاگ برای اشکال‌زدایی
# -----------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# -----------------------
# توکن بات
# -----------------------
TELEGRAM_TOKEN = "توکن_بات_شما"
SEARCH_API_URL = "https://simorghai.ir/api/search"  # آدرس جستجو در سایت

# -----------------------
# شروع بات
# -----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 آمار بازدید", callback_data="stats")],
        [InlineKeyboardButton("🔍 جستجوی هوش مصنوعی", callback_data="ai_search")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("سلام! یکی از گزینه‌ها رو انتخاب کن:", reply_markup=reply_markup)

# -----------------------
# هندلر دکمه‌ها
# -----------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "stats":
        try:
            stats = get_site_stats()
            await query.edit_message_text(f"📊 آمار بازدید:\n\n{stats}")
        except Exception as e:
            logger.error(f"خطا در دریافت آمار بازدید: {e}")
            await query.edit_message_text("❌ خطا در دریافت آمار بازدید. لطفاً بعداً تلاش کنید.")

    elif query.data == "ai_search":
        await query.edit_message_text("🔍 لطفاً عبارت مورد نظر را برای جستجو ارسال کنید:")
        context.user_data["awaiting_search"] = True

# -----------------------
# دریافت متن جستجو
# -----------------------
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting_search"):
        query_text = update.message.text
        results = search_ai(query_text)
        context.user_data["awaiting_search"] = False

        if results:
            formatted_results = "\n\n".join([f"🔹 {r}" for r in results])
            await update.message.reply_text(f"نتایج جستجو:\n\n{formatted_results}")
        else:
            await update.message.reply_text("❌ نتیجه‌ای یافت نشد.")

# -----------------------
# تابع نمونه دریافت آمار
# -----------------------
def get_site_stats():
    # اینجا باید API آمار سایت خودتان را فراخوانی کنید
    # مثال:
    response = requests.get("https://simorghai.ir/api/stats", timeout=10)
    response.raise_for_status()
    data = response.json()
    return f"بازدید امروز: {data.get('today', 0)}\nبازدید کل: {data.get('total', 0)}"

# -----------------------
# تابع جستجوی AI
# -----------------------
def search_ai(query):
    try:
        response = requests.get(SEARCH_API_URL, params={"q": query}, timeout=10)
        response.raise_for_status()
        data = response.json()

        # فرض: API شما لیستی از نتایج در data["results"] دارد
        return [item["title"] for item in data.get("results", [])]
    except Exception as e:
        logger.error(f"خطا در جستجو: {e}")
        return []

# -----------------------
# اجرای بات
# -----------------------
def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    application.run_polling()

if __name__ == "__main__":
    main()
