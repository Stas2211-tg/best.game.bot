import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from flask import Flask, send_from_directory, request, jsonify
import threading
import random
import os

TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 123456789))
DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "localhost:5000")
WEBAPP_URL = f"https://{DOMAIN}/web_app/index.html"

bot = telebot.TeleBot(TOKEN)
flask_app = Flask(__name__, static_folder='web_app', static_url_path='')

users = {}

@bot.message_handler(commands=['start'])
def start(message):
    uid = str(message.chat.id)
    name = message.from_user.first_name
    
    if uid not in users:
        users[uid] = {"coins": 100, "games": 0, "wins": 0}
    
    text = f"""⚡ *N Y X A R A* ⚡

Привет, *{name}*.

💰 Баланс: `{users[uid]['coins']}` монет

🎮 Нажми на кнопку, чтобы войти в игру."""
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🚀 ВОЙТИ В ИГРУ", web_app=WebAppInfo(url=WEBAPP_URL)))
    
    bot.send_message(uid, text, reply_markup=kb, parse_mode="Markdown")

# API
@flask_app.route('/web_app/<path:filename>')
def serve_webapp(filename):
    return send_from_directory('web_app', filename)

@flask_app.route('/api', methods=['POST'])
def api():
    data = request.json
    uid = str(data.get('user_id'))
    action = data.get('action')
    
    if uid not in users:
        users[uid] = {"coins": 100, "games": 0, "wins": 0}
    
    u = users[uid]
    
    if action == "profile":
        return jsonify({
            "coins": u["coins"],
            "games": u["games"],
            "wins": u["wins"]
        })
    
    elif action == "bonus":
        u["coins"] += 25
        return jsonify({"success": True, "coins": u["coins"], "message": "+25"})
    
    elif action == "dice1":
        if u["coins"] < 1:
            return jsonify({"success": False, "message": "Нет монет"})
        u["coins"] -= 1
        u["games"] += 1
        roll = random.randint(1, 6)
        if data.get("guess") == roll:
            win = 2
            u["coins"] += win
            u["wins"] += 1
            return jsonify({"success": True, "win": True, "roll": roll, "coins": u["coins"], "message": f"+{win}"})
        return jsonify({"success": True, "win": False, "roll": roll, "coins": u["coins"], "message": "-1"})
    
    elif action == "dice2":
        if u["coins"] < 1:
            return jsonify({"success": False, "message": "Нет монет"})
        u["coins"] -= 1
        u["games"] += 1
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2
        if data.get("guess") == total:
            win = 3
            u["coins"] += win
            u["wins"] += 1
            return jsonify({"success": True, "win": True, "roll": total, "dice": [d1, d2], "coins": u["coins"], "message": f"+{win}"})
        return jsonify({"success": True, "win": False, "roll": total, "dice": [d1, d2], "coins": u["coins"], "message": "-1"})
    
    elif action == "rps":
        if u["coins"] < 1:
            return jsonify({"success": False, "message": "Нет монет"})
        u["coins"] -= 1
        u["games"] += 1
        choice = data.get("choice")
        bot_choice = random.choice(["камень", "ножницы", "бумага"])
        if choice == bot_choice:
            u["coins"] += 1
            return jsonify({"success": True, "win": False, "bot": bot_choice, "coins": u["coins"], "message": "0"})
        if (choice == "камень" and bot_choice == "ножницы") or (choice == "ножницы" and bot_choice == "бумага") or (choice == "бумага" and bot_choice == "камень"):
            win = 3
            u["coins"] += win
            u["wins"] += 1
            return jsonify({"success": True, "win": True, "bot": bot_choice, "coins": u["coins"], "message": f"+{win}"})
        return jsonify({"success": True, "win": False, "bot": bot_choice, "coins": u["coins"], "message": "-1"})
    
    elif action == "slots":
        if u["coins"] < 1:
            return jsonify({"success": False, "message": "Нет монет"})
        u["coins"] -= 1
        u["games"] += 1
        reel = [random.choice(["🍒", "🍊", "🍋", "🔔", "💎", "7️⃣"]) for _ in range(3)]
        win = 0
        if reel[0] == reel[1] == reel[2] == "7️⃣":
            win = 50
        elif reel[0] == reel[1] == reel[2]:
            win = 20
        elif reel[0] == reel[1] or reel[1] == reel[2] or reel[0] == reel[2]:
            win = 5
        if win > 0:
            u["coins"] += win
            u["wins"] += 1
            return jsonify({"success": True, "win": True, "reel": reel, "coins": u["coins"], "message": f"+{win}"})
        return jsonify({"success": True, "win": False, "reel": reel, "coins": u["coins"], "message": "-1"})
    
    elif action == "guess":
        if u["coins"] < 1:
            return jsonify({"success": False, "message": "Нет монет"})
        u["coins"] -= 1
        u["games"] += 1
        secret = random.randint(1, 10)
        if data.get("guess") == secret:
            win = 3
            u["coins"] += win
            u["wins"] += 1
            return jsonify({"success": True, "win": True, "secret": secret, "coins": u["coins"], "message": f"+{win}"})
        return jsonify({"success": True, "win": False, "secret": secret, "coins": u["coins"], "message": "-1"})
    
    elif action == "clan_create":
        return jsonify({"success": False, "message": "Скоро"})
    
    return jsonify({"success": False, "message": "Ошибка"})

def run_flask():
    flask_app.run(host='0.0.0.0', port=5000)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("✅ NYXARA GAME запущен")
    bot.infinity_polling(skip_pending=True)
