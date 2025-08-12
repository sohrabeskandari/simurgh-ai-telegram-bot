#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
import json
import aiohttp
import asyncio
from datetime import datetime
from typing import Dict, Tuple, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# -----------------------------
# تنظیمات لاگ
# -----------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger("simorgh_bot")

# -----------------------------
# خواندن متغیرهای محیطی
# -----------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # اختیاری
SEARCH_API_URL = os.getenv("SEARCH_API_URL")  # باید ست شود اگر می‌خواهید جستجوی سایت داشته باشید
SITE_STATS_URL = os.getenv("SITE_STATS_URL")  # اختیاری
CHANNEL_ID = os.getenv("CHANNEL_ID", "@simorghAI")

# مقدارهای پیش‌فرض/قابل تغییر
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "5"))
MAX_QUESTION_LENGTH = int(os.getenv("MAX_QUESTION_LENGTH", "500"))

if not TELEGRAM_TOKEN:
    logger.error("متغیر محیطی TELEGRAM_TOKEN تنظیم نشده. لطفاً آن را اضافه کنید.")
    raise SystemExit(1)


# -----------------------------
# کلاس مدیریت بات
# -----------------------------
class SimorghAIBot:
    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        search_api_url: Optional[str] = None,
        site_stats_url: Optional[str] = None,
        channel_id: str = "@simorghAI",
        daily_limit: int = 5,
        max_question_length: int = 500,
    ):
        self.gemini_api_key = gemini_api_key
        self.gemini_url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-1.5-flash-latest:generateContent"
        )
        self.search_api_url = search_api_url
        self.site_stats_url = site_stats_url
        self.channel_id = channel_id
        self.DAILY_LIMIT = daily_limit
        self.MAX_QUESTION_LENGTH = max_question_length

        # ذخیره‌ی مصرف کاربران (در production از دیتابیس استفاده کنید)
        self.user_usage: Dict[int, Dict] = {}

    async def is_user_member(self, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
        """چک می‌کند کاربر عضو کانال است یا خیر (برمی‌گرداند True/False)."""
        try:
            member = await context.bot.get_chat_member(self.channel_id, user_id)
            return member.status in ("member", "administrator", "creator")
        except Exception as e:
            logger.warning(f"خطا در بررسی عضویت کاربر {user_id}: {e}")
            # اگر نتوانستیم بررسی کنیم، به صورت محافظه‌کارانه False برگردانیم
            return False

    def check_user_limit(self, user_id: int) -> Tuple[bool, int]:
        """بررسی محدودیت روزانه کاربر. برمی‌گرداند (می‌تواند بپرسد؟, باقی‌مانده)."""
        today = datetime.utcnow().date()
        if user_id not in self.user_usage:
            self.user_usage[user_id] = {"date": today, "count": 0}
        user_data = self.user_usage[user_id]
        if user_data["date"] != today:
            user_data["date"] = today
            user_data["count"] = 0
        remaining = self.DAILY_LIMIT - user_data["count"]
        return user_data["count"] < self.DAILY_LIMIT, max(0, remaining)

    def increment_user_usage(self, user_id: int):
        if user_id not in self.user_usage:
            self.user_usage[user_id] = {"date": datetime.utcnow().date(), "count": 0}
        self.user_usage[user_id]["count"] += 1

    async def ask_gemini(self, question: str, user_name: str = "کاربر") -> str:
        """ارسال سوال به Gemini (اگر کلید وجود داشته باشد)."""
        if not self.gemini_api_key:
            return "⚠️ پاسخ‌دهی هوش‌مصنوعی (Gemini) پیکربندی نشده است."

        prompt = (
            f"شما دستیار هوشمند کانال خبری هوش مصنوعی سیمرغ هستید.\n\n"
            f"به سوال زیر پاسخ دهید (فارسی، حدود 200-300 کلمه، در صورت امکان مثال عملی):\n\n"
            f"سوال {user_name}: {question}"
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.7,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 512,
            },
        }

        headers = {"Content-Type": "application/json"}
        params = {"key": self.gemini_api_key}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.gemini_url, headers=headers, params=params, json=payload, timeout=30) as resp:
                    text = await resp.text()
                    if resp.status != 200:
                        logger.error(f"Gemini API returned {resp.status}: {text}")
                        return "❌ خطا در ارتباط با سرویس پاسخ‌گوی هوش مصنوعی. لطفاً بعداً تلاش کنید."
                    data = await resp.json()
                    # ساختار پاسخ: candidates -> content -> parts -> [ {text: "..."} ]
                    candidates = data.get("candidates") or []
                    if not candidates:
                        logger.error(f"Gemini returned no candidates: {json.dumps(data)[:400]}")
                        return "❌ نتوانستم پاسخی تولید کنم. لطفاً سوال‌تان را واضح‌تر کنید."
                    content = candidates[0].get("content", {})
                    parts = content.get("parts") or []
                    if not parts:
                        return "❌ پاسخ نامعتبری دریافت شد."
                    return parts[0].get("text", "").strip() or "❌ پاسخ خالی دریافت شد."
        except asyncio.TimeoutError:
            logger.exception("Timeout to Gemini")
            return "❌ زمان پاسخ هوش مصنوعی طولانی شد. لطفاً دوباره تلاش کنید."
        except Exception as e:
            logger.exception(f"Exception in ask_gemini: {e}")
            return "❌ خطای داخلی در سرویس هوش مصنوعی. لطفاً بعداً تلاش کنید."

    async def search_site_by_model(self, model_code: str) -> str:
        """جستجو در سایت با استفاده از API جستجو (اگر تعریف شده باشد)."""
        if not self.search_api_url:
            return "⚠️ آدرس API جستجو پیکربندی نشده است."
        params = {"q": model_code}  # اگر API شما پارامتر متفاوت می‌خواهد، اینجا را تغییر دهید
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.search_api_url, params=params, timeout=20) as resp:
                    text = await resp.text()
                    if resp.status != 200:
                        logger.error(f"Search API returned {resp.status}: {text}")
                        return f"❌ خطا در جستجوی سایت (کد {resp.status})."
                    # سعی می‌کنیم JSON بخوانیم
                    try:
                        data = await resp.json()
                        # سعی برای استخراج نتایج متداول
                        results = data.get("results") or data.get("items") or data
                        # فرمت مناسب خروجی
                        if isinstance(results, list):
                            if not results:
                                return "❌ نتیجه‌ای یافت نشد."
                            # محدود به چند مورد اول برای کوتاهی پیام
                            formatted = []
                            for item in results[:8]:
                                if isinstance(item, dict):
                                    title = item.get("title") or item.get("name") or item.get("id") or str(item)
                                    summary = item.get("summary") or item.get("excerpt") or ""
                                    formatted.append(f"• {title}" + (f"\n  {summary}" if summary else ""))
                                else:
                                    formatted.append(f"• {str(item)}")
                            return "🔎 نتایج جستجو:\n\n" + "\n\n".join(formatted)
                        else:
                            # اگر شیء، آن را pretty print می‌کنیم
                            pretty = json.dumps(results, ensure_ascii=False, indent=2)
                            return f"🔎 نتایج (JSON):\n\n{pretty[:3500]}"
                    except Exception:
                        # اگر JSON نبود، متن خام را برمی‌گردانیم (مثلاً HTML یا متن)
                        return f"🔎 نتیجه جستجو (متن):\n\n{(text[:3500] + '...') if len(text) > 3500 else text}"
        except asyncio.TimeoutError:
            logger.exception("Timeout while searching site")
            return "❌ زمان جستجو طولانی شد. دوباره تلاش کنید."
        except Exception as e:
            logger.exception(f"Exception in search_site_by_model: {e}")
            return "❌ خطای داخلی هنگام جستجو. لطفاً بعداً تلاش کنید."

    async def get_site_stats(self) -> Optional[str]:
        """درخواست آمار از API سایت (اگر موجود باشد)."""
        if not self.site_stats_url:
            return None
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.site_stats_url, timeout=15) as resp:
                    if resp.status != 200:
                        logger.error(f"Site stats returned {resp.status}")
                        return None
                    data = await resp.json()
                    # انتظار ساختاری مشابه {today:..., total:...}
                    today = data.get("today") or data.get("visits_today") or data.get("daily") 
                    total = data.get("total") or data.get("visits_total") or data.get("all_time")
                    return f"بازدید امروز: {today}\nبازدید کل: {total}"
        except Exception as e:
            logger.warning(f"Could not fetch site stats: {e}")
            return None


# نمونه‌ی سراسری
bot_instance = SimorghAIBot(
    gemini_api_key=GEMINI_API_KEY,
    search_api_url=SEARCH_API_URL,
    site_stats_url=SITE_STATS_URL,
    channel_id=CHANNEL_ID,
    daily_limit=DAILY_LIMIT,
    max_question_length=MAX_QUESTION_LENGTH,
)


# -----------------------------
# متن ثابت‌ها
# -----------------------------
WELCOME_TEXT = (
    "🤖 سلام! به ربات هوش مصنوعی سیمرغ خوش آمدید.\n\n"
    "قابلیت‌ها:\n"
    "• پاسخ به سوالات AI (اگر پیکربندی شده باشد)\n"
    "• جستجو در سایت با «کد مدل» (در صورت فعال بودن API)\n"
    f"• محدودیت روزانه: {bot_instance.DAILY_LIMIT} سوال\n\n"
    "برای شروع /start را بزنید یا از دکمه‌ها استفاده کنید."
)

HELP_TEXT = (
    "📖 راهنمای استفاده:\n"
    "• یک سوال مرتبط با هوش مصنوعی بنویسید و ارسال کنید.\n"
    "• یا از دکمه '🔍 جستجو با کد مدل' برای جستجوی داخل سایت استفاده کنید.\n"
    "• برای استفاده از قابلیت پاسخ‌هوش‌مصنوعی، GEMINI_API_KEY باید تنظیم شده باشد.\n"
    "❓ پشتیبانی: @SimorghAI"
)


# -----------------------------
# هندلرها
# -----------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    kb = [
        [InlineKeyboardButton("🔗 عضویت در کانال سیمرغ", url=f"https://t.me/{bot_instance.channel_id.lstrip('@')}")],
        [InlineKeyboardButton("❓ راهنما", callback_data="help")],
        [InlineKeyboardButton("📊 آمار بازدید", callback_data="stats")],
        [InlineKeyboardButton("🔍 جستجو با کد مدل", callback_data="search_model")],
    ]
    reply_markup = InlineKeyboardMarkup(kb)
    name = user.first_name or "کاربر"
    await update.message.reply_text(f"سلام {name}!\n\n{WELCOME_TEXT}", reply_markup=reply_markup)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # این هندلر هم برای دستور /help و هم برای دکمهٔ help استفاده می‌شود
    if update.callback_query:
        await update.callback_query.edit_message_text(HELP_TEXT)
    else:
        await update.message.reply_text(HELP_TEXT)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "help":
        await query.edit_message_text(HELP_TEXT)
        return

    if data == "stats":
        # اول تلاش برای گرفتن آمار سایت (در صورت فعال بودن)
        stats = await bot_instance.get_site_stats()
        if stats:
            await query.edit_message_text("📊 آمار سایت:\n\n" + stats)
            return
        # در غیر اینصورت آمار استفاده کاربر را نمایش می‌دهیم
        uid = query.from_user.id
        can_ask, remaining = bot_instance.check_user_limit(uid)
        used = bot_instance.DAILY_LIMIT - remaining
        stats_text = (
            f"📊 آمار استفاده شما\n\n"
            f"تاریخ: {datetime.utcnow().strftime('%Y/%m/%d')}\n"
            f"✅ استفاده شده: {used}/{bot_instance.DAILY_LIMIT}\n"
            f"⏰ باقی‌مانده: {remaining} سوال\n\n"
            "🔄 آمار فردا ریست می‌شود"
        )
        await query.edit_message_text(stats_text)
        return

    if data == "search_model":
        # علامت‌گذاری حالت انتظار در context.user_data
        context.user_data["awaiting_model_code"] = True
        await query.edit_message_text("🔍 لطفاً کد مدل را ارسال کنید (مثال: M12345) — یا عبارت مورد نظر را تایپ کنید.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # پیام متنی از کاربر
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    text = update.message.text.strip()

    # 1) اگر در حالت جستجوی مدل هستیم
    if context.user_data.get("awaiting_model_code"):
        context.user_data["awaiting_model_code"] = False
        await update.message.reply_text("⌛ در حال جستجو...")

        result_text = await bot_instance.search_site_by_model(text)
        await update.message.reply_text(result_text)
        return

    # 2) بررسی عضویت در کانال (اگر بخواهید الزام کنید)
    try:
        is_member = await bot_instance.is_user_member(context, user.id)
    except Exception:
        is_member = False

    if not is_member:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 عضویت در کانال", url=f"https://t.me/{bot_instance.channel_id.lstrip('@')}")]])
        await update.message.reply_text(
            "❌ برای استفاده از ربات، لطفاً ابتدا عضو کانال سیمرغ شوید.",
            reply_markup=kb,
        )
        return

    # 3) طول پیام
    if len(text) > bot_instance.MAX_QUESTION_LENGTH:
        await update.message.reply_text(
            f"❌ سوال شما خیلی طولانی است؛ لطفاً کمتر از {bot_instance.MAX_QUESTION_LENGTH} کاراکتر بنویسید."
        )
        return

    # 4) محدودیت روزانه
    can_ask, remaining = bot_instance.check_user_limit(user.id)
    if not can_ask:
        await update.message.reply_text("❌ شما امروز تعداد مجاز سوالات را استفاده کرده‌اید. فردا دوباره تلاش کنید.")
        return

    # 5) اعلام وضعیت تایپ
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except Exception:
        # اگر دچار خطا شدیم، ادامه می‌دهیم
        pass

    # 6) ارسال به Gemini (اگر پیکربندی شده)
    await update.message.reply_text("⌛ در حال پردازش سوال شما، لطفاً منتظر بمانید...")
    answer = await bot_instance.ask_gemini(text, user.first_name or "کاربر")

    # اگر پاسخ با علامت خطا شروع شد، حساب کاربری افزایش داده نشود.
    if not answer.startswith("❌") and not answer.startswith("⚠️"):
        bot_instance.increment_user_usage(user.id)
        remaining -= 1

    footer = f"\n\n━━━━━━━━━━━━━━\n💡 سوالات باقی‌مانده: {max(0, remaining)}/{bot_instance.DAILY_LIMIT}\n🔗 کانال: {bot_instance.channel_id}"
    full_answer = answer + footer

    # ارسال پاسخ (تقسیم در صورت طولانی بودن)
    try:
        if len(full_answer) <= 4096:
            await update.message.reply_text(full_answer)
        else:
            # اگر خیلی طولانی است، ابتدا پاسخ و سپس footer را جدا می‌فرستیم
            await update.message.reply_text(answer)
            await update.message.reply_text(footer)
    except Exception as e:
        logger.exception(f"Failed to send answer message: {e}")
        # تلاش برای ارسال متن ساده‌تر
        try:
            await update.message.reply_text(answer[:4000])
        except Exception:
            pass


# -----------------------------
# راه‌اندازی و اجرا
# -----------------------------
def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # هندلرها
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🚀 بات سیمرغ AI شروع شد...")
    application.run_polling()  # اگر می‌خواهید webhook استفاده کنید باید این بخش را تغییر دهید


if __name__ == "__main__":
    main()
