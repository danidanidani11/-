import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext
import random
import sqlite3
from datetime import datetime

# تنظیمات لاگ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# تنظیمات ربات
TOKEN = '8078210260:AAEX-vz_apP68a6WhzaGhuAKK7amC1qUiEY'
CHANNEL_USERNAME = '@charkhoun'
ADMIN_ID = 5542927340
TRON_ADDRESS = 'TJ4xrwKJzKjk6FgKfuuqwah3Az5Ur22kJb'

# اتصال به دیتابیس
conn = sqlite3.connect('wheel_bot.db', check_same_thread=False)
cursor = conn.cursor()

# ایجاد جداول مورد نیاز
cursor.execute('''
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
)
''')

cursor.execute('''
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
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS prizes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    prize_type TEXT,
    prize_value TEXT,
    status TEXT DEFAULT 'pending',
    timestamp TEXT,
    FOREIGN KEY(user_id) REFERENCES users(user_id)
''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS hidden_stage_codes (
    code TEXT PRIMARY KEY,
    used INTEGER DEFAULT 0
)''')

cursor.execute('''
CREATE TABLE IF NOT EXISTS top_winners (
    user_id INTEGER,
    username TEXT,
    prize TEXT,
    timestamp TEXT,
    PRIMARY KEY(user_id, prize)
''')

conn.commit()

# تعریف جوایز گردونه
PRIZES = [
    {"name": "پوچ", "probability": 70.0, "value": "0"},
    {"name": "100 هزار تومان", "probability": 3.0, "value": "100000"},
    {"name": "پریمیوم 3 ماهه تلگرام", "probability": 0.1, "value": "premium"},
    {"name": "10 میلیون تومان", "probability": 0.01, "value": "10000000"},
    {"name": "کتاب رایگان", "probability": 5.0, "value": "book"},
    {"name": "کد ورود به مرحله پنهان", "probability": 21.89, "value": "hidden_stage"}
]

# هزینه چرخش گردونه
SPIN_COST = 50

# تابع برای بررسی عضویت کاربر در کانال
def is_user_member(user_id, context):
    try:
        member = context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking membership: {e}")
        return False

# تابع برای ایجاد منوی اصلی
def main_menu(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    
    # بررسی عضویت در کانال
    if not is_user_member(user_id, context):
        context.bot.send_message(
            chat_id=user_id,
            text=f"⚠️ برای استفاده از ربات باید در کانال ما عضو شوید:\n{CHANNEL_USERNAME}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME[1:]}")],
                [InlineKeyboardButton("بررسی عضویت", callback_data="check_membership")]
            ])
        )
        return
    
    keyboard = [
        [InlineKeyboardButton("چرخوندن گردونه", callback_data="spin_wheel")],
        [InlineKeyboardButton("موجودی", callback_data="balance")],
        [InlineKeyboardButton("مرحله پنهان", callback_data="hidden_stage")],
        [InlineKeyboardButton("خوش شانس ترین های ماه", callback_data="top_winners")],
        [InlineKeyboardButton("پروفایل", callback_data="profile")],
        [InlineKeyboardButton("دعوت دوستان", callback_data="invite_friends")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.callback_query:
        update.callback_query.edit_message_text(
            text="🏠 منوی اصلی:",
            reply_markup=reply_markup
        )
    else:
        update.message.reply_text(
            text="🏠 منوی اصلی:",
            reply_markup=reply_markup
        )

# تابع برای چرخاندن گردونه
def spin_wheel(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    
    # بررسی موجودی کاربر
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    balance = result[0] if result else 0
    
    if balance < SPIN_COST:
        query.answer()
        query.edit_message_text(
            text=f"💰 موجودی شما کافی نیست!\n\nهزینه هر چرخش: {SPIN_COST} تومان\nموجودی شما: {balance} تومان",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("افزایش موجودی", callback_data="increase_balance")],
                [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
            )
        )
        return
    
    # کسر هزینه از موجودی کاربر
    new_balance = balance - SPIN_COST
    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
    conn.commit()
    
    # چرخش گردونه و انتخاب جایزه
    spin_result = random.choices(
        [prize['value'] for prize in PRIZES],
        weights=[prize['probability'] for prize in PRIZES],
        k=1
    )[0]
    
    prize_name = next(prize['name'] for prize in PRIZES if prize['value'] == spin_result)
    
    # ذخیره اطلاعات جایزه
    cursor.execute(
        "INSERT INTO prizes (user_id, prize_type, prize_value, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, prize_name, spin_result, datetime.now().isoformat())
    )
    conn.commit()
    
    # ذخیره در تاریخچه جوایز کاربر
    cursor.execute(
        "UPDATE users SET prizes_won = prizes_won || ? WHERE user_id = ?",
        (f"{prize_name}, ", user_id)
    )
    conn.commit()
    
    # ارسال پیام به ادمین
    user = query.from_user
    admin_message = (
        f"🎉 کاربر جایزه برده!\n\n"
        f"👤 کاربر: @{user.username}\n"
        f"🆔 آیدی: {user.id}\n"
        f"🏆 جایزه: {prize_name}\n"
        f"⏰ زمان: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    context.bot.send_message(
        chat_id=ADMIN_ID,
        text=admin_message
    )
    
    # پاسخ به کاربر
    if spin_result == "hidden_stage":
        # ایجاد کد مرحله پنهان
        hidden_code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=8))
        cursor.execute(
            "INSERT INTO hidden_stage_codes (code) VALUES (?)",
            (hidden_code,)
        )
        conn.commit()
        
        query.edit_message_text(
            text=f"🎉 شما جایزه بردید!\n\n🏆 جایزه شما: {prize_name}\n\n🔑 کد شما: {hidden_code}\n\nاین کد را در بخش 'مرحله پنهان' وارد کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("مرحله پنهان", callback_data="hidden_stage")],
                [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
            ])
        )
    elif spin_result != "0":  # اگر جایزه غیر از پوچ باشد
        query.edit_message_text(
            text=f"🎉 شما جایزه بردید!\n\n🏆 جایزه شما: {prize_name}\n\nلطفاً برای دریافت جایزه با ادمین تماس بگیرید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
            ])
        )
        
        # ارسال پیام به کاربر برای تماس با ادمین
        context.bot.send_message(
            chat_id=user_id,
            text=f"👤 برای دریافت جایزه خود ({prize_name}) لطفاً با ادمین تماس بگیرید: @{CHANNEL_USERNAME[1:]}"
        )
    else:
        query.edit_message_text(
            text=f"متأسفیم! این بار جایزه‌ای نبردید.\n\nموجودی جدید شما: {new_balance} تومان",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("چرخش مجدد", callback_data="spin_wheel")],
                [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
            ])
        )

# تابع برای نمایش موجودی
def show_balance(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    balance = result[0] if result else 0
    
    query.edit_message_text(
        text=f"💰 موجودی شما: {balance} تومان",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("افزایش موجودی", callback_data="increase_balance")],
            [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
        ])
    )

# تابع برای افزایش موجودی
def increase_balance(update: Update, context: CallbackContext):
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
    
    query.edit_message_text(
        text=f"💳 لطفاً مبلغ مورد نظر برای افزایش موجودی را انتخاب کنید:\n\n🔹 آدرس ترون: {TRON_ADDRESS}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# تابع برای ثبت درخواست افزایش موجودی
def request_deposit(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    amount = int(query.data.split('_')[1])
    
    context.user_data['deposit_amount'] = amount
    
    query.edit_message_text(
        text=f"💰 شما مبلغ {amount} تومان را برای افزایش موجودی انتخاب کردید.\n\nلطفاً تصویر یا متن فیش واریزی خود را ارسال کنید.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("انصراف", callback_data="balance")]
        ])
    )

# تابع برای پردازش فیش واریزی
def process_deposit_proof(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    amount = context.user_data.get('deposit_amount', 0)
    
    if amount == 0:
        update.message.reply_text("خطایی رخ داده است. لطفاً دوباره تلاش کنید.")
        return
    
    # ذخیره اطلاعات تراکنش
    proof = update.message.text or "تصویر ارسال شده"
    cursor.execute(
        "INSERT INTO transactions (user_id, amount, type, proof, timestamp) VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, "deposit", proof, datetime.now().isoformat())
    )
    conn.commit()
    
    # ارسال به ادمین برای تایید
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
    
    context.bot.send_message(
        chat_id=ADMIN_ID,
        text=admin_message,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    update.message.reply_text(
        text="✅ فیش واریزی شما با موفقیت دریافت شد و برای تایید به ادمین ارسال شد.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
        ])
    )

# تابع برای تایید یا رد درخواست توسط ادمین
def handle_admin_decision(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data.split('_')
    action = data[0]
    user_id = int(data[1])
    amount = int(data[2])
    
    # آپدیت وضعیت تراکنش
    cursor.execute(
        "UPDATE transactions SET status = ?, admin_id = ? WHERE user_id = ? AND amount = ? AND status = 'pending'",
        (action, query.from_user.id, user_id, amount)
    )
    conn.commit()
    
    if action == "approve":
        # افزایش موجودی کاربر
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        current_balance = cursor.fetchone()[0] or 0
        new_balance = current_balance + amount
        
        cursor.execute(
            "UPDATE users SET balance = ? WHERE user_id = ?",
            (new_balance, user_id)
        )
        conn.commit()
        
        # ارسال پیام به کاربر
        context.bot.send_message(
            chat_id=user_id,
            text=f"✅ درخواست افزایش موجودی شما به مبلغ {amount} تومان تأیید شد.\n\n💰 موجودی جدید شما: {new_balance} تومان",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("چرخاندن گردونه", callback_data="spin_wheel")],
                [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
            ])
        )
        
        query.answer("درخواست با موفقیت تایید شد و موجودی کاربر افزایش یافت.")
    else:
        # ارسال پیام به کاربر در صورت رد درخواست
        context.bot.send_message(
            chat_id=user_id,
            text=f"❌ متأسفانه درخواست افزایش موجودی شما به مبلغ {amount} تومان رد شد.\n\nلطفاً در صورت نیاز با پشتیبانی تماس بگیرید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
            ])
        )
        
        query.answer("درخواست رد شد.")
    
    query.edit_message_text(
        text=query.message.text + f"\n\nوضعیت: {action == 'approve' and 'تایید شد ✅' or 'رد شد ❌'}",
        reply_markup=None
    )

# تابع برای مدیریت مرحله پنهان
def hidden_stage_menu(update: Update, context: CallbackContext):
    query = update.callback_query
    
    keyboard = [
        [InlineKeyboardButton("شروع بازی", callback_data="start_hidden_game")],
        [InlineKeyboardButton("خرید مرحله پنهان (5,000 تومان)", callback_data="buy_hidden_stage")],
        [InlineKeyboardButton("وارد کردن کد ورود", callback_data="enter_hidden_code")],
        [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
    ]
    
    query.edit_message_text(
        text="🔒 مرحله پنهان:\n\nدر این مرحله می‌توانید با وارد کردن کد صحیح، 50 هزار تومان پاداش بگیرید!\n\n💰 پاداش: 50,000 تومان + 1 چرخش رایگان",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# تابع برای خرید مرحله پنهان
def buy_hidden_stage(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    
    # بررسی موجودی کاربر
    cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    balance = result[0] if result else 0
    
    cost = 5000  # 5 هزار تومان
    
    if balance < cost:
        query.answer()
        query.edit_message_text(
            text=f"💰 موجودی شما کافی نیست!\n\nهزینه خرید مرحله پنهان: {cost} تومان\nموجودی شما: {balance} تومان",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("افزایش موجودی", callback_data="increase_balance")],
                [InlineKeyboardButton("بازگشت", callback_data="hidden_stage")]
            )
        )
        return
    
    # کسر هزینه از موجودی کاربر
    new_balance = balance - cost
    cursor.execute("UPDATE users SET balance = ? WHERE user_id = ?", (new_balance, user_id))
    conn.commit()
    
    # ایجاد کد تصادفی
    hidden_code = ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=8))
    cursor.execute(
        "INSERT INTO hidden_stage_codes (code) VALUES (?)",
        (hidden_code,)
    )
    conn.commit()
    
    query.edit_message_text(
        text=f"✅ مرحله پنهان با موفقیت خریداری شد!\n\n🔑 کد شما: {hidden_code}\n\n💰 موجودی جدید شما: {new_balance} تومان\n\nلطفاً این کد را در بخش 'وارد کردن کد ورود' وارد کنید.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("وارد کردن کد", callback_data="enter_hidden_code")],
            [InlineKeyboardButton("بازگشت", callback_data="hidden_stage")]
        ])
    )

# تابع برای وارد کردن کد مرحله پنهان
def enter_hidden_code(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    
    context.user_data['waiting_for_code'] = True
    
    query.edit_message_text(
        text="🔢 لطفاً کد مرحله پنهان خود را وارد کنید:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("بازگشت", callback_data="hidden_stage")]
        ])
    )

# تابع برای پردازش کد مرحله پنهان
def process_hidden_code(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    code = update.message.text.upper().strip()
    
    if not context.user_data.get('waiting_for_code', False):
        update.message.reply_text("لطفاً از منوی ربات استفاده کنید.")
        return
    
    # بررسی کد در دیتابیس
    cursor.execute(
        "SELECT * FROM hidden_stage_codes WHERE code = ? AND used = 0",
        (code,)
    )
    result = cursor.fetchone()
    
    if result:
        # علامت زدن کد به عنوان استفاده شده
        cursor.execute(
            "UPDATE hidden_stage_codes SET used = 1 WHERE code = ?",
            (code,)
        )
        conn.commit()
        
        # افزایش موجودی کاربر
        reward = 50000  # 50 هزار تومان
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        current_balance = cursor.fetchone()[0] or 0
        new_balance = current_balance + reward
        
        cursor.execute(
            "UPDATE users SET balance = ? WHERE user_id = ?",
            (new_balance, user_id)
        )
        conn.commit()
        
        # ذخیره اطلاعات جایزه
        cursor.execute(
            "INSERT INTO prizes (user_id, prize_type, prize_value, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, "پاداش مرحله پنهان", str(reward), datetime.now().isoformat())
        )
        conn.commit()
        
        # ذخیره در لیست برندگان
        user = update.message.from_user
        cursor.execute(
            "INSERT OR REPLACE INTO top_winners (user_id, username, prize, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, user.username, f"پاداش مرحله پنهان: {reward} تومان", datetime.now().isoformat())
        )
        conn.commit()
        
        update.message.reply_text(
            text=f"✅ کد تایید شد!\n\n💰 شما {reward} تومان پاداش گرفتید!\n\n🎁 همچنین یک چرخش رایگان دریافت کردید!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("چرخش رایگان", callback_data="spin_wheel")],
                [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
            ])
        )
        
        # حذف حالت انتظار برای کد
        context.user_data.pop('waiting_for_code', None)
    else:
        update.message.reply_text(
            text="❌ کد وارد شده نامعتبر است یا قبلاً استفاده شده است.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("دوباره امتحان کنید", callback_data="enter_hidden_code")],
                [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
            ])
        )

# تابع برای نمایش برندگان خوش شانس
def show_top_winners(update: Update, context: CallbackContext):
    query = update.callback_query
    
    cursor.execute(
        "SELECT username, prize FROM top_winners ORDER BY timestamp DESC LIMIT 10"
    )
    winners = cursor.fetchall()
    
    if not winners:
        text = "هنوز برنده‌ای ثبت نشده است."
    else:
        text = "🏆 خوش شانس‌ترین‌های ماه:\n\n"
        for i, (username, prize) in enumerate(winners, 1):
            text += f"{i}. @{username} - {prize}\n"
    
    query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
        ])
    )

# تابع برای نمایش پروفایل کاربر
def show_profile(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    
    cursor.execute(
        "SELECT balance, invites_count, prizes_won FROM users WHERE user_id = ?",
        (user_id,)
    )
    result = cursor.fetchone()
    
    if result:
        balance, invites_count, prizes_won = result
        prizes_won = prizes_won or "هنوز جایزه‌ای نبرده‌اید"
    else:
        balance = 0
        invites_count = 0
        prizes_won = "هنوز جایزه‌ای نبرده‌اید"
    
    text = (
        f"👤 پروفایل شما:\n\n"
        f"💰 موجودی: {balance} تومان\n"
        f"👥 تعداد دعوت شده‌ها: {invites_count} نفر\n"
        f"🎁 جوایز برده شده:\n{prizes_won}"
    )
    
    query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
        ])
    )

# تابع برای دعوت دوستان
def invite_friends(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    
    # ایجاد لینک دعوت
    invite_link = f"https://t.me/{context.bot.username}?start=invite_{user_id}"
    
    text = (
        f"👥 دعوت از دوستان\n\n"
        f"با هر دعوت موفق 2,000 تومان پاداش بگیرید!\n\n"
        f"🔗 لینک اختصاصی شما:\n{invite_link}\n\n"
        f"📌 این لینک را برای دوستان خود ارسال کنید و زمانی که آنها با این لینک وارد ربات شوند و اولین چرخش را انجام دهند، شما پاداش می‌گیرید!"
    )
    
    query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="main_menu")]
        ])
    )

# تابع برای پردازش دعوت‌ها
def process_invite(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    args = context.args
    
    if args and args[0].startswith('invite_'):
        inviter_id = int(args[0].split('_')[1])
        
        # بررسی اینکه کاربر قبلاً دعوت نشده باشد
        cursor.execute(
            "SELECT invited_by FROM users WHERE user_id = ?",
            (user_id,)
        )
        result = cursor.fetchone()
        
        if not result or not result[0]:
            # ثبت دعوت
            cursor.execute(
                "INSERT OR IGNORE INTO users (user_id, invited_by) VALUES (?, ?)",
                (user_id, inviter_id)
            )
            cursor.execute(
                "UPDATE users SET invited_by = ? WHERE user_id = ? AND invited_by = 0",
                (inviter_id, user_id)
            )
            conn.commit()
            
            # افزایش تعداد دعوت‌های دعوت کننده
            cursor.execute(
                "UPDATE users SET invites_count = invites_count + 1 WHERE user_id = ?",
                (inviter_id,)
            )
            
            # افزایش موجودی دعوت کننده
            invite_reward = 2000  # 2 هزار تومان
            cursor.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (invite_reward, inviter_id)
            )
            conn.commit()
            
            # اطلاع به دعوت کننده
            try:
                context.bot.send_message(
                    chat_id=inviter_id,
                    text=f"🎉 کاربری که دعوت کرده‌اید وارد ربات شد!\n\n💰 شما {invite_reward} تومان پاداش گرفتید!"
                )
            except:
                pass

# تابع شروع ربات
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    
    # ثبت کاربر در دیتابیس
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
        (user.id, user.username, user.first_name, user.last_name)
    )
    conn.commit()
    
    # پردازش دعوت اگر وجود داشته باشد
    if context.args:
        process_invite(update, context)
    
    # نمایش منوی اصلی
    main_menu(update, context)

# تابع برای نمایش منو با دستور menu
def show_menu(update: Update, context: CallbackContext):
    main_menu(update, context)

# تابع برای بررسی عضویت
def check_membership(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    
    if is_user_member(user_id, context):
        query.answer("✅ شما عضو کانال هستید. لطفاً از منوی ربات استفاده کنید.")
        main_menu(update, context)
    else:
        query.answer("❌ شما هنوز عضو کانال نشده‌اید!", show_alert=True)

# تابع اصلی
def main():
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    # دستورات
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('menu', show_menu))
    
    # پردازش پیام‌های متنی
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, process_text))
    
    # پردازش فیش واریزی
    dispatcher.add_handler(MessageHandler(Filters.photo | Filters.document, process_deposit_proof))
    
    # کال‌بک‌ها
    dispatcher.add_handler(CallbackQueryHandler(main_menu, pattern='^main_menu$'))
    dispatcher.add_handler(CallbackQueryHandler(spin_wheel, pattern='^spin_wheel$'))
    dispatcher.add_handler(CallbackQueryHandler(show_balance, pattern='^balance$'))
    dispatcher.add_handler(CallbackQueryHandler(increase_balance, pattern='^increase_balance$'))
    dispatcher.add_handler(CallbackQueryHandler(request_deposit, pattern='^deposit_'))
    dispatcher.add_handler(CallbackQueryHandler(handle_admin_decision, pattern='^(approve|reject)_'))
    dispatcher.add_handler(CallbackQueryHandler(hidden_stage_menu, pattern='^hidden_stage$'))
    dispatcher.add_handler(CallbackQueryHandler(buy_hidden_stage, pattern='^buy_hidden_stage$'))
    dispatcher.add_handler(CallbackQueryHandler(enter_hidden_code, pattern='^enter_hidden_code$'))
    dispatcher.add_handler(CallbackQueryHandler(show_top_winners, pattern='^top_winners$'))
    dispatcher.add_handler(CallbackQueryHandler(show_profile, pattern='^profile$'))
    dispatcher.add_handler(CallbackQueryHandler(invite_friends, pattern='^invite_friends$'))
    dispatcher.add_handler(CallbackQueryHandler(check_membership, pattern='^check_membership$'))
    
    # شروع ربات
    updater.start_polling()
    updater.idle()

def process_text(update: Update, context: CallbackContext):
    if context.user_data.get('waiting_for_code', False):
        process_hidden_code(update, context)
    else:
        # اگر کاربر در حال ارسال فیش متنی است
        if 'deposit_amount' in context.user_data:
            process_deposit_proof(update, context)
        else:
            update.message.reply_text(
                "لطفاً از منوی ربات استفاده کنید.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("منوی اصلی", callback_data="main_menu")]
                )
            )

if __name__ == '__main__':
    main()
