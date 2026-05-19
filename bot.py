import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import random
import requests
import json
import os
from datetime import datetime, timedelta

# ========== ТОКЕН ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ==========
TOKEN = os.getenv("TOKEN")
if TOKEN is None:
    print("❌ ОШИБКА: Токен не найден! Добавь переменную TOKEN в Railway")
    exit(1)

ADMIN_ID = 6615344173  # ЗАМЕНИ НА СВОЙ TELEGRAM ID

bot = telebot.TeleBot(TOKEN)
DATA_FILE = "user_data.json"

# ========== РАБОТА С ДАННЫМИ ==========
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

def add_coins(user_id, amount):
    user = get_user(user_id)
    user["coins"] += amount
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
        KeyboardButton("💸 Перевести монеты")
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
        "🎉 *Добро пожаловать в игровой бот!*\n\n"
        f"💰 *Стартовый бонус:* 5 монет\n\n"
        "🎮 Игры стоят 1 монету, победа приносит выигрыш!\n"
        "🎁 Заходи каждый день за бонусом!\n\n"
        "👇 *Выбери действие:*",
        reply_markup=main_keyboard(),
        parse_mode="Markdown"
    )

# ========== ОБРАБОТЧИК КНОПОК ==========
@bot.message_handler(func=lambda message: True)
def handle_buttons(message):
    user_id = message.chat.id
    text = message.text
    user = get_user(user_id)

    if text == "🎮 Игры":
        bot.send_message(user_id, "🎮 *Выбери игру (вход 1 монета):*", reply_markup=games_keyboard(), parse_mode="Markdown")

    elif text == "🎁 Ежедневный бонус":
        if can_take_bonus(user_id):
            add_coins(user_id, 10)
            user["last_bonus"] = datetime.now().isoformat()
            save_data()
            bot.send_message(user_id, "🎁 *Ты получил 10 монет!* 💰", parse_mode="Markdown")
        else:
            bot.send_message(user_id, "⏳ *Бонус уже получен! Заходи завтра.*", parse_mode="Markdown")

    elif text == "💰 Мой баланс":
        bot.send_message(user_id, f"💰 *Твой баланс:* {user['coins']} монет", parse_mode="Markdown")

    elif text == "💸 Перевести монеты":
        bot.send_message(user_id, "💸 *Перевод монет:*\n\n`/transfer @username 10`\n\nПример: `/transfer @durov 10`", parse_mode="Markdown")

    elif text == "🎲 Рандом":
        keyboard = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        keyboard.add(KeyboardButton("🎲 Случайное число"), KeyboardButton("🪙 Монетка"))
        keyboard.add(KeyboardButton("🔙 Назад"))
        bot.send_message(user_id, "🎲 *Выбери:*", reply_markup=keyboard, parse_mode="Markdown")

    elif text == "🎲 Случайное число":
        bot.send_message(user_id, f"🎲 *{random.randint(1, 100)}*", parse_mode="Markdown")
    
    elif text == "🪙 Монетка":
        result = random.choice(["Орёл 🦅", "Решка 💰"])
        bot.send_message(user_id, f"🪙 *{result}*", parse_mode="Markdown")

    elif text == "📱 Мои соцсети":
        keyboard = InlineKeyboardMarkup(row_width=1)
        keyboard.add(
            InlineKeyboardButton("📘 Telegram канал", url="https://t.me/@Stasyan_MD")
        )
        bot.send_message(user_id, "📱 *Мои соцсети:*", reply_markup=keyboard, parse_mode="Markdown")

    elif text == "❓ Задать вопрос":
        bot.send_message(user_id, "✍️ *Напиши свой вопрос:*", parse_mode="Markdown")
        waiting_for_message[user_id] = True

    elif text == "💰 Курс валют":
        try:
            url = "https://www.cbr-xml-daily.ru/daily_json.js"
            response = requests.get(url)
            data = response.json()
            usd = data["Valute"]["USD"]["Value"]
            eur = data["Valute"]["EUR"]["Value"]
            bot.send_message(
                user_id,
                f"💰 *Курс ЦБ РФ:*\n\n🇺🇸 USD: {usd:.2f} ₽\n🇪🇺 EUR: {eur:.2f} ₽",
                parse_mode="Markdown"
            )
        except:
            bot.send_message(user_id, "❌ Ошибка получения курса")

    elif text == "😄 Анекдот":
        jokes = [
            "🍟 - Картошка фри есть?\n- Нет\n- А картошка по-деревенски?\n- Тоже нет\n- А что есть?\n- Картошка 😄",
            "Встретились два друга:\n- Как жизнь?\n- Да вот, жена не готовит...\n- И ты живой? 🤯"
        ]
        bot.send_message(user_id, random.choice(jokes))

    elif text == "🔙 Назад":
        bot.send_message(user_id, "🔙 *Главное меню:*", reply_markup=main_keyboard(), parse_mode="Markdown")

    else:
        if waiting_for_message.get(user_id):
            user_name = message.from_user.first_name or "Пользователь"
            username = f"@{message.from_user.username}" if message.from_user.username else "нет"
            bot.send_message(
                ADMIN_ID,
                f"📩 *Вопрос от {user_name} ({username})*\n🆔 `{user_id}`\n📝: {text}",
                parse_mode="Markdown"
            )
            bot.send_message(user_id, "✅ *Вопрос отправлен!*", parse_mode="Markdown")
            waiting_for_message[user_id] = False
        elif user.get("game") == "guess":
            handle_guess(user_id, text)
        elif user.get("game") == "hangman":
            handle_hangman_guess(user_id, text.lower())
        else:
            bot.send_message(user_id, "Используй кнопки 👇", reply_markup=main_keyboard())

# ========== ИГРЫ ==========
def check_and_pay(user_id):
    if not remove_coins(user_id, 1):
        bot.send_message(user_id, "❌ *Недостаточно монет!* (нужна 1 монета)\nЗабери ежедневный бонус.", parse_mode="Markdown")
        return False
    return True

def handle_guess(user_id, guess_text):
    user = get_user(user_id)
    try:
        guess = int(guess_text)
        if guess == user["number"]:
            win = random.randint(5, 10)
            add_coins(user_id, win)
            bot.send_message(user_id, f"🎉 *Угадал!* +{win} монет", parse_mode="Markdown")
            user["game"] = None
        elif guess < user["number"]:
            bot.send_message(user_id, "📈 *Больше*", parse_mode="Markdown")
        else:
            bot.send_message(user_id, "📉 *Меньше*", parse_mode="Markdown")
    except:
        bot.send_message(user_id, "❌ Введи число!")

def handle_hangman_guess(user_id, guess):
    user = get_user(user_id)
    game = user.get("hangman")
    if not game:
        return
    word = game["word"]
    if guess == word:
        win = random.randint(8, 12)
        add_coins(user_id, win)
        bot.send_message(user_id, f"🎉 *Победа!* +{win} монет", parse_mode="Markdown")
        user["game"] = None
        user["hangman"] = None
    elif guess in game.get("guessed", []):
        bot.send_message(user_id, "⚠️ Уже называл")
    elif guess in word:
        game["guessed"].append(guess)
        bot.send_message(user_id, f"✅ Буква '{guess}' есть!")
        if all(l in game["guessed"] for l in word):
            win = random.randint(8, 12)
            add_coins(user_id, win)
            bot.send_message(user_id, f"🎉 *Победа!* +{win} монет", parse_mode="Markdown")
            user["game"] = None
            user["hangman"] = None
    else:
        game["attempts"] -= 1
        bot.send_message(user_id, f"❌ Нет буквы '{guess}'. Осталось: {game['attempts']}")
        if game["attempts"] <= 0:
            bot.send_message(user_id, f"💀 *Проигрыш!* Слово: {word}", parse_mode="Markdown")
            user["game"] = None
            user["hangman"] = None

# ========== INLINE КНОПКИ ==========
@bot.callback_query_handler(func=lambda call: True)
def game_callback(call):
    user_id = call.message.chat.id
    data = call.data

    if data == "exit_games":
        bot.edit_message_text("🎮 Выход", call.message.chat.id, call.message.message_id)
        return

    if data == "guess_number":
        if not check_and_pay(user_id):
            return
        number = random.randint(1, 20)
        user = get_user(user_id)
        user["game"] = "guess"
        user["number"] = number
        save_data()
        bot.edit_message_text("🔢 *Я загадал число от 1 до 20!*", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

    elif data == "rps":
        if not check_and_pay(user_id):
            return
        keyboard = InlineKeyboardMarkup(row_width=3)
        keyboard.add(
            InlineKeyboardButton("🗻", callback_data="rps_rock"),
            InlineKeyboardButton("✂️", callback_data="rps_scissors"),
            InlineKeyboardButton("📄", callback_data="rps_paper")
        )
        bot.edit_message_text("✂️ *Выбери:*", call.message.chat.id, call.message.message_id, reply_markup=keyboard, parse_mode="Markdown")

    elif data.startswith("rps_"):
        choices = {"rps_rock": "камень", "rps_scissors": "ножницы", "rps_paper": "бумага"}
        user_choice = choices[data]
        bot_choice = random.choice(["камень", "ножницы", "бумага"])
        if user_choice == bot_choice:
            win = 2
            result = "🤝 Ничья!"
        elif (user_choice == "камень" and bot_choice == "ножницы") or \
             (user_choice == "ножницы" and bot_choice == "бумага") or \
             (user_choice == "бумага" and bot_choice == "камень"):
            win = random.randint(3, 8)
            result = "🎉 Победа!"
        else:
            win = 0
            result = "😭 Поражение!"
        if win:
            add_coins(user_id, win)
        bot.edit_message_text(f"{result}\n💰 +{win} монет" if win else f"{result}\n💰 0 монет", call.message.chat.id, call.message.message_id)

    elif data == "dice":
        if not check_and_pay(user_id):
            return
        win = random.randint(2, 5)
        add_coins(user_id, win)
        bot.edit_message_text(f"🎲 Выпало: {random.randint(1, 6)}\n💰 +{win} монет", call.message.chat.id, call.message.message_id)

    elif data == "two_dice":
        if not check_and_pay(user_id):
            return
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        win = random.randint(3, 7)
        add_coins(user_id, win)
        bot.edit_message_text(f"🎲🎲 {d1}+{d2}={d1+d2}\n💰 +{win} монет", call.message.chat.id, call.message.message_id)

    elif data == "oracle":
        if not check_and_pay(user_id):
            return
        answers = ["✅ Да", "❌ Нет", "🤔 Скорее да", "🌟 Да", "💫 Спроси позже"]
        win = random.randint(1, 3)
        add_coins(user_id, win)
        bot.edit_message_text(f"🔮 *{random.choice(answers)}*\n💰 +{win} монет", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

    elif data == "hangman":
        if not check_and_pay(user_id):
            return
        words = {"python": "🐍 Язык", "телефон": "📱 Устройство", "компьютер": "💻 Устройство", "солнце": "☀️ Светило", "радуга": "🌈 После дождя"}
        word = random.choice(list(words.keys()))
        user = get_user(user_id)
        user["game"] = "hangman"
        user["hangman"] = {"word": word, "guessed": [], "attempts": 6, "hint": words[word]}
        save_data()
        bot.edit_message_text(f"📝 *Виселица!*\nПодсказка: {words[word]}\nПиши буквы или слово целиком.", call.message.chat.id, call.message.message_id, parse_mode="Markdown")

# ========== ПЕРЕВОД МОНЕТ ==========
@bot.message_handler(commands=['transfer'])
def transfer_coins(message):
    user_id = str(message.chat.id)
    sender = get_user(user_id)
    try:
        parts = message.text.split()
        if len(parts) != 3:
            bot.send_message(user_id, "❌ Формат: `/transfer @username 10`", parse_mode="Markdown")
            return
        target_username = parts[1].replace("@", "").lower()
        amount = int(parts[2])
        if amount <= 0:
            bot.send_message(user_id, "❌ Сумма > 0")
            return
        target_id = None
        for uid, data in user_data.items():
            if data.get("username") == target_username:
                target_id = uid
                break
        if not target_id:
            bot.send_message(user_id, f"❌ @{target_username} не найден")
            return
        if sender["coins"] < amount:
            bot.send_message(user_id, f"❌ Мало монет. Баланс: {sender['coins']}")
            return
        remove_coins(user_id, amount)
        add_coins(target_id, amount)
        bot.send_message(user_id, f"✅ Переведено {amount} монет @{target_username}")
        bot.send_message(int(target_id), f"🎉 +{amount} монет от @{message.from_user.username}")
    except:
        bot.send_message(user_id, "❌ Ошибка. Пример: `/transfer @durov 10`", parse_mode="Markdown")

# ========== ОТВЕТ АДМИНА ==========
@bot.message_handler(commands=['answer'])
def answer_user(message):
    if message.chat.id != ADMIN_ID:
        return
    try:
        parts = message.text.split(maxsplit=2)
        user_id = int(parts[1])
        answer_text = parts[2]
        bot.send_message(user_id, f"📬 *Ответ:*\n{answer_text}", parse_mode="Markdown")
        bot.send_message(ADMIN_ID, f"✅ Отправлено {user_id}")
    except:
        bot.send_message(ADMIN_ID, "❌ /answer ID текст")

# ========== ЗАПУСК ==========
if __name__ == "__main__":
    print("🤖 Полный бот запущен!")
    bot.infinity_polling(skip_pending=True)
