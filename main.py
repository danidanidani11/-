import os
import sqlite3
from fastapi import FastAPI, Request
import json
from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update
)
from telegram.ext import (
    ApplicationBuilder, CallbackContext, ContextTypes,
    CommandHandler, CallbackQueryHandler, MessageHandler, filters
)

TOKEN = "8078210260:AAEX-vz_apP68a6WhzaGhuAKK7amC1qUiEY"
ADMIN_ID = 5542927340
CHANNEL_ID = "@charkhoun"
TRON_ADDRESS = "TJ4xrwKJzKjk6FgKfuuqwah3Az5Ur22kJb"

SPIN_COST = 50000
SECRET_COST = 5000
INVITE_REWARD = 2000
SECRET_REWARD = 50000

WEBHOOK_URL = "https://0kik4x8alj.onrender.com"

app = FastAPI()
application = ApplicationBuilder().token(TOKEN).build()
conn = sqlite3.connect("users.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    invites INTEGER DEFAULT 0,
    invite_code TEXT,
    secret_access INTEGER DEFAULT 0
)
''')
conn.commit()

# --------------------------- Keyboards ---------------------------

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

def back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="back")]])

# --------------------------- Utils ---------------------------

def get_or_create_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (user_id) VALUES (?)", (user_id,))
        conn.commit()

def update_balance(user_id, amount):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()

def get_balance(user_id):
    cursor.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
    return cursor.fetchone()[0]

# --------------------------- Handlers ---------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id)

    if context.args:
        ref_code = context.args[0]
        if ref_code.isdigit() and int(ref_code) != user.id:
            cursor.execute("SELECT * FROM users WHERE user_id=?", (int(ref_code),))
            if cursor.fetchone():
                update_balance(int(ref_code), INVITE_REWARD)
                cursor.execute("UPDATE users SET invites = invites + 1 WHERE user_id=?", (int(ref_code),))
                conn.commit()

    await update.message.reply_text(
        "🎉 خوش آمدی به گردونه شانس!\n\nبا چرخوندن گردونه شانس بگیر و در مرحله پنهان جایزه ببر!",
        reply_markup=main_menu()
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    get_or_create_user(user_id)

    if query.data == "back":
        await query.edit_message_text("منوی اصلی:", reply_markup=main_menu())

    elif query.data == "balance":
        balance = get_balance(user_id)
        await query.edit_message_text(f"💰 موجودی شما: {balance} تومان", reply_markup=back_button())

    elif query.data == "spin":
        balance = get_balance(user_id)
        if balance < SPIN_COST:
            await query.edit_message_text("❌ موجودی شما کافی نیست.", reply_markup=back_button())
            return

        import random
        update_balance(user_id, -SPIN_COST)

        chance = random.randint(1, 1000)
        if chance <= 209:  # 20.9%
            cursor.execute("UPDATE users SET secret_access = 1 WHERE user_id=?", (user_id,))
            conn.commit()
            result = "🎁 برنده مرحله پنهان شدی!"
        else:
            result = "😢 متاسفانه برنده نشدی!"

        await query.edit_message_text(f"{result}", reply_markup=back_button())
        await context.bot.send_message(ADMIN_ID, f"🎡 چرخش جدید توسط {user_id}\nنتیجه: {result}")

    elif query.data == "secret":
        cursor.execute("SELECT secret_access FROM users WHERE user_id=?", (user_id,))
        access = cursor.fetchone()[0]
        if access:
            import random
            number = random.randint(1, 300)
            context.user_data["secret_number"] = number
            await query.edit_message_text(
                "🔐 مرحله پنهان!\n\nیک عدد بین ۱ تا ۳۰۰ حدس بزن (فقط یک شانس داری):",
                reply_markup=back_button()
            )
            context.user_data["waiting_for_secret_guess"] = True
        else:
            balance = get_balance(user_id)
            if balance < SECRET_COST:
                await query.edit_message_text("❌ برای ورود نیاز به پرداخت ۵۰۰۰ تومان است و موجودی کافی نیست.", reply_markup=back_button())
            else:
                update_balance(user_id, -SECRET_COST)
                import random
                number = random.randint(1, 300)
                context.user_data["secret_number"] = number
                context.user_data["waiting_for_secret_guess"] = True
                await query.edit_message_text(
                    "🎲 یک عدد بین ۱ تا ۳۰۰ حدس بزن (فقط یک شانس داری):",
                    reply_markup=back_button()
                )

    elif query.data == "top":
        cursor.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10")
        rows = cursor.fetchall()
        msg = "🏆 خوش‌شانس‌ترین‌ها:\n\n"
        for i, row in enumerate(rows, 1):
            msg += f"{i}. {row[0]} - {row[1]} تومان\n"
        await query.edit_message_text(msg, reply_markup=back_button())

    elif query.data == "profile":
        cursor.execute("SELECT balance, invites FROM users WHERE user_id=?", (user_id,))
        balance, invites = cursor.fetchone()
        await query.edit_message_text(
            f"👤 پروفایل شما:\n\nموجودی: {balance} تومان\nدعوت موفق: {invites} نفر",
            reply_markup=back_button()
        )

    elif query.data == "invite":
        invite_link = f"https://t.me/charkhoon_bot?start={user_id}"
        await query.edit_message_text(
            f"📢 لینک دعوت شما:\n{invite_link}\n\nبا دعوت دوستان، ۲۰۰۰ تومان هدیه بگیر!",
            reply_markup=back_button()
        )

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if context.user_data.get("waiting_for_secret_guess"):
        context.user_data["waiting_for_secret_guess"] = False
        try:
            guess = int(text)
            number = context.user_data.get("secret_number")
            if guess == number:
                update_balance(user_id, SECRET_REWARD)
                await update.message.reply_text(f"🎉 درست گفتی! جایزه {SECRET_REWARD} تومان به موجودیت اضافه شد.")
            else:
                await update.message.reply_text(f"❌ عدد درست {number} بود. شانست رو امتحان کن دوباره!")
        except:
            await update.message.reply_text("لطفاً فقط یک عدد بفرست.")

# --------------------------- Register Handlers ---------------------------

application.add_handler(CommandHandler("start", start))
application.add_handler(CallbackQueryHandler(callback_handler))
application.add_handler(MessageHandler(filters.TEXT, handle_messages))

# --------------------------- FastAPI Webhook ---------------------------

@app.on_event("startup")
async def on_startup():
    await application.bot.delete_webhook()
    await application.bot.set_webhook(WEBHOOK_URL)
    await application.initialize()
    await application.start()

@app.on_event("shutdown")
async def on_shutdown():
    await application.stop()
    await application.shutdown()
    conn.close()

@app.post("/")
async def webhook(req: Request):
    data = await req.body()
    update = Update.de_json(data.decode(), application.bot)
    await application.process_update(update)
    return {"ok": True}
