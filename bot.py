import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import random
import requests
import json
import os
from datetime import datetime, timedelta

# ========== НАСТРОЙКИ ==========
TOKEN = os.getenv("TOKEN")  # Токен из переменных окружения Render
ADMIN_ID = 6615344173  # СВОЙ ID (число)
DATA_FILE = "user_data.json"
# ===============================

bot = telebot.TeleBot(TOKEN)

# Загрузка данных
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(user_data, f, ensure_ascii=False, indent=2)

user_data = load_data()
waiting_for_message = {}

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_user(user_id):
    user_id = str(user_id)
    if user_id not in user_data:
        user_data[user_id] = {
            "coins": 5,
            "last_bonus": None,
            "game": None,
            "number": None,
            "hangman": None,
            "username": None,
            "total_donated": 0
        }
        save_data()
    return user_data[user_id]

def add_coins(user_id, amount, from_donate=False):
    user = get_user(user_id)
    user["coins"] += amount
    if from_donate:
        user["total_donated"] = user.get("total_donated", 0) + amount
    save_data()
    return user["coins"]

def remove_coins(user_id, amount):
    user = get_user(user_id)
    if user["coins"] >= amount:
        user["coins"] -= amount
        save_data()
        return True
    return False

def can_take_bonus(user_id):
    user = get_user(user_id)
    if user["last_bonus"] is None:
        return True
    last = datetime.fromisoformat(user["last_bonus"])
    return datetime.now() - last >= timedelta(hours=24)

# ========== КЛАВИАТУРЫ ==========
def main_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        KeyboardButton("🎮 Игры"),
        KeyboardButton("🎲 Рандом"),
        KeyboardButton("📱 Мои соцсети"),
        KeyboardButton("❓ Задать вопрос"),
        KeyboardButton("💰 Курс валют"),
        KeyboardButton("😄 Анекдот"),
        KeyboardButton("🎁 Ежедневный бонус"),
        KeyboardButton("💰 Мой баланс"),
        KeyboardButton("💸 Перевести монеты"),
        KeyboardButton("💎 Пополнить баланс")
    )
    return keyboard

def games_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("🔢 Угадай число (1💰)", callback_data="guess_number"),
        InlineKeyboardButton("✂️ Камень-ножницы (1💰)", callback_data="rps"),
        InlineKeyboardButton("🎲 Один кубик (1💰)", callback_data="dice"),
        InlineKeyboardButton("🎲🎲 Два кубика (1💰)", callback_data="two_dice"),
        InlineKeyboardButton("🔮 Оракул (1💰)", callback_data="oracle"),
        InlineKeyboardButton("📝 Виселица (1💰)", callback_data="hangman"),
        InlineKeyboardButton("❌ Выйти", callback_data="exit_games")
    )
    return keyboard

def donate_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("⭐ 50 монет", callback_data="donate_50"),
        InlineKeyboardButton("⭐ 100 монет", callback_data="donate_100"),
        InlineKeyboardButton("⭐ 200 монет", callback_data="donate_200"),
        InlineKeyboardButton("⭐ 300 монет", callback_data="donate_300"),
        InlineKeyboardButton("⭐ 400 монет", callback_data="donate_400"),
        InlineKeyboardButton("⭐ 500 монет", callback_data="donate_500")
    )
    return keyboard

# ========== КОМАНДА /start ==========
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id
    user = get_user(user_id)
    
    if message.from_user.username:
        user["username"] = message.from_user.username.lower()
        save_data()
    
    bot.send_message(
        user_id,
        "🎉 *Добро пожаловать!*\n\n"
        f"💰 *Стартовый бонус:* 5 монет\n\n"
        "👇 *Выбери действие:*",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )

# ========== ДОНАТ ==========
@bot.callback_query_handler(func=lambda call: call.data.startswith("donate_"))
def handle_donate(call):
    user_id = call.message.chat.id
    amount = int(call.data.split("_")[1])
    
    prices = [telebot.types.LabeledPrice(label=f"{amount} монет", amount=amount * 100)]
    
    try:
        bot.send_invoice(
            chat_id=user_id,
            title="💎 Пополнение",
            description=f"{amount} монет",
            invoice_payload=f"donate_{amount}",
            provider_token="",
            currency="XTR",
            prices=prices
        )
    except Exception as e:
        bot.send_message(user_id, f"❌ Ошибка: {e}")

@bot.pre_checkout_query_handler(func=lambda query: True)
def handle_pre_checkout(query):
    bot.answer_pre_checkout_query(query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def handle_payment(message):
    user_id = message.chat.id
    payload = message.successful_payment.invoice_payload
    amount = int(payload.split("_")[1])
    
    add_coins(user_id, amount, from_donate=True)
    bot.send_message(user_id, f"✅ Начислено {amount} монет! Спасибо! 💎")

# ========== ОБРАБОТЧИК КНОПОК ==========
@bot.message_handler(func=lambda message: True)
def handle_buttons(message):
    user_id = message.chat.id
    text = message.text
    user = get_user(user_id)

    if text == "🎮 Игры":
        bot.send_message(user_id, "🎮 *Выбери игру:*", reply_markup=games_keyboard(), parse_mode="Markdown")

    elif text == "💎 Пополнить баланс":
        bot.send_message(user_id, "💎 *Выбери сумму:*", reply_markup=donate_keyboard(), parse_mode="Markdown")

    elif text == "🎁 Ежедневный бонус":
        if can_take_bonus(user_id):
            add_coins(user_id, 10)
            user["last_bonus"] = datetime.now().isoformat()
            save_data()
            bot.send_message(user_id, "🎁 +10 монет!", parse_mode="Markdown")
        else:
            bot.send_message(user_id, "⏳ Бонус уже получен. Завтра!", parse_mode="Markdown")

    elif text == "💰 Мой баланс":
        bot.send_message(user_id, f"💰 *{user['coins']} монет*", parse_mode="Markdown")

    elif text == "💸 Перевести монеты":
        bot.send_message(user_id, "💸 `/transfer @username 10`", parse_mode="Markdown")

    elif text == "🎲 Рандом":
        keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        keyboard.add(KeyboardButton("🎲 Число"), KeyboardButton("🪙 Монетка"))
        keyboard.add(KeyboardButton("🔙 Назад"))
        bot.send_message(user_id, "🎲 *Выбери:*", reply_markup=keyboard, parse_mode="Markdown")

    elif text == "🎲 Число":
        bot.send_message(user_id, f"🎲 *{random.randint(1, 100)}*", parse_mode="Markdown")
    
    elif text == "🪙 Монетка":
        result = random.choice(["Орёл 🦅", "Решка 💰"])
        bot.send_message(user_id, f"🪙 *{result}*", parse_mode="Markdown")

    elif text == "📱 Мои соцсети":
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(InlineKeyboardButton("📘 Telegram", url="https://t.me/@Stasyan_MD"))
        bot.send_message(user_id, "📱 *Мои соцсети:*", reply_markup=keyboard, parse_mode="Markdown")

    elif text == "❓ Задать вопрос":
        bot.send_message(user_id, "✍️ *Напиши вопрос:*", parse_mode="Markdown")
        waiting_for_message[user_id] = True

    elif text == "💰 Курс валют":
        try:
            r = requests.get("https://www.cbr-xml-daily.ru/daily_json.js")
            data = r.json()
            bot.send_message(user_id, f"💰 USD: {data['Valute']['USD']['Value']:.2f} ₽\nEUR: {data['Valute']['EUR']['Value']:.2f} ₽", parse_mode="Markdown")
        except:
            bot.send_message(user_id, "❌ Ошибка курса")

    elif text == "😄 Анекдот":
        jokes = ["Почему бот не отвечает? Потому что программист чай пьёт ☕"]
        bot.send_message(user_id, random.choice(jokes))

    elif text == "🔙 Назад":
        bot.send_message(user_id, "🔙 *Главное меню:*", reply_markup=main_keyboard(), parse_mode="Markdown")

    else:
        if waiting_for_message.get(user_id):
            bot.send_message(ADMIN_ID, f"📩 Вопрос от {user_id}: {text}")
            bot.send_message(user_id, "✅ Отправлено!", parse_mode="Markdown")
            waiting_for_message[user_id] = False
        else:
            bot.send_message(user_id, "Используй кнопки 👇", reply_markup=main_keyboard())

# ========== ИГРЫ ==========
def check_and_pay(user_id):
    if not remove_coins(user_id, 1):
        bot.send_message(user_id, "❌ Нужна 1 монета!")
        return False
    return True

@bot.callback_query_handler(func=lambda call: True)
def game_callback(call):
    user_id = call.message.chat.id
    data = call.data

    if data == "guess_number":
        if not check_and_pay(user_id): return
        number = random.randint(1, 20)
        user = get_user(user_id)
        user["game"] = "guess"
        user["number"] = number
        save_data()
        bot.edit_message_text("🔢 Угадай число (1-20):", call.message.chat.id, call.message.message_id)

    elif data == "rps":
        if not check_and_pay(user_id): return
        keyboard = InlineKeyboardMarkup(row_width=3)
        keyboard.add(
            InlineKeyboardButton("🗻", callback_data="rps_rock"),
            InlineKeyboardButton("✂️", callback_data="rps_scissors"),
            InlineKeyboardButton("📄", callback_data="rps_paper")
        )
        bot.edit_message_text("Выбери:", call.message.chat.id, call.message.message_id, reply_markup=keyboard)

    elif data.startswith("rps_"):
        choices = {"rps_rock": "камень", "rps_scissors": "ножницы", "rps_paper": "бумага"}
        user_choice = choices[data]
        bot_choice = random.choice(["камень", "ножницы", "бумага"])
        win = random.randint(2, 5) if user_choice == bot_choice else random.randint(3, 8)
        add_coins(user_id, win)
        bot.edit_message_text(f"Твой ход: {user_choice}\nБот: {bot_choice}\n💰 +{win} монет", call.message.chat.id, call.message.message_id)

    elif data == "dice":
        if not check_and_pay(user_id): return
        win = random.randint(2, 5)
        add_coins(user_id, win)
        bot.edit_message_text(f"🎲 Выпало: {random.randint(1, 6)}\n💰 +{win} монет", call.message.chat.id, call.message.message_id)

    elif data == "two_dice":
        if not check_and_pay(user_id): return
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        win = random.randint(3, 7)
        add_coins(user_id, win)
        bot.edit_message_text(f"🎲🎲 {d1}+{d2}={d1+d2}\n💰 +{win} монет", call.message.chat.id, call.message.message_id)

    elif data == "oracle":
        if not check_and_pay(user_id): return
        answers = ["✅ Да", "❌ Нет", "🤔 Скорее да"]
        win = random.randint(1, 3)
        add_coins(user_id, win)
        bot.edit_message_text(f"🔮 {random.choice(answers)}\n💰 +{win} монет", call.message.chat.id, call.message.message_id)

    elif data == "hangman":
        if not check_and_pay(user_id): return
        bot.edit_message_text("📝 Виселица (пока в разработке)", call.message.chat.id, call.message.message_id)

    elif data == "exit_games":
        bot.edit_message_text("🎮 Выход", call.message.chat.id, call.message.message_id)

# ========== ПЕРЕВОД ==========
@bot.message_handler(commands=['transfer'])
def transfer_coins(message):
    user_id = str(message.chat.id)
    sender = get_user(user_id)
    try:
        parts = message.text.split()
        target_username = parts[1].replace("@", "")
        amount = int(parts[2])
        target_id = None
        for uid, data in user_data.items():
            if data.get("username") == target_username:
                target_id = uid
                break
        if not target_id:
            bot.send_message(user_id, "❌ Пользователь не найден")
            return
        if sender["coins"] < amount:
            bot.send_message(user_id, "❌ Мало монет")
            return
        remove_coins(user_id, amount)
        add_coins(target_id, amount)
        bot.send_message(user_id, f"✅ Переведено {amount} монет @{target_username}")
    except:
        bot.send_message(user_id, "❌ /transfer @username 10")

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    print("🤖 Бот запущен!")
    bot.infinity_polling()