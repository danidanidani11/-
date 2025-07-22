import asyncio
import random
import sqlite3
from fastapi import FastAPI, Request
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    Update
)
from telegram.ext import (
    ApplicationBuilder, CallbackQueryHandler, CommandHandler,
    MessageHandler, ContextTypes, filters
)

# تنظیمات اولیه
TOKEN = "8078210260:AAEX-vz_apP68a6WhzaGhuAKK7amC1qUiEY"
ADMIN_ID = 5542927340
CHANNEL_ID = "@charkhoun"
TRON_ADDRESS = "TJ4xrwKJzKjk6FgKfuuqwah3Az5Ur22kJb"

SPIN_COST = 50000
HIDDEN_STAGE_COST = 5000
HIDDEN_STAGE_PRIZE = 50000
INVITE_REWARD = 2000

# اتصال به دیتابیس
conn = sqlite3.connect("db.sqlite3", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    spins INTEGER DEFAULT 0,
    invites INTEGER DEFAULT 0,
    hidden_code TEXT,
    invited_by INTEGER
)
""")
conn.commit()

# تعریف FastAPI و Application تلگرام
app = FastAPI()
application = ApplicationBuilder().token(TOKEN).build()

# ------------------ دکمه‌ها ------------------ #
def get_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎰 چرخوندن گردونه", callback_data="spin")],
        [InlineKeyboardButton("💰 موجودی", callback_data="balance")],
        [InlineKeyboardButton("🎯 مرحله پنهان", callback_data="hidden_stage")],
        [InlineKeyboardButton("🏆 خوش‌شانس‌ترین‌ها", callback_data="top")],
        [InlineKeyboardButton("👤 پروفایل", callback_data="profile")],
        [InlineKeyboardButton("🤝 دعوت دوستان", callback_data="invite")]
    ])

def get_back_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]
    ])

def get_balance_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ افزایش موجودی", callback_data="increase_balance")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_menu")]
    ])

# ------------------ هندلرها ------------------ #
@application.on_callback_query()
async def handle_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if query.data == "back_to_menu":
        await query.edit_message_text("به منوی اصلی خوش آمدید!", reply_markup=get_main_menu())

    elif query.data == "balance":
        balance = get_balance(user_id)
        await query.edit_message_text(
            f"💰 موجودی شما: {balance} تومان",
            reply_markup=get_balance_keyboard()
        )

    elif query.data == "increase_balance":
        await query.edit_message_text(
            f"برای افزایش موجودی، مبلغ موردنظر را به آدرس زیر واریز کنید:\n\n"
            f"💸 آدرس TRON:\n`{TRON_ADDRESS}`\n\n"
            f"سپس رسید را ارسال کنید تا بررسی شود.",
            parse_mode="Markdown",
            reply_markup=get_back_menu()
        )

    elif query.data == "spin":
        balance = get_balance(user_id)
        if balance < SPIN_COST:
            await query.edit_message_text(
                f"💰 موجودی شما کافی نیست!\n\nهزینه هر چرخش: {SPIN_COST} تومان\nموجودی شما: {balance} تومان",
                reply_markup=get_balance_keyboard()
            )
            return

        result = spin_wheel()
        update_balance(user_id, -SPIN_COST)
        msg = f"🎰 نتیجه چرخش شما: {result}"

        if result == "🎯 مرحله پنهان رایگان":
            set_hidden_code(user_id)
            msg += "\n\nشما وارد مرحله پنهان شدید!"
        elif result == "🏆 ۲۰۰۰۰ تومان":
            update_balance(user_id, 20000)
        elif result == "💰 ۵۰۰۰۰ تومان":
            update_balance(user_id, 50000)
        elif result == "💎 ۱۰۰۰۰۰ تومان":
            update_balance(user_id, 100000)

        await query.edit_message_text(msg, reply_markup=get_back_menu())
        await notify_admin(f"🎡 کاربر {user_id} گردونه را چرخاند و نتیجه: {result}")

    elif query.data == "hidden_stage":
        code = get_hidden_code(user_id)
        if not code:
            balance = get_balance(user_id)
            if balance < HIDDEN_STAGE_COST:
                await query.edit_message_text(
                    f"💰 برای ورود به مرحله پنهان باید {HIDDEN_STAGE_COST} تومان پرداخت کنید.",
                    reply_markup=get_balance_keyboard()
                )
                return
            update_balance(user_id, -HIDDEN_STAGE_COST)
            set_hidden_code(user_id)
            await query.edit_message_text("🎯 وارد مرحله پنهان شدید!\n\nیک عدد بین ۱ تا ۲۰۰ حدس بزنید:", reply_markup=get_back_menu())
        else:
            await query.edit_message_text("🎯 شما در مرحله پنهان هستید!\nیک عدد بین ۱ تا ۲۰۰ حدس بزنید:", reply_markup=get_back_menu())

        context.user_data["waiting_for_guess"] = True

    elif query.data == "top":
        cursor.execute("SELECT user_id, spins FROM users ORDER BY spins DESC LIMIT 10")
        top = cursor.fetchall()
        text = "🏆 خوش‌شانس‌ترین‌های ماه:\n\n"
        for i, (uid, sp) in enumerate(top, 1):
            text += f"{i}. {uid} - {sp} چرخش\n"
        await query.edit_message_text(text, reply_markup=get_back_menu())

    elif query.data == "profile":
        cursor.execute("SELECT balance, spins, invites FROM users WHERE user_id=?", (user_id,))
        row = cursor.fetchone()
        if row:
            balance, spins, invites = row
        else:
            balance, spins, invites = 0, 0, 0
        text = f"👤 پروفایل شما:\n\n💰 موجودی: {balance} تومان\n🎰 چرخش‌ها: {spins}\n🤝 دعوت‌ها: {invites}"
        await query.edit_message_text(text, reply_markup=get_back_menu())

    elif query.data == "invite":
        link = f"https://t.me/charkhoon_bot?start={user_id}"
        await query.edit_message_text(
            f"لینک دعوت اختصاصی شما:\n{link}\n\nبا دعوت دوستان ۲۰۰۰ تومان دریافت کنید!",
            reply_markup=get_back_menu()
        )

@application.on_message(filters.TEXT & (~filters.COMMAND))
async def process_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if context.user_data.get("waiting_for_guess"):
        context.user_data["waiting_for_guess"] = False
        code = get_hidden_code(user_id)
        if not code:
            await update.message.reply_text("❌ مرحله پنهان فعال نیست.")
            return
        try:
            guess = int(text)
            if guess == int(code):
                update_balance(user_id, HIDDEN_STAGE_PRIZE)
                await update.message.reply_text(
                    f"🎉 تبریک! شما برنده {HIDDEN_STAGE_PRIZE} تومان شدید.",
                    reply_markup=get_main_menu()
                )
                clear_hidden_code(user_id)
            else:
                await update.message.reply_text(
                    "❌ حدس اشتباه بود.\nبرای ورود مجدد باید گردونه بچرخونید یا مبلغ پرداخت کنید.",
                    reply_markup=get_main_menu()
                )
                clear_hidden_code(user_id)
        except:
            await update.message.reply_text("عدد نامعتبر.")

@application.on_message(filters.COMMAND)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    invited_by = int(args[0]) if args else None

    if not user_exists(user_id):
        add_user(user_id, invited_by)
        if invited_by and invited_by != user_id:
            update_balance(invited_by, INVITE_REWARD)
            increment_invites(invited_by)
            await notify_admin(f"🎁 کاربر {user_id} توسط {invited_by} دعوت شد.")

    await update.message.reply_text("🎉 به گردونه شانس خوش آمدید!", reply_markup=get_main_menu())

# ------------------ ابزار ------------------ #
def user_exists(user_id):
    cursor.execute("SELECT 1 FROM users WHERE user_id=?", (user_id,))
    return cursor.fetchone() is not None

def add_user(user_id, invited_by):
    cursor.execute("INSERT INTO users (user_id, invited_by) VALUES (?, ?)", (user_id, invited_by))
    conn.commit()

def get_balance(user_id):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else 0

def update_balance(user_id, amount):
    cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    cursor.execute("UPDATE users SET balance = balance + ?, spins = spins + ? WHERE user_id=?", (amount, 1 if amount == -SPIN_COST else 0, user_id))
    conn.commit()

def increment_invites(user_id):
    cursor.execute("UPDATE users SET invites = invites + 1 WHERE user_id=?", (user_id,))
    conn.commit()

def spin_wheel():
    choices = [
        "🎯 مرحله پنهان رایگان",  # 20.9%
        "🏆 ۲۰۰۰۰ تومان",          # 30%
        "💰 ۵۰۰۰۰ تومان",          # 20%
        "💎 ۱۰۰۰۰۰ تومان",         # 10%
        "❌ هیچی نبردی!"           # 19.1%
    ]
    weights = [20.9, 30, 20, 10, 19.1]
    return random.choices(choices, weights=weights)[0]

def set_hidden_code(user_id):
    code = str(random.randint(1, 200))
    cursor.execute("UPDATE users SET hidden_code=? WHERE user_id=?", (code, user_id))
    conn.commit()

def get_hidden_code(user_id):
    cursor.execute("SELECT hidden_code FROM users WHERE user_id=?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row and row[0] else None

def clear_hidden_code(user_id):
    cursor.execute("UPDATE users SET hidden_code=NULL WHERE user_id=?", (user_id,))
    conn.commit()

async def notify_admin(text):
    try:
        await application.bot.send_message(chat_id=ADMIN_ID, text=text)
    except:
        pass

# ------------------ FastAPI Webhook ------------------ #
WEBHOOK_URL = "https://0kik4x8alj.onrender.com"

@app.on_event("startup")
async def startup():
    await application.bot.delete_webhook()
    await application.bot.set_webhook(url=WEBHOOK_URL)
    await application.initialize()
    await application.start()

@app.on_event("shutdown")
async def shutdown():
    await application.stop()
    await application.shutdown()
    conn.close()

@app.post("/")
async def telegram_webhook(req: Request):
    data = await req.body()
    update = Update.de_json(data.decode("utf-8"), application.bot)
    await application.process_update(update)
    return {"ok": True}
