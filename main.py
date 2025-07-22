import os
import sqlite3
import random
import json
from fastapi import FastAPI, Request
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, ContextTypes,
    CommandHandler, CallbackQueryHandler, MessageHandler, filters
)
from contextlib import contextmanager
import hashlib
import time
import logging
from telegram.error import TelegramError
from tenacity import retry, stop_after_attempt, wait_fixed
from dotenv import load_dotenv

# بارگذاری متغیرهای محیطی
load_dotenv()

# تنظیم لاگ‌ها
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# متغیرهای محیطی
TOKEN = os.getenv("BOT_TOKEN", "8078210260:AAEX-vz_apP68a6WhzaGhuAKK7amC1qUiEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 5542927340))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@charkhoun")
TRON_ADDRESS = os.getenv("TRON_ADDRESS", "TJ4xrwKJzKjk6FgKfuuqwah3Az5Ur22kJb")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://0kik4x8alj.onrender.com")
STRICT_MEMBERSHIP = os.getenv("STRICT_MEMBERSHIP", "true").lower() == "true"

SPIN_COST = 50
SECRET_COST = 5000
INVITE_REWARD = 2000
SECRET_REWARD = 50000

app = FastAPI()

# مدیریت اتصال به دیتابیس
@contextmanager
def get_db_connection():
    conn = sqlite3.connect("users.db", check_same_thread=False)
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                invites INTEGER DEFAULT 0,
                invite_code TEXT UNIQUE,
                secret_access INTEGER DEFAULT 0,
                prizes TEXT DEFAULT '',
                last_action TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS top_winners (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                prize TEXT,
                win_time TIMESTAMP
            )
        ''')
        conn.commit()

# مقداردهی اولیه دیتابیس
init_db()

# --------------------------- کیبوردها ---------------------------

def main_menu():
    keyboard = [
        [InlineKeyboardButton("🎯 چرخوندن گردونه", callback_data="spin")],
        [InlineKeyboardButton("💰 موجودی", callback_data="balance")],
        [InlineKeyboardButton("🕵️ مرحله پنهان", callback_data="secret")],
        [InlineKeyboardButton("🏆 خوش‌شانس‌ترین‌ها", callback_data="top")],
        [InlineKeyboardButton("👤 پروفایل", callback_data="profile")],
        [InlineKeyboardButton("📢 دعوت دوستان", callback_data="invite")]
    ]
    return InlineKeyboardMarkup(keyboard)

def chat_menu():
    keyboard = [
        [KeyboardButton("🎯 چرخوندن گردونه"), KeyboardButton("💰 موجودی")],
        [KeyboardButton("🕵️ مرحله پنهان"), KeyboardButton("🏆 خوش‌شانس‌ترین‌ها")],
        [KeyboardButton("👤 پروفایل"), KeyboardButton("📢 دعوت دوستان")],
        [KeyboardButton("📌 منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back")]])

def deposit_amounts():
    keyboard = [
        [InlineKeyboardButton("۱۰ هزار تومان", callback_data="deposit_10000")],
        [InlineKeyboardButton("۳۰ هزار تومان", callback_data="deposit_30000")],
        [InlineKeyboardButton("۵۰ هزار تومان", callback_data="deposit_50000")],
        [InlineKeyboardButton("۲۰۰ هزار تومان", callback_data="deposit_200000")],
        [InlineKeyboardButton("۵۰۰ هزار تومان", callback_data="deposit_500000")],
        [InlineKeyboardButton("۱ میلیون تومان", callback_data="deposit_1000000")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
    ]
    return InlineKeyboardMarkup(keyboard)

def secret_menu():
    keyboard = [
        [InlineKeyboardButton("شروع بازی", callback_data="start_secret_game")],
        [InlineKeyboardButton("خرید مرحله پنهان", callback_data="buy_secret_access")],
        [InlineKeyboardButton("وارد کردن کد ورود", callback_data="enter_secret_code")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --------------------------- توابع کمکی ---------------------------

def generate_invite_code(user_id: int) -> str:
    return hashlib.md5(f"{user_id}{time.time()}".encode()).hexdigest()[:8]

def get_or_create_user(user_id: int) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        if not cursor.fetchone():
            invite_code = generate_invite_code(user_id)
            cursor.execute(
                "INSERT INTO users (user_id, invite_code, last_action) VALUES (?, ?, ?)",
                (user_id, invite_code, time.time())
            )
            conn.commit()

def update_balance(user_id: int, amount: int) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance + ?, last_action = ? WHERE user_id = ?",
                      (amount, time.time(), user_id))
        conn.commit()

def get_balance(user_id: int) -> int:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 0

def add_prize(user_id: int, prize: str) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET prizes = prizes || ?, last_action = ? WHERE user_id = ?",
                      (f"{prize},", time.time(), user_id))
        conn.commit()

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

def rate_limit_check(user_id: int, seconds: int = 5) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT last_action FROM users WHERE user_id=?", (user_id,))
        result = cursor.fetchone()
        if result and result[0]:
            return time.time() - result[0] > seconds
        return True

# --------------------------- هندلرها ---------------------------

async def start(update: Update, context: ContextTypes):
    user = update.effective_user
    get_or_create_user(user.id)

    try:
        if not await check_channel_membership(user.id, context):
            await update.message.reply_text(
                f"⚠️ لطفا ابتدا در کانال ما عضو شوید:\n{CHANNEL_ID}\nسپس /start را دوباره بزنید.\n\n"
                "اگر مشکلی پیش آمد، دوباره امتحان کنید یا با پشتیبانی تماس بگیرید."
            )
            return
    except Exception as e:
        logger.error(f"خطای بررسی عضویت برای کاربر {user.id}: {str(e)}")
        await update.message.reply_text(
            "⚠️ خطایی در بررسی عضویت رخ داد. لطفاً دوباره امتحان کنید یا با پشتیبانی تماس بگیرید.",
            reply_markup=back_button()
        )
        return

    if context.args:
        ref_code = context.args[0]
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE invite_code=?", (ref_code,))
            referrer = cursor.fetchone()
            if referrer and referrer[0] != user.id:
                update_balance(referrer[0], INVITE_REWARD)
                cursor.execute("UPDATE users SET invites = invites + 1 WHERE user_id=?", (referrer[0],))
                conn.commit()

    await update.message.reply_text(
        "🎉 خوش آمدی به گردونه شانس!\n\nبا چرخوندن گردونه شانس بگیر و در مرحله پنهان جایزه ببر!",
        reply_markup=chat_menu()
    )

async def menu(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    try:
        if not await check_channel_membership(user_id, context):
            await update.message.reply_text(
                f"⚠️ لطفا ابتدا در کانال ما عضو شوید:\n{CHANNEL_ID}\nسپس دوباره امتحان کنید."
            )
            return
    except Exception as e:
        logger.error(f"خطای بررسی عضویت در منو برای کاربر {user_id}: {str(e)}")
        await update.message.reply_text(
            "⚠️ خطایی در بررسی عضویت رخ داد. لطفاً دوباره امتحان کنید یا با پشتیبانی تماس بگیرید.",
            reply_markup=back_button()
        )
        return

    await update.message.reply_text("منوی اصلی:", reply_markup=chat_menu())

async def spin_wheel(user_id: int, context: ContextTypes) -> str:
    if not rate_limit_check(user_id):
        return "❌ لطفاً چند ثانیه صبر کنید و دوباره امتحان کنید."
    
    result = random.choices(
        ["پوچ", "100 هزار تومان", "پریمیوم ۳ ماهه تلگرام", "۱۰ میلیون تومان", "کتاب رایگان", "کد ورود به مرحله پنهان"],
        weights=[70, 3, 0.1, 0.01, 5, 21.89],
        k=1
    )[0]
    
    prize_msg = ""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if result == "پوچ":
            prize_msg = "متاسفانه این بار برنده نشدی! 🎡"
        elif result == "100 هزار تومان":
            update_balance(user_id, 100000)
            prize_msg = "🎉 برنده 100 هزار تومان شدی! موجودی شما افزایش یافت."
            add_prize(user_id, "100 هزار تومان")
        elif result == "پریمیوم ۳ ماهه تلگرام":
            prize_msg = "🎁 برنده اشتراک پریمیوم ۳ ماهه تلگرام شدی! لطفا با ادمین تماس کنید."
            add_prize(user_id, "پریمیوم ۳ ماهه تلگرام")
            cursor.execute("INSERT OR REPLACE INTO top_winners (user_id, username, prize, win_time) VALUES (?, ?, ?, ?)",
                         (user_id, context.user_data.get('username', 'Unknown'), result, time.time()))
        elif result == "۱۰ میلیون تومان":
            prize_msg = "🏆 برنده ۱۰ میلیون تومان شدی! لطفا با ادمین تماس کنید."
            add_prize(user_id, "۱۰ میلیون تومان")
            cursor.execute("INSERT OR REPLACE INTO top_winners (user_id, username, prize, win_time) VALUES (?, ?, ?, ?)",
                         (user_id, context.user_data.get('username', 'Unknown'), result, time.time()))
        elif result == "کتاب رایگان":
            prize_msg = "📚 برنده کتاب رایگان شدی! لطفا با ادمین تماس کنید."
            add_prize(user_id, "کتاب رایگان")
        elif result == "کد ورود به مرحله پنهان":
            cursor.execute("UPDATE users SET secret_access = 1, last_action = ? WHERE user_id = ?",
                         (time.time(), user_id))
            prize_msg = "🔓 برنده کد ورود به مرحله پنهان شدی! حالا میتونی در بازی شرکت کنی."
            add_prize(user_id, "کد ورود به مرحله پنهان")
        conn.commit()
    
    await context.bot.send_message(ADMIN_ID, f"🎡 کاربر {user_id} گردونه را چرخاند و برنده شد: {result}")
    return prize_msg

async def callback_handler(update: Update, context: ContextTypes):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    get_or_create_user(user_id)

    try:
        if not await check_channel_membership(user_id, context):
            await query.edit_message_text(
                f"⚠️ لطفا ابتدا در کانال ما عضو شوید:\n{CHANNEL_ID}\nسپس دوباره امتحان کنید.\n\n"
                "اگر مشکلی پیش آمد، دوباره امتحان کنید یا با پشتیبانی تماس بگیرید.",
                reply_markup=back_button()
            )
            return
    except Exception as e:
        logger.error(f"خطای بررسی عضویت در callback برای کاربر {user_id}: {str(e)}")
        await query.edit_message_text(
            "⚠️ خطایی در بررسی عضویت رخ داد. لطفاً دوباره امتحان کنید یا با پشتیبانی تماس بگیرید.",
            reply_markup=back_button()
        )
        return

    try:
        if query.data == "back":
            context.user_data.clear()
            await query.edit_message_text("منوی اصلی:", reply_markup=chat_menu())

        elif query.data == "balance":
            balance = get_balance(user_id)
            keyboard = [
                [InlineKeyboardButton("💰 افزایش موجودی", callback_data="deposit")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
            ]
            await query.edit_message_text(
                f"💰 موجودی شما: {balance} تومان",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif query.data == "deposit":
            await query.edit_message_text(
                "لطفا مبلغ مورد نظر را انتخاب کنید:",
                reply_markup=deposit_amounts()
            )

        elif query.data.startswith("deposit_"):
            amount = int(query.data.split("_")[1])
            await query.edit_message_text(
                f"لطفا مبلغ {amount} تومان به آدرس زیر واریز کنید:\n\n{TRON_ADDRESS}\n\n"
                "پس از واریز، رسید پرداخت را ارسال کنید.",
                reply_markup=back_button()
            )
            context.user_data["deposit_amount"] = amount

        elif query.data == "spin":
            if not rate_limit_check(user_id):
                await query.edit_message_text(
                    "❌ لطفاً چند ثانیه صبر کنید و دوباره امتحان کنید.",
                    reply_markup=back_button()
                )
                return
                
            balance = get_balance(user_id)
            if balance < SPIN_COST:
                keyboard = [
                    [InlineKeyboardButton("💰 افزایش موجودی", callback_data="deposit")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
                ]
                await query.edit_message_text(
                    f"❌ موجودی شما کافی نیست. هزینه چرخش: {SPIN_COST} تومان\nموجودی فعلی: {balance} تومان",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return

            update_balance(user_id, -SPIN_COST)
            prize_msg = await spin_wheel(user_id, context)
            await query.edit_message_text(
                f"🎡 گردونه در حال چرخش...\n\n{prize_msg}",
                reply_markup=back_button()
            )

        elif query.data == "secret":
            await query.edit_message_text(
                "🕵️ مرحله پنهان:\n\n"
                "در این مرحله شما باید یک عدد بین 1 تا 100 را حدس بزنید.\n"
                "در صورت بردن، 50 هزار تومان جایزه میگیری (1 گردونه رایگان)!",
                reply_markup=secret_menu()
            )

        elif query.data == "start_secret_game":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT secret_access FROM users WHERE user_id=?", (user_id,))
                access = cursor.fetchone()[0]
            if not access:
                await query.edit_message_text(
                    "❌ شما دسترسی به مرحله پنهان ندارید.\n"
                    "یا باید از گردونه کد ورود بگیری یا خریداری کنی.",
                    reply_markup=secret_menu()
                )
                return
            
            number = random.randint(1, 100)
            context.user_data["secret_number"] = number
            await query.edit_message_text(
                "🔢 یک عدد بین 1 تا 100 حدس بزن:",
                reply_markup=back_button()
            )
            context.user_data["waiting_for_secret_guess"] = True

        elif query.data == "buy_secret_access":
            balance = get_balance(user_id)
            if balance < SECRET_COST:
                await query.edit_message_text(
                    f"❌ موجودی شما کافی نیست. هزینه خرید دسترسی: {SECRET_COST} تومان",
                    reply_markup=secret_menu()
                )
                return
            
            update_balance(user_id, -SECRET_COST)
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET secret_access = 1, last_action = ? WHERE user_id = ?",
                             (time.time(), user_id))
                conn.commit()
            await query.edit_message_text(
                "✅ دسترسی به مرحله پنهان خریداری شد! حالا میتونی بازی رو شروع کنی.",
                reply_markup=secret_menu()
            )

        elif query.data == "enter_secret_code":
            await query.edit_message_text(
                "لطفا کد ورود به مرحله پنهان را وارد کنید:",
                reply_markup=back_button()
            )
            context.user_data["waiting_for_secret_code"] = True

        elif query.data == "top":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id, username, prize FROM top_winners ORDER BY win_time DESC LIMIT 10")
                rows = cursor.fetchall()
            msg = "🏆 خوش‌شانس‌ترین‌ها:\n\n"
            for i, row in enumerate(rows, 1):
                msg += f"{i}. @{row[1] or 'Unknown'} - برنده {row[2]}\n"
            if not rows:
                msg = "هنوز برنده ای ثبت نشده است."
            await query.edit_message_text(msg, reply_markup=back_button())

        elif query.data == "profile":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT balance, invites, prizes, invite_code FROM users WHERE user_id=?", (user_id,))
                balance, invites, prizes, invite_code = cursor.fetchone()
            prizes = prizes[:-1] if prizes else "هیچ جایزه‌ای"
            await query.edit_message_text(
                f"👤 پروفایل شما:\n\n"
                f"💰 موجودی: {balance} تومان\n"
                f"👥 دعوت موفق: {invites} نفر\n"
                f"🔗 کد دعوت: {invite_code}\n"
                f"🎁 جوایز برده شده: {prizes}",
                reply_markup=back_button()
            )

        elif query.data == "invite":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT invite_code FROM users WHERE user_id=?", (user_id,))
                invite_code = cursor.fetchone()[0]
            invite_link = f"https://t.me/charkhoon_bot?start={invite_code}"
            await query.edit_message_text(
                f"📢 لینک دعوت شما:\n{invite_link}\n\n"
                "با دعوت هر دوست 2000 تومان جایزه بگیر!",
                reply_markup=back_button()
            )

    except Exception as e:
        logger.error(f"خطای هندلر callback برای کاربر {user_id}: {str(e)}")
        await query.edit_message_text(
            f"❌ خطایی رخ داد: {str(e)}\nلطفاً دوباره امتحان کنید.",
            reply_markup=back_button()
        )

async def handle_messages(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""

    try:
        if not await check_channel_membership(user_id, context):
            await update.message.reply_text(
                f"⚠️ لطفا ابتدا در کانال ما عضو شوید:\n{CHANNEL_ID}\nسپس دوباره امتحان کنید.\n\n"
                "اگر مشکلی پیش آمد، دوباره امتحان کنید یا با پشتیبانی تماس بگیرید.",
                reply_markup=chat_menu()
            )
            return
    except Exception as e:
        logger.error(f"خطای بررسی عضویت در هندلر پیام برای کاربر {user_id}: {str(e)}")
        await update.message.reply_text(
            "⚠️ خطایی در بررسی عضویت رخ داد. لطفاً دوباره امتحان کنید یا با پشتیبانی تماس بگیرید.",
            reply_markup=chat_menu()
        )
        return

    try:
        if text == "📌 منو":
            await update.message.reply_text("منوی اصلی:", reply_markup=chat_menu())
            return

        if text == "🎯 چرخوندن گردونه":
            if not rate_limit_check(user_id):
                await update.message.reply_text(
                    "❌ لطفاً چند ثانیه صبر کنید و دوباره امتحان کنید.",
                    reply_markup=chat_menu()
                )
                return
                
            balance = get_balance(user_id)
            if balance < SPIN_COST:
                keyboard = [
                    [InlineKeyboardButton("💰 افزایش موجودی", callback_data="deposit")],
                    [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
                ]
                await update.message.reply_text(
                    f"❌ موجودی شما کافی نیست. هزینه چرخش: {SPIN_COST} تومان\nموجودی فعلی: {balance} تومان",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return

            update_balance(user_id, -SPIN_COST)
            prize_msg = await spin_wheel(user_id, context)
            await update.message.reply_text(
                f"🎡 گردونه در حال چرخش...\n\n{prize_msg}",
                reply_markup=chat_menu()
            )

        elif text == "💰 موجودی":
            balance = get_balance(user_id)
            keyboard = [
                [InlineKeyboardButton("💰 افزایش موجودی", callback_data="deposit")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
            ]
            await update.message.reply_text(
                f"💰 موجودی شما: {balance} تومان",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif text == "🕵️ مرحله پنهان":
            await update.message.reply_text(
                "🕵️ مرحله پنهان:\n\n"
                "در این مرحله شما باید یک عدد بین 1 تا 100 را حدس بزنید.\n"
                "در صورت بردن، 50 هزار تومان جایزه میگیری (1 گردونه رایگان)!",
                reply_markup=secret_menu()
            )

        elif text == "🏆 خوش‌شانس‌ترین‌ها":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id, username, prize FROM top_winners ORDER BY win_time DESC LIMIT 10")
                rows = cursor.fetchall()
            msg = "🏆 خوش‌شانس‌ترین‌ها:\n\n"
            for i, row in enumerate(rows, 1):
                msg += f"{i}. @{row[1] or 'Unknown'} - برنده {row[2]}\n"
            if not rows:
                msg = "هنوز برنده ای ثبت نشده است."
            await update.message.reply_text(msg, reply_markup=chat_menu())

        elif text == "👤 پروفایل":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT balance, invites, prizes, invite_code FROM users WHERE user_id=?", (user_id,))
                balance, invites, prizes, invite_code = cursor.fetchone()
            prizes = prizes[:-1] if prizes else "هیچ جایزه‌ای"
            await update.message.reply_text(
                f"👤 پروفایل شما:\n\n"
                f"💰 موجودی: {balance} تومان\n"
                f"👥 دعوت موفق: {invites} نفر\n"
                f"🔗 کد دعوت: {invite_code}\n"
                f"🎁 جوایز برده شده: {prizes}",
                reply_markup=chat_menu()
            )

        elif text == "📢 دعوت دوستان":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT invite_code FROM users WHERE user_id=?", (user_id,))
                invite_code = cursor.fetchone()[0]
            invite_link = f"https://t.me/charkhoon_bot?start={invite_code}"
            await update.message.reply_text(
                f"📢 لینک دعوت شما:\n{invite_link}\n\n"
                "با دعوت هر دوست 2000 تومان جایزه بگیر!",
                reply_markup=chat_menu()
            )

        elif context.user_data.get("waiting_for_secret_guess"):
            context.user_data["waiting_for_secret_guess"] = False
            try:
                guess = int(text)
                if not 1 <= guess <= 100:
                    raise ValueError("عدد باید بین 1 تا 100 باشد")
                number = context.user_data.get("secret_number")
                if guess == number:
                    update_balance(user_id, SECRET_REWARD)
                    await update.message.reply_text(
                        f"🎉 درست گفتی! جایزه {SECRET_REWARD} تومان (1 گردونه رایگان) به موجودیت اضافه شد.",
                        reply_markup=chat_menu()
                    )
                else:
                    await update.message.reply_text(
                        f"❌ عدد درست {number} بود. شانست رو امتحان کن دوباره!",
                        reply_markup=chat_menu()
                    )
            except ValueError as e:
                await update.message.reply_text(
                    f"❌ {str(e)}. لطفاً فقط یک عدد معتبر بفرست.",
                    reply_markup=chat_menu()
                )

        elif context.user_data.get("waiting_for_secret_code"):
            context.user_data["waiting_for_secret_code"] = False
            secret_code = os.getenv("SECRET_CODE", "SECRET123")
            if text == secret_code:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("UPDATE users SET secret_access = 1, last_action = ? WHERE user_id = ?",
                                 (time.time(), user_id))
                    conn.commit()
                await update.message.reply_text(
                    "✅ کد تایید شد! حالا میتونی بازی رو شروع کنی.",
                    reply_markup=secret_menu()
                )
            else:
                await update.message.reply_text(
                    "❌ کد وارد شده معتبر نیست.",
                    reply_markup=secret_menu()
                )

        elif context.user_data.get("deposit_amount"):
            amount = context.user_data.pop("deposit_amount")
            
            if update.message.photo:
                photo = update.message.photo[-1].file_id
                await context.bot.send_photo(
                    ADMIN_ID,
                    photo,
                    caption=f"📤 درخواست افزایش موجودی\n\nکاربر: {user_id}\nمبلغ: {amount} تومان"
                )
            else:
                await context.bot.send_message(
                    ADMIN_ID,
                    f"📤 درخواست افزایش موجودی\n\nکاربر: {user_id}\nمبلغ: {amount} تومان\n\nرسید:\n{text}"
                )
            
            await update.message.reply_text(
                "✅ رسید پرداخت برای بررسی به ادمین ارسال شد. پس از تایید، موجودی شما افزایش می‌یابد.",
                reply_markup=chat_menu()
            )

    except Exception as e:
        logger.error(f"خطای هندلر پیام برای کاربر {user_id}: {str(e)}")
        await update.message.reply_text(
            f"❌ خطایی رخ داد: {str(e)}\nلطفاً دوباره امتحان کنید.",
            reply_markup=chat_menu()
        )

async def handle_admin_approval(update: Update, context: ContextTypes):
    if update.effective_user.id != ADMIN_ID:
        return
    
    if update.message.reply_to_message and "درخواست افزایش موجودی" in update.message.reply_to_message.text:
        try:
            reply_text = update.message.reply_to_message.text
            user_id = int(reply_text.split("کاربر:")[1].split("\n")[0].strip())
            amount = int(reply_text.split("مبلغ:")[1].split("تومان")[0].strip())
            text = update.message.text.lower()
            
            if "تایید" in text:
                update_balance(user_id, amount)
                await context.bot.send_message(
                    user_id,
                    f"✅ درخواست افزایش موجودی شما به مبلغ {amount} تومان تایید شد.",
                    reply_markup=chat_menu()
                )
                await update.message.reply_text("✅ درخواست تایید شد.", reply_markup=chat_menu())
            elif "رد" in text:
                await context.bot.send_message(
                    user_id,
                    f"❌ درخواست افزایش موجودی شما به مبلغ {amount} تومان رد شد.",
                    reply_markup=chat_menu()
                )
                await update.message.reply_text("✅ درخواست رد شد.", reply_markup=chat_menu())
            else:
                await update.message.reply_text("لطفاً فقط 'تایید' یا 'رد' بنویسید.", reply_markup=chat_menu())
        except Exception as e:
            logger.error(f"خطای تایید ادمین: {str(e)}")
            await update.message.reply_text(f"خطا در پردازش: {str(e)}", reply_markup=chat_menu())

# --------------------------- ثبت هندلرها ---------------------------

application = ApplicationBuilder().token(TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("menu", menu))
application.add_handler(CallbackQueryHandler(callback_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
application.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_messages))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_approval))

# --------------------------- وب‌هوک FastAPI ---------------------------

@app.on_event("startup")
async def on_startup():
    try:
        await application.bot.delete_webhook()
        await application.bot.set_webhook(WEBHOOK_URL)
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
