import asyncio
import logging
from datetime import datetime, timedelta
import json
import os
from typing import Dict, Optional
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# تنظیمات لاگ
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# کلاس اصلی بات
class SimorghAIBot:
    def __init__(self, telegram_token: str, gemini_api_key: str):
        self.telegram_token = telegram_token
        self.gemini_api_key = 
        self.gemini_url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent"
        
        # ذخیره استفاده کاربران (در production از دیتابیس استفاده کنید)
        self.user_usage: Dict[int, Dict] = {}
        
        # محدودیت‌ها
        self.DAILY_LIMIT = 5  # سوال در روز
        self.MAX_QUESTION_LENGTH = 500  # کاراکتر
        
        # کانال رسمی (ID کانال خودتان را جایگزین کنید)
        self.CHANNEL_ID = "@simorghAI"  # یا ID عددی کانال
        
    async def is_user_member(self, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
        """بررسی عضویت کاربر در کانال"""
        try:
            member = await context.bot.get_chat_member(self.CHANNEL_ID, user_id)
            return member.status in ['member', 'administrator', 'creator']
        except:
            return False
    
    def check_user_limit(self, user_id: int) -> tuple[bool, int]:
        """بررسی محدودیت روزانه کاربر"""
        today = datetime.now().date()
        
        if user_id not in self.user_usage:
            self.user_usage[user_id] = {'date': today, 'count': 0}
        
        user_data = self.user_usage[user_id]
        
        # اگر روز جدید است، ریست کن
        if user_data['date'] != today:
            user_data['date'] = today
            user_data['count'] = 0
        
        remaining = self.DAILY_LIMIT - user_data['count']
        return user_data['count'] < self.DAILY_LIMIT, remaining
    
    def increment_user_usage(self, user_id: int):
        """افزایش تعداد استفاده کاربر"""
        if user_id in self.user_usage:
            self.user_usage[user_id]['count'] += 1
    
    async def ask_gemini(self, question: str, user_name: str = "کاربر") -> str:
        """ارسال سوال به Gemini API"""
        try:
            # پرامپت بهینه شده برای کانال AI
            prompt = f"""شما دستیار هوشمند کانال خبری هوش مصنوعی سیمرغ هستید. 
به سوال زیر پاسخ دهید:
- پاسخ را به فارسی و در حدود 200-300 کلمه بدهید
- در صورت امکان مثال عملی بزنید
- اگر سوال مرتبط با AI نیست، کاربر را به موضوعات مرتبط با هوش مصنوعی هدایت کنید

سوال {user_name}: {question}"""

            payload = {
                "contents": [{
                    "parts": [{"text": prompt}]
                }],
                "generationConfig": {
                    "temperature": 0.7,
                    "topK": 40,
                    "topP": 0.95,
                    "maxOutputTokens": 512,
                }
            }
            
            headers = {"Content-Type": "application/json"}
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.gemini_url}?key={self.gemini_api_key}",
                    headers=headers,
                    json=payload
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        if 'candidates' in result and len(result['candidates']) > 0:
                            text = result['candidates'][0]['content']['parts'][0]['text']
                            return text.strip()
                        else:
                            return "❌ متأسفانه نتوانستم پاسخ مناسبی تولید کنم. لطفاً دوباره تلاش کنید."
                    else:
                        error_text = await response.text()
                        logger.error(f"Gemini API error: {response.status} - {error_text}")
                        return "❌ خطا در ارتباط با سرور. لطفاً بعداً تلاش کنید."
                        
        except Exception as e:
            logger.error(f"Error in ask_gemini: {str(e)}")
            return "❌ خطای غیرمنتظره. لطفاً بعداً تلاش کنید."

# هندلرهای بات
bot_instance = None

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پیام خوش‌آمدگویی"""
    user = update.effective_user
    
    keyboard = [
        [InlineKeyboardButton("🔗 عضویت در کانال سیمرغ", url=f"https://t.me/{bot_instance.CHANNEL_ID[1:]}")],
        [InlineKeyboardButton("❓ راهنما", callback_data="help")],
        [InlineKeyboardButton("📊 آمار استفاده", callback_data="stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = f"""🤖 سلام {user.first_name}!

به ربات هوش مصنوعی کانال سیمرغ خوش آمدید! 🚀

🎯 **قابلیت‌ها:**
• پاسخ به سوالات مربوط به هوش مصنوعی
• راهنمایی در مورد ابزارها و تکنولوژی‌های AI  
• آخرین اخبار و ترندهای هوش مصنوعی

📝 **محدودیت‌ها:**
• {bot_instance.DAILY_LIMIT} سوال در روز برای هر کاربر
• حداکثر {bot_instance.MAX_QUESTION_LENGTH} کاراکتر برای هر سوال
• عضویت در کانال الزامی است

برای شروع، سوال خود را بپرسید! 👇"""
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """راهنمای استفاده"""
    help_text = """📖 **راهنمای استفاده از ربات سیمرغ AI**

🔸 **چگونه سوال بپرسم؟**
فقط سوال خود را تایپ کنید و ارسال کنید!

🔸 **نمونه سوالات:**
• "تفاوت ChatGPT و Claude چیست؟"
• "چطور یک مدل AI آموزش دهم؟"  
• "بهترین ابزارهای No-Code AI کدامند؟"

🔸 **نکات مهم:**
✅ سوالات مرتبط با هوش مصنوعی بپرسید
✅ سوال را واضح و مفصل بیان کنید
✅ از کلمات کلیدی مناسب استفاده کنید

❌ از سوالات نامرتبط خودداری کنید
❌ پیام‌های خیلی کوتاه یا مبهم نفرستید

📞 **پشتیبانی:** @SimorghAI_Support"""
    
    await update.message.reply_text(help_text)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """پردازش پیام‌های کاربران"""
    user = update.effective_user
    message = update.message.text
    
    # بررسی عضویت در کانال
    if not await bot_instance.is_user_member(context, user.id):
        keyboard = [[InlineKeyboardButton("🔗 عضویت در کانال", url=f"https://t.me/{bot_instance.CHANNEL_ID[1:]}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "❌ برای استفاده از ربات، ابتدا باید عضو کانال سیمرغ باشید.\n"
            "لطفاً عضو شده و دوباره سوال خود را بپرسید! 👆",
            reply_markup=reply_markup
        )
        return
    
    # بررسی طول پیام
    if len(message) > bot_instance.MAX_QUESTION_LENGTH:
        await update.message.reply_text(
            f"❌ سوال شما خیلی طولانی است! لطفاً کمتر از {bot_instance.MAX_QUESTION_LENGTH} کاراکتر بنویسید."
        )
        return
    
    # بررسی محدودیت روزانه
    can_ask, remaining = bot_instance.check_user_limit(user.id)
    if not can_ask:
        await update.message.reply_text(
            "❌ شما امروز تعداد مجاز سوالات خود را استفاده کرده‌اید.\n"
            "فردا دوباره تلاش کنید! ⏰"
        )
        return
    
    # ارسال پیام "در حال تایپ..."
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    
    # پردازش سوال
    try:
        # افزایش شمارنده استفاده
        bot_instance.increment_user_usage(user.id)
        
        # دریافت پاسخ از Gemini
        answer = await bot_instance.ask_gemini(message, user.first_name)
        
        # اضافه کردن footer
        remaining -= 1  # کاهش به دلیل استفاده فعلی
        footer = f"\n\n━━━━━━━━━━━━━━\n💡 سوالات باقی‌مانده: {remaining}/{bot_instance.DAILY_LIMIT}\n🔗 کانال: @SimorghAI"
        
        full_answer = answer + footer
        
        # ارسال پاسخ
        if len(full_answer) > 4096:  # محدودیت تلگرام
            # تقسیم پیام طولانی
            await update.message.reply_text(answer)
            await update.message.reply_text(footer)
        else:
            await update.message.reply_text(full_answer)
            
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        await update.message.reply_text(
            "❌ خطا در پردازش سوال شما. لطفاً دوباره تلاش کنید."
        )

async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """نمایش آمار کاربر"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    can_ask, remaining = bot_instance.check_user_limit(user_id)
    
    stats_text = f"""📊 **آمار استفاده شما**

🗓 تاریخ: {datetime.now().strftime('%Y/%m/%d')}
✅ استفاده شده: {bot_instance.DAILY_LIMIT - remaining}/{bot_instance.DAILY_LIMIT}
⏰ باقی‌مانده: {remaining} سوال

🔄 آمار فردا ریست می‌شود"""
    
    await query.edit_message_text(stats_text)

def main():
    """اجرای اصلی بات"""
    # متغیرهای محیطی (در production از .env file استفاده کنید)
    TELEGRAM_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"  # توکن ربات تلگرام
    GEMINI_API_KEY = "YOUR_GEMINI_API_KEY"      # کلید API جمینای
    
    if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
        print("❌ لطفاً توکن‌های لازم را تنظیم کنید!")
        return
    
    # ایجاد نمونه بات
    global bot_instance
    bot_instance = SimorghAIBot(TELEGRAM_TOKEN, GEMINI_API_KEY)
    
    # ایجاد اپلیکیشن تلگرام
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # اضافه کردن هندلرها
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # اجرای بات
    print("🚀 بات سیمرغ AI شروع شد...")
    application.run_polling()

if __name__ == "__main__":
    main()
