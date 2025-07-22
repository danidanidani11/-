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

SPIN_COST = 50  # Changed to 50 tomans for testing
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
    secret_access INTEGER DEFAULT 0,
    prizes TEXT DEFAULT ''
)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS top_winners (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    prize TEXT
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
        [InlineKeyboardButton("📢 دعوت دوستان", callback_data="invite")],
        [InlineKeyboardButton("📌 منو", callback_data="menu")]
    ]
    return InlineKeyboardMarkup(keyboard)

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

def add_prize(user_id, prize):
    cursor.execute("UPDATE users SET prizes = prizes || ? WHERE user_id = ?", (f"{prize},", user_id))
    conn.commit()

def check_channel_membership(user_id, context):
    try:
        member = context.bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

# --------------------------- Handlers ---------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id)

    if not check_channel_membership(user.id, context):
        await update.message.reply_text(
            f"⚠️ لطفا ابتدا در کانال ما عضو شوید:\n{CHANNEL_ID}\nسپس /start را دوباره بزنید."
        )
        return

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

async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("منوی اصلی:", reply_markup=main_menu())

async def spin_wheel(user_id, context):
    import random
    result = random.choices(
        ["پوچ", "100 هزار تومان", "پریمیوم ۳ ماهه تلگرام", "۱۰ میلیون تومان", "کتاب رایگان", "کد ورود به مرحله پنهان"],
        weights=[70, 3, 0.1, 0.01, 5, 21.89],
        k=1
    )[0]
    
    prize_msg = ""
    if result == "پوچ":
        prize_msg = "متاسفانه این بار برنده نشدی! 🎡"
    elif result == "100 هزار تومان":
        update_balance(user_id, 100000)
        prize_msg = "🎉 برنده 100 هزار تومان شدی! موجودی شما افزایش یافت."
        add_prize(user_id, "100 هزار تومان")
    elif result == "پریمیوم ۳ ماهه تلگرام":
        prize_msg = "🎁 برنده اشتراک پریمیوم ۳ ماهه تلگرام شدی! لطفا با ادمین تماس بگیرید."
        add_prize(user_id, "پریمیوم ۳ ماهه تلگرام")
    elif result == "۱۰ میلیون تومان":
        prize_msg = "🏆 برنده ۱۰ میلیون تومان شدی! لطفا با ادمین تماس بگیرید."
        add_prize(user_id, "۱۰ میلیون تومان")
    elif result == "کتاب رایگان":
        prize_msg = "📚 برنده کتاب رایگان شدی! لطفا با ادمین تماس بگیرید."
        add_prize(user_id, "کتاب رایگان")
    elif result == "کد ورود به مرحله پنهان":
        cursor.execute("UPDATE users SET secret_access = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        prize_msg = "🔓 برنده کد ورود به مرحله پنهان شدی! حالا میتونی در بازی شرکت کنی."
        add_prize(user_id, "کد ورود به مرحله پنهان")
    
    await context.bot.send_message(ADMIN_ID, f"🎡 کاربر {user_id} گردونه را چرخاند و برنده شد: {result}")
    return prize_msg

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    get_or_create_user(user_id)

    if not check_channel_membership(user_id, context):
        await query.edit_message_text(
            f"⚠️ لطفا ابتدا در کانال ما عضو شوید:\n{CHANNEL_ID}\nسپس دوباره امتحان کنید.",
            reply_markup=back_button()
        )
        return

    if query.data == "back":
        await query.edit_message_text("منوی اصلی:", reply_markup=main_menu())

    elif query.data == "menu":
        await query.edit_message_text("منوی اصلی:", reply_markup=main_menu())

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
        balance = get_balance(user_id)
        if balance < SPIN_COST:
            keyboard = [
                [InlineKeyboardButton("💰 افزایش موجودی", callback_data="deposit")],
                [InlineKeyboardButton("🔙 بازگشت", callback_data="back")]
            ]
            await query.edit_message_text(
                f"❌ موجودی شما کافی نیست. هزینه چرخش: {SPIN_COST} تومان\nموجودی فعلی: {balance} تومان",
                reply_markup=InlineKeyboardMarkup(keyboard)
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
        cursor.execute("SELECT secret_access FROM users WHERE user_id=?", (user_id,))
        access = cursor.fetchone()[0]
        if not access:
            await query.edit_message_text(
                "❌ شما دسترسی به مرحله پنهان ندارید.\n"
                "یا باید از گردونه کد ورود بگیری یا خریداری کنی.",
                reply_markup=secret_menu()
            )
            return
        
        import random
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
        cursor.execute("UPDATE users SET secret_access = 1 WHERE user_id = ?", (user_id,))
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
        cursor.execute("SELECT user_id, username, prize FROM top_winners ORDER BY prize DESC LIMIT 10")
        rows = cursor.fetchall()
        msg = "🏆 خوش‌شانس‌ترین‌ها:\n\n"
        for i, row in enumerate(rows, 1):
            msg += f"{i}. @{row[1]} - برنده {row[2]}\n"
        if not rows:
            msg = "هنوز برنده ای ثبت نشده است."
        await query.edit_message_text(msg, reply_markup=back_button())

    elif query.data == "profile":
        cursor.execute("SELECT balance, invites, prizes FROM users WHERE user_id=?", (user_id,))
        balance, invites, prizes = cursor.fetchone()
        prizes = prizes[:-1] if prizes else "هیچ جایزه‌ای"
        await query.edit_message_text(
            f"👤 پروفایل شما:\n\n"
            f"💰 موجودی: {balance} تومان\n"
            f"👥 دعوت موفق: {invites} نفر\n"
            f"🎁 جوایز برده شده: {prizes}",
            reply_markup=back_button()
        )

    elif query.data == "invite":
        invite_link = f"https://t.me/charkhoon_bot?start={user_id}"
        await query.edit_message_text(
            f"📢 لینک دعوت شما:\n{invite_link}\n\n"
            "با دعوت هر دوست 2000 تومان جایزه بگیر!",
            reply_markup=back_button()
        )

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if not check_channel_membership(user_id, context):
        await update.message.reply_text(
            f"⚠️ لطفا ابتدا در کانال ما عضو شوید:\n{CHANNEL_ID}\nسپس دوباره امتحان کنید."
        )
        return

    if context.user_data.get("waiting_for_secret_guess"):
        context.user_data["waiting_for_secret_guess"] = False
        try:
            guess = int(text)
            number = context.user_data.get("secret_number")
            if guess == number:
                update_balance(user_id, SECRET_REWARD)
                await update.message.reply_text(
                    f"🎉 درست گفتی! جایزه {SECRET_REWARD} تومان (1 گردونه رایگان) به موجودیت اضافه شد.",
                    reply_markup=back_button()
                )
            else:
                await update.message.reply_text(
                    f"❌ عدد درست {number} بود. شانست رو امتحان کن دوباره!",
                    reply_markup=back_button()
                )
        except:
            await update.message.reply_text("لطفاً فقط یک عدد بفرست.")

    elif context.user_data.get("waiting_for_secret_code"):
        context.user_data["waiting_for_secret_code"] = False
        if text == "SECRET123":  # Example code
            cursor.execute("UPDATE users SET secret_access = 1 WHERE user_id = ?", (user_id,))
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
        amount = context.user_data["deposit_amount"]
        del context.user_data["deposit_amount"]
        
        if update.message.photo:
            # Handle photo receipt
            photo = update.message.photo[-1].file_id
            await context.bot.send_photo(
                ADMIN_ID,
                photo,
                caption=f"📤 درخواست افزایش موجودی\n\nکاربر: {user_id}\nمبلغ: {amount} تومان"
            )
        else:
            # Handle text receipt
            await context.bot.send_message(
                ADMIN_ID,
                f"📤 درخواست افزایش موجودی\n\nکاربر: {user_id}\nمبلغ: {amount} تومان\n\nرسید:\n{text}"
            )
        
        await update.message.reply_text(
            "✅ رسید پرداخت برای بررسی به ادمین ارسال شد. پس از تایید، موجودی شما افزایش می‌یابد.",
            reply_markup=back_button()
        )

async def handle_admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    if update.message.reply_to_message and "درخواست افزایش موجودی" in update.message.reply_to_message.caption:
        try:
            text = update.message.text
            if "تایید" in text:
                user_id = int(text.split("کاربر:")[1].split("\n")[0].strip())
                amount = int(text.split("مبلغ:")[1].split("تومان")[0].strip())
                update_balance(user_id, amount)
                await context.bot.send_message(
                    user_id,
                    f"✅ درخواست افزایش موجودی شما به مبلغ {amount} تومان تایید شد."
                )
            elif "رد" in text:
                user_id = int(text.split("کاربر:")[1].split("\n")[0].strip())
                amount = int(text.split("مبلغ:")[1].split("تومان")[0].strip())
                await context.bot.send_message(
                    user_id,
                    f"❌ درخواست افزایش موجودی شما به مبلغ {amount} تومان رد شد."
                )
        except Exception as e:
            await update.message.reply_text(f"خطا در پردازش: {str(e)}")

# --------------------------- Register Handlers ---------------------------

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("menu", menu))
application.add_handler(CallbackQueryHandler(callback_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
application.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_messages))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_approval))

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
    update = Update.de_json(json.loads(data), application.bot)
    await application.process_update(update)
    return {"ok": True}
