import logging
import random
import sqlite3
from datetime import datetime
from telegram import ReplyKeyboardMarkup, KeyboardButton, Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler
)
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
SPIN_COST = 50000  # 50,000 تومان
INVITE_REWARD = 2000
HIDDEN_STAGE_COST = 5000
HIDDEN_STAGE_REWARD = 50000

# Conversation states
GUESSING_NUMBER = 1

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
    prizes_won TEXT DEFAULT '',
    last_spin_time TEXT
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

CREATE TABLE IF NOT EXISTS hidden_stage_guesses (
    user_id INTEGER PRIMARY KEY,
    target_number INTEGER,
    attempts INTEGER DEFAULT 0,
    timestamp TEXT
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

# Keyboard layouts
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["چرخوندن گردونه (50,000 تومان)"],
        ["موجودی", "پروفایل"],
        ["مرحله پنهان", "دعوت دوستان"],
        ["خوش شانس‌ترین‌های ماه"]
    ], resize_keyboard=True)

def get_balance_keyboard():
    return ReplyKeyboardMarkup([
        ["افزایش موجودی"],
        ["بازگشت به منوی اصلی"]
    ], resize_keyboard=True)

def get_deposit_keyboard():
    return ReplyKeyboardMarkup([
        ["10 هزار تومان", "30 هزار تومان"],
        ["50 هزار تومان", "200 هزار تومان"],
        ["500 هزار تومان", "1 میلیون تومان"],
        ["بازگشت به منوی اصلی"]
    ], resize_keyboard=True)

def get_hidden_stage_keyboard():
    return ReplyKeyboardMarkup([
        ["شروع بازی (5,000 تومان)"],
        ["وارد کردن کد ورود"],
        ["بازگشت به منوی اصلی"]
    ], resize_keyboard=True)

def get_back_to_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["بازگشت به منوی اصلی"]
    ], resize_keyboard=True)

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

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username, user.first_name, user.last_name)

    if context.args and context.args[0].startswith('invite_'):
        await process_invite(update, context)

    await main_menu(update, context)

# Main menu
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = update.effective_user

    # Register user
    register_user(user_id, user.username, user.first_name, user.last_name)

    # Check membership
    if not await is_user_member(user_id, context):
        await update.message.reply_text(
            f"⚠️ برای استفاده از ربات باید در کانال ما عضو شوید:\n{CHANNEL_USERNAME}",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("بررسی عضویت")]
            ], resize_keyboard=True)
        )
        return

    await update.message.reply_text(
        "🏠 منوی اصلی:",
        reply_markup=get_main_menu_keyboard()
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

# Spin the wheel
async def spin_wheel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Register user
    register_user(user_id, update.effective_user.username, 
                 update.effective_user.first_name, update.effective_user.last_name)

    # Check membership
    if not await is_user_member(user_id, context):
        await update.message.reply_text(
            "❌ لطفاً ابتدا در کانال عضو شوید!",
            reply_markup=get_main_menu_keyboard()
        )
        return

    # Check balance
    try:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        balance = result[0] if result else 0

        if balance < SPIN_COST:
            await update.message.reply_text(
                f"💰 موجودی شما کافی نیست!\n\nهزینه هر چرخش: {SPIN_COST:,} تومان\nموجودی شما: {balance:,} تومان",
                reply_markup=get_balance_keyboard()
            )
            return

        # Deduct cost
        new_balance = balance - SPIN_COST
        cursor.execute("UPDATE users SET balance = ?, last_spin_time = ? WHERE user_id = ?",
                      (new_balance, datetime.now().isoformat(), user_id))
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
                    text=f"🎉 کاربری که دعوت کرده‌اید اولین چرخش خود را انجام داد!\n\n💰 شما {INVITE_REWARD:,} تومان پاداش گرفتید!"
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
        user = update.effective_user
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
            await update.message.reply_text(
                f"🎉 شما جایزه بردید!\n\n🏆 جایزه شما: {prize_name}\n\n🔑 کد شما: {hidden_code}\n\nاین کد را در بخش 'مرحله پنهان' وارد کنید.",
                reply_markup=get_hidden_stage_keyboard()
            )
        elif spin_result != "0":
            await update.message.reply_text(
                f"🎉 شما جایزه بردید!\n\n🏆 جایزه شما: {prize_name}\n\nلطفاً برای دریافت جایزه با ادمین تماس بگیرید.",
                reply_markup=get_main_menu_keyboard()
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=f"👤 برای دریافت جایزه خود ({prize_name}) لطفاً با ادمین تماس بگیرید: @{CHANNEL_USERNAME[1:]}"
            )
        else:
            await update.message.reply_text(
                f"متأسفیم! این بار جایزه‌ای نبردید.\n\nموجودی جدید شما: {new_balance:,} تومان",
                reply_markup=ReplyKeyboardMarkup([
                    ["چرخوندن گردونه (50,000 تومان)"],
                    ["بازگشت به منوی اصلی"]
                ], resize_keyboard=True)
            )
    except sqlite3.Error as e:
        logger.error(f"Database error in spin_wheel: {e}")
        await update.message.reply_text(
            "❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.",
            reply_markup=get_main_menu_keyboard()
        )

# Show balance
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Register user
    register_user(user_id, update.effective_user.username, 
                 update.effective_user.first_name, update.effective_user.last_name)

    try:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        balance = result[0] if result else 0

        await update.message.reply_text(
            f"💰 موجودی شما: {balance:,} تومان",
            reply_markup=get_balance_keyboard()
        )
    except sqlite3.Error as e:
        logger.error(f"Database error in show_balance: {e}")
        await update.message.reply_text(
            "❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.",
            reply_markup=get_main_menu_keyboard()
        )

# Increase balance menu
async def increase_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"💳 لطفاً مبلغ مورد نظر برای افزایش موجودی را انتخاب کنید:\n\n🔹 آدرس ترون: {TRON_ADDRESS}",
        reply_markup=get_deposit_keyboard()
    )

# Request deposit
async def request_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = int(update.message.text.split()[0]) * 1000  # Convert to Tomans
    context.user_data['deposit_amount'] = amount

    await update.message.reply_text(
        f"💰 شما مبلغ {amount:,} تومان را برای افزایش موجودی انتخاب کردید.\n\nلطفاً تصویر یا متن فیش واریزی خود را ارسال کنید.",
        reply_markup=ReplyKeyboardMarkup([
            ["انصراف"]
        ], resize_keyboard=True)
    )

# Process deposit proof
async def process_deposit_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    amount = context.user_data.get('deposit_amount', 0)

    if amount == 0:
        await update.message.reply_text(
            "خطایی رخ داده است. لطفاً دوباره تلاش کنید.",
            reply_markup=get_main_menu_keyboard()
        )
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
            f"💰 مبلغ: {amount:,} تومان\n"
            f"📌 فیش: {proof}\n\n"
            f"لطفاً تایید یا رد کنید:"
        )

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_message
        )

        await update.message.reply_text(
            "✅ فیش واریزی شما با موفقیت دریافت شد و برای تایید به ادمین ارسال شد.",
            reply_markup=get_main_menu_keyboard()
        )
    except sqlite3.Error as e:
        logger.error(f"Database error in process_deposit_proof: {e}")
        await update.message.reply_text(
            "❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.",
            reply_markup=get_main_menu_keyboard()
        )

# Hidden stage menu
async def hidden_stage_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔒 مرحله پنهان:\n\nدر این مرحله می‌توانید با حدس عدد صحیح بین 1 تا 200، 50 هزار تومان پاداش بگیرید!\n\n💰 پاداش: 50,000 تومان",
        reply_markup=get_hidden_stage_keyboard()
    )

# Start hidden stage game
async def start_hidden_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Register user
    register_user(user_id, update.effective_user.username, 
                 update.effective_user.first_name, update.effective_user.last_name)

    try:
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        balance = result[0] if result else 0

        if balance < HIDDEN_STAGE_COST:
            await update.message.reply_text(
                f"💰 موجودی شما کافی نیست!\n\nهزینه ورود به بازی: {HIDDEN_STAGE_COST:,} تومان\nموجودی شما: {balance:,} تومان",
                reply_markup=get_balance_keyboard()
            )
            return

        # Deduct cost
        new_balance = balance - HIDDEN_STAGE_COST
        cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))

        # Generate target number
        target_number = random.randint(1, 200)
        
        # Save game state
        cursor.execute(
            "INSERT OR REPLACE INTO hidden_stage_guesses (user_id, target_number, attempts, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, target_number, 0, datetime.now().isoformat())
        )
        conn.commit()

        await update.message.reply_text(
            f"🔢 بازی حدس عدد شروع شد!\n\n💰 هزینه ورود: {HIDDEN_STAGE_COST:,} تومان\n💵 موجودی جدید: {new_balance:,} تومان\n\nعدد مورد نظر بین 1 تا 200 است. لطفاً عدد خود را وارد کنید:",
            reply_markup=ReplyKeyboardMarkup([
                ["انصراف"]
            ], resize_keyboard=True)
        )
        return GUESSING_NUMBER
    except sqlite3.Error as e:
        logger.error(f"Database error in start_hidden_game: {e}")
        await update.message.reply_text(
            "❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END

# Process number guess
async def process_number_guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    guess_text = update.message.text.strip()

    try:
        # Get game state
        cursor.execute(
            "SELECT target_number, attempts FROM hidden_stage_guesses WHERE user_id = ?",
            (user_id,)
        )
        result = cursor.fetchone()
        
        if not result:
            await update.message.reply_text(
                "خطایی در بازی رخ داده است. لطفاً دوباره شروع کنید.",
                reply_markup=get_main_menu_keyboard()
            )
            return ConversationHandler.END
            
        target_number, attempts = result

        # Validate guess
        try:
            guess = int(guess_text)
            if guess < 1 or guess > 200:
                raise ValueError
        except ValueError:
            await update.message.reply_text("لطفاً عددی بین 1 تا 200 وارد کنید!")
            return GUESSING_NUMBER

        # Update attempts
        attempts += 1
        cursor.execute(
            "UPDATE hidden_stage_guesses SET attempts = ? WHERE user_id = ?",
            (attempts, user_id)
        )
        conn.commit()

        # Check guess
        if guess == target_number:
            # User won
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
                (user_id, user.username, f"پاداش مرحله پنهان: {HIDDEN_STAGE_REWARD:,} تومان", datetime.now().isoformat())
            )
            
            # Clear game state
            cursor.execute(
                "DELETE FROM hidden_stage_guesses WHERE user_id = ?",
                (user_id,)
            )
            conn.commit()

            await update.message.reply_text(
                f"🎉 تبریک می‌گوییم! شما عدد را درست حدس زدید!\n\n💰 شما {HIDDEN_STAGE_REWARD:,} تومان پاداش گرفتید!\n\n💰 موجودی جدید شما: {new_balance:,} تومان",
                reply_markup=get_main_menu_keyboard()
            )
            return ConversationHandler.END
        else:
            # Give hint
            hint = "عدد مورد نظر بزرگتر است." if guess < target_number else "عدد مورد نظر کوچکتر است."
            await update.message.reply_text(
                f"{hint}\n\nشما {attempts} بار تلاش کرده‌اید. عدد بعدی را وارد کنید:",
                reply_markup=ReplyKeyboardMarkup([
                    ["انصراف"]
                ], resize_keyboard=True)
            )
            return GUESSING_NUMBER
    except sqlite3.Error as e:
        logger.error(f"Database error in process_number_guess: {e}")
        await update.message.reply_text(
            "❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.",
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END

# Enter hidden code
async def enter_hidden_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔢 لطفاً کد مرحله پنهان خود را وارد کنید:",
        reply_markup=ReplyKeyboardMarkup([
            ["بازگشت"]
        ], resize_keyboard=True)
    )
    context.user_data['waiting_for_code'] = True

# Process hidden code
async def process_hidden_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    code = update.message.text.upper().strip()

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
                (user_id, user.username, f"پاداش مرحله پنهان: {HIDDEN_STAGE_REWARD:,} تومان", datetime.now().isoformat())
            )
            conn.commit()

            await update.message.reply_text(
                f"✅ کد تایید شد!\n\n💰 شما {HIDDEN_STAGE_REWARD:,} تومان پاداش گرفتید!",
                reply_markup=get_main_menu_keyboard()
            )
            context.user_data.pop('waiting_for_code', None)
        else:
            await update.message.reply_text(
                "❌ کد وارد شده نامعتبر است یا قبلاً استفاده شده است.",
                reply_markup=get_hidden_stage_keyboard()
            )
    except sqlite3.Error as e:
        logger.error(f"Database error in process_hidden_code: {e}")
        await update.message.reply_text(
            "❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.",
            reply_markup=get_main_menu_keyboard()
        )

# Show top winners
async def show_top_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        cursor.execute(
            "SELECT username, prize FROM top_winners ORDER BY timestamp DESC LIMIT 10"
        )
        winners = cursor.fetchall()

        text = "🏆 خوش شانس‌ترین‌های ماه:\n\n" if winners else "هنوز برنده‌ای ثبت نشده است."
        for i, (username, prize) in enumerate(winners, 1):
            text += f"{i}. @{username} - {prize}\n"

        await update.message.reply_text(
            text,
            reply_markup=get_main_menu_keyboard()
        )
    except sqlite3.Error as e:
        logger.error(f"Database error in show_top_winners: {e}")
        await update.message.reply_text(
            "❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.",
            reply_markup=get_main_menu_keyboard()
        )

# Show profile
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Register user
    register_user(user_id, update.effective_user.username, 
                 update.effective_user.first_name, update.effective_user.last_name)

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
            f"💰 موجودی: {balance:,} تومان\n"
            f"👥 تعداد دعوت شده‌ها: {invites_count} نفر\n"
            f"🎁 جوایز برده شده:\n{prizes_won}"
        )

        await update.message.reply_text(
            text,
            reply_markup=get_main_menu_keyboard()
        )
    except sqlite3.Error as e:
        logger.error(f"Database error in show_profile: {e}")
        await update.message.reply_text(
            "❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.",
            reply_markup=get_main_menu_keyboard()
        )

# Invite friends (simplified message)
async def invite_friends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    invite_link = f"https://t.me/{context.bot.username}?start=invite_{user_id}"

    await update.message.reply_text(
        f"👥 دعوت از دوستان\n\nبا هر دعوت موفق {INVITE_REWARD:,} تومان پاداش بگیرید!\n\n🔗 لینک دعوت شما:\n{invite_link}",
        reply_markup=get_main_menu_keyboard()
    )

# Check membership
async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if await is_user_member(user_id, context):
        await update.message.reply_text(
            "✅ شما عضو کانال هستید. لطفاً از منوی ربات استفاده کنید.",
            reply_markup=get_main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            "❌ شما هنوز عضو کانال نشده‌اید!",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("بررسی عضویت")]
            ], resize_keyboard=True)
        )

# Cancel action
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "عملیات لغو شد.",
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

# Main function
async def main():
    # Create the Application
    application = Application.builder().token(TOKEN).build()

    # Add conversation handler for hidden stage game
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^شروع بازی"), start_hidden_game)],
        states={
            GUESSING_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_number_guess)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    application.add_handler(conv_handler)

    # Commands
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('menu', main_menu))

    # Message handlers
    application.add_handler(MessageHandler(filters.Regex("^چرخوندن گردونه"), spin_wheel))
    application.add_handler(MessageHandler(filters.Regex("^موجودی$"), show_balance))
    application.add_handler(MessageHandler(filters.Regex("^افزایش موجودی$"), increase_balance))
    application.add_handler(MessageHandler(filters.Regex("^\d+ هزار تومان$") | filters.Regex("^\d+ میلیون تومان$"), request_deposit))
    application.add_handler(MessageHandler(filters.Regex("^مرحله پنهان$"), hidden_stage_menu))
    application.add_handler(MessageHandler(filters.Regex("^وارد کردن کد ورود$"), enter_hidden_code))
    application.add_handler(MessageHandler(filters.Regex("^خوش شانس‌ترین‌های ماه$"), show_top_winners))
    application.add_handler(MessageHandler(filters.Regex("^پروفایل$"), show_profile))
    application.add_handler(MessageHandler(filters.Regex("^دعوت دوستان$"), invite_friends))
    application.add_handler(MessageHandler(filters.Regex("^بررسی عضویت$"), check_membership))
    application.add_handler(MessageHandler(filters.Regex("^بازگشت"), main_menu))
    
    # Handle deposit proofs (text or photo)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process_text))
    application.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, process_deposit_proof))

    # Initialize and run the application
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    # Keep the application running
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

# Process text messages
async def process_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_for_code', False):
        await process_hidden_code(update, context)
    elif 'deposit_amount' in context.user_data:
        await process_deposit_proof(update, context)
    else:
        await update.message.reply_text(
            "لطفاً از منوی ربات استفاده کنید.",
            reply_markup=get_main_menu_keyboard()
        )

if __name__ == '__main__':
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
