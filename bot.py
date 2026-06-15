import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from flask import Flask, send_from_directory, request, jsonify
import threading
import random
import os
from datetime import datetime, timedelta

TOKEN = os.getenv("TOKEN")
DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "localhost:5000")
WEBAPP_URL = f"https://{DOMAIN}/web_app/index.html"

# Стикер из переменной Railway (если не задан — пусто)
STICKER_ID = os.getenv("STICKER_ID", "")

bot = telebot.TeleBot(TOKEN)
flask_app = Flask(__name__, static_folder='web_app', static_url_path='')

# Данные
users = {}
alliances = {}
next_alliance_id = 1

# 20 питомцев (полный список)
PETS = [
    {"id": 1, "name": "Искровая Лиса", "emoji": "🦊", "price": 1000, "base_income": 2, "food_price": 200, "food_increase": 1},
    {"id": 2, "name": "Теневой Волк", "emoji": "🐺", "price": 2500, "base_income": 5, "food_price": 500, "food_increase": 2},
    {"id": 3, "name": "Лунный Дракончик", "emoji": "🐉", "price": 5000, "base_income": 12, "food_price": 1000, "food_increase": 3},
    {"id": 4, "name": "Эфирный Феникс", "emoji": "🔥", "price": 10000, "base_income": 25, "food_price": 2000, "food_increase": 5},
    {"id": 5, "name": "Кристальный Голем", "emoji": "🗿", "price": 20000, "base_income": 50, "food_price": 4000, "food_increase": 10},
    {"id": 6, "name": "Грозовой Грифон", "emoji": "🦅", "price": 35000, "base_income": 90, "food_price": 7000, "food_increase": 15},
    {"id": 7, "name": "Звездный Страж", "emoji": "✨", "price": 50000, "base_income": 130, "food_price": 10000, "food_increase": 20},
    {"id": 8, "name": "Властелин Времени", "emoji": "⏳", "price": 75000, "base_income": 180, "food_price": 15000, "food_increase": 25},
    {"id": 9, "name": "Астральный Левиафан", "emoji": "🐋", "price": 100000, "base_income": 250, "food_price": 20000, "food_increase": 30},
    {"id": 10, "name": "Пылающий Титан", "emoji": "👹", "price": 150000, "base_income": 350, "food_price": 30000, "food_increase": 40},
    {"id": 11, "name": "Ледяной Вихрь", "emoji": "❄️", "price": 200000, "base_income": 480, "food_price": 40000, "food_increase": 50},
    {"id": 12, "name": "Электрический Элементаль", "emoji": "⚡", "price": 300000, "base_income": 650, "food_price": 60000, "food_increase": 60},
    {"id": 13, "name": "Песчаный Гигант", "emoji": "🏜️", "price": 400000, "base_income": 850, "food_price": 80000, "food_increase": 75},
    {"id": 14, "name": "Призрачный Рыцарь", "emoji": "👻", "price": 500000, "base_income": 1100, "food_price": 100000, "food_increase": 90},
    {"id": 15, "name": "Космическая Сфинкс", "emoji": "🐱", "price": 650000, "base_income": 1400, "food_price": 130000, "food_increase": 110},
    {"id": 16, "name": "Хаос-Демон", "emoji": "😈", "price": 800000, "base_income": 1800, "food_price": 160000, "food_increase": 130},
    {"id": 17, "name": "Небесный Херувим", "emoji": "👼", "price": 1000000, "base_income": 2300, "food_price": 200000, "food_increase": 160},
    {"id": 18, "name": "Войд-Пожиратель", "emoji": "🌀", "price": 1300000, "base_income": 3000, "food_price": 260000, "food_increase": 190},
    {"id": 19, "name": "Магический Архимаг", "emoji": "🧙", "price": 1600000, "base_income": 3800, "food_price": 320000, "food_increase": 220},
    {"id": 20, "name": "Изначальный Хаос", "emoji": "🌌", "price": 2000000, "base_income": 5000, "food_price": 400000, "food_increase": 260},
]

def get_winrate(user):
    games = user.get("games", 0)
    wins = user.get("wins", 0)
    return round((wins / games) * 100, 1) if games > 0 else 0

def send_notification_if_needed(user_id, user):
    now = datetime.now()
    last_notify = user.get("last_notify")
    if not last_notify or now - datetime.fromisoformat(last_notify) >= timedelta(days=3):
        winrate = get_winrate(user)
        text = f"""🌙 *Н И К С А Р* 🌙

«Ты снова здесь, странник.  
Эфир не терпит пустоты. Твой баланс — {user['coins']}.  
Твоя тень сыграла {user['games']} игр, из них {user['wins']} — во славу хаоса.»

⚡ Винрейт: {winrate}%  
🌀 Жми на кнопку, чтобы войти."""
        
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🌙 ВОЙТИ", web_app=WebAppInfo(url=WEBAPP_URL)))
        
        if STICKER_ID:
            try:
                bot.send_sticker(int(user_id), STICKER_ID)
            except:
                pass
        
        bot.send_message(int(user_id), text, reply_markup=kb, parse_mode="Markdown")
        user["last_notify"] = now.isoformat()

def collect_pet_income(user_id, pet_id):
    user = users.get(str(user_id))
    if not user or "pets" not in user:
        return 0
    for pet in user["pets"]:
        if pet["id"] == pet_id:
            last = datetime.fromisoformat(pet["last_collect"])
            now = datetime.now()
            hours = (now - last).total_seconds() / 3600
            pet_data = PETS[pet_id-1]
            base = pet_data["base_income"] + (pet["level"]-1) * pet_data["food_increase"]
            earned = int(base * hours)
            if earned > 0:
                user["coins"] += earned
                pet["last_collect"] = now.isoformat()
            return earned
    return 0

def feed_pet(user_id, pet_id):
    user = users.get(str(user_id))
    if not user or "pets" not in user:
        return False, "Нет питомца"
    for pet in user["pets"]:
        if pet["id"] == pet_id:
            pet_data = PETS[pet_id-1]
            cost = pet_data["food_price"] * pet["level"]
            if user["coins"] >= cost:
                user["coins"] -= cost
                pet["level"] += 1
                return True, f"Уровень {pet['level']}"
            return False, f"Нужно {cost} эфира"
    return False, "Ошибка"

def update_alliance_total(alliance_id):
    total = 0
    for uid in alliances[alliance_id]["members"]:
        total += users.get(uid, {}).get("coins", 0)
    alliances[alliance_id]["total_coins"] = total

def get_alliance_leaderboard():
    sorted_all = sorted(alliances.values(), key=lambda x: x["total_coins"], reverse=True)
    return [(a["name"], a["total_coins"]) for a in sorted_all[:10]]

@bot.message_handler(commands=['start'])
def start(message):
    uid = str(message.chat.id)
    name = message.from_user.first_name

    if uid not in users:
        users[uid] = {"coins": 1000, "games": 0, "wins": 0, "pets": [], "alliance_id": None, "last_bonus": None, "last_notify": None}

    user = users[uid]
    winrate = get_winrate(user)

    text = f"""◈ *Н И К С А Р* ◈

«Ты снова здесь, {name}.  
Эфир не терпит пустоты. Твой баланс — {user['coins']}.  
Твоя тень сыграла {user['games']} игр, из них {user['wins']} — во славу хаоса.»

⚡ Винрейт: {winrate}%  
🌀 Жми на кнопку, странник."""

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🌙 ВОЙТИ", web_app=WebAppInfo(url=WEBAPP_URL)))

    if STICKER_ID:
        try:
            bot.send_sticker(uid, STICKER_ID)
        except:
            pass

    bot.send_message(uid, text, reply_markup=kb, parse_mode="Markdown")
    send_notification_if_needed(uid, user)

# ========== API (сокращённо, но полностью рабочий) ==========
@flask_app.route('/web_app/<path:filename>')
def serve_webapp(filename):
    return send_from_directory('web_app', filename)

@flask_app.route('/api', methods=['POST'])
def api():
    data = request.json
    uid = str(data.get('user_id'))
    action = data.get('action')

    if uid not in users:
        users[uid] = {"coins": 1000, "games": 0, "wins": 0, "pets": [], "alliance_id": None, "last_bonus": None, "last_notify": None}
    u = users[uid]

    if action == "profile":
        return jsonify({"coins": u["coins"], "games": u["games"], "wins": u["wins"]})

    elif action == "bonus":
        now = datetime.now()
        last = u.get("last_bonus")
        if last and datetime.fromisoformat(last) > now - timedelta(hours=24):
            return jsonify({"success": False, "message": "Дар уже был сегодня"})
        u["coins"] += 100
        u["last_bonus"] = now.isoformat()
        return jsonify({"success": True, "coins": u["coins"], "message": "+100"})

    elif action == "dice1":
        if u["coins"] < 1:
            return jsonify({"error": "Нет эфира"})
        guess = data.get("guess", 1)
        roll = random.randint(1, 6)
        u["coins"] -= 1
        u["games"] += 1
        if guess == roll:
            win = 3
            u["coins"] += win
            u["wins"] += 1
            return jsonify({"win": True, "roll": roll, "coins": u["coins"], "message": f"+{win}"})
        return jsonify({"win": False, "roll": roll, "coins": u["coins"], "message": "-1"})

    elif action == "dice2":
        if u["coins"] < 1:
            return jsonify({"error": "Нет эфира"})
        guess = data.get("guess", 2)
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2
        u["coins"] -= 1
        u["games"] += 1
        if guess == total:
            win = 5
            u["coins"] += win
            u["wins"] += 1
            return jsonify({"win": True, "dice": [d1, d2], "total": total, "coins": u["coins"], "message": f"+{win}"})
        return jsonify({"win": False, "dice": [d1, d2], "total": total, "coins": u["coins"], "message": "-1"})

    elif action == "rps":
        if u["coins"] < 1:
            return jsonify({"error": "Нет эфира"})
        choice = data.get("choice")
        bot_choice = random.choice(["камень", "ножницы", "бумага"])
        u["coins"] -= 1
        u["games"] += 1
        if choice == bot_choice:
            u["coins"] += 1
            return jsonify({"win": False, "bot": bot_choice, "coins": u["coins"], "message": "0"})
        if (choice == "камень" and bot_choice == "ножницы") or (choice == "ножницы" and bot_choice == "бумага") or (choice == "бумага" and bot_choice == "камень"):
            win = 4
            u["coins"] += win
            u["wins"] += 1
            return jsonify({"win": True, "bot": bot_choice, "coins": u["coins"], "message": f"+{win}"})
        return jsonify({"win": False, "bot": bot_choice, "coins": u["coins"], "message": "-1"})

    elif action == "slots":
        if u["coins"] < 1:
            return jsonify({"error": "Нет эфира"})
        reel = [random.choice(["🍒", "🍊", "🍋", "🔔", "💎", "7️⃣"]) for _ in range(3)]
        u["coins"] -= 1
        u["games"] += 1
        if reel[0] == reel[1] == reel[2] == "7️⃣":
            win = 50
        elif reel[0] == reel[1] == reel[2]:
            win = 20
        elif reel[0] == reel[1] or reel[1] == reel[2] or reel[0] == reel[2]:
            win = 5
        else:
            win = 0
        if win > 0:
            u["coins"] += win
            u["wins"] += 1
            return jsonify({"win": True, "reel": reel, "coins": u["coins"], "message": f"+{win}"})
        return jsonify({"win": False, "reel": reel, "coins": u["coins"], "message": "-1"})

    elif action == "guess":
        if u["coins"] < 1:
            return jsonify({"error": "Нет эфира"})
        guess = data.get("guess", 1)
        secret = random.randint(1, 10)
        u["coins"] -= 1
        u["games"] += 1
        if guess == secret:
            win = 4
            u["coins"] += win
            u["wins"] += 1
            return jsonify({"win": True, "secret": secret, "coins": u["coins"], "message": f"+{win}"})
        return jsonify({"win": False, "secret": secret, "coins": u["coins"], "message": "-1"})

    elif action == "get_pets":
        pets_data = []
        for p in PETS:
            owned = False
            level = 0
            for up in u.get("pets", []):
                if up["id"] == p["id"]:
                    owned = True
                    level = up["level"]
            pets_data.append({"id": p["id"], "name": p["name"], "emoji": p["emoji"], "price": p["price"], "owned": owned, "level": level})
        return jsonify({"pets": pets_data})

    elif action == "buy_pet":
        pet_id = data.get("pet_id")
        pet = PETS[pet_id-1]
        if u["coins"] >= pet["price"]:
            u["coins"] -= pet["price"]
            if "pets" not in u:
                u["pets"] = []
            u["pets"].append({"id": pet_id, "level": 1, "last_collect": datetime.now().isoformat()})
            return jsonify({"success": True, "coins": u["coins"], "message": f"Питомец {pet['name']}"})
        return jsonify({"success": False, "message": "Нет эфира"})

    elif action == "collect_pet":
        pet_id = data.get("pet_id")
        earned = collect_pet_income(uid, pet_id)
        return jsonify({"success": True, "coins": u["coins"], "earned": earned})

    elif action == "feed_pet":
        pet_id = data.get("pet_id")
        ok, msg = feed_pet(uid, pet_id)
        return jsonify({"success": ok, "coins": u["coins"], "message": msg})

    elif action == "alliance_info":
        user_alliance = u.get("alliance_id")
        return jsonify({"alliance_id": user_alliance, "top": get_alliance_leaderboard()})

    elif action == "create_alliance":
        name = data.get("name")
        min_coins = data.get("min_coins", 0)
        global next_alliance_id
        alliances[next_alliance_id] = {"name": name, "owner_id": uid, "min_coins": min_coins, "members": [uid], "total_coins": u["coins"]}
        u["alliance_id"] = next_alliance_id
        next_alliance_id += 1
        return jsonify({"success": True, "alliance_id": next_alliance_id-1})

    elif action == "join_alliance":
        alliance_id = data.get("alliance_id")
        if alliance_id in alliances and u["coins"] >= alliances[alliance_id]["min_coins"]:
            alliances[alliance_id]["members"].append(uid)
            u["alliance_id"] = alliance_id
            update_alliance_total(alliance_id)
            return jsonify({"success": True})
        return jsonify({"success": False})

    return jsonify({"error": "Неизвестное действие"})

def run_flask():
    flask_app.run(host='0.0.0.0', port=5000)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("✅ Бот НИКСАР запущен")
    bot.infinity_polling(skip_pending=True)
