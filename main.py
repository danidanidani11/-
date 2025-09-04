import os
import psycopg2
import random
import json
from fastapi import FastAPI, Request
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, KeyboardButton, BotCommand
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    CommandHandler, CallbackQueryHandler, MessageHandler, filters
)
from contextlib import contextmanager
import time
import logging
from telegram.error import TelegramError
from tenacity import retry, stop_after_attempt, wait_fixed
from dotenv import load_dotenv
from datetime import datetime
import asyncio
import tempfile

# تنظیم لاگ‌ها برای دیباگ بهتر
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

# بارگذاری متغیرهای محیطی
load_dotenv()

# متغیرهای محیطی
TOKEN = os.getenv("BOT_TOKEN", "8078210260:AAEX-vz_apP68a6WhzaGhuAKK7amC1qUiEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 5542927340))
YOUR_ID = int(os.getenv("YOUR_ID", 123456789))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@charkhoun")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://charkhon_user:grMZtPEdreHgfbZrmSnrueTjgpvTzdk2@dpg-d2sislggjchc73aeb7og-a/charkhon")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://0kik4x8alj.onrender.com")
STRICT_MEMBERSHIP = os.getenv("STRICT_MEMBERSHIP", "true").lower() == "true"

SPIN_COST = 0
INVITE_REWARD = 1
MIN_WITHDRAWAL = 2000000

app = FastAPI()

# مدیریت اتصال به دیتابیس
@contextmanager
def get_db_connection():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        yield conn
        conn.close()
    except Exception as e:
        logger.error(f"خطای اتصال به دیتابیس: {str(e)}")
        raise

def init_db():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    balance INTEGER DEFAULT 0,
                    invites INTEGER DEFAULT 0,
                    spins INTEGER DEFAULT 2,
                    total_earnings INTEGER DEFAULT 0,
                    card_number TEXT,
                    last_action TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS top_winners (
                    user_id BIGINT PRIMARY KEY,
                    username TEXT,
                    total_earnings INTEGER,
                    last_win TIMESTAMP
                )
            ''')
            conn.commit()
            logger.info("دیتابیس با موفقیت مقداردهی شد")
    except Exception as e:
        logger.error(f"خطا در مقداردهی دیتابیس: {str(e)}")
        raise

# --------------------------- توابع کمکی ---------------------------

def get_or_create_user(user_id: int) -> None:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO users (user_id, spins, last_action) VALUES (%s, %s, %s)",
                    (user_id, 2, datetime.now())
                )
                conn.commit()
                logger.info(f"کاربر جدید ایجاد شد: {user_id}")
    except Exception as e:
        logger.error(f"خطا در get_or_create_user برای کاربر {user_id}: {str(e)}")
        raise

def update_balance(user_id: int, amount: int) -> None:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET balance = balance + %s, total_earnings = total_earnings + %s, last_action = %s WHERE user_id = %s",
                (amount, amount if amount > 0 else 0, datetime.now(), user_id)
            )
            conn.commit()
            logger.info(f"موجودی کاربر {user_id} آپدیت شد: {amount}")
    except Exception as e:
        logger.error(f"خطا در update_balance برای کاربر {user_id}: {str(e)}")
        raise

def update_spins(user_id: int, spins: int) -> None:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET spins = spins + %s, last_action = %s WHERE user_id = %s",
                (spins, datetime.now(), user_id)
            )
            conn.commit()
            logger.info(f"تعداد چرخش‌های کاربر {user_id} آپدیت شد: {spins}")
    except Exception as e:
        logger.error(f"خطا در update_spins برای کاربر {user_id}: {str(e)}")
        raise

def get_balance_and_spins(user_id: int) -> tuple:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT balance, spins FROM users WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            return result if result else (0, 2)
    except Exception as e:
        logger.error(f"خطا در get_balance_and_spins برای کاربر {user_id}: {str(e)}")
        raise

def get_user_data(user_id: int) -> tuple:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT balance, invites, total_earnings, card_number FROM users WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            return result if result else (0, 0, 0, None)
    except Exception as e:
        logger.error(f"خطا در get_user_data برای کاربر {user_id}: {str(e)}")
        raise

def save_card_number(user_id: int, card_number: str) -> None:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET card_number = %s, last_action = %s WHERE user_id = %s",
                (card_number, datetime.now(), user_id)
            )
            conn.commit()
            logger.info(f"شماره کارت برای کاربر {user_id} ذخیره شد")
    except Exception as e:
        logger.error(f"خطا در save_card_number برای کاربر {user_id}: {str(e)}")
        raise

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def check_channel_membership(user_id: int, context: ContextTypes) -> bool:
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        is_member = member.status in ['member', 'administrator', 'creator']
        logger.info(f"بررسی عضویت برای کاربر {user_id}: {'عضو است' if is_member else 'عضو نیست'}")
        return is_member
    except TelegramError as e:
        logger.error(f"خطای API تلگرام در بررسی عضویت برای کاربر {user_id}: {str(e)}")
        if STRICT_MEMBERSHIP:
            raise
        return False
    except Exception as e:
        logger.error(f"خطای غیرمنتظره در بررسی عضویت برای کاربر {user_id}: {str(e)}")
        if STRICT_MEMBERSHIP:
            raise
        return False

# --------------------------- دستورات ادمین ---------------------------

async def backup_db(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.", reply_markup=chat_menu())
        return

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users")
            users = cursor.fetchall()
            cursor.execute("SELECT * FROM top_winners")
            top_winners = cursor.fetchall()

        backup_data = {
            "users": [dict(zip([desc[0] for desc in cursor.description], row)) for row in users],
            "top_winners": [dict(zip([desc[0] for desc in cursor.description], row)) for row in top_winners]
        }
        backup_file = f"/tmp/backup_{int(time.time())}.json"
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, default=str)
        
        with open(backup_file, "rb") as f:
            await context.bot.send_document(
                ADMIN_ID,
                document=f,
                filename=f"backup_{int(time.time())}.json",
                caption="✅ فایل بکاپ دیتابیس"
            )
        logger.info("فایل بکاپ دیتابیس با موفقیت برای ادمین ارسال شد")
        await update.message.reply_text("✅ بکاپ دیتابیس با موفقیت ارسال شد.", reply_markup=chat_menu())
    except Exception as e:
        logger.error(f"خطا در backup_db: {str(e)}")
        await update.message.reply_text(f"❌ خطا در ایجاد بکاپ: {str(e)}", reply_markup=chat_menu())

async def clear_db(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.", reply_markup=chat_menu())
        return

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users")
            cursor.execute("DELETE FROM top_winners")
            conn.commit()
        await update.message.reply_text("✅ دیتابیس با موفقیت پاک شد.", reply_markup=chat_menu())
    except Exception as e:
        logger.error(f"خطا در clear_db: {str(e)}")
        await update.message.reply_text(f"❌ خطا در پاک کردن دیتابیس: {str(e)}", reply_markup=chat_menu())

async def stats(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.", reply_markup=chat_menu())
        return

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0] or 0
            cursor.execute("SELECT SUM(invites) FROM users")
            total_invites = cursor.fetchone()[0] or 0
            cursor.execute("SELECT SUM(total_earnings) FROM users")
            total_earnings = cursor.fetchone()[0] or 0
        await update.message.reply_text(
            f"📊 آمار ربات:\n\n"
            f"👥 تعداد کل کاربران: {total_users:,}\n"
            f"📢 تعداد کل دعوت‌ها: {total_invites:,}\n"
            f"💰 مجموع درآمد کاربران: {total_earnings:,} تومان",
            reply_markup=chat_menu()
        )
    except Exception as e:
        logger.error(f"خطا در stats: {str(e)}")
        await update.message.reply_text(f"❌ خطا در دریافت آمار: {str(e)}", reply_markup=chat_menu())

# --------------------------- کیبوردها ---------------------------

def main_menu():
    keyboard = [
        [InlineKeyboardButton("🎯 چرخوندن گردونه", callback_data="spin")],
        [InlineKeyboardButton("💰 موجودی", callback_data="balance")],
        [InlineKeyboardButton("🏆 پر درآمد ها", callback_data="top")],
        [InlineKeyboardButton("👤 پروفایل", callback_data="profile")],
        [InlineKeyboardButton("📢 دعوت دوستان", callback_data="invite")]
    ]
    return InlineKeyboardMarkup(keyboard)

def chat_menu():
    keyboard = [
        [KeyboardButton("🎯 چرخوندن گردونه"), KeyboardButton("💰 موجودی")],
        [KeyboardButton("🏆 پر درآمد ها"), KeyboardButton("👤 پروفایل")],
        [KeyboardButton("📢 دعوت دوستان")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back")]])

def withdrawal_menu():
    keyboard = [
        [InlineKeyboardButton("💸 درخواست برداشت", callback_data="request_withdrawal")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --------------------------- هندلرها ---------------------------

async def start(update: Update, context: ContextTypes):
    user = update.effective_user
    logger.debug(f"دستور /start توسط کاربر {user.id} اجرا شد")
    try:
        get_or_create_user(user.id)
    except Exception as e:
        logger.error(f"خطا در ایجاد/دریافت کاربر {user.id}: {str(e)}")
        await update.message.reply_text(
            "❌ خطایی رخ داد. لطفاً دوباره امتحان کنید یا با پشتیبانی (@daniaam) تماس بگیرید.",
            reply_markup=chat_menu()
        )
        return

    try:
        if not await check_channel_membership(user.id, context):
            await update.message.reply_text(
                f"⚠️ لطفا ابتدا در کانال ما عضو شوید:\n{CHANNEL_ID}\nسپس /start را دوباره بزنید.\n\n"
                "اگر مشکلی پیش آمد، با پشتیبانی (@daniaam) تماس بگیرید."
            )
            return
    except Exception as e:
        logger.error(f"خطای بررسی عضویت برای کاربر {user.id}: {str(e)}")
        await update.message.reply_text(
            "⚠️ خطایی در بررسی عضویت رخ داد. لطفاً دوباره امتحان کنید یا با پشتیبانی (@daniaam) تماس بگیرید.",
            reply_markup=chat_menu()
        )
        return

    try:
        if context.args:
            ref_id = context.args[0]
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (int(ref_id),))
                referrer = cursor.fetchone()
                if referrer and referrer[0] != user.id:
                    update_spins(referrer[0], INVITE_REWARD)
                    cursor.execute("UPDATE users SET invites = invites + 1 WHERE user_id = %s", (referrer[0],))
                    conn.commit()
                    logger.info(f"کاربر {user.id} از طریق دعوت {ref_id} ثبت شد")
                    await context.bot.send_message(
                        referrer[0],
                        "🎉 یه دوست جدید با لینک دعوتت به گردونه شانس پیوست! یه چرخش رایگان برات اضافه شد! 🚀"
                    )
                    await update.message.reply_text(
                        "🎉 تبریک! از طریق دعوت یه دوست وارد شدی! حالا توی کانال ما هستی و می‌تونی گردونه رو بچرخونی!",
                        reply_markup=chat_menu()
                    )
                else:
                    await update.message.reply_text(
                        "🎉 خوش آمدی به گردونه شانس!\n\n"
                        "دو چرخش رایگان داری! با هر دعوت موفق، یه چرخش دیگه بگیر!\n"
                        "برای شروع، یکی از گزینه‌های زیر رو انتخاب کن:",
                        reply_markup=chat_menu()
                    )
        else:
            await update.message.reply_text(
                "🎉 خوش آمدی به گردونه شانس!\n\n"
                "دو چرخش رایگان داری! با هر دعوت موفق، یه چرخش دیگه بگیر!\n"
                "برای شروع، یکی از گزینه‌های زیر رو انتخاب کن:",
                reply_markup=chat_menu()
            )
    except Exception as e:
        logger.error(f"خطا در پردازش دعوت برای کاربر {user.id}: {str(e)}")
        await update.message.reply_text(
            f"❌ خطایی رخ داد: {str(e)}\nلطفاً دوباره امتحان کنید یا با پشتیبانی (@daniaam) تماس بگیرید.",
            reply_markup=chat_menu()
        )

async def menu(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    logger.debug(f"دستور /menu توسط کاربر {user_id} اجرا شد")
    try:
        if not await check_channel_membership(user_id, context):
            await update.message.reply_text(
                f"⚠️ لطفا ابتدا در کانال ما عضو شوید:\n{CHANNEL_ID}\nسپس دوباره امتحان کنید."
            )
            return
        await update.message.reply_text("منوی اصلی:", reply_markup=chat_menu())
    except Exception as e:
        logger.error(f"خطای بررسی عضویت در منو برای کاربر {user_id}: {str(e)}")
        await update.message.reply_text(
            "⚠️ خطایی در بررسی عضویت رخ داد. لطفاً دوباره امتحان کنید یا با پشتیبانی (@daniaam) تماس بگیرید.",
            reply_markup=chat_menu()
        )

async def spin_wheel(user_id: int, context: ContextTypes) -> tuple:
    try:
        await context.bot.send_message(
            user_id,
            "🎡 گردونه شانس در حال چرخیدنه... آماده باش! 🌀"
        )
        await asyncio.sleep(1)
        await context.bot.send_message(
            user_id,
            "⚡ سرعتش داره بیشتر می‌شه... چی قراره برنده شی؟! 😎"
        )
        await asyncio.sleep(1)
        await context.bot.send_message(
            user_id,
            "⏳ لحظه حقیقت نزدیکه... 🎉"
        )
        await asyncio.sleep(1)

        amount = random.choices(
            [random.randint(20000, 50000), random.randint(50001, 100000), random.randint(100001, 300000)],
            weights=[70, 25, 5],
            k=1
        )[0]
        
        update_balance(user_id, amount)
        update_spins(user_id, -1)
        
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO top_winners (user_id, username, total_earnings, last_win) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE "
                "SET total_earnings = top_winners.total_earnings + %s, last_win = %s",
                (user_id, context.user_data.get('username', 'Unknown'), amount, datetime.now(), amount, datetime.now())
            )
            conn.commit()
        
        await context.bot.send_message(
            ADMIN_ID,
            f"🎡 کاربر {user_id} گردونه رو چرخوند و برنده شد: {amount:,} تومان"
        )
        return amount, f"🎉 تبریک! شما برنده {amount:,} تومان شدید! 🎊\nدوباره بچرخون یا دوستاتو دعوت کن تا چرخش بیشتر بگیری!"
    except Exception as e:
        logger.error(f"خطا در spin_wheel برای کاربر {user_id}: {str(e)}")
        raise

async def callback_handler(update: Update, context: ContextTypes):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    logger.debug(f"Callback دریافت شد از کاربر {user_id}: {query.data}")
    try:
        get_or_create_user(user_id)
    except Exception as e:
        logger.error(f"خطا در ایجاد/دریافت کاربر {user_id} در callback: {str(e)}")
        await query.message.reply_text(
            f"❌ خطایی رخ داد: {str(e)}\nلطفاً دوباره امتحان کنید یا با پشتیبانی (@daniaam) تماس بگیرید.",
            reply_markup=chat_menu()
        )
        return

    try:
        if not await check_channel_membership(user_id, context):
            await query.message.reply_text(
                f"⚠️ لطفا ابتدا در کانال ما عضو شوید:\n{CHANNEL_ID}\nسپس دوباره امتحان کنید.\n\n"
                "اگر مشکلی پیش آمد، با پشتیبانی (@daniaam) تماس بگیرید.",
                reply_markup=chat_menu()
            )
            return
    except Exception as e:
        logger.error(f"خطای بررسی عضویت در callback برای کاربر {user_id}: {str(e)}")
        await query.message.reply_text(
            "⚠️ خطایی در بررسی عضویت رخ داد. لطفاً دوباره امتحان کنید یا با پشتیبانی (@daniaam) تماس بگیرید.",
            reply_markup=chat_menu()
        )
        return

    try:
        if query.data == "back":
            context.user_data.clear()
            await query.message.reply_text("منوی اصلی:", reply_markup=chat_menu())

        elif query.data == "balance":
            balance, spins = get_balance_and_spins(user_id)
            msg = (
                f"💰 موجودی شما: {balance:,} تومان\n"
                f"🎡 تعداد چرخش‌های رایگان: {spins}\n\n"
                "📝 برای برداشت، موجودی شما باید حداقل ۲,۰۰۰,۰۰۰ تومان باشه.\n"
                "با دعوت دوستان و چرخوندن گردونه، موجودیتو افزایش بده!"
            )
            if balance >= MIN_WITHDRAWAL:
                await query.message.reply_text(msg, reply_markup=withdrawal_menu())
            else:
                await query.message.reply_text(msg, reply_markup=chat_menu())

        elif query.data == "request_withdrawal":
            balance, _ = get_balance_and_spins(user_id)
            if balance < MIN_WITHDRAWAL:
                await query.message.reply_text(
                    f"❌ موجودی شما برای برداشت کافی نیست. حداقل موجودی: {MIN_WITHDRAWAL:,} تومان",
                    reply_markup=chat_menu()
                )
                return
            user_data = get_user_data(user_id)
            card_number = user_data[3]
            if not card_number:
                await query.message.reply_text(
                    "💸 لطفاً شماره کارت ۱۶ رقمی خود را برای برداشت وارد کنید:",
                    reply_markup=back_button()
                )
                context.user_data["waiting_for_card_number"] = True
            else:
                await query.message.reply_text(
                    "💸 لطفاً مقدار برداشت (به تومان) را وارد کنید:",
                    reply_markup=back_button()
                )
                context.user_data["waiting_for_withdrawal_amount"] = True
                context.user_data["card_number"] = card_number

        elif query.data == "spin":
            balance, spins = get_balance_and_spins(user_id)
            if spins <= 0:
                await query.message.reply_text(
                    "❌ شما چرخش رایگان ندارید! 😕\nدوستاتو دعوت کن تا چرخش جدید بگیری!",
                    reply_markup=chat_menu()
                )
                return

            amount, prize_msg = await spin_wheel(user_id, context)
            await query.message.reply_text(prize_msg, reply_markup=chat_menu())

        elif query.data == "top":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id, username, total_earnings FROM top_winners ORDER BY total_earnings DESC LIMIT 10")
                rows = cursor.fetchall()
            msg = "🏆 پر درآمدهای گردونه شانس:\n\n"
            for i, row in enumerate(rows, 1):
                msg += f"{i}. @{row[1] or 'Unknown'} - درآمد: {row[2]:,} تومان\n"
            if not rows:
                msg = "🏆 هنوز برنده‌ای ثبت نشده! تو اولین باش! 😎"
            await query.message.reply_text(msg, reply_markup=chat_menu())

        elif query.data == "profile":
            user_data = get_user_data(user_id)
            balance, invites, total_earnings, _ = user_data
            await query.message.reply_text(
                f"👤 پروفایل شما:\n\n"
                f"💰 موجودی: {balance:,} تومان\n"
                f"👥 دعوت‌های موفق: {invites} نفر\n"
                f"💸 درآمد کل: {total_earnings:,} تومان\n\n"
                "با دعوت دوستان و چرخوندن گردونه، موجودیتو افزایش بده!",
                reply_markup=chat_menu()
            )

        elif query.data == "invite":
            invite_link = f"https://t.me/charkhoon_bot?start={user_id}"
            await query.message.reply_text(
                f"📢 لینک دعوت اختصاصی شما:\n{invite_link}\n\n"
                "دوستاتو دعوت کن و با هر دعوت موفق، یه چرخش رایگان بگیر! 🚀",
                reply_markup=chat_menu()
            )

    except Exception as e:
        logger.error(f"خطای هندلر callback برای کاربر {user_id}: {str(e)}")
        await query.message.reply_text(
            f"❌ خطایی رخ داد: {str(e)}\nلطفاً دوباره امتحان کنید یا با پشتیبانی (@daniaam) تماس بگیرید.",
            reply_markup=chat_menu()
        )

async def handle_messages(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""
    logger.debug(f"پیام دریافت شد از کاربر {user_id}: {text}")

    try:
        if not await check_channel_membership(user_id, context):
            await update.message.reply_text(
                f"⚠️ لطفا ابتدا در کانال ما عضو شوید:\n{CHANNEL_ID}\nسپس دوباره امتحان کنید.\n\n"
                "اگر مشکلی پیش آمد، با پشتیبانی (@daniaam) تماس بگیرید.",
                reply_markup=chat_menu()
            )
            return
    except Exception as e:
        logger.error(f"خطای بررسی عضویت در هندلر پیام برای کاربر {user_id}: {str(e)}")
        await update.message.reply_text(
            "⚠️ خطایی در بررسی عضویت رخ داد. لطفاً دوباره امتحان کنید یا با پشتیبانی (@daniaam) تماس بگیرید.",
            reply_markup=chat_menu()
        )
        return

    try:
        if text == "🎯 چرخوندن گردونه":
            balance, spins = get_balance_and_spins(user_id)
            if spins <= 0:
                await update.message.reply_text(
                    "❌ شما چرخش رایگان ندارید! 😕\nدوستاتو دعوت کن تا چرخش جدید بگیری!",
                    reply_markup=chat_menu()
                )
                return

            amount, prize_msg = await spin_wheel(user_id, context)
            await update.message.reply_text(prize_msg, reply_markup=chat_menu())

        elif text == "💰 موجودی":
            balance, spins = get_balance_and_spins(user_id)
            msg = (
                f"💰 موجودی شما: {balance:,} تومان\n"
                f"🎡 تعداد چرخش‌های رایگان: {spins}\n\n"
                "📝 برای برداشت، موجودی شما باید حداقل ۲,۰۰۰,۰۰۰ تومان باشه.\n"
                "با دعوت دوستان و چرخوندن گردونه، موجودیتو افزایش بده!"
            )
            if balance >= MIN_WITHDRAWAL:
                await update.message.reply_text(msg, reply_markup=withdrawal_menu())
            else:
                await update.message.reply_text(msg, reply_markup=chat_menu())

        elif text == "🏆 پر درآمد ها":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id, username, total_earnings FROM top_winners ORDER BY total_earnings DESC LIMIT 10")
                rows = cursor.fetchall()
            msg = "🏆 پر درآمدهای گردونه شانس:\n\n"
            for i, row in enumerate(rows, 1):
                msg += f"{i}. @{row[1] or 'Unknown'} - درآمد: {row[2]:,} تومان\n"
            if not rows:
                msg = "🏆 هنوز برنده‌ای ثبت نشده! تو اولین باش! 😎"
            await update.message.reply_text(msg, reply_markup=chat_menu())

        elif text == "👤 پروفایل":
            user_data = get_user_data(user_id)
            balance, invites, total_earnings, _ = user_data
            await update.message.reply_text(
                f"👤 پروفایل شما:\n\n"
                f"💰 موجودی: {balance:,} تومان\n"
                f"👥 دعوت‌های موفق: {invites} نفر\n"
                f"💸 درآمد کل: {total_earnings:,} تومان\n\n"
                "با دعوت دوستان و چرخوندن گردونه، موجودیتو افزایش بده!",
                reply_markup=chat_menu()
            )

        elif text == "📢 دعوت دوستان":
            invite_link = f"https://t.me/charkhoon_bot?start={user_id}"
            await update.message.reply_text(
                f"📢 لینک دعوت اختصاصی شما:\n{invite_link}\n\n"
                "دوستاتو دعوت کن و با هر دعوت موفق، یه چرخش رایگان بگیر! 🚀",
                reply_markup=chat_menu()
            )

        elif context.user_data.get("waiting_for_card_number"):
            context.user_data["waiting_for_card_number"] = False
            card_number = text.strip()
            if not card_number.isdigit() or len(card_number) != 16:
                await update.message.reply_text(
                    "❌ شماره کارت نامعتبر است. لطفاً یک شماره کارت ۱۶ رقمی معتبر وارد کنید.",
                    reply_markup=chat_menu()
                )
                return
            save_card_number(user_id, card_number)
            await update.message.reply_text(
                "💸 لطفاً مقدار برداشت (به تومان) را وارد کنید:",
                reply_markup=back_button()
            )
            context.user_data["waiting_for_withdrawal_amount"] = True
            context.user_data["card_number"] = card_number

        elif context.user_data.get("waiting_for_withdrawal_amount"):
            context.user_data["waiting_for_withdrawal_amount"] = False
            amount = text.strip()
            if not amount.isdigit():
                await update.message.reply_text(
                    "❌ مقدار برداشت باید یک عدد باشد. لطفاً دوباره وارد کنید.",
                    reply_markup=chat_menu()
                )
                return
            amount = int(amount)
            balance, _ = get_balance_and_spins(user_id)
            if amount <= 0 or amount > balance:
                await update.message.reply_text(
                    f"❌ مقدار برداشت نامعتبر است. موجودی شما: {balance:,} تومان",
                    reply_markup=chat_menu()
                )
                return
            card_number = context.user_data.get("card_number")
            update_balance(user_id, -amount)
            await context.bot.send_message(
                ADMIN_ID,
                f"💸 درخواست برداشت جدید:\n"
                f"👤 کاربر: {user_id}\n"
                f"💰 مقدار: {amount:,} تومان\n"
                f"💳 شماره کارت: {card_number}\n"
                f"لطفاً بررسی کنید."
            )
            await update.message.reply_text(
                f"✅ درخواست برداشت {amount:,} تومان ثبت شد. با پشتیبانی (@daniaam) هماهنگ کنید.",
                reply_markup=chat_menu()
            )
            context.user_data.clear()

    except Exception as e:
        logger.error(f"خطای هندلر پیام برای کاربر {user_id}: {str(e)}")
        await update.message.reply_text(
            f"❌ خطایی رخ داد: {str(e)}\nلطفاً دوباره امتحان کنید یا با پشتیبانی (@daniaam) تماس بگیرید.",
            reply_markup=chat_menu()
        )

# --------------------------- ثبت هندلرها و تنظیم منوی ربات ---------------------------

application = ApplicationBuilder().token(TOKEN).build()

async def set_menu_commands(application):
    commands = [
        BotCommand(command="/start", description="شروع ربات"),
        BotCommand(command="/backup_db", description="بکاپ دیتابیس (ادمین)"),
        BotCommand(command="/clear_db", description="پاک کردن دیتابیس (ادمین)"),
        BotCommand(command="/stats", description="آمار ربات (ادمین)")
    ]
    await application.bot.set_my_commands(commands)

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("menu", menu))
application.add_handler(CommandHandler("backup_db", backup_db))
application.add_handler(CommandHandler("clear_db", clear_db))
application.add_handler(CommandHandler("stats", stats))
application.add_handler(CallbackQueryHandler(callback_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))

# --------------------------- وب‌هوک FastAPI ---------------------------

@app.on_event("startup")
async def on_startup():
    try:
        await application.bot.delete_webhook()
        await application.bot.set_webhook(WEBHOOK_URL)
        await set_menu_commands(application)
        init_db()
        await application.initialize()
        await application.start()
        logger.info("ربات با موفقیت شروع شد و وب‌هوک تنظیم شد")
    except Exception as e:
        logger.error(f"خطای استارتاپ: {str(e)}")
        raise

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await application.stop()
        await application.shutdown()
        logger.info("ربات با موفقیت متوقف شد")
    except Exception as e:
        logger.error(f"خطای خاموش کردن: {str(e)}")

@app.post("/")
async def webhook(req: Request):
    try:
        data = await req.body()
        update = Update.de_json(json.loads(data), application.bot)
        await application.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"خطای وب‌هوک: {str(e)}")
        return {"ok": False}
