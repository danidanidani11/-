import os
import psycopg2
import random
import json
from fastapi import FastAPI, Request
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, ReplyKeyboardMarkup, KeyboardButton, BotCommand, BotCommandScopeChat, BotCommandScopeDefault
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
DEFAULT_CHANNEL_ID = os.getenv("CHANNEL_ID", "@Charkhoun")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://neondb_owner:npg_qpBCcgGS9d5H@ep-rapid-band-aemkydem-pooler.c-2.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://0kik4x8alj.onrender.com")
STRICT_MEMBERSHIP = os.getenv("STRICT_MEMBERSHIP", "true").lower() == "true"

SPIN_COST = 0
INVITE_REWARD = 1
MIN_WITHDRAWAL = 2000000  # حداقل برداشت: ۲ میلیون تومان
ADMIN_BALANCE_BOOST = 10_000_000  # اضافه کردن ۱۰ میلیون تومان به موجودی ادمین
ADMIN_INITIAL_SPINS = 999999  # تعداد گردونه بی‌نهایت برای ادمین

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

def check_db_connectivity():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            logger.info(f"اتصال به دیتابیس موفق: {result}")
            return True
    except Exception as e:
        logger.error(f"خطا در بررسی اتصال دیتابیس: {str(e)}")
        return False

def refresh_db_connection():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            conn.commit()
            logger.info("اتصال دیتابیس تازه‌سازی شد")
    except Exception as e:
        logger.error(f"خطا در تازه‌سازی اتصال دیتابیس: {str(e)}")

def init_db():
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # ایجاد جدول users و افزودن ستون is_new_user اگر وجود ندارد
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    balance INTEGER DEFAULT 0,
                    invites INTEGER DEFAULT 0,
                    spins INTEGER DEFAULT 2,
                    total_earnings INTEGER DEFAULT 0,
                    card_number TEXT,
                    last_action TIMESTAMP,
                    username TEXT,
                    pending_ref_id BIGINT,
                    is_new_user BOOLEAN DEFAULT TRUE
                )
            ''')
            # افزودن ستون is_new_user اگر وجود ندارد
            cursor.execute('''
                DO $$ 
                BEGIN
                    IF NOT EXISTS (
                        SELECT FROM pg_attribute 
                        WHERE attrelid = 'users'::regclass 
                        AND attname = 'is_new_user'
                    ) THEN
                        ALTER TABLE users ADD COLUMN is_new_user BOOLEAN DEFAULT TRUE;
                    END IF;
                END $$;
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS channels (
                    channel_id TEXT PRIMARY KEY,
                    channel_name TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS payments (
                    payment_id SERIAL PRIMARY KEY,
                    user_id BIGINT,
                    amount INTEGER,
                    card_number TEXT,
                    confirmed_at TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS invitations (
                    inviter_id BIGINT,
                    invitee_id BIGINT,
                    invited_at TIMESTAMP,
                    PRIMARY KEY (inviter_id, invitee_id)
                )
            ''')
            
            # اضافه کردن کانال پیش‌فرض اگر وجود ندارد
            cursor.execute("SELECT 1 FROM channels WHERE channel_id = %s", (DEFAULT_CHANNEL_ID,))
            if not cursor.fetchone():
                cursor.execute(
                    "INSERT INTO channels (channel_id, channel_name) VALUES (%s, %s)",
                    (DEFAULT_CHANNEL_ID, "کانال اصلی")
                )
            
            conn.commit()
            logger.info("دیتابیس با موفقیت مقداردهی شد")
    except Exception as e:
        logger.error(f"خطا در مقداردهی دیتابیس: {str(e)}")
        raise

# --------------------------- توابع کمکی ---------------------------

def is_user_new(user_id: int) -> bool:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # بررسی وجود ستون is_new_user
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'is_new_user'")
            has_is_new_user = cursor.fetchone() is not None
            if has_is_new_user:
                cursor.execute("SELECT is_new_user FROM users WHERE user_id = %s", (user_id,))
                result = cursor.fetchone()
                is_new = result[0] if result else True
            else:
                is_new = True  # اگر ستون وجود ندارد، فرض می‌کنیم کاربر جدید است
            conn.commit()
            logger.debug(f"بررسی وضعیت کاربر {user_id}: is_new_user = {is_new}")
            return is_new
    except Exception as e:
        logger.error(f"خطا در is_user_new برای کاربر {user_id}: {str(e)}")
        return True

def get_or_create_user(user_id: int, username: str = None) -> None:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
            user_exists = cursor.fetchone()
            if not user_exists:
                initial_balance = ADMIN_BALANCE_BOOST if user_id == ADMIN_ID else 0
                initial_spins = ADMIN_INITIAL_SPINS if user_id == ADMIN_ID else 2
                cursor.execute(
                    "INSERT INTO users (user_id, balance, spins, last_action, username, is_new_user) VALUES (%s, %s, %s, %s, %s, %s)",
                    (user_id, initial_balance, initial_spins, datetime.now(), username, True)
                )
                logger.info(f"کاربر جدید {user_id} ایجاد شد")
            else:
                cursor.execute(
                    "UPDATE users SET last_action = %s, username = %s WHERE user_id = %s",
                    (datetime.now(), username, user_id)
                )
                if user_id == ADMIN_ID:
                    cursor.execute(
                        "UPDATE users SET balance = balance + %s, spins = %s WHERE user_id = %s",
                        (ADMIN_BALANCE_BOOST, ADMIN_INITIAL_SPINS, user_id)
                    )
                logger.info(f"کاربر موجود {user_id} به‌روزرسانی شد")
            conn.commit()
    except Exception as e:
        logger.error(f"خطا در get_or_create_user برای کاربر {user_id}: {str(e)}")
        raise

def mark_user_as_old(user_id: int) -> None:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            # بررسی وجود ستون is_new_user
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'is_new_user'")
            if cursor.fetchone():
                cursor.execute(
                    "UPDATE users SET is_new_user = FALSE WHERE user_id = %s",
                    (user_id,)
                )
                conn.commit()
                logger.info(f"کاربر {user_id} به عنوان کاربر قدیمی علامت‌گذاری شد")
            else:
                logger.warning(f"ستون is_new_user برای کاربر {user_id} وجود ندارد")
    except Exception as e:
        logger.error(f"خطا در mark_user_as_old برای کاربر {user_id}: {str(e)}")

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

def get_balance_and_spins(user_id: int) -> tuple:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT balance, spins FROM users WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            conn.commit()
            logger.debug(f"دریافت موجودی و چرخش‌ها برای کاربر {user_id}: {result}")
            return result if result else (0, 2)
    except Exception as e:
        logger.error(f"خطا در get_balance_and_spins برای کاربر {user_id}: {str(e)}")
        return (0, 2)

def get_user_data(user_id: int) -> tuple:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT balance, invites, total_earnings, card_number, username FROM users WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            conn.commit()
            logger.debug(f"دریافت داده‌های کاربر {user_id}: {result}")
            return result if result else (0, 0, 0, None, None)
    except Exception as e:
        logger.error(f"خطا در get_user_data برای کاربر {user_id}: {str(e)}")
        return (0, 0, 0, None, None)

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

def record_payment(user_id: int, amount: int, card_number: str) -> int:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO payments (user_id, amount, card_number, confirmed_at) VALUES (%s, %s, %s, %s) RETURNING payment_id",
                (user_id, amount, card_number, datetime.now())
            )
            payment_id = cursor.fetchone()[0]
            conn.commit()
            logger.info(f"پرداخت برای کاربر {user_id} با مقدار {amount} ثبت شد: payment_id={payment_id}")
            return payment_id
    except Exception as e:
        logger.error(f"خطا در record_payment برای کاربر {user_id}: {str(e)}")
        return 0

def check_invitation(inviter_id: int, invitee_id: int) -> bool:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM invitations WHERE inviter_id = %s AND invitee_id = %s",
                (inviter_id, invitee_id)
            )
            result = cursor.fetchone()
            conn.commit()
            logger.debug(f"بررسی دعوت: inviter {inviter_id}, invitee {invitee_id}: {result is not None}")
            return result is not None
    except Exception as e:
        logger.error(f"خطا در check_invitation برای inviter {inviter_id} و invitee {invitee_id}: {str(e)}")
        return False

def record_invitation(inviter_id: int, invitee_id: int) -> None:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO invitations (inviter_id, invitee_id, invited_at) VALUES (%s, %s, %s)",
                (inviter_id, invitee_id, datetime.now())
            )
            conn.commit()
            logger.info(f"دعوت از {inviter_id} برای {invitee_id} ثبت شد")
    except Exception as e:
        logger.error(f"خطا در record_invitation برای inviter {inviter_id} و invitee {invitee_id}: {str(e)}")

def save_pending_ref(user_id: int, ref_id: int) -> None:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET pending_ref_id = %s WHERE user_id = %s",
                (ref_id, user_id)
            )
            conn.commit()
            logger.info(f"لینک دعوت در انتظار برای کاربر {user_id} ذخیره شد: {ref_id}")
    except Exception as e:
        logger.error(f"خطا در save_pending_ref برای کاربر {user_id}: {str(e)}")

def get_pending_ref(user_id: int) -> int:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pending_ref_id FROM users WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            conn.commit()
            logger.debug(f"دریافت لینک دعوت در انتظار برای کاربر {user_id}: {result[0] if result else None}")
            return result[0] if result and result[0] else None
    except Exception as e:
        logger.error(f"خطا در get_pending_ref برای کاربر {user_id}: {str(e)}")
        return None

def clear_pending_ref(user_id: int) -> None:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET pending_ref_id = NULL WHERE user_id = %s",
                (user_id,)
            )
            conn.commit()
            logger.info(f"لینک دعوت در انتظار برای کاربر {user_id} پاک شد")
    except Exception as e:
        logger.error(f"خطا در clear_pending_ref برای کاربر {user_id}: {str(e)}")

def get_channels() -> list:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT channel_id, channel_name FROM channels ORDER BY added_at")
            result = cursor.fetchall()
            conn.commit()
            logger.debug(f"کانال‌ها دریافت شدند: {result}")
            return result
    except Exception as e:
        logger.error(f"خطا در get_channels: {str(e)}")
        return []

def add_channel(channel_id: str, channel_name: str = None) -> bool:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO channels (channel_id, channel_name) VALUES (%s, %s) ON CONFLICT (channel_id) DO NOTHING",
                (channel_id, channel_name or channel_id)
            )
            conn.commit()
            logger.info(f"کانال {channel_id} اضافه شد")
            return True
    except Exception as e:
        logger.error(f"خطا در add_channel: {str(e)}")
        return False

def remove_channel(channel_id: str) -> bool:
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM channels WHERE channel_id = %s", (channel_id,))
            conn.commit()
            logger.info(f"کانال {channel_id} حذف شد")
            return True
    except Exception as e:
        logger.error(f"خطا در remove_channel: {str(e)}")
        return False

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def check_channel_membership(user_id: int, context: ContextTypes) -> bool:
    try:
        channels = get_channels()
        if not channels:
            logger.info(f"کاربر {user_id}: هیچ کانال اجباری وجود ندارد")
            return True
            
        for channel_id, channel_name in channels:
            try:
                # بررسی ادمین بودن ربات
                bot_member = await context.bot.get_chat_member(channel_id, context.bot.id)
                if bot_member.status not in ['administrator', 'creator']:
                    logger.error(f"ربات در کانال {channel_id} ادمین نیست")
                    return False
                
                # بررسی عضویت کاربر
                member = await context.bot.get_chat_member(channel_id, user_id)
                if member.status not in ['member', 'administrator', 'creator']:
                    logger.info(f"کاربر {user_id} در کانال {channel_id} عضو نیست")
                    return False
            except TelegramError as e:
                logger.error(f"خطای API تلگرام در بررسی عضویت برای کانال {channel_id}: {str(e)}")
                if STRICT_MEMBERSHIP:
                    raise
                continue
        
        logger.info(f"کاربر {user_id} در تمام کانال‌ها عضو است")
        return True
    except Exception as e:
        logger.error(f"خطای غیرمنتظره در بررسی عضویت برای کاربر {user_id}: {str(e)}")
        if STRICT_MEMBERSHIP:
            raise
        return False

async def send_new_user_notification(user_id: int, username: str, context: ContextTypes):
    try:
        message = (
            f"👤 کاربر جدید به ربات اضافه شد:\n\n"
            f"🆔 آیدی عددی: {user_id}\n"
            f"📛 یوزرنیم: @{username if username else 'بدون یوزرنیم'}\n"
            f"📅 تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=message
            )
            logger.info(f"اطلاع‌رسانی کاربر جدید به ADMIN_ID {ADMIN_ID} ارسال شد: {user_id}")
        except TelegramError as e:
            logger.warning(f"خطا در ارسال به ADMIN_ID {ADMIN_ID}: {str(e)}. تلاش برای ارسال به YOUR_ID {YOUR_ID}")
            await context.bot.send_message(
                chat_id=YOUR_ID,
                text=message
            )
            logger.info(f"اطلاع‌رسانی کاربر جدید به YOUR_ID {YOUR_ID} ارسال شد: {user_id}")
    except Exception as e:
        logger.error(f"خطا در ارسال اطلاع‌رسانی کاربر جدید برای کاربر {user_id}: {str(e)}")

# --------------------------- دستورات ادمین ---------------------------

async def debug(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.")
        return

    try:
        # بررسی اتصال دیتابیس
        db_status = check_db_connectivity()
        msg = f"🔍 وضعیت دیتابیس: {'متصل' if db_status else 'قطع'}\n\n"

        # دریافت داده‌های خام
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COALESCE(SUM(invites), 0) FROM users")
            total_invites = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COALESCE(SUM(total_earnings), 0) FROM users")
            total_earnings = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM payments")
            total_payments = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM channels")
            total_channels = cursor.fetchone()[0] or 0
            
            # بررسی وجود ستون is_new_user قبل از کوئری
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'is_new_user'")
            has_is_new_user = cursor.fetchone() is not None
            if has_is_new_user:
                cursor.execute("SELECT user_id, is_new_user FROM users LIMIT 5")
                recent_users = cursor.fetchall()
            else:
                cursor.execute("SELECT user_id, username FROM users LIMIT 5")
                recent_users = [(row[0], False) for row in cursor.fetchall()]  # اگر ستون وجود ندارد، فرض می‌کنیم همه قدیمی هستند
            conn.commit()

        msg += (
            f"📊 داده‌های خام دیتابیس:\n"
            f"👥 تعداد کاربران: {total_users}\n"
            f"📢 تعداد دعوت‌ها: {total_invites}\n"
            f"💰 مجموع درآمد: {total_earnings:,} تومان\n"
            f"💸 تعداد پرداخت‌ها: {total_payments}\n"
            f"📺 تعداد کانال‌ها: {total_channels}\n\n"
            f"👤 ۵ کاربر اخیر:\n"
        )
        for user_id_val, is_new in recent_users:
            msg += f"کاربر {user_id_val}: {'جدید' if is_new else 'قدیمی'}\n"

        # تست ارسال اعلان
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text="🔔 تست اعلان ادمین"
        )
        msg += "\n✅ اعلان تست به ادمین ارسال شد"

        await update.message.reply_text(msg)
        logger.info(f"دستور /debug توسط ادمین {user_id} اجرا شد")
    except Exception as e:
        logger.error(f"خطا در debug برای کاربر {user_id}: {str(e)}")
        await update.message.reply_text(f"❌ خطا در دیباگ: {str(e)}")

async def backup_db(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.")
        return

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users")
            users = cursor.fetchall()
            cursor.execute("SELECT * FROM top_winners")
            top_winners = cursor.fetchall()
            cursor.execute("SELECT * FROM payments")
            payments = cursor.fetchall()
            cursor.execute("SELECT * FROM invitations")
            invitations = cursor.fetchall()
            cursor.execute("SELECT * FROM channels")
            channels = cursor.fetchall()

        backup_data = {
            "users": [dict(zip([desc[0] for desc in cursor.description], row)) for row in users],
            "top_winners": [dict(zip([desc[0] for desc in cursor.description], row)) for row in top_winners],
            "payments": [dict(zip([desc[0] for desc in cursor.description], row)) for row in payments],
            "invitations": [dict(zip([desc[0] for desc in cursor.description], row)) for row in invitations],
            "channels": [dict(zip([desc[0] for desc in cursor.description], row)) for row in channels]
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
        await update.message.reply_text("✅ بکاپ دیتابیس با موفقیت ارسال شد.")
    except Exception as e:
        logger.error(f"خطا در backup_db: {str(e)}")
        await update.message.reply_text(f"❌ خطا در ایجاد بکاپ: {str(e)}")

async def restore_db(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.")
        return

    await update.message.reply_text("📤 لطفاً فایل آخرین بکاپ دیتابیس را ارسال کنید:")
    context.user_data["waiting_for_backup_file"] = True

async def handle_backup_file(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID or not context.user_data.get("waiting_for_backup_file"):
        return

    try:
        # دریافت فایل بکاپ
        document = update.message.document
        if not document:
            await update.message.reply_text("❌ لطفاً یک فایل بکاپ ارسال کنید.")
            return

        # دانلود فایل
        file = await context.bot.get_file(document.file_id)
        with tempfile.NamedTemporaryFile(mode="w+b", suffix=".json", delete=False) as temp_file:
            await file.download_to_memory(temp_file)
            temp_file.seek(0)
            backup_data = json.load(temp_file)

        # بازیابی داده‌ها
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # پاک کردن داده‌های موجود
            cursor.execute("DELETE FROM users")
            cursor.execute("DELETE FROM top_winners")
            cursor.execute("DELETE FROM payments")
            cursor.execute("DELETE FROM invitations")
            cursor.execute("DELETE FROM channels")
            
            # درج داده‌های جدید - کاربران
            users_inserted = 0
            users_skipped = 0
            for user in backup_data.get("users", []):
                user_id_val = user.get("user_id")
                if user_id_val is None:
                    logger.warning("ردیف کاربر با user_id null نادیده گرفته شد")
                    users_skipped += 1
                    continue
                    
                try:
                    cursor.execute(
                        "INSERT INTO users (user_id, balance, invites, spins, total_earnings, card_number, last_action, username, pending_ref_id, is_new_user) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET "
                        "balance = EXCLUDED.balance, invites = EXCLUDED.invites, spins = EXCLUDED.spins, "
                        "total_earnings = EXCLUDED.total_earnings, card_number = EXCLUDED.card_number, "
                        "last_action = EXCLUDED.last_action, username = EXCLUDED.username, "
                        "pending_ref_id = EXCLUDED.pending_ref_id, is_new_user = EXCLUDED.is_new_user",
                        (user_id_val, user.get("balance", 0), user.get("invites", 0), 
                         user.get("spins", 2), user.get("total_earnings", 0), user.get("card_number"), 
                         user.get("last_action"), user.get("username"), user.get("pending_ref_id"), 
                         user.get("is_new_user", True))
                    )
                    users_inserted += 1
                except Exception as e:
                    logger.error(f"خطا در درج کاربر {user_id_val}: {str(e)}")
                    users_skipped += 1
            
            # درج داده‌های جدید - برندگان برتر
            winners_inserted = 0
            winners_skipped = 0
            for winner in backup_data.get("top_winners", []):
                user_id_val = winner.get("user_id")
                if user_id_val is None:
                    logger.warning("ردیف برنده با user_id null نادیده گرفته شد")
                    winners_skipped += 1
                    continue
                    
                try:
                    cursor.execute(
                        "INSERT INTO top_winners (user_id, username, total_earnings, last_win) "
                        "VALUES (%s, %s, %s, %s) ON CONFLICT (user_id) DO UPDATE SET "
                        "username = EXCLUDED.username, total_earnings = EXCLUDED.total_earnings, last_win = EXCLUDED.last_win",
                        (user_id_val, winner.get("username"), winner.get("total_earnings", 0), winner.get("last_win"))
                    )
                    winners_inserted += 1
                except Exception as e:
                    logger.error(f"خطا در درج برنده {user_id_val}: {str(e)}")
                    winners_skipped += 1
            
            # درج داده‌های جدید - پرداخت‌ها
            payments_inserted = 0
            payments_skipped = 0
            for payment in backup_data.get("payments", []):
                payment_id_val = payment.get("payment_id")
                user_id_val = payment.get("user_id")
                
                if user_id_val is None:
                    logger.warning(f"ردیف پرداخت {payment_id_val} با user_id null نادیده گرفته شد")
                    payments_skipped += 1
                    continue
                    
                try:
                    cursor.execute(
                        "INSERT INTO payments (payment_id, user_id, amount, card_number, confirmed_at) "
                        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (payment_id) DO UPDATE SET "
                        "user_id = EXCLUDED.user_id, amount = EXCLUDED.amount, card_number = EXCLUDED.card_number, "
                        "confirmed_at = EXCLUDED.confirmed_at",
                        (payment_id_val, user_id_val, payment.get("amount", 0), 
                         payment.get("card_number"), payment.get("confirmed_at"))
                    )
                    payments_inserted += 1
                except Exception as e:
                    logger.error(f"خطا در درج پرداخت {payment_id_val}: {str(e)}")
                    payments_skipped += 1
            
            # درج داده‌های جدید - دعوت‌ها
            invitations_inserted = 0
            invitations_skipped = 0
            for invitation in backup_data.get("invitations", []):
                inviter_id = invitation.get("inviter_id")
                invitee_id = invitation.get("invitee_id")
                
                if inviter_id is None or invitee_id is None:
                    logger.warning("ردیف دعوت با inviter_id یا invitee_id null نادیده گرفته شد")
                    invitations_skipped += 1
                    continue
                    
                try:
                    cursor.execute(
                        "INSERT INTO invitations (inviter_id, invitee_id, invited_at) "
                        "VALUES (%s, %s, %s) ON CONFLICT (inviter_id, invitee_id) DO UPDATE SET "
                        "invited_at = EXCLUDED.invited_at",
                        (inviter_id, invitee_id, invitation.get("invited_at"))
                    )
                    invitations_inserted += 1
                except Exception as e:
                    logger.error(f"خطا در درج دعوت {inviter_id}-{invitee_id}: {str(e)}")
                    invitations_skipped += 1
            
            # درج داده‌های جدید - کانال‌ها
            channels_inserted = 0
            channels_skipped = 0
            for channel in backup_data.get("channels", []):
                channel_id_val = channel.get("channel_id")
                if channel_id_val is None:
                    logger.warning("ردیف کانال با channel_id null نادیده گرفته شد")
                    channels_skipped += 1
                    continue
                    
                try:
                    cursor.execute(
                        "INSERT INTO channels (channel_id, channel_name, added_at) "
                        "VALUES (%s, %s, %s) ON CONFLICT (channel_id) DO UPDATE SET "
                        "channel_name = EXCLUDED.channel_name, added_at = EXCLUDED.added_at",
                        (channel_id_val, channel.get("channel_name"), channel.get("added_at"))
                    )
                    channels_inserted += 1
                except Exception as e:
                    logger.error(f"خطا در درج کانال {channel_id_val}: {str(e)}")
                    channels_skipped += 1
            
            conn.commit()

        context.user_data["waiting_for_backup_file"] = False
        
        # تازه‌سازی اتصال دیتابیس
        refresh_db_connection()
        
        # پاک کردن کش‌های محلی
        if hasattr(context, 'user_data'):
            context.user_data.clear()
        
        # ارسال گزارش بازیابی
        report_msg = (
            f"✅ دیتابیس با موفقیت بازیابی شد!\n\n"
            f"📊 گزارش بازیابی:\n"
            f"👥 کاربران: {users_inserted} درج شدند، {users_skipped} نادیده گرفته شدند\n"
            f"🏆 برندگان: {winners_inserted} درج شدند، {winners_skipped} نادیده گرفته شدند\n"
            f"💸 پرداخت‌ها: {payments_inserted} درج شدند، {payments_skipped} نادیده گرفته شدند\n"
            f"📩 دعوت‌ها: {invitations_inserted} درج شدند، {invitations_skipped} نادیده گرفته شدند\n"
            f"📺 کانال‌ها: {channels_inserted} درج شدند، {channels_skipped} نادیده گرفته شدند\n\n"
            f"🔄 اطلاعات جدید اکنون در دسترس هستند. ممکن است نیاز باشد ربات را restart کنید."
        )
        
        await update.message.reply_text(report_msg)
        logger.info(f"دیتابیس توسط ادمین {user_id} بازیابی شد. گزارش: {report_msg}")

        # تازه‌سازی اطلاعات ادمین
        try:
            get_or_create_user(ADMIN_ID, "admin")
            logger.info("اطلاعات ادمین پس از بازیابی تازه‌سازی شد")
        except Exception as e:
            logger.error(f"خطا در تازه‌سازی اطلاعات ادمین: {str(e)}")

    except Exception as e:
        logger.error(f"خطا در بازیابی دیتابیس: {str(e)}")
        await update.message.reply_text(f"❌ خطا در بازیابی دیتابیس: {str(e)}")

async def clear_db(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.")
        return

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users")
            cursor.execute("DELETE FROM top_winners")
            cursor.execute("DELETE FROM payments")
            cursor.execute("DELETE FROM invitations")
            conn.commit()
        await update.message.reply_text("✅ دیتابیس با موفقیت پاک شد.")
        logger.info("دیتابیس با موفقیت پاک شد")
    except Exception as e:
        logger.error(f"خطا در clear_db: {str(e)}")
        await update.message.reply_text(f"❌ خطا در پاک کردن دیتابیس: {str(e)}")

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def stats(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.")
        return

    try:
        # تازه‌سازی اتصال دیتابیس
        refresh_db_connection()

        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # تعداد کل کاربران
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0] or 0
            logger.debug(f"Stats: total_users = {total_users}")
            
            # تعداد کاربران فعال (کاربرانی که در 24 ساعت گذشته فعالیت داشته‌اند)
            cursor.execute("SELECT COUNT(*) FROM users WHERE last_action >= NOW() - INTERVAL '24 hours'")
            active_users = cursor.fetchone()[0] or 0
            logger.debug(f"Stats: active_users = {active_users}")
            
            # تعداد کل دعوت‌ها
            cursor.execute("SELECT COALESCE(SUM(invites), 0) FROM users")
            total_invites = cursor.fetchone()[0] or 0
            logger.debug(f"Stats: total_invites = {total_invites}")
            
            # مجموع درآمد کاربران
            cursor.execute("SELECT COALESCE(SUM(total_earnings), 0) FROM users")
            total_earnings = cursor.fetchone()[0] or 0
            logger.debug(f"Stats: total_earnings = {total_earnings}")
            
            # تعداد پرداخت‌های تأییدشده
            cursor.execute("SELECT COUNT(*) FROM payments")
            total_payments = cursor.fetchone()[0] or 0
            logger.debug(f"Stats: total_payments = {total_payments}")
            
            # تعداد کانال‌های اجباری
            cursor.execute("SELECT COUNT(*) FROM channels")
            total_channels = cursor.fetchone()[0] or 0
            logger.debug(f"Stats: total_channels = {total_channels}")
            
            conn.commit()

        msg = (
            f"📊 آمار ربات:\n\n"
            f"👥 تعداد کل کاربران: {total_users:,}\n"
            f"🚀 کاربران فعال (24h): {active_users:,}\n"
            f"📢 تعداد کل دعوت‌ها: {total_invites:,}\n"
            f"💰 مجموع درآمد کاربران: {total_earnings:,} تومان\n"
            f"💸 تعداد پرداخت‌های تأییدشده: {total_payments:,}\n"
            f"📺 تعداد کانال‌های اجباری: {total_channels}"
        )
        await update.message.reply_text(msg)
        logger.info(f"آمار ربات برای ادمین {user_id} ارسال شد: {msg}")
    except Exception as e:
        logger.error(f"خطا در stats برای کاربر {user_id}: {str(e)}")
        await update.message.reply_text(f"❌ خطا در دریافت آمار: {str(e)}")

async def user_info(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.")
        return

    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, username, balance, invites FROM users ORDER BY user_id")
            users = cursor.fetchall()
            conn.commit()

        if not users:
            await update.message.reply_text("📉 هیچ کاربری ثبت نشده است.")
            return

        users_per_message = 50
        for i in range(0, len(users), users_per_message):
            msg = f"📋 اطلاعات کاربران (بخش {i // users_per_message + 1}):\n\n"
            for user in users[i:i + users_per_message]:
                user_id_val = user[0]
                username, balance, invites = user[1], user[2], user[3]
                username_display = f"@{username}" if username else "بدون یوزرنیم"
                msg += (
                    f"👤 آیدی عددی: {user_id_val}\n"
                    f"📛 یوزرنیم: {username_display}\n"
                    f"💰 موجودی: {balance:,} تومان\n"
                    f"👥 دعوت‌ها: {invites} نفر\n"
                    f"{'-' * 20}\n"
                )
            await update.message.reply_text(msg)
            await asyncio.sleep(0.5)

        logger.info("اطلاعات کاربران برای ادمین ارسال شد")
    except Exception as e:
        logger.error(f"خطا در user_info: {str(e)}")
        await update.message.reply_text(f"❌ خطا در دریافت اطلاعات کاربران: {str(e)}")

async def list_channels(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.")
        return

    channels = get_channels()
    if not channels:
        msg = "📺 هیچ کانالی برای عضویت اجباری تنظیم نشده است."
    else:
        msg = "📺 کانال‌های اجباری:\n\n"
        for i, (channel_id, channel_name) in enumerate(channels, 1):
            msg += f"{i}. {channel_name} ({channel_id})\n"

    keyboard = [
        [InlineKeyboardButton("✅ افزودن کانال اجباری", callback_data="add_channel")],
        [InlineKeyboardButton("❌ حذف کانال اجباری", callback_data="remove_channel")],
        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back")]
    ]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def gift_users(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.")
        return

    keyboard = [
        [InlineKeyboardButton("✅ بله", callback_data="confirm_gift_yes")],
        [InlineKeyboardButton("❌ خیر", callback_data="confirm_gift_no")]
    ]
    await update.message.reply_text(
        "🎁 آیا می‌خواهید هدیه (یک فرصت گردونه) به همه کاربران ارسال شود؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --------------------------- کیبوردها ---------------------------

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

def payment_confirmation_button(user_id: int, amount: int):
    keyboard = [[InlineKeyboardButton("🔴 پرداخت شد", callback_data=f"confirm_payment_{user_id}_{amount}")]]
    return InlineKeyboardMarkup(keyboard)

def membership_check_keyboard():
    keyboard = [[InlineKeyboardButton("✅ عضو شدم", callback_data="check_membership")]]
    return InlineKeyboardMarkup(keyboard)

def remove_channel_keyboard(channels):
    keyboard = [[InlineKeyboardButton(f"حذف {channel_name} ({channel_id})", callback_data=f"delete_channel_{channel_id}")]
                for channel_id, channel_name in channels]
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_channel_menu")])
    return InlineKeyboardMarkup(keyboard)

# --------------------------- هندلرها ---------------------------

async def start(update: Update, context: ContextTypes):
    user = update.effective_user
    logger.debug(f"دستور /start توسط کاربر {user.id} اجرا شد")
    
    try:
        # ذخیره یا به‌روزرسانی اطلاعات کاربر
        get_or_create_user(user.id, user.username)
    except Exception as e:
        logger.error(f"خطا در ایجاد/دریافت کاربر {user.id}: {str(e)}")
        await update.message.reply_text(
            f"❌ خطایی در ثبت اطلاعات کاربر رخ داد: {str(e)}. لطفاً دوباره امتحان کنید.",
            reply_markup=chat_menu()
        )
        return

    try:
        # بررسی عضویت در کانال‌ها
        is_member = await check_channel_membership(user.id, context)
        if not is_member:
            # ذخیره لینک دعوت اگر وجود دارد
            if context.args:
                try:
                    ref_id = int(context.args[0])
                    if ref_id != user.id:
                        save_pending_ref(user.id, ref_id)
                        logger.info(f"لینک دعوت برای کاربر {user.id} ذخیره شد: {ref_id}")
                except ValueError:
                    logger.warning(f"لینک دعوت نامعتبر برای کاربر {user.id}: {context.args[0]}")
                except Exception as e:
                    logger.error(f"خطا در ذخیره لینک دعوت برای کاربر {user.id}: {str(e)}")
            
            # نمایش دکمه عضویت اینلاین
            channels = get_channels()
            if channels:
                channel_links = "\n".join([f"• {channel_id}" for channel_id, channel_name in channels])
                await update.message.reply_text(
                    f"👋 سلام {user.first_name}!\n\n"
                    f"⚠️ برای استفاده از ربات، باید در کانال‌های زیر عضو شوید:\n\n"
                    f"{channel_links}\n\n"
                    "پس از عضویت، روی دکمه «✅ عضو شدم» کلیک کنید.",
                    reply_markup=membership_check_keyboard()
                )
            else:
                # اگر هیچ کانال اجباری وجود ندارد
                if is_user_new(user.id):
                    await send_new_user_notification(user.id, user.username, context)
                await update.message.reply_text(
                    "👋 سلام! به ربات خوش آمدید!",
                    reply_markup=chat_menu()
                )
            return
    except TelegramError as te:
        logger.error(f"خطای API تلگرام در بررسی عضویت برای کاربر {user.id}: {str(te)}")
        await update.message.reply_text(
            "⚠️ خطایی در بررسی عضویت در کانال رخ داد. لطفاً مطمئن شوید ربات در کانال‌ها ادمین است و دوباره امتحان کنید.",
            reply_markup=chat_menu()
        )
        return
    except Exception as e:
        logger.error(f"خطای غیرمنتظره در بررسی عضویت برای کاربر {user.id}: {str(e)}")
        await update.message.reply_text(
            f"❌ خطای غیرمنتظره‌ای رخ داد: {str(e)}. لطفاً دوباره امتحان کنید.",
            reply_markup=chat_menu()
        )
        return

    # پردازش لینک دعوت (اگر کانال اجباری وجود ندارد)
    try:
        if context.args:
            try:
                ref_id = int(context.args[0])
                if ref_id != user.id and is_user_new(user.id) and not check_invitation(ref_id, user.id):
                    with get_db_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (ref_id,))
                        referrer = cursor.fetchone()
                        if referrer:
                            update_spins(ref_id, INVITE_REWARD)
                            cursor.execute("UPDATE users SET invites = invites + 1 WHERE user_id = %s", (ref_id,))
                            record_invitation(ref_id, user.id)
                            conn.commit()
                            logger.info(f"کاربر {user.id} از طریق دعوت {ref_id} ثبت شد")
                            await context.bot.send_message(
                                ref_id,
                                "🎉 یه نفر با لینک دعوتت به گردونه شانس پیوست! یه فرصت گردونه برات اضافه شد! 🚀"
                            )
            except ValueError:
                logger.warning(f"لینک دعوت نامعتبر برای کاربر {user.id}: {context.args[0]}")
            except Exception as e:
                logger.error(f"خطا در پردازش دعوت برای کاربر {user.id}: {str(e)}")
        
        # پردازش لینک دعوت ذخیره شده
        pending_ref = get_pending_ref(user.id)
        if pending_ref and pending_ref != user.id and is_user_new(user.id) and not check_invitation(pending_ref, user.id):
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (pending_ref,))
                    referrer = cursor.fetchone()
                    if referrer:
                        update_spins(pending_ref, INVITE_REWARD)
                        cursor.execute("UPDATE users SET invites = invites + 1 WHERE user_id = %s", (pending_ref,))
                        record_invitation(pending_ref, user.id)
                        conn.commit()
                        logger.info(f"کاربر {user.id} از طریق دعوت ذخیره شده {pending_ref} ثبت شد")
                        await context.bot.send_message(
                            pending_ref,
                            "🎉 یه نفر با لینک دعوتت به گردونه شانس پیوست! یه فرصت گردونه برات اضافه شد! 🚀"
                        )
                clear_pending_ref(user.id)
            except Exception as e:
                logger.error(f"خطا در پردازش لینک دعوت ذخیره شده برای کاربر {user.id}: {str(e)}")

        if is_user_new(user.id):
            await send_new_user_notification(user.id, user.username, context)
            mark_user_as_old(user.id)

        await update.message.reply_text(
            "🎉 خوش اومدی به گردونه شانس!\n\n"
            "برای شروع، یکی از گزینه‌های زیر رو انتخاب کن:",
            reply_markup=chat_menu()
        )
    except Exception as e:
        logger.error(f"خطا در پردازش /start برای کاربر {user.id}: {str(e)}")
        await update.message.reply_text(
            f"❌ خطایی رخ داد: {str(e)}. لطفاً دوباره امتحان کنید.",
            reply_markup=chat_menu()
        )

async def menu(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    logger.debug(f"دستور /menu توسط کاربر {user_id} اجرا شد")
    try:
        if not await check_channel_membership(user_id, context):
            channels = get_channels()
            if channels:
                channel_links = "\n".join([f"• {channel_id}" for channel_id, channel_name in channels])
                await update.message.reply_text(
                    f"⚠️ لطفا ابتدا در کانال‌های زیر عضو شوید:\n\n{channel_links}\nسپس دوباره امتحان کنید.",
                    reply_markup=membership_check_keyboard()
                )
            return
        await update.message.reply_text("منوی اصلی:", reply_markup=chat_menu())
    except Exception as e:
        logger.error(f"خطای بررسی عضویت در منو برای کاربر {user_id}: {str(e)}")
        await update.message.reply_text(
            f"⚠️ خطایی در بررسی عضویت رخ داد: {str(e)}. لطفاً دوباره امتحان کنید.",
            reply_markup=chat_menu()
        )
        return

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
            weights=[85, 13, 2],
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
        
        return amount, f"🎉 تبریک! شما برنده {amount:,} تومان شدید! 🎊\nدوباره بچرخون یا دوستاتو دعوت کن تا فرصت گردونه بیشتر بگیری!"
    except Exception as e:
        logger.error(f"خطا در spin_wheel برای کاربر {user_id}: {str(e)}")
        return 0, f"❌ خطا در چرخاندن گردونه: {str(e)}. لطفاً دوباره امتحان کنید."

async def callback_handler(update: Update, context: ContextTypes):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    logger.debug(f"Callback دریافت شد از کاربر {user_id}: {query.data}")
    
    if query.data.startswith("confirm_payment_") and user_id != ADMIN_ID:
        await query.message.reply_text("❌ شما اجازه تأیید پرداخت را ندارید.")
        return

    try:
        get_or_create_user(user_id, query.from_user.username)
    except Exception as e:
        logger.error(f"خطا در ایجاد/دریافت کاربر {user_id} در callback: {str(e)}")
        await query.message.reply_text(
            f"❌ خطایی رخ داد: {str(e)}. لطفاً دوباره امتحان کنید.",
            reply_markup=chat_menu()
        )
        return

    try:
        if query.data == "check_membership":
            if not await check_channel_membership(user_id, context):
                channels = get_channels()
                if channels:
                    channel_links = "\n".join([f"• {channel_id}" for channel_id, channel_name in channels])
                    await query.message.edit_text(
                        f"❌ هنوز در کانال‌های زیر عضو نشدید!\n\n{channel_links}\n\nلطفاً در کانال‌ها عضو شوید و سپس روی دکمه «✅ عضو شدم» کلیک کنید.",
                        reply_markup=membership_check_keyboard()
                    )
                return
            
            # ارسال اطلاع‌رسانی برای کاربر جدید
            if is_user_new(user_id):
                await send_new_user_notification(user_id, query.from_user.username, context)

                # پردازش لینک دعوت ذخیره شده
                pending_ref = get_pending_ref(user_id)
                if pending_ref and pending_ref != user_id and is_user_new(user_id) and not check_invitation(pending_ref, user_id):
                    try:
                        with get_db_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (pending_ref,))
                            referrer = cursor.fetchone()
                            if referrer:
                                update_spins(pending_ref, INVITE_REWARD)
                                cursor.execute("UPDATE users SET invites = invites + 1 WHERE user_id = %s", (pending_ref,))
                                record_invitation(pending_ref, user_id)
                                conn.commit()
                                logger.info(f"کاربر {user_id} از طریق دعوت ذخیره شده {pending_ref} ثبت شد")
                                await context.bot.send_message(
                                    pending_ref,
                                    "🎉 یه نفر با لینک دعوتت به گردونه شانس پیوست! یه فرصت گردونه برات اضافه شد! 🚀"
                                )
                        clear_pending_ref(user_id)
                    except Exception as e:
                        logger.error(f"خطا در پردازش لینک دعوت ذخیره شده در callback برای کاربر {user_id}: {str(e)}")

                mark_user_as_old(user_id)
                logger.debug(f"کاربر {user_id} اطلاع‌رسانی شد و به عنوان قدیمی علامت‌گذاری شد")

            await query.message.edit_text(
                "✅ عضویت شما تأیید شد!\n\n"
                "🎉 خوش اومدی به گردونه شانس!\n\n"
                "برای شروع، یکی از گزینه‌های زیر رو انتخاب کن:",
                reply_markup=None
            )
            await context.bot.send_message(user_id, "منوی اصلی:", reply_markup=chat_menu())
            return

        if not await check_channel_membership(user_id, context):
            channels = get_channels()
            if channels:
                channel_links = "\n".join([f"• {channel_id}" for channel_id, channel_name in channels])
                await query.message.reply_text(
                    f"⚠️ لطفا ابتدا در کانال‌های زیر عضو شوید:\n\n{channel_links}\nسپس دوباره امتحان کنید.",
                    reply_markup=membership_check_keyboard()
                )
            return
    except Exception as e:
        logger.error(f"خطای بررسی عضویت در callback برای کاربر {user_id}: {str(e)}")
        await query.message.reply_text(
            f"⚠️ خطایی در بررسی عضویت رخ داد: {str(e)}. لطفاً دوباره امتحان کنید.",
            reply_markup=chat_menu()
        )
        return

    try:
        if query.data == "back":
            context.user_data.clear()
            await query.message.reply_text("منوی اصلی:", reply_markup=chat_menu())

        elif query.data == "balance":
            balance, spins = get_balance_and_spins(user_id)
            if balance < MIN_WITHDRAWAL:
                await query.message.reply_text(
                    f"💰 موجودی شما: {balance:,} تومان\n"
                    f"🎡 تعداد فرصت گردونه: {spins}\n\n"
                    f"❌ موجودی کافی نداری! حداقل {MIN_WITHDRAWAL:,} تومان نیازه.\n"
                    "با دعوت دوستان و چرخوندن گردونه، موجودیتو افزایش بده!",
                    reply_markup=chat_menu()
                )
            else:
                await query.message.reply_text(
                    f"💰 موجودی شما: {balance:,} تومان\n"
                    f"🎡 تعداد فرصت گردونه: {spins}\n\n"
                    f"📝 برای برداشت، می‌تونی درخواست بدی! (حداقل {MIN_WITHDRAWAL:,} تومان)\n"
                    "با دعوت دوستان و چرخوندن گردونه، موجودیتو افزایش بده!",
                    reply_markup=withdrawal_menu()
                )

        elif query.data == "request_withdrawal":
            balance, _ = get_balance_and_spins(user_id)
            if balance < MIN_WITHDRAWAL:
                await query.message.reply_text(
                    f"❌ موجودی کافی نداری! حداقل {MIN_WITHDRAWAL:,} تومان نیازه.",
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
                    f"💸 لطفاً مقدار برداشت (به تومان، حداقل {MIN_WITHDRAWAL:,}) را وارد کنید:",
                    reply_markup=back_button()
                )
                context.user_data["waiting_for_withdrawal_amount"] = True
                context.user_data["card_number"] = card_number

        elif query.data == "spin":
            balance, spins = get_balance_and_spins(user_id)
            if spins <= 0:
                await query.message.reply_text(
                    "❌ شما فرصت گردونه ندارید! 😕\nدوستاتو دعوت کن تا فرصت جدید بگیری!",
                    reply_markup=chat_menu()
                )
                return

            amount, prize_msg = await spin_wheel(user_id, context)
            await query.message.reply_text(prize_msg, reply_markup=chat_menu())

        elif query.data == "top":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id, total_earnings FROM top_winners ORDER BY total_earnings DESC LIMIT 10")
                rows = cursor.fetchall()
                conn.commit()
            msg = "🏆 پر درآمدهای گردونه شانس:\n\n"
            for i, row in enumerate(rows, 1):
                msg += f"{i}. آیدی: {row[0]} - درآمد: {row[1]:,} تومان\n"
            if not rows:
                msg = "🏆 هنوز برنده‌ای ثبت نشده! تو اولین باش! 😎"
            await query.message.reply_text(msg, reply_markup=chat_menu())

        elif query.data == "profile":
            user_data = get_user_data(user_id)
            balance, invites, total_earnings, _, _ = user_data
            _, spins = get_balance_and_spins(user_id)
            await query.message.reply_text(
                f"👤 پروفایل شما:\n\n"
                f"💰 موجودی: {balance:,} تومان\n"
                f"🎡 تعداد فرصت گردونه: {spins}\n"
                f"👥 دعوت‌های موفق: {invites} نفر\n"
                f"💸 درآمد کل: {total_earnings:,} تومان\n\n"
                "با دعوت دوستان و چرخوندن گردونه، موجودیتو افزایش بده!",
                reply_markup=chat_menu()
            )

        elif query.data == "invite":
            invite_link = f"https://t.me/Charkhoun_bot?start={user_id}"
            await query.message.reply_text(
                f"📢 لینک دعوت اختصاصی شما:\n{invite_link}\n\n"
                "دوستاتو دعوت کن و با هر دعوت موفق، یه فرصت گردونه بگیر! 🚀",
                reply_markup=chat_menu()
            )

        elif query.data == "add_channel":
            if user_id != ADMIN_ID:
                await query.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.")
                return
            await query.message.reply_text(
                "✅ لطفاً آیدی کانال را وارد کنید و ربات را در آن ادمین کنید:",
                reply_markup=back_button()
            )
            context.user_data["waiting_for_channel_id"] = True

        elif query.data == "remove_channel":
            if user_id != ADMIN_ID:
                await query.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.")
                return
            channels = get_channels()
            if not channels:
                await query.message.reply_text(
                    "📺 هیچ کانالی برای عضویت اجباری تنظیم نشده است.",
                    reply_markup=back_button()
                )
                return
            await query.message.reply_text(
                "❌ کانال مورد نظر برای حذف را انتخاب کنید:",
                reply_markup=remove_channel_keyboard(channels)
            )

        elif query.data == "back_to_channel_menu":
            channels = get_channels()
            if not channels:
                msg = "📺 هیچ کانالی برای عضویت اجباری تنظیم نشده است."
            else:
                msg = "📺 کانال‌های اجباری:\n\n"
                for i, (channel_id, channel_name) in enumerate(channels, 1):
                    msg += f"{i}. {channel_name} ({channel_id})\n"
            keyboard = [
                [InlineKeyboardButton("✅ افزودن کانال اجباری", callback_data="add_channel")],
                [InlineKeyboardButton("❌ حذف کانال اجباری", callback_data="remove_channel")],
                [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back")]
            ]
            await query.message.edit_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

        elif query.data.startswith("delete_channel_"):
            if user_id != ADMIN_ID:
                await query.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.")
                return
            channel_id = query.data.replace("delete_channel_", "")
            if remove_channel(channel_id):
                channels = get_channels()
                if not channels:
                    msg = "📺 هیچ کانالی برای عضویت اجباری تنظیم نشده است."
                else:
                    msg = "📺 کانال‌های اجباری:\n\n"
                    for i, (chan_id, chan_name) in enumerate(channels, 1):
                        msg += f"{i}. {chan_name} ({chan_id})\n"
                keyboard = [
                    [InlineKeyboardButton("✅ افزودن کانال اجباری", callback_data="add_channel")],
                    [InlineKeyboardButton("❌ حذف کانال اجباری", callback_data="remove_channel")],
                    [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back")]
                ]
                await query.message.edit_text(
                    f"✅ کانال {channel_id} با موفقیت حذف شد.\n\n{msg}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await query.message.edit_text(
                    f"❌ خطا در حذف کانال {channel_id}.",
                    reply_markup=back_button()
                )

        elif query.data.startswith("confirm_payment_"):
            logger.debug(f"Processing confirm_payment callback: {query.data}")
            try:
                parts = query.data.split("_")
                if len(parts) != 4:
                    logger.error(f"فرمت callback_data نامعتبر: {query.data}")
                    await query.message.reply_text("❌ خطا در تأیید پرداخت: فرمت داده نامعتبر.")
                    return
                
                target_user_id = int(parts[2])
                amount = int(parts[3])
                user_data = get_user_data(target_user_id)
                card_number = user_data[3]
                
                if not card_number:
                    logger.error(f"شماره کارت برای کاربر {target_user_id} ثبت نشده است")
                    await query.message.reply_text("❌ خطا: شماره کارت ثبت نشده است.")
                    return
                
                payment_id = record_payment(target_user_id, amount, card_number)
                await context.bot.send_message(
                    target_user_id,
                    f"✅ برداشت {amount:,} تومان به شماره کارت شما واریز شد! 🎉"
                )
                await query.message.edit_text("✅ تأیید شد", reply_markup=None)
                logger.info(f"پرداخت برای کاربر {target_user_id} با مقدار {amount} تأیید شد")
                
            except ValueError as e:
                logger.error(f"خطا در پردازش callback_data: {query.data}, خطا: {str(e)}")
                await query.message.reply_text("❌ خطا در تأیید پرداخت: داده نامعتبر است.")
            except Exception as e:
                logger.error(f"خطا در تأیید پرداخت برای کاربر {target_user_id}: {str(e)}")
                await query.message.reply_text(f"❌ خطا در تأیید پرداخت: {str(e)}")

        elif query.data == "confirm_gift_yes":
            if user_id != ADMIN_ID:
                await query.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.")
                return
            try:
                with get_db_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT user_id FROM users")
                    all_users = cursor.fetchall()
                    conn.commit()

                gifted_count = 0
                for (uid,) in all_users:
                    if uid != ADMIN_ID:  # ادمین رو هدیه نده
                        update_spins(uid, 1)
                        try:
                            await context.bot.send_message(
                                uid,
                                "🎁 هدیه از طرف ادمین! یک فرصت گردونه اضافی به شما داده شد. از گردونه شانس لذت ببر! 🚀"
                            )
                            gifted_count += 1
                        except TelegramError as te:
                            logger.warning(f"نتوانست به کاربر {uid} پیام هدیه بفرستد: {str(te)}")
                        await asyncio.sleep(0.1)  # برای جلوگیری از rate limit

                await query.message.edit_text(
                    f"✅ هدیه با موفقیت به {gifted_count} کاربر ارسال شد!",
                    reply_markup=None
                )
                logger.info(f"هدیه به {gifted_count} کاربر ارسال شد")
            except Exception as e:
                logger.error(f"خطا در ارسال هدیه: {str(e)}")
                await query.message.edit_text(f"❌ خطا در ارسال هدیه: {str(e)}")

        elif query.data == "confirm_gift_no":
            await query.message.edit_text("❌ عملیات هدیه لغو شد.", reply_markup=chat_menu())

    except Exception as e:
        logger.error(f"خطای هندلر callback برای کاربر {user_id}: {str(e)}")
        await query.message.reply_text(
            f"❌ خطایی رخ داد: {str(e)}. لطفاً دوباره امتحان کنید.",
            reply_markup=chat_menu()
        )

async def handle_messages(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    text = update.message.text.strip() if update.message.text else ""
    logger.debug(f"پیام دریافت شد از کاربر {user_id}: {text}")

    try:
        if not await check_channel_membership(user_id, context):
            channels = get_channels()
            if channels:
                channel_links = "\n".join([f"• {channel_id}" for channel_id, channel_name in channels])
                await update.message.reply_text(
                    f"⚠️ لطفا ابتدا در کانال‌های زیر عضو شوید:\n\n{channel_links}\nسپس دوباره امتحان کنید.",
                    reply_markup=membership_check_keyboard()
                )
            return
    except Exception as e:
        logger.error(f"خطای بررسی عضویت در هندلر پیام برای کاربر {user_id}: {str(e)}")
        await update.message.reply_text(
            f"⚠️ خطایی در بررسی عضویت رخ داد: {str(e)}. لطفاً دوباره امتحان کنید.",
            reply_markup=chat_menu()
        )
        return

    try:
        if text == "🎯 چرخوندن گردونه":
            balance, spins = get_balance_and_spins(user_id)
            if spins <= 0:
                await update.message.reply_text(
                    "❌ شما فرصت گردونه ندارید! 😕\nدوستاتو دعوت کن تا فرصت جدید بگیری!",
                    reply_markup=chat_menu()
                )
                return

            amount, prize_msg = await spin_wheel(user_id, context)
            await update.message.reply_text(prize_msg, reply_markup=chat_menu())

        elif text == "💰 موجودی":
            balance, spins = get_balance_and_spins(user_id)
            if balance < MIN_WITHDRAWAL:
                await update.message.reply_text(
                    f"💰 موجودی شما: {balance:,} تومان\n"
                    f"🎡 تعداد فرصت گردونه: {spins}\n\n"
                    f"❌ موجودی کافی نداری! حداقل {MIN_WITHDRAWAL:,} تومان نیازه.\n"
                    "با دعوت دوستان و چرخوندن گردونه، موجودیتو افزایش بده!",
                    reply_markup=chat_menu()
                )
            else:
                await update.message.reply_text(
                    f"💰 موجودی شما: {balance:,} تومان\n"
                    f"🎡 تعداد فرصت گردونه: {spins}\n\n"
                    f"📝 برای برداشت، می‌تونی درخواست بدی! (حداقل {MIN_WITHDRAWAL:,} تومان)\n"
                    "با دعوت دوستان و چرخوندن گردونه، موجودیتو افزایش بده!",
                    reply_markup=withdrawal_menu()
                )

        elif text == "🏆 پر درآمد ها":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id, total_earnings FROM top_winners ORDER BY total_earnings DESC LIMIT 10")
                rows = cursor.fetchall()
                conn.commit()
            msg = "🏆 پر درآمدهای گردونه شانس:\n\n"
            for i, row in enumerate(rows, 1):
                msg += f"{i}. آیدی: {row[0]} - درآمد: {row[1]:,} تومان\n"
            if not rows:
                msg = "🏆 هنوز برنده‌ای ثبت نشده! تو اولین باش! 😎"
            await update.message.reply_text(msg, reply_markup=chat_menu())

        elif text == "👤 پروفایل":
            user_data = get_user_data(user_id)
            balance, invites, total_earnings, _, _ = user_data
            _, spins = get_balance_and_spins(user_id)
            await update.message.reply_text(
                f"👤 پروفایل شما:\n\n"
                f"💰 موجودی: {balance:,} تومان\n"
                f"🎡 تعداد فرصت گردونه: {spins}\n"
                f"👥 دعوت‌های موفق: {invites} نفر\n"
                f"💸 درآمد کل: {total_earnings:,} تومان\n\n"
                "با دعوت دوستان و چرخوندن گردونه، موجودیتو افزایش بده!",
                reply_markup=chat_menu()
            )

        elif text == "📢 دعوت دوستان":
            invite_link = f"https://t.me/Charkhoun_bot?start={user_id}"
            await update.message.reply_text(
                f"📢 لینک دعوت اختصاصی شما:\n{invite_link}\n\n"
                "دوستاتو دعوت کن و با هر دعوت موفق، یه فرصت گردونه بگیر! 🚀",
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
                f"💸 لطفاً مقدار برداشت (به تومان، حداقل {MIN_WITHDRAWAL:,}) را وارد کنید:",
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
            if amount < MIN_WITHDRAWAL:
                await update.message.reply_text(
                    f"❌ مقدار برداشت باید حداقل {MIN_WITHDRAWAL:,} تومان باشد.",
                    reply_markup=chat_menu()
                )
                return
            if amount <= 0 or amount > balance:
                await update.message.reply_text(
                    f"❌ مقدار برداشت نامعتبر است. موجودی شما: {balance:,} تومان",
                    reply_markup=chat_menu()
                )
                return
            user_data = get_user_data(user_id)
            invites = user_data[1]
            card_number = context.user_data.get("card_number")
            update_balance(user_id, -amount)
            await context.bot.send_message(
                ADMIN_ID,
                f"💸 درخواست برداشت جدید:\n"
                f"👤 آیدی کاربر: {user_id}\n"
                f"💰 مقدار برداشت: {amount:,} تومان\n"
                f"👥 تعداد دعوت‌های موفق: {invites} نفر\n"
                f"💳 شماره کارت: {card_number}",
                reply_markup=payment_confirmation_button(user_id, amount)
            )
            await update.message.reply_text(
                f"✅ درخواست برداشت {amount:,} تومان ثبت شد. ادمین جایزه شما رو پرداخت می‌کنه! لطفاً منتظر تأیید باشید.",
                reply_markup=chat_menu()
            )
            context.user_data.clear()

        elif context.user_data.get("waiting_for_channel_id"):
            if user_id != ADMIN_ID:
                await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.")
                context.user_data.clear()
                return
            context.user_data["waiting_for_channel_id"] = False
            channel_id = text.strip()
            if not channel_id.startswith("@"):
                await update.message.reply_text(
                    "❌ آیدی کانال باید با @ شروع شود. لطفاً دوباره وارد کنید.",
                    reply_markup=back_button()
                )
                context.user_data["waiting_for_channel_id"] = True
                return
            try:
                chat = await context.bot.get_chat(channel_id)
                channel_name = chat.title or channel_id
                member = await context.bot.get_chat_member(channel_id, context.bot.id)
                if member.status not in ['administrator', 'creator']:
                    await update.message.reply_text(
                        "❌ ربات در کانال ادمین نیست. لطفاً ربات را ادمین کنید و دوباره امتحان کنید.",
                        reply_markup=back_button()
                    )
                    context.user_data["waiting_for_channel_id"] = True
                    return
                if add_channel(channel_id, channel_name):
                    channels = get_channels()
                    if not channels:
                        msg = "📺 هیچ کانالی برای عضویت اجباری تنظیم نشده است."
                    else:
                        msg = "📺 کانال‌های اجباری:\n\n"
                        for i, (chan_id, chan_name) in enumerate(channels, 1):
                            msg += f"{i}. {chan_name} ({chan_id})\n"
                    keyboard = [
                        [InlineKeyboardButton("✅ افزودن کانال اجباری", callback_data="add_channel")],
                        [InlineKeyboardButton("❌ حذف کانال اجباری", callback_data="remove_channel")],
                        [InlineKeyboardButton("🔙 بازگشت به منو", callback_data="back")]
                    ]
                    await update.message.reply_text(
                        f"✅ کانال {channel_id} با موفقیت اضافه شد.\n\n{msg}",
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                else:
                    await update.message.reply_text(
                        f"❌ خطا در اضافه کردن کانال {channel_id}. ممکن است قبلاً اضافه شده باشد.",
                        reply_markup=back_button()
                    )
            except TelegramError as e:
                logger.error(f"خطا در بررسی کانال {channel_id}: {str(e)}")
                await update.message.reply_text(
                    f"❌ خطا در بررسی کانال: {str(e)}. لطفاً مطمئن شوید آیدی کانال درست است و ربات ادمین است.",
                    reply_markup=back_button()
                )
                context.user_data["waiting_for_channel_id"] = True

    except Exception as e:
        logger.error(f"خطای هندلر پیام برای کاربر {user_id}: {str(e)}")
        await update.message.reply_text(
            f"❌ خطایی رخ داد: {str(e)}. لطفاً دوباره امتحان کنید.",
            reply_markup=chat_menu()
        )

# --------------------------- هندلر فایل برای restore ---------------------------

async def handle_document(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID or not context.user_data.get("waiting_for_backup_file"):
        return
    
    await handle_backup_file(update, context)

# --------------------------- ثبت هندلرها و تنظیم منوی ربات ---------------------------

application = ApplicationBuilder().token(TOKEN).build()

async def set_menu_commands(application):
    user_commands = [
        BotCommand(command="/start", description="شروع ربات")
    ]
    admin_commands = [
        BotCommand(command="/start", description="شروع ربات"),
        BotCommand(command="/backup_db", description="بکاپ دیتابیس (ادمین)"),
        BotCommand(command="/restore", description="بازیابی دیتابیس (ادمین)"),
        BotCommand(command="/clear_db", description="پاک کردن دیتابیس (ادمین)"),
        BotCommand(command="/stats", description="آمار ربات (ادمین)"),
        BotCommand(command="/user_info", description="اطلاعات کاربران (ادمین)"),
        BotCommand(command="/list_channels", description="مدیریت کانال‌های اجباری (ادمین)"),
        BotCommand(command="/debug", description="دیباگ وضعیت ربات (ادمین)"),
        BotCommand(command="/gift_users", description="هدیه به کاربران (ادمین)")
    ]
    await application.bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())
    await application.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("menu", menu))
application.add_handler(CommandHandler("backup_db", backup_db))
application.add_handler(CommandHandler("restore", restore_db))
application.add_handler(CommandHandler("clear_db", clear_db))
application.add_handler(CommandHandler("stats", stats))
application.add_handler(CommandHandler("user_info", user_info))
application.add_handler(CommandHandler("list_channels", list_channels))
application.add_handler(CommandHandler("debug", debug))
application.add_handler(CommandHandler("gift_users", gift_users))
application.add_handler(CallbackQueryHandler(callback_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
application.add_handler(MessageHandler(filters.Document.ALL, handle_document))

# --------------------------- وب‌هوک FastAPI ---------------------------

@app.on_event("startup")
async def on_startup():
    try:
        if not check_db_connectivity():
            logger.error("اتصال به دیتابیس در استارتاپ ناموفق بود")
            raise Exception("عدم اتصال به دیتابیس")
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
