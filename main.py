import os
import random
from flask import Flask, request
import telebot
from telebot import types
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = '7954708829:AAFg7Mwj5-iGwIsUmfDRr6ZRJZr2jZ28jz0'
ADMIN_ID = 5542927340
CHANNEL_USERNAME = 'fromheartsoul'
PDF_PATH = 'books/hozhin_harman.pdf'

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# User states and data storage
user_state = {}
user_balances = {}
invite_codes = {}
number_game_data = {}

# Lottery wheel prizes
WHEEL_PRIZES = [
    "10,000 تومان",
    "20,000 تومان",
    "30,000 تومان",
    "40,000 تومان",
    "50,000 تومان",
    "100,000 تومان",
    "200,000 تومان",
    "500,000 تومان"
]
LOTTERY_COST = 50000  # 50,000 Tomans

# Number game settings
NUMBER_GAME_COST = 5000  # 5,000 Tomans
NUMBER_GAME_PRIZE = 50000  # 50,000 Tomans

# Initialize user balances
def init_user_balance(user_id):
    if user_id not in user_balances:
        user_balances[user_id] = 0

# Generate invite code
def generate_invite_code(user_id):
    code = str(user_id)[-6:] + str(random.randint(1000, 9999))
    invite_codes[code] = user_id
    return code

# --- Inline Keyboards ---
def get_main_inline_keyboard():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📖 خرید کتاب", callback_data="buy_book"),
        InlineKeyboardButton("🎰 چرخش گردونه", callback_data="spin_wheel")
    )
    markup.row(
        InlineKeyboardButton("🔢 بازی عدد", callback_data="number_game"),
        InlineKeyboardButton("💰 کیف پول", callback_data="wallet")
    )
    markup.row(
        InlineKeyboardButton("📣 دعوت دوستان", callback_data="invite_friends"),
        InlineKeyboardButton("ℹ️ درباره کتاب", callback_data="about_book")
    )
    return markup

def get_wallet_keyboard():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("➕ افزایش موجودی", callback_data="deposit"),
        InlineKeyboardButton("🎰 چرخش گردونه", callback_data="spin_wheel")
    )
    markup.row(
        InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")
    )
    return markup

def get_number_game_keyboard():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("🔢 حدس بزن", callback_data="guess_number"),
        InlineKeyboardButton("🔙 بازگشت", callback_data="main_menu")
    )
    return markup

# --- Handlers ---
@bot.message_handler(commands=['start'])
def start_handler(message):
    init_user_balance(message.from_user.id)
    welcome_text = """
    به ربات فروش کتاب «هوژین و حرمان» خوش آمدید 🌸

    🎰 چرخش گردونه با جایزه تا 500,000 تومان
    🔢 بازی حدس عدد با جایزه 50,000 تومان
    📣 دعوت از دوستان و دریافت 2,000 تومان به ازای هر دعوت
    """
    bot.send_message(
        message.chat.id,
        welcome_text,
        reply_markup=get_main_inline_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data == "main_menu")
def main_menu_callback(call):
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="منوی اصلی:",
        reply_markup=get_main_inline_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data == "buy_book")
def buy_book_callback(call):
    user_state[call.from_user.id] = 'awaiting_receipt'
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="لطفاً رسید پرداخت خود را ارسال کنید (عکس یا متن)."
    )

@bot.message_handler(content_types=['text', 'photo'], func=lambda msg: user_state.get(msg.from_user.id) == 'awaiting_receipt')
def handle_receipt(message):
    user_state.pop(message.from_user.id)

    if message.content_type == 'photo':
        file_id = message.photo[-1].file_id
        caption = message.caption or "رسید پرداخت"
        sent = bot.send_photo(
            ADMIN_ID, file_id, caption=f"{caption}\n\nاز طرف: {message.from_user.id}"
        )
    else:
        sent = bot.send_message(
            ADMIN_ID,
            f"رسید پرداخت از کاربر {message.from_user.id}:\n\n{message.text}"
        )

    # Admin approval buttons
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ تایید", callback_data=f"approve_{message.from_user.id}"),
        InlineKeyboardButton("❌ رد", callback_data=f"reject_{message.from_user.id}")
    )
    bot.send_message(ADMIN_ID, "آیا رسید را تایید می‌کنید؟", reply_markup=markup)
    bot.send_message(message.chat.id, "رسید شما برای بررسی ارسال شد ✅")

@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("reject_"))
def handle_approval(call):
    user_id = int(call.data.split("_")[1])
    if call.data.startswith("approve_"):
        bot.send_document(user_id, open(PDF_PATH, "rb"))
        bot.send_message(user_id, "📘 خرید شما تایید شد. فایل کتاب برایتان ارسال شد.")
        bot.send_message(ADMIN_ID, f"✅ فایل برای {user_id} ارسال شد.")
    else:
        bot.send_message(user_id, "❌ رسید شما رد شد. لطفاً مجدد تلاش کنید.")
        bot.send_message(ADMIN_ID, f"❌ رسید کاربر {user_id} رد شد.")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "spin_wheel")
def spin_wheel_callback(call):
    init_user_balance(call.from_user.id)
    
    if user_balances[call.from_user.id] < LOTTERY_COST:
        bot.answer_callback_query(
            call.id,
            f"موجودی شما کافی نیست. حداقل موجودی مورد نیاز: {LOTTERY_COST:,} تومان",
            show_alert=True
        )
        return
    
    # Deduct balance
    user_balances[call.from_user.id] -= LOTTERY_COST
    
    # Spin the wheel
    prize = random.choice(WHEEL_PRIZES)
    prize_amount = int(prize.split(",")[0].strip(" تومان")) * 1000
    
    # Add prize to balance
    user_balances[call.from_user.id] += prize_amount
    
    # Show result
    result_text = f"""
    🎉 نتیجه چرخش گردونه 🎉
    
    شما برنده {prize} شدید!
    
    موجودی فعلی: {user_balances[call.from_user.id]:,} تومان
    """
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=result_text,
        reply_markup=get_main_inline_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data == "number_game")
def number_game_callback(call):
    game_info = """
    🔢 بازی حدس عدد
    
    عددی بین 1 تا 200 انتخاب شده است.
    اگر عدد را درست حدس بزنید، 50,000 تومان برنده می‌شوید!
    
    هزینه ورود: 5,000 تومان
    """
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=game_info,
        reply_markup=get_number_game_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data == "guess_number")
def guess_number_callback(call):
    init_user_balance(call.from_user.id)
    
    if user_balances[call.from_user.id] < NUMBER_GAME_COST:
        bot.answer_callback_query(
            call.id,
            f"موجودی شما کافی نیست. حداقل موجودی مورد نیاز: {NUMBER_GAME_COST:,} تومان",
            show_alert=True
        )
        return
    
    # Deduct balance
    user_balances[call.from_user.id] -= NUMBER_GAME_COST
    
    # Generate random number
    number_game_data[call.from_user.id] = random.randint(1, 200)
    user_state[call.from_user.id] = 'awaiting_number_guess'
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text="عدد خود را بین 1 تا 200 وارد کنید:",
        reply_markup=InlineKeyboardMarkup().add(
            InlineKeyboardButton("🔙 بازگشت", callback_data="number_game")
        )
    )

@bot.message_handler(func=lambda msg: user_state.get(msg.from_user.id) == 'awaiting_number_guess')
def handle_number_guess(message):
    try:
        guess = int(message.text)
        user_id = message.from_user.id
        target_number = number_game_data.get(user_id)
        
        if not target_number:
            bot.send_message(message.chat.id, "خطایی رخ داد. لطفاً دوباره شروع کنید.")
            return
            
        if guess == target_number:
            # User won
            user_balances[user_id] += NUMBER_GAME_PRIZE
            result_text = f"""
            🎉 تبریک! شما برنده شدید!
            
            عدد صحیح: {target_number}
            جایزه شما: {NUMBER_GAME_PRIZE:,} تومان
            
            موجودی فعلی: {user_balances[user_id]:,} تومان
            """
        else:
            # User lost
            hint = "بیشتر" if guess < target_number else "کمتر"
            result_text = f"""
            ❌ حدس شما اشتباه بود!
            
            عدد شما: {guess}
            عدد صحیح {hint} از این مقدار است.
            
            موجودی فعلی: {user_balances[user_id]:,} تومان
            """
        
        bot.send_message(
            message.chat.id,
            result_text,
            reply_markup=get_main_inline_keyboard()
        )
        user_state.pop(user_id)
        
    except ValueError:
        bot.send_message(message.chat.id, "لطفاً یک عدد معتبر وارد کنید!")

@bot.callback_query_handler(func=lambda call: call.data == "invite_friends")
def invite_friends_callback(call):
    invite_code = generate_invite_code(call.from_user.id)
    invite_link = f"https://t.me/{bot.get_me().username}?start={invite_code}"
    
    invite_text = f"""
    📣 دعوت از دوستان
    
    با دعوت هر دوست 2,000 تومان جایزه بگیرید!
    
    لینک دعوت شما:
    {invite_link}
    """
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=invite_text,
        reply_markup=get_main_inline_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data == "wallet")
def wallet_callback(call):
    init_user_balance(call.from_user.id)
    wallet_text = f"""
    💰 کیف پول شما
    
    موجودی: {user_balances[call.from_user.id]:,} تومان
    
    هزینه چرخش گردونه: {LOTTERY_COST:,} تومان
    هزینه بازی عدد: {NUMBER_GAME_COST:,} تومان
    """
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=wallet_text,
        reply_markup=get_wallet_keyboard()
    )

@bot.callback_query_handler(func=lambda call: call.data == "about_book")
def about_book_callback(call):
    about_text = """
    📖 درباره کتاب هوژین و حرمان
    
    رمان هوژین و حرمان روایتی عاشقانه است که تلفیقی از سبک سورئالیسم، رئالیسم و روان است.
    
    نام هوژین واژه ای کردی است که به معنای کسی است که با آمدنش نور زندگی شما میشود.
    حرمان نیز به معنای کسی است که بالاترین حد اندوه را تجربه کرده است.
    """
    
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=about_text,
        reply_markup=get_main_inline_keyboard()
    )

# Handle new users coming from invite links
@bot.message_handler(func=lambda msg: len(msg.text.split()) > 1 and msg.text.split()[1] in invite_codes)
def handle_invited_user(message):
    invite_code = message.text.split()[1]
    referrer_id = invite_codes.get(invite_code)
    
    if referrer_id and referrer_id != message.from_user.id:
        # Add bonus to referrer
        init_user_balance(referrer_id)
        user_balances[referrer_id] += 2000
        
        # Notify both users
        bot.send_message(
            referrer_id,
            f"✅ کاربر جدید با لینک دعوت شما وارد شد! 2,000 تومان به حساب شما اضافه شد."
        )
    
    # Send welcome message
    start_handler(message)

# --- Flask Webhook ---
@app.route('/', methods=["POST"])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return '', 403

@app.route('/')
def index():
    return "ربات فعال است."

if __name__ == '__main__':
    # Remove any existing webhook and set new one
    bot.remove_webhook()
    bot.set_webhook(url='https://hozhin.onrender.com/' + TOKEN)
    
    # Start Flask app
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
