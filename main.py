import logging
import random
import sqlite3
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from fastapi import FastAPI, Request
import uvicorn
import asyncio

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
TOKEN = '8078210260:AAEX-vz_apP68a6WhzaGhuAKK7amC1qUiEY'
CHANNEL_USERNAME = '@charkhoun'
ADMIN_ID = 5542927340
TRON_ADDRESS = 'TJ4xrwKJzKjk6FgKfuuqwah3Az5Ur22kJb'
SPIN_COST = 50000  # Updated to 50,000 Toman
INVITE_REWARD = 2000
HIDDEN_STAGE_COST = 5000
HIDDEN_STAGE_REWARD = 50000

# Database connection
conn = sqlite3.connect('wheel_bot.db', check_same_thread=False)
cursor = conn.cursor()

# Create necessary tables
cursor.executescript('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    balance INTEGER DEFAULT 0,
    invited_by INTEGER DEFAULT 0,
    invites_count INTEGER DEFAULT 0,
    prizes_won TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    type TEXT,
    status TEXT DEFAULT 'pending',
    proof TEXT,
    admin_id INTEGER,
    timestamp TEXT,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS prizes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    prize_type TEXT,
    prize_value TEXT,
    status TEXT DEFAULT 'pending',
    timestamp TEXT,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS hidden_stage_codes (
    code TEXT PRIMARY KEY,
    used INTEGER DEFAULT 0,
    user_id INTEGER
);

CREATE TABLE IF NOT EXISTS top_winners (
    user_id INTEGER,
    username TEXT,
    prize TEXT,
    timestamp TEXT,
    PRIMARY KEY(user_id, prize)
);
''')
conn.commit()

# Define prizes for the wheel
PRIZES = [
    {"name": "پوچ", "probability": 70.0, "value": "0"},
    {"name": "100 هزار تومان", "probability": 3.0, "value": "100000"},
    {"name": "پریمیوم 3 ماهه تلگرام", "probability": 0.1, "value": "premium"},
    {"name": "10 میلیون تومان", "probability": 0.01, "value": "10000000"},
    {"name": "کتاب رایگان", "probability": 5.0, "value": "book"},
    {"name": "کد ورود به مرحله پنهان", "probability": 21.89, "value": "hidden_stage"}
]

# FastAPI app for webhook
app = FastAPI()

# Check channel membership
async def is_user_member(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        return False

# Register user if not exists
def register_user(user_id: int, username: str, first_name: str, last_name: str):
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
            (user_id, username, first_name, last_name)
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Database error in register_user: {e}")

# Main menu
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user

    # Register user
    register_user(user_id, user.username, user.first_name, user.last_name)

    # Check membership
    if not await is_user_member(user_id, context):
        keyboard = [
            [InlineKeyboardButton("عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
            [InlineKeyboardButton("بررسی عضویت", callback_data="check_membership")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        text = f"⚠️ برای استفاده از ربات باید در کانال ما عضو شوید:\n{CHANNEL_USERNAME}"

        if update.callback_query:
            await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
        else:
            await update.message.reply_text(text=text, reply_markup=reply_markup)
        return

    keyboard = [
        [InlineKeyboardButton("چرخوندن گردونه", callback_data="spin_wheel")],
        [InlineKeyboardButton("موجودی", callback_data="balance")],
        [InlineKeyboardButton("مرحله پنهان", callback_data="hidden_stage")],
        [InlineKeyboardButton("خوش شانس‌ترین‌های ماه", callback_data="top_winners")],
        [InlineKeyboardButton("پروفایل", callback_data="profile")],
        [InlineKeyboardButton("دعوت دوستان", callback_data="invite_friends")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = "🏠 منوی اصلی:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup)

# Spin the wheel
async def spin_wheel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    # Register user
    register_user(user_id, query.from_user.username, query.from_user.first_name, query.from_user.last_name)

    # Check membership
    if not await is_user_member(user_id, context):
        await query.answer("❌ لطفاً ابتدا در کانال عضو شوید!", show_alert=True)
        await main_menu(update, context)
        return

    # Check balance
    try:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        balance = result[0] if result else 0

        if balance < SPIN_COST:
            await query.answer()
            await query.edit_message_text(
                text=f"💰 موجودی شما کافی نیست!\n\nهزینه هر چرخش: {SPIN_COST} تومان\nموجودی شما: {balance} تومان",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("افزایش موجودی", callback_data="increase_balance")],
                    [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
                ])
            )
            return

        # Deduct cost
        new_balance = balance - SPIN_COST
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?",
                      (new_balance, user_id))
        conn.commit()

        # Process invites
        cursor.execute("SELECT invited_by FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        invited_by = result[0] if result else 0
        if invited_by:
            cursor.execute("UPDATE users SET balance = balance + ?, invites_count = invites_count + 1 WHERE user_id = ?",
                          (INVITE_REWARD, invited_by))
            conn.commit()
            try:
                await context.bot.send_message(
                    chat_id=invited_by,
                    text=f"🎉 کاربری که دعوت کرده‌اید اولین چرخش خود را انجام داد!\n\n💰 شما {INVITE_REWARD} تومان پاداش گرفتید!"
                )
            except Exception as e:
                logger.error(f"Error sending invite reward message: {e}")
            cursor.execute("UPDATE users SET invited_by = 0 WHERE user_id = ?", (user_id,))
            conn.commit()

        # Spin the wheel
        spin_result = random.choices(
            [prize['value'] for prize in PRIZES],
            weights=[prize['probability'] for prize in PRIZES],
            k=1
        )[0]
        prize_name = next(prize['name'] for prize in PRIZES if prize['value'] == spin_result)

        # Save prize
        cursor.execute(
            "INSERT INTO prizes (user_id, prize_type, prize_value, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, prize_name, spin_result, datetime.now().isoformat())
        )
        cursor.execute(
            "UPDATE users SET prizes_won = prizes_won || ? WHERE user_id = ?",
            (f"{prize_name}, ", user_id)
        )
        conn.commit()

        # Notify admin
        user = query.from_user
        admin_message = (
            f"🎉 کاربر جایزه برده!\n\n"
            f"👤 کاربر: @{user.username}\n"
            f"🆔 آیدی: {user.id}\n"
            f"🏆 جایزه: {prize_name}\n"
            f"⏰ زمان: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await context.bot.send_message(chat_id=ADMIN_ID, text=admin_message)

        # Respond to user
        if spin_result == "hidden_stage":
            hidden_code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=8))
            cursor.execute(
                "INSERT INTO hidden_stage_codes (code, user_id) VALUES (?, ?)",
                (hidden_code, user_id)
            )
            conn.commit()
            await query.edit_message_text(
                text=f"🎉 شما جایزه بردید!\n\n🏆 جایزه شما: {prize_name}\n\n🔑 کد شما: {hidden_code}\n\nاین کد را در بخش 'مرحله پنهان' وارد کنید.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("مرحله پنهان", callback_data="hidden_stage")],
                    [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
                ])
            )
        elif spin_result != "0":
            await query.edit_message_text(
                text=f"🎉 شما جایزه بردید!\n\n🏆 جایزه شما: {prize_name}\n\nلطفاً برای دریافت جایزه با ادمین تماس بگیرید.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
                ])
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"👤 برای دریافت جایزه خود ({prize_name}) لطفاً با ادمین تماس بگیرید: @{CHANNEL_USERNAME[1:]}"
            )
        else:
            await query.edit_message_text(
                text=f"متأسفیم! این بار جایزه‌ای نبردید.\n\nموجودی جدید شما: {new_balance} تومان",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("چرخش مجدد", callback_data="spin_wheel")],
                    [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
                ])
            )
    except sqlite3.Error as e:
        logger.error(f"Database error in spin_wheel: {e}")
        await query.answer("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.", show_alert=True)

# Show balance
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    # Register user
    register_user(user_id, query.from_user.username, query.from_user.first_name, query.from_user.last_name)

    try:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        balance = result[0] if result else 0

        await query.edit_message_text(
            text=f"💰 موجودی شما: {balance} تومان",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("افزایش موجودی", callback_data="increase_balance")],
                [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
            ])
        )
    except sqlite3.Error as e:
        logger.error(f"Database error in show_balance: {e}")
        await query.answer("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.", show_alert=True)

# Increase balance
async def increase_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    keyboard = [
        [
            InlineKeyboardButton("10 هزار تومان", callback_data="deposit_10000"),
            InlineKeyboardButton("30 هزار تومان", callback_data="deposit_30000")
        ],
        [
            InlineKeyboardButton("50 هزار تومان", callback_data="deposit_50000"),
            InlineKeyboardButton("200 هزار تومان", callback_data="deposit_200000")
        ],
        [
            InlineKeyboardButton("500 هزار تومان", callback_data="deposit_500000"),
            InlineKeyboardButton("1 میلیون تومان", callback_data="deposit_1000000")
        ],
        [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text=f"💳 لطفاً مبلغ مورد نظر برای افزایش موجودی را انتخاب کنید:\n\n🔹 آدرس ترون: {TRON_ADDRESS}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Request deposit
async def request_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    amount = int(query.data.split('_')[1])

    context.user_data['deposit_amount'] = amount

    await query.edit_message_text(
        text=f"💰 شما مبلغ {amount} تومان را برای افزایش موجودی انتخاب کردید.\n\nلطفاً تصویر یا متن فیش واریزی خود را ارسال کنید.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("انصراف", callback_data="balance")]
        ])
    )

# Process deposit proof
async def process_deposit_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    amount = context.user_data.get('deposit_amount', 0)

    if amount == 0:
        await update.message.reply_text("خطایی رخ داده است. لطفاً دوباره تلاش کنید.")
        return

    try:
        proof = update.message.text or "تصویر ارسال شده"
        cursor.execute(
            "INSERT INTO transactions (user_id, amount, type, proof, timestamp) VALUES (?, ?, ?, ?, ?)",
            (user_id, amount, "deposit", proof, datetime.now().isoformat())
        )
        conn.commit()

        user = update.message.from_user
        admin_message = (
            f"📥 درخواست افزایش موجودی جدید\n\n"
            f"👤 کاربر: @{user.username}\n"
            f"🆔 آیدی: {user.id}\n"
            f"💰 مبلغ: {amount} تومان\n"
            f"📌 فیش: {proof}\n\n"
            f"لطفاً تایید یا رد کنید:"
        )

        keyboard = [
            [
                InlineKeyboardButton("✅ تایید", callback_data=f"approve_{user_id}_{amount}"),
                InlineKeyboardButton("❌ رد", callback_data=f"reject_{user_id}_{amount}")
            ]
        ]

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

        await update.message.reply_text(
            text="✅ فیش واریزی شما با موفقیت دریافت شد و برای تایید به ادمین ارسال شد.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
            ])
        )
    except sqlite3.Error as e:
        logger.error(f"Database error in process_deposit_proof: {e}")
        await update.message.reply_text("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.")

# Handle admin decision
async def handle_admin_decision(update: Update, context: ContextTypes.GROK):
    query = update.callback_query
    data = query.data.split('_')
    action = data[0]
    user_id = int(data[1])
    amount = int(data[2])

    try:
        cursor.execute(
            "UPDATE transactions SET status = ?, admin_id = ? WHERE user_id = ? AND amount = ? AND status = 'pending'",
            (action, query.from_user.id, user_id, amount)
        )
        conn.commit()

        if action == "approve":
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            current_balance = cursor.fetchone()[0] or 0
            new_balance = current_balance + amount

            cursor.execute(
                "UPDATE users SET balance = ? WHERE user_id = ?",
                (new_balance, user_id)
            )
            conn.commit()

            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ درخواست افزایش موجودی شما به مبلغ {amount} تومان تأیید شد.\n\n💰 موجودی جدید شما: {new_balance} تومان",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("چرخاندن گردونه", callback_data="spin_wheel")],
                    [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
                ])
            )
            await query.answer("درخواست با موفقیت تایید شد و موجودی کاربر افزایش یافت.")
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"❌ متأسفانه درخواست افزایش موجودی شما به مبلغ {amount} تومان رد شد.\n\nلطفاً در صورت نیاز با پشتیبانی تماس بگیرید.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
                ])
            )
            await query.answer("درخواست رد شد.")

        await query.edit_message_text(
            text=query.message.text + f"\n\nوضعیت: {action == 'approve' and 'تایید شد ✅' or 'رد شد ❌'}",
            reply_markup=None
        )
    except sqlite3.Error as e:
        logger.error(f"Database error in handle_admin_decision: {e}")
        await query.answer("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.", show_alert=True)

# Hidden stage menu
async def hidden_stage_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    keyboard = [
        [InlineKeyboardButton("شروع بازی", callback_data="start_hidden_game")],
        [InlineKeyboardButton("خرید مرحله پنهان (5,000 تومان)", callback_data="buy_hidden_stage")],
        [InlineKeyboardButton("وارد کردن کد ورود", callback_data="enter_hidden_code")],
        [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
    ]

    await query.edit_message_text(
        text="🔒 مرحله پنهان:\n\nدر این مرحله باید یک عدد بین 1 تا 200 را حدس بزنید!\n\n💰 هزینه ورود: 5,000 تومان\n🏆 پاداش: 50,000 تومان",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# Start hidden game
async def start_hidden_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    # Register user
    register_user(user_id, query.from_user.username, query.from_user.first_name, query.from_user.last_name)

    try:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        balance = result[0] if result else 0

        if balance < HIDDEN_STAGE_COST:
            await query.answer()
            await query.edit_message_text(
                text=f"💰 موجودی شما کافی نیست!\n\nهزینه بازی: {HIDDEN_STAGE_COST} تومان\nموجودی شما: {balance} تومان",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("افزایش موجودی", callback_data="increase_balance")],
                    [InlineKeyboardButton("بازگشت", callback_data="hidden_stage")]
                ])
            )
            return

        # Deduct cost
        new_balance = balance - HIDDEN_STAGE_COST
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
        conn.commit()

        # Generate random number
        context.user_data['hidden_number'] = random.randint(1, 200)
        context.user_data['waiting_for_guess'] = True

        await query.edit_message_text(
            text=f"💰 هزینه بازی ({HIDDEN_STAGE_COST} تومان) کسر شد.\n\n🔢 یک عدد بین 1 تا 200 وارد کنید:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("انصراف", callback_data="hidden_stage")]
            ])
        )
    except sqlite3.Error as e:
        logger.error(f"Database error in start_hidden_game: {e}")
        await query.answer("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.", show_alert=True)

# Process number guess
async def process_number_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    guess = update.message.text.strip()

    if not context.user_data.get('waiting_for_guess', False):
        await update.message.reply_text(
            text="لطفاً از منوی ربات استفاده کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
            ])
        )
        return

    try:
        guess = int(guess)
        if not 1 <= guess <= 200:
            await update.message.reply_text(
                text="❌ لطفاً یک عدد بین 1 تا 200 وارد کنید.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("دوباره امتحان کنید", callback_data="start_hidden_game")],
                    [InlineKeyboardButton("بازگشت", callback_data="hidden_stage")]
                ])
            )
            return

        hidden_number = context.user_data['hidden_number']
        context.user_data.pop('waiting_for_guess', None)
        context.user_data.pop('hidden_number', None)

        if guess == hidden_number:
            cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
            current_balance = cursor.fetchone()[0] or 0
            new_balance = current_balance + HIDDEN_STAGE_REWARD

            cursor.execute(
                "UPDATE users SET balance = ? WHERE user_id = ?",
                (new_balance, user_id)
            )

            cursor.execute(
                "INSERT INTO prizes (user_id, prize_type, prize_value, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, "پاداش مرحله پنهان", str(HIDDEN_STAGE_REWARD), datetime.now().isoformat())
            )

            user = update.message.from_user
            cursor.execute(
                "INSERT OR REPLACE INTO top_winners (user_id, username, prize, timestamp) VALUES (?, ?, ?, ?)",
                (user_id, user.username, f"پاداش مرحله پنهان: {HIDDEN_STAGE_REWARD} تومان", datetime.now().isoformat())
            )
            conn.commit()

            await update.message.reply_text(
                text=f"🎉 تبریک! شما عدد درست ({hidden_number}) را حدس زدید!\n\n💰 پاداش: {HIDDEN_STAGE_REWARD} تومان\nموجودی جدید: {new_balance} تومان",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("بازی دوباره", callback_data="start_hidden_game")],
                    [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
                ])
            )
        else:
            await update.message.reply_text(
                text=f"❌ متأسفیم! عدد درست {hidden_number} بود.\nدوباره امتحان کنید!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("بازی دوباره", callback_data="start_hidden_game")],
                    [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
                ])
            )
    except ValueError:
        await update.message.reply_text(
            text="❌ لطفاً یک عدد معتبر وارد کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("دوباره امتحان کنید", callback_data="start_hidden_game")],
                [InlineKeyboardButton("بازگشت", callback_data="hidden_stage")]
            ])
        )
    except sqlite3.Error as e:
        logger.error(f"Database error in process_number_guess: {e}")
        await update.message.reply_text("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.")

# Buy hidden stage
async def buy_hidden_stage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    # Register user
    register_user(user_id, query.from_user.username, query.from_user.first_name, query.from_user.last_name)

    try:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        balance = result[0] if result else 0

        if balance < HIDDEN_STAGE_COST:
            await query.answer()
            await query.edit_message_text(
                text=f"💰 موجودی شما کافی نیست!\n\nهزینه خرید مرحله پنهان: {HIDDEN_STAGE_COST} تومان\nموجودی شما: {balance} تومان",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("افزایش موجودی", callback_data="increase_balance")],
                    [InlineKeyboardButton("بازگشت", callback_data="hidden_stage")]
                ])
            )
            return

        new_balance = balance - HIDDEN_STAGE_COST
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))

        hidden_code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=8))
        cursor.execute(
            "INSERT INTO hidden_stage_codes (code, user_id) VALUES (?, ?)",
            (hidden_code, user_id)
        )
        conn.commit()

        await query.edit_message_text(
            text=f"✅ مرحله پنهان با موفقیت خریداری شد!\n\n🔑 کد شما: {hidden_code}\n\n💰 موجودی جدید شما: {new_balance} تومان\n\nلطفاً این کد را در بخش 'وارد کردن کد ورود' وارد کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("وارد کردن کد", callback_data="enter_hidden_code")],
                [InlineKeyboardButton("بازگشت", callback_data="hidden_stage")]
            ])
        )
    except sqlite3.Error as e:
        logger.error(f"Database error in buy_hidden_stage: {e}")
        await query.answer("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.", show_alert=True)

# Enter hidden code
async def enter_hidden_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    context.user_data['waiting_for_code'] = True

    await query.edit_message_text(
        text="🔢 لطفاً کد مرحله پنهان خود را وارد کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("بازگشت", callback_data="hidden_stage")]
        ])
    )

# Process hidden code
async def process_hidden_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    code = update.message.text.upper().strip()

    if not context.user_data.get('waiting_for_code', False):
        await update.message.reply_text(
            text="لطفاً از منوی ربات استفاده کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
            ])
        )
        return

    try:
        cursor.execute(
            "SELECT user_id FROM hidden_stage_codes WHERE code = ? AND used = 0",
            (code,)
        )
        result = cursor.fetchone()

        if result and result[0] == user_id:
            cursor.execute(
                "UPDATE hidden_stage_codes SET used = 1 WHERE code = ?",
                (code,)
            )
            conn.commit()

            await update.message.reply_text(
                text="✅ کد تایید شد!\n\nلطفاً بازی را شروع کنید.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("شروع بازی", callback_data="start_hidden_game")],
                    [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
                ])
            )
            context.user_data.pop('waiting_for_code', None)
        else:
            await update.message.reply_text(
                text="❌ کد وارد شده نامعتبر است یا قبلاً استفاده شده است.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("دوباره امتحان کنید", callback_data="enter_hidden_code")],
                    [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
                ])
            )
    except sqlite3.Error as e:
        logger.error(f"Database error in process_hidden_code: {e}")
        await update.message.reply_text("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.")

# Show top winners
async def show_top_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    try:
        cursor.execute(
            "SELECT username, prize FROM top_winners ORDER BY timestamp DESC LIMIT 10"
        )
        winners = cursor.fetchall()

        text = "🏆 خوش شانس‌ترین‌های ماه:\n\n" if winners else "هنوز برنده‌ای ثبت نشده است."
        for i, (username, prize) in enumerate(winners, 1):
            text += f"{i}. @{username} - {prize}\n"

        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
            ])
        )
    except sqlite3.Error as e:
        logger.error(f"Database error in show_top_winners: {e}")
        await query.answer("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.", show_alert=True)

# Show profile
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    # Register user
    register_user(user_id, query.from_user.username, query.from_user.first_name, query.from_user.last_name)

    try:
        cursor.execute(
            "SELECT balance, invites_count, prizes_won FROM users WHERE user_id = ?",
            (user_id,)
        )
        result = cursor.fetchone()

        balance, invites_count, prizes_won = result if result else (0, 0, "هنوز جایزه‌ای نبرده‌اید")
        prizes_won = prizes_won or "هنوز جایزه‌ای نبرده‌اید"

        text = (
            f"👤 پروفایل شما:\n\n"
            f"💰 موجودی: {balance} تومان\n"
            f"👥 تعداد دعوت شده‌ها: {invites_count} نفر\n"
            f"🎁 جوایز برده شده:\n{prizes_won}"
        )

        await query.edit_message_text(
            text=text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
            ])
        )
    except sqlite3.Error as e:
        logger.error(f"Database error in show_profile: {e}")
        await query.answer("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.", show_alert=True)

# Invite friends
async def invite_friends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    invite_link = f"https://t.me/{context.bot.username}?start=invite_{user_id}"

    text = f"🔗 لینک دعوت شما:\n{invite_link}\n\n💰 پاداش دعوت: {INVITE_REWARD} تومان"

    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
        ])
    )

# Process invite
async def process_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    if args and args[0].startswith('invite_'):
        inviter_id = int(args[0].split('_')[1])

        try:
            cursor.execute("SELECT invited_by FROM users WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()

            if not result or result[0] == 0:
                cursor.execute(
                    "INSERT OR IGNORE INTO users (user_id, invited_by) VALUES (?, ?)",
                    (user_id, inviter_id)
                )
                cursor.execute(
                    "UPDATE users SET invited_by = ? WHERE user_id = ? AND invited_by = 0",
                    (inviter_id, user_id)
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database error in process_invite: {e}")

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name, user.last_name)

    if context.args:
        await process_invite(update, context)

    await main_menu(update, context)

# Show menu command
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await main_menu(update, context)

# Check membership
async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if await is_user_member(user_id, context):
        await query.answer("✅ شما عضو کانال هستید. لطفاً از منوی ربات استفاده کنید.")
        await main_menu(update, context)
    else:
        await query.answer("❌ شما هنوز عضو کانال نشده‌اید!", show_alert=True)

# Process text messages
async def process_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_for_code', False):
        await process_hidden_code(update, context)
    elif context.user_data.get('waiting_for_guess', False):
        await process_number_guess(update, context)
    elif 'deposit_amount' in context.user_data:
        await process_deposit_proof(update, context)
    else:
        await update.message.reply_text(
            text="لطفاً از منوی ربات استفاده کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
            ])
        )

# Webhook handler
@app.post("/webhook")
async def webhook(request: Request):
    update = Update.de_json(await request.json(), application.bot)
    await application.process_update(update)
    return {"status": "ok"}

# Main function
async def main():
    # Create the Application
    application = Application.builder().token(TOKEN).build()

    # Commands
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('menu', show_menu))

    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_text))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, process_deposit_proof))

    # Callback handlers
    application.add_handler(CallbackQueryHandler(main_menu, pattern='^main_menu$'))
    application.add_handler(CallbackQueryHandler(spin_wheel, pattern='^spin_wheel$'))
    application.add_handler(CallbackQueryHandler(show_balance, pattern='^balance$'))
    application.add_handler(CallbackQueryHandler(increase_balance, pattern='^increase_balance$'))
    application.add_handler(CallbackQueryHandler(request_deposit, pattern='^deposit_'))
    application.add_handler(CallbackQueryHandler(handle_admin_decision, pattern='^(approve|reject)_'))
    application.add_handler(CallbackQueryHandler(hidden_stage_menu, pattern='^hidden_stage$'))
    application.add_handler(CallbackQueryHandler(buy_hidden_stage, pattern='^buy_hidden_stage$'))
    application.add_handler(CallbackQueryHandler(enter_hidden_code, pattern='^enter_hidden_code$'))
    application.add_handler(CallbackQueryHandler(start_hidden_game, pattern='^start_hidden_game$'))
    application.add_handler(CallbackQueryHandler(show_top_winners, pattern='^top_winners$'))
    application.add_handler(CallbackQueryHandler(show_profile, pattern='^profile$'))
    application.add_handler(CallbackQueryHandler(invite_friends, pattern='^invite_friends$'))
    application.add_handler(CallbackQueryHandler(check_membership, pattern='^check_membership$'))

    # Set webhook
    WEBHOOK_URL = "https://0kik4x8alj.onrender.com/webhook"  # Replace with your Render URL
    await application.bot.set_webhook(url=WEBHOOK_URL)

    # Initialize and run the application
    await application.initialize()
    await application.start()

    # Start FastAPI server
    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == '__main__':
    # Use the existing event loop
    loop = asyncio.get_event_loop()
    try:
        if loop.is_running():
            loop.create_task(main())
        else:
            loop.run_until_complete(main())
    except RuntimeError as e:
        logger.error(f"Event loop error: {e}")
    finally:
        conn.close()
