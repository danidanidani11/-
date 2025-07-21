import asyncio
import json
import random
from flask import Flask, request
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage

# ============ تنظیمات اصلی ============
TOKEN = '8078210260:AAEX-vz_apP68a6WhzaGhuAKK7amC1qUiEY'
ADMIN_ID = 5542927340
CHANNEL_USERNAME = "@charkhoun"
TRON_ADDRESS = "TJ4xrwKJzKjk6FgKfuuqwah3Az5Ur22kJb"
WEBHOOK_URL = "https://charkhoun.onrender.com/webhook"

# ============ بوت و دیسپچر ============
bot = Bot(token=TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())

# ============ فلask ============
app = Flask(__name__)

# ============ فایل دیتا ============
DATA_FILE = "users.json"

def load_users():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_users(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)

users = load_users()

# ============ چک عضویت اجباری ============
async def is_user_joined(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False

# ============ منوی اصلی ============
def main_menu():
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 چرخوندن گردونه", callback_data="spin")
    kb.button(text="💰 موجودی", callback_data="wallet")
    kb.button(text="🌀 مرحله پنهان", callback_data="secret_menu")
    kb.button(text="🏆 خوش‌شانس‌ترین‌ها", callback_data="top")
    kb.button(text="👤 پروفایل", callback_data="profile")
    kb.button(text="🤝 دعوت دوستان", callback_data="invite")
    kb.adjust(2, 2, 2)
    return kb.as_markup()

# ============ هندل استارت ============
@dp.message(F.text == "/start")
async def start_handler(message: Message):
    user_id = str(message.from_user.id)
    if not await is_user_joined(message.from_user.id):
        join_text = f"""❗️برای استفاده از ربات، ابتدا در کانال ما عضو شو:

📢 {CHANNEL_USERNAME}

سپس /start را بزن."""
        await message.answer(join_text)
        return

    if user_id not in users:
        users[user_id] = {
            "balance": 0,
            "invites": 0,
            "rewards": [],
            "ref": None,
            "spin_count": 0,
            "secret_code": None
        }
        save_users(users)

    await message.answer(f"🎉 خوش آمدی <b>{message.from_user.first_name}</b>!\nبه گردونه شانس!", reply_markup=main_menu())

# ============ گردونه شانس ============
@dp.callback_query(F.data == "spin")
async def spin_wheel(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    user = users.get(user_id)

    if not await is_user_joined(callback.from_user.id):
        await callback.message.edit_text(f"""❗️برای استفاده از ربات، ابتدا در کانال ما عضو شو:

📢 {CHANNEL_USERNAME}

سپس /start را بزن.""")
        return

    if user["balance"] < 50000:
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ افزایش موجودی", callback_data="wallet")
        kb.button(text="🔙 بازگشت", callback_data="menu")
        await callback.message.edit_text(
            f"💸 مبلغ لازم برای چرخوندن گردونه ۵۰ هزار تومنه.\nموجودی فعلی شما: {user['balance']:,} تومان",
            reply_markup=kb.as_markup())
        return

    # کم کردن مبلغ
    user["balance"] -= 50000
    user["spin_count"] += 1

    # جوایز و احتمال‌ها
    rewards = [
        ("پوچ", 70),
        ("۱۰۰ هزار تومان", 3),
        ("پریمیوم ۳ ماهه تلگرام", 0.1),
        ("۱۰ میلیون تومان", 0.01),
        ("کتاب رایگان", 5),
        ("کد ورود به مرحله پنهان", 21.89)
    ]

    # انتخاب تصادفی
    roll = random.uniform(0, 100)
    cumulative = 0
    result = "پوچ"
    for reward, chance in rewards:
        cumulative += chance
        if roll <= cumulative:
            result = reward
            break

    users[user_id]["rewards"].append(result)
    save_users(users)

    # ارسال پیام به کاربر
    text = f"🎯 گردونه چرخید!\n\nنتیجه: <b>{result}</b>"

    # اگر برنده شد و جایزه جدی بود
    if result not in ["پوچ", "کد ورود به مرحله پنهان"]:
        text += "\n\n🎁 برای دریافت جایزه، به پیوی ادمین پیام بده:"
        text += f"\n👉 @your_admin_username"  # آی‌دی واقعی ادمین رو بذار اینجا

    if result == "کد ورود به مرحله پنهان":
        secret_code = str(random.randint(100000, 999999))
        users[user_id]["secret_code"] = secret_code
        text += f"\n🔐 کد ورود به مرحله پنهان شما:\n<code>{secret_code}</code>"

    if result == "۱۰۰ هزار تومان":
        users[user_id]["balance"] += 100000
        text += "\n💸 مبلغ ۱۰۰ هزار تومان به موجودیت اضافه شد."

    if result == "۱۰ میلیون تومان":
        users[user_id]["balance"] += 10000000
        text += "\n💰 مبلغ ۱۰ میلیون تومان به موجودیت اضافه شد."

    save_users(users)

    # دکمه بازگشت
    kb = InlineKeyboardBuilder()
    kb.button(text="🔙 بازگشت", callback_data="menu")

    # ارسال به کاربر
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

    # ارسال گزارش به ادمین
    admin_text = f"🎲 <b>گردونه چرخانده شد</b>\n\n" \
                 f"👤 <a href='tg://user?id={callback.from_user.id}'>{callback.from_user.first_name}</a>\n" \
                 f"🎁 جایزه: <b>{result}</b>\n" \
                 f"💰 موجودی جدید: {users[user_id]['balance']:,} تومان"
    await bot.send_message(chat_id=ADMIN_ID, text=admin_text)

# ============ موجودی ============
@dp.callback_query(F.data == "wallet")
async def show_wallet(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    user = users.get(user_id)
    
    text = f"💰 موجودی شما: {user['balance']:,} تومان"
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ افزایش موجودی", callback_data="increase_balance")
    kb.button(text="🔙 بازگشت", callback_data="menu")
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

@dp.callback_query(F.data == "increase_balance")
async def choose_amount(callback: CallbackQuery):
    kb = InlineKeyboardBuilder()
    amounts = [10000, 30000, 50000, 200000, 500000, 1000000]
    for amt in amounts:
        kb.button(text=f"{amt:,} تومان", callback_data=f"pay_{amt}")
    kb.button(text="🔙 بازگشت", callback_data="wallet")
    await callback.message.edit_text("💵 مبلغ مورد نظر رو انتخاب کن:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("pay_"))
async def request_payment(callback: CallbackQuery):
    amount = int(callback.data.split("_")[1])
    user_id = str(callback.from_user.id)
    
    users[user_id]["pending_amount"] = amount
    save_users(users)

    text = f"""💸 لطفاً مبلغ {amount:,} تومان را به آدرس زیر در شبکه ترون (TRC20) واریز کن:

<b>{TRON_ADDRESS}</b>

سپس فیش واریز را (عکس یا متن) همینجا بفرست.
"""
    await callback.message.edit_text(text)

@dp.message(F.photo | F.text)
async def handle_payment_receipt(message: Message):
    user_id = str(message.from_user.id)
    user = users.get(user_id)
    
    if "pending_amount" not in user:
        return  # اگر منتظر فیش نیست، نادیده بگیر

    amount = user["pending_amount"]
    caption = f"💸 <b>درخواست افزایش موجودی</b>\n\n" \
              f"👤 <a href='tg://user?id={message.from_user.id}'>{message.from_user.first_name}</a>\n" \
              f"📥 مبلغ: {amount:,} تومان\n\n"

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ تایید", callback_data=f"approve_{user_id}_{amount}")
    kb.button(text="❌ رد", callback_data="reject")

    if message.photo:
        file_id = message.photo[-1].file_id
        await bot.send_photo(chat_id=ADMIN_ID, photo=file_id, caption=caption, reply_markup=kb.as_markup())
    else:
        caption += f"📝 فیش:\n{message.text}"
        await bot.send_message(chat_id=ADMIN_ID, text=caption, reply_markup=kb.as_markup())

    await message.reply("✅ فیش ارسال شد. پس از تایید توسط ادمین، موجودی شما افزایش پیدا می‌کنه.")
    del users[user_id]["pending_amount"]
    save_users(users)

@dp.callback_query(F.data.startswith("approve_"))
async def approve_payment(callback: CallbackQuery):
    parts = callback.data.split("_")
    user_id, amount = parts[1], int(parts[2])
    users[user_id]["balance"] += amount
    save_users(users)

    await bot.send_message(chat_id=int(user_id), text=f"✅ پرداخت شما تایید شد و {amount:,} تومان به موجودی‌تون اضافه شد.")
    await callback.message.edit_text("✅ پرداخت تایید شد.")

@dp.callback_query(F.data == "reject")
async def reject_payment(callback: CallbackQuery):
    await callback.message.edit_text("❌ پرداخت رد شد.")

@dp.callback_query(F.data == "secret_game")
async def enter_secret_game(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    user = users.get(user_id)

    if not user.get("secret_access"):
        await callback.message.edit_text(
            "🔒 شما دسترسی به مرحله پنهان ندارید.\n\n"
            "می‌تونی با چرخوندن گردونه یا خرید با ۵ هزار تومان وارد بشی.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🛒 خرید مرحله پنهان (۵۰۰۰)", callback_data="buy_secret")],
                    [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu")]
                ]
            )
        )
        return

    number = random.randint(1, 300)
    user["secret_number"] = number
    user["awaiting_guess"] = True
    user["secret_access"] = False
    save_users(users)

    await callback.message.edit_text(
        "🤫 مرحله پنهان فعال شد!\n\n"
        "باید عددی بین ۱ تا ۳۰۰ حدس بزنی (فقط یک شانس داری!)\n"
        "اگر درست بگی، یک گردونه رایگان برنده می‌شی! 🎉\n\n"
        "منتظر عددت هستم..."
    )

@dp.callback_query(F.data == "buy_secret")
async def buy_secret_access(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    user = users.get(user_id)

    if user["balance"] < 5000:
        await callback.message.edit_text("❌ موجودی شما برای خرید این مرحله کافی نیست.", reply_markup=menu_kb())
        return

    user["balance"] -= 5000
    user["secret_access"] = True
    save_users(users)

    await callback.message.edit_text("✅ مرحله پنهان برای شما فعال شد.\nدوباره روی دکمه مرحله پنهان بزن.", reply_markup=menu_kb())

@dp.message(F.text.regexp(r"^\d{1,3}$"))
async def handle_guess(message: Message):
    user_id = str(message.from_user.id)
    user = users.get(user_id)

    if not user.get("awaiting_guess"):
        return

    guess = int(message.text)
    correct = user["secret_number"]
    user["awaiting_guess"] = False
    del user["secret_number"]
    save_users(users)

    if guess == correct:
        user["spin_count"] += 1
        save_users(users)
        await message.reply("🎯 تبریک! درست حدس زدی و یک گردونه رایگان گرفتی! 🌀")
    else:
        await message.reply(f"❌ اشتباه گفتی. عدد درست: {correct}\nدفعه بعدی بیشتر دقت کن! 😉")

  @dp.callback_query(F.data == "invite")
async def invite_friends(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    bot_username = (await bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={user_id}"

    await callback.message.edit_text(
        f"🎁 با دعوت دوستانت ۲۰۰۰ تومان جایزه بگیر!\n\n"
        f"لینک دعوت اختصاصی شما:\n{link}\n\n"
        "وقتی دوستت از این لینک وارد بشه و عضو کانال باشه، جایزه می‌گیری!",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu")]
            ]
        )
    )

@dp.message(Command("start"))
async def start_command(message: Message, command: CommandObject):
    user_id = str(message.from_user.id)

    if user_id not in users:
        users[user_id] = {
            "balance": 0,
            "spin_count": 0,
            "referred_by": None,
            "referrals": 0,
            "prizes": [],
            "awaiting_guess": False,
            "secret_access": False
        }

        if command.args:
            inviter_id = command.args.strip()
            if inviter_id != user_id and inviter_id in users:
                users[user_id]["referred_by"] = inviter_id
                users[inviter_id]["referrals"] += 1
                users[inviter_id]["balance"] += 2000
                await bot.send_message(
                    int(inviter_id),
                    f"🎉 یک نفر با لینک دعوت شما وارد شد و ۲۰۰۰ تومان به موجودی‌ات اضافه شد!"
                )

        save_users(users)

    await message.answer("سلام 👋\nبه ربات گردونه شانس خوش اومدی!", reply_markup=menu_kb())

@dp.callback_query(F.data == "profile")
async def profile_handler(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    user = users.get(user_id, {
        "balance": 0,
        "spin_count": 0,
        "referred_by": None,
        "referrals": 0,
        "prizes": [],
        "awaiting_guess": False,
        "secret_access": False
    })

    prizes_text = " - " + "\n - ".join(user["prizes"]) if user["prizes"] else "هیچ جایزه‌ای هنوز نبردی."

    await callback.message.edit_text(
        f"📊 اطلاعات پروفایل شما:\n\n"
        f"💰 موجودی: {user['balance']:,} تومان\n"
        f"👥 تعداد دعوت‌های موفق: {user['referrals']}\n"
        f"🎁 جوایز برده‌شده:\n{prizes_text}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data="menu")]
            ]
        )
    )

