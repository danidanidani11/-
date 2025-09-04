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
import hashlib
import time
import logging
from telegram.error import TelegramError
from tenacity import retry, stop_after_attempt, wait_fixed
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables
TOKEN = os.getenv("BOT_TOKEN", "8078210260:AAEX-vz_apP68a6WhzaGhuAKK7amC1qUiEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 5542927340))
YOUR_ID = int(os.getenv("YOUR_ID", 123456789))  # Replace with your ID
CHANNEL_ID = os.getenv("CHANNEL_ID", "@charkhoun")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://charkhon_user:grMZtPEdreHgfbZrmSnrueTjgpvTzdk2@dpg-d2sislggjchc73aeb7og-a/charkhon")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://0kik4x8alj.onrender.com")
STRICT_MEMBERSHIP = os.getenv("STRICT_MEMBERSHIP", "true").lower() == "true"

SPIN_COST = 0  # No cost for spins, handled by invitations or free spins
INVITE_REWARD = 1  # One spin per successful invite
MIN_WITHDRAWAL = 2000000  # Minimum balance for withdrawal (2M Toman)

app = FastAPI()

# Database connection management
@contextmanager
def get_db_connection():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                invites INTEGER DEFAULT 0,
                spins INTEGER DEFAULT 2,  -- Two free spins initially
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

# Initialize database
init_db()

# --------------------------- Keyboards ---------------------------

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
        [InlineKeyboardButton("💸 برداشت وجه", callback_data="withdraw")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
    ]
    return InlineKeyboardMarkup(keyboard)

# --------------------------- Helper Functions ---------------------------

def generate_invite_code(user_id: int) -> str:
    return hashlib.md5(f"{user_id}{time.time()}".encode()).hexdigest()[:8]

def get_or_create_user(user_id: int) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
        if not cursor.fetchone():
            invite_code = generate_invite_code(user_id)
            cursor.execute(
                "INSERT INTO users (user_id, spins, last_action) VALUES (%s, %s, %s)",
                (user_id, 2, time.time())
            )
            conn.commit()

def update_balance(user_id: int, amount: int) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET balance = balance + %s, total_earnings = total_earnings + %s, last_action = %s WHERE user_id = %s",
            (amount, amount if amount > 0 else 0, time.time(), user_id)
        )
        conn.commit()

def update_spins(user_id: int, spins: int) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET spins = spins + %s, last_action = %s WHERE user_id = %s",
            (spins, time.time(), user_id)
        )
        conn.commit()

def get_balance_and_spins(user_id: int) -> tuple:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance, spins FROM users WHERE user_id=%s", (user_id,))
        result = cursor.fetchone()
        return result if result else (0, 2)

def get_user_data(user_id: int) -> tuple:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT balance, invites, total_earnings, card_number FROM users WHERE user_id=%s", (user_id,))
        return cursor.fetchone()

def save_card_number(user_id: int, card_number: str) -> None:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET card_number = %s, last_action = %s WHERE user_id = %s",
            (card_number, time.time(), user_id)
        )
        conn.commit()

@retry(stop=stop_after_attempt(3), wait=wait_fixed(2))
async def check_channel_membership(user_id: int, context: ContextTypes) -> bool:
    try:
        member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        is_member = member.status in ['member', 'administrator', 'creator']
        logger.info(f"Membership check for user {user_id}: {'Member' if is_member else 'Not a member'}")
        return is_member
    except TelegramError as e:
        logger.error(f"Telegram API error checking membership for user {user_id}: {str(e)}")
        if STRICT_MEMBERSHIP:
            raise
        return False
    except Exception as e:
        logger.error(f"Unexpected error checking membership for user {user_id}: {str(e)}")
        if STRICT_MEMBERSHIP:
            raise
        return False

# --------------------------- Admin Commands ---------------------------

async def backup_db(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.", reply_markup=chat_menu())
        return

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users")
        users = cursor.fetchall()
        cursor.execute("SELECT * FROM top_winners")
        top_winners = cursor.fetchall()

    backup_data = {"users": users, "top_winners": top_winners}
    with open(f"backup_{int(time.time())}.json", "w") as f:
        json.dump(backup_data, f, ensure_ascii=False)
    
    await update.message.reply_text("✅ بکاپ دیتابیس با موفقیت ایجاد شد.", reply_markup=chat_menu())

async def clear_db(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.", reply_markup=chat_menu())
        return

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users")
        cursor.execute("DELETE FROM top_winners")
        conn.commit()
    
    await update.message.reply_text("✅ دیتابیس با موفقیت پاک شد.", reply_markup=chat_menu())

async def stats(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("❌ شما اجازه انجام این عملیات را ندارید.", reply_markup=chat_menu())
        return

    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(invites) FROM users")
        total_invites = cursor.fetchone()[0] or 0
    
    await update.message.reply_text(
        f"📊 آمار ربات:\n\n"
        f"👥 تعداد کل کاربران: {total_users}\n"
        f"📢 تعداد کل دعوت‌ها: {total_invites}",
        reply_markup=chat_menu()
    )

# --------------------------- Handlers ---------------------------

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
        logger.error(f"Membership check error for user {user.id}: {str(e)}")
        await update.message.reply_text(
            "⚠️ خطایی در بررسی عضویت رخ داد. لطفاً دوباره امتحان کنید یا با پشتیبانی تماس بگیرید.",
            reply_markup=back_button()
        )
        return

    if context.args:
        ref_code = context.args[0]
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE invite_code=%s", (ref_code,))
            referrer = cursor.fetchone()
            if referrer and referrer[0] != user.id:
                update_spins(referrer[0], INVITE_REWARD)
                cursor.execute("UPDATE users SET invites = invites + 1 WHERE user_id=%s", (referrer[0],))
                conn.commit()

    await update.message.reply_text(
        "🎉 خوش آمدی به گردونه شانس!\n\n"
        "دو چرخش رایگان داری! با هر دعوت موفق، یک چرخش دیگه بگیر!",
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
        logger.error(f"Membership check error in menu for user {user_id}: {str(e)}")
        await update.message.reply_text(
            "⚠️ خطایی در بررسی عضویت رخ داد. لطفاً دوباره امتحان کنید یا با پشتیبانی تماس بگیرید.",
            reply_markup=back_button()
        )
        return

    await update.message.reply_text("منوی اصلی:", reply_markup=chat_menu())

async def spin_wheel(user_id: int, context: ContextTypes) -> tuple:
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
            (user_id, context.user_data.get('username', 'Unknown'), amount, time.time(), amount, time.time())
        )
        conn.commit()
    
    await context.bot.send_message(ADMIN_ID, f"🎡 کاربر {user_id} گردونه را چرخاند و برنده شد: {amount} تومان")
    return amount, f"🎉 شما برنده {amount} تومان شدید!"

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
        logger.error(f"Membership check error in callback for user {user_id}: {str(e)}")
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
            balance, spins = get_balance_and_spins(user_id)
            if balance >= MIN_WITHDRAWAL:
                await query.edit_message_text(
                    f"💰 موجودی شما: {balance} تومان\n"
                    f"🎡 تعداد چرخش‌ها: {spins}",
                    reply_markup=withdrawal_menu()
                )
            else:
                await query.edit_message_text(
                    f"💰 موجودی شما: {balance} تومان\n"
                    f"🎡 تعداد چرخش‌ها: {spins}\n\n"
                    f"برای برداشت وجه، موجودی باید حداقل {MIN_WITHDRAWAL} تومان باشد.",
                    reply_markup=back_button()
                )

        elif query.data == "withdraw":
            balance, _ = get_balance_and_spins(user_id)
            if balance < MIN_WITHDRAWAL:
                await query.edit_message_text(
                    f"❌ موجودی شما برای برداشت کافی نیست. حداقل موجودی: {MIN_WITHDRAWAL} تومان",
                    reply_markup=back_button()
                )
                return
            user_data = get_user_data(user_id)
            card_number = user_data[3]
            if card_number:
                await query.edit_message_text(
                    f"💸 شماره کارت ثبت‌شده: {card_number}\n"
                    "لطفاً برای هماهنگی برداشت با پشتیبانی (@daniaam) تماس بگیرید.",
                    reply_markup=back_button()
                )
            else:
                await query.edit_message_text(
                    "💸 لطفاً شماره کارت خود را برای برداشت وارد کنید:",
                    reply_markup=back_button()
                )
                context.user_data["waiting_for_card_number"] = True

        elif query.data == "spin":
            balance, spins = get_balance_and_spins(user_id)
            if spins <= 0:
                await query.edit_message_text(
                    "❌ شما چرخش رایگان ندارید. با دعوت دوستان چرخش جدید بگیرید!",
                    reply_markup=back_button()
                )
                return

            amount, prize_msg = await spin_wheel(user_id, context)
            await query.edit_message_text(
                f"🎡 گردونه در حال چرخش...\n\n{prize_msg}",
                reply_markup=back_button()
            )

        elif query.data == "top":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id, username, total_earnings FROM top_winners ORDER BY total_earnings DESC LIMIT 10")
                rows = cursor.fetchall()
            msg = "🏆 پر درآمد ها:\n\n"
            for i, row in enumerate(rows, 1):
                msg += f"{i}. @{row[1] or 'Unknown'} - درآمد: {row[2]} تومان\n"
            if not rows:
                msg = "هنوز برنده‌ای ثبت نشده است."
            await query.edit_message_text(msg, reply_markup=back_button())

        elif query.data == "profile":
            user_data = get_user_data(user_id)
            balance, invites, total_earnings, _ = user_data
            await query.edit_message_text(
                f"👤 پروفایل شما:\n\n"
                f"💰 موجودی: {balance} تومان\n"
                f"👥 دعوت موفق: {invites} نفر\n"
                f"💸 درآمد کل: {total_earnings} تومان",
                reply_markup=back_button()
            )

        elif query.data == "invite":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT invite_code FROM users WHERE user_id=%s", (user_id,))
                invite_code = cursor.fetchone()[0]
            invite_link = f"https://t.me/charkhoon_bot?start={invite_code}"
            await query.edit_message_text(
                f"📢 لینک دعوت شما:\n{invite_link}\n\n"
                "با هر دعوت موفق، یک چرخش رایگان بگیر!",
                reply_markup=back_button()
            )

    except Exception as e:
        logger.error(f"Callback handler error for user {user_id}: {str(e)}")
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
        logger.error(f"Membership check error in message handler for user {user_id}: {str(e)}")
        await update.message.reply_text(
            "⚠️ خطایی در بررسی عضویت رخ داد. لطفاً دوباره امتحان کنید یا با پشتیبانی تماس بگیرید.",
            reply_markup=chat_menu()
        )
        return

    try:
        if text == "🎯 چرخوندن گردونه":
            balance, spins = get_balance_and_spins(user_id)
            if spins <= 0:
                await update.message.reply_text(
                    "❌ شما چرخش رایگان ندارید. با دعوت دوستان چرخش جدید بگیرید!",
                    reply_markup=chat_menu()
                )
                return

            amount, prize_msg = await spin_wheel(user_id, context)
            await update.message.reply_text(
                f"🎡 گردونه در حال چرخش...\n\n{prize_msg}",
                reply_markup=chat_menu()
            )

        elif text == "💰 موجودی":
            balance, spins = get_balance_and_spins(user_id)
            if balance >= MIN_WITHDRAWAL:
                await update.message.reply_text(
                    f"💰 موجودی شما: {balance} تومان\n"
                    f"🎡 تعداد چرخش‌ها: {spins}",
                    reply_markup=withdrawal_menu()
                )
            else:
                await update.message.reply_text(
                    f"💰 موجودی شما: {balance} تومان\n"
                    f"🎡 تعداد چرخش‌ها: {spins}\n\n"
                    f"برای برداشت وجه، موجودی باید حداقل {MIN_WITHDRAWAL} تومان باشد.",
                    reply_markup=back_button()
                )

        elif text == "🏆 پر درآمد ها":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT user_id, username, total_earnings FROM top_winners ORDER BY total_earnings DESC LIMIT 10")
                rows = cursor.fetchall()
            msg = "🏆 پر درآمد ها:\n\n"
            for i, row in enumerate(rows, 1):
                msg += f"{i}. @{row[1] or 'Unknown'} - درآمد: {row[2]} تومان\n"
            if not rows:
                msg = "هنوز برنده‌ای ثبت نشده است."
            await update.message.reply_text(msg, reply_markup=chat_menu())

        elif text == "👤 پروفایل":
            user_data = get_user_data(user_id)
            balance, invites, total_earnings, _ = user_data
            await update.message.reply_text(
                f"👤 پروفایل شما:\n\n"
                f"💰 موجودی: {balance} تومان\n"
                f"👥 دعوت موفق: {invites} نفر\n"
                f"💸 درآمد کل: {total_earnings} تومان",
                reply_markup=chat_menu()
            )

        elif text == "📢 دعوت دوستان":
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT invite_code FROM users WHERE user_id=%s", (user_id,))
                invite_code = cursor.fetchone()[0]
            invite_link = f"https://t.me/charkhoon_bot?start={invite_code}"
            await update.message.reply_text(
                f"📢 لینک دعوت شما:\n{invite_link}\n\n"
                "با هر دعوت موفق، یک چرخش رایگان بگیر!",
                reply_markup=chat_menu()
            )

        elif context.user_data.get("waiting_for_card_number"):
            context.user_data["waiting_for_card_number"] = False
            card_number = text.strip()
            if not card_number.isdigit() or len(card_number) != 16:
                await update.message.reply_text(
                    "❌ شماره کارت نامعتبر است. لطفاً یک شماره کارت 16 رقمی معتبر وارد کنید.",
                    reply_markup=chat_menu()
                )
                return
            save_card_number(user_id, card_number)
            await update.message.reply_text(
                f"✅ شماره کارت {card_number} ثبت شد. لطفاً برای هماهنگی برداشت با پشتیبانی (@daniaam) تماس بگیرید.",
                reply_markup=chat_menu()
            )

    except Exception as e:
        logger.error(f"Message handler error for user {user_id}: {str(e)}")
        await update.message.reply_text(
            f"❌ خطایی رخ داد: {str(e)}\nلطفاً دوباره امتحان کنید.",
            reply_markup=chat_menu()
        )

# --------------------------- Register Handlers and Bot Menu ---------------------------

application = ApplicationBuilder().token(TOKEN).build()

# Set bot menu commands
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

# --------------------------- FastAPI Webhook ---------------------------

@app.on_event("startup")
async def on_startup():
    try:
        await application.bot.delete_webhook()
        await application.bot.set_webhook(WEBHOOK_URL)
        await set_menu_commands(application)  # Set bot menu
        await application.initialize()
        await application.start()
        logger.info("Bot started successfully and webhook set")
    except Exception as e:
        logger.error(f"Startup error: {str(e)}")
        raise

@app.on_event("shutdown")
async def on_shutdown():
    try:
        await application.stop()
        await application.shutdown()
        logger.info("Bot stopped successfully")
    except Exception as e:
        logger.error(f"Shutdown error: {str(e)}")

@app.post("/")
async def webhook(req: Request):
    try:
        data = await req.body()
        update = Update.de_json(json.loads(data), application.bot)
        await application.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return {"ok": False}
