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

# Хранилище пользователей (в памяти)
users = {}

@bot.message_handler(commands=['start'])
def start(message):
    uid = str(message.chat.id)
    name = message.from_user.first_name
    
    if uid not in users:
        users[uid] = {"coins": 100, "games": 0, "wins": 0}
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🎮 ОТКРЫТЬ ИГРУ", web_app=WebAppInfo(url=WEBAPP_URL)))
    
    bot.send_message(uid, 
        f"🎮 *NYXARA GAME*\n\n"
        f"Привет, {name}! 👋\n"
        f"💰 Твой баланс: {users[uid]['coins']} монет\n\n"
        f"🚀 Нажми на кнопку ниже, чтобы начать играть!",
        reply_markup=kb, parse_mode="Markdown")

# ========== API ДЛЯ MINI APP ==========
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
    
    user = users[uid]
    
    if action == "profile":
        return jsonify({
            "coins": user["coins"],
            "total_games": user["games"],
            "total_wins": user["wins"]
        })
    
    elif action == "bonus":
        user["coins"] += 25
        return jsonify({"success": True, "coins": user["coins"], "message": "🎁 +25 монет!"})
    
    elif action == "dice1":
        guess = data.get("guess", 1)
        if user["coins"] < 1:
            return jsonify({"success": False, "message": "❌ Нет монет"})
        
        user["coins"] -= 1
        user["games"] += 1
        roll = random.randint(1, 6)
        
        if guess == roll:
            win = 2
            user["coins"] += win
            user["wins"] += 1
            return jsonify({"success": True, "win": True, "roll": roll, "coins": user["coins"], "message": f"🎲 {roll} Победа! +{win}💰"})
        else:
            return jsonify({"success": True, "win": False, "roll": roll, "coins": user["coins"], "message": f"🎲 {roll} Проигрыш!"})
    
    elif action == "dice2":
        guess = data.get("guess", 2)
        if user["coins"] < 1:
            return jsonify({"success": False, "message": "❌ Нет монет"})
        
        user["coins"] -= 1
        user["games"] += 1
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2
        
        if guess == total:
            win = 3
            user["coins"] += win
            user["wins"] += 1
            return jsonify({"success": True, "win": True, "roll": total, "dice": [d1, d2], "coins": user["coins"], "message": f"🎲 {d1}+{d2}={total} Победа! +{win}💰"})
        else:
            return jsonify({"success": True, "win": False, "roll": total, "dice": [d1, d2], "coins": user["coins"], "message": f"🎲 {d1}+{d2}={total} Проигрыш!"})
    
    elif action == "rps":
        choice = data.get("choice", "")
        choices = ["камень", "ножницы", "бумага"]
        
        if choice not in choices:
            return jsonify({"success": False, "message": "❌ Неверный выбор"})
        
        if user["coins"] < 1:
            return jsonify({"success": False, "message": "❌ Нет монет"})
        
        user["coins"] -= 1
        user["games"] += 1
        bot_choice = random.choice(choices)
        
        if choice == bot_choice:
            user["coins"] += 1
            return jsonify({"success": True, "win": False, "bot": bot_choice, "coins": user["coins"], "message": f"🤝 Ничья! Бот выбрал {bot_choice}"})
        elif (choice == "камень" and bot_choice == "ножницы") or (choice == "ножницы" and bot_choice == "бумага") or (choice == "бумага" and bot_choice == "камень"):
            win = random.randint(3, 5)
            user["coins"] += win
            user["wins"] += 1
            return jsonify({"success": True, "win": True, "bot": bot_choice, "coins": user["coins"], "message": f"🎉 Победа! Бот выбрал {bot_choice} +{win}💰"})
        else:
            return jsonify({"success": True, "win": False, "bot": bot_choice, "coins": user["coins"], "message": f"💀 Поражение! Бот выбрал {bot_choice}"})
    
    elif action == "slots":
        if user["coins"] < 1:
            return jsonify({"success": False, "message": "❌ Нет монет"})
        
        user["coins"] -= 1
        user["games"] += 1
        reel = [random.choice(["🍒", "🍊", "🍋", "🔔", "💎", "7️⃣"]) for _ in range(3)]
        
        if reel[0] == reel[1] == reel[2] == "7️⃣":
            win = 50
        elif reel[0] == reel[1] == reel[2]:
            win = 20
        elif reel[0] == reel[1] or reel[1] == reel[2] or reel[0] == reel[2]:
            win = 5
        else:
            win = 0
        
        if win > 0:
            user["coins"] += win
            user["wins"] += 1
            return jsonify({"success": True, "win": True, "reel": reel, "coins": user["coins"], "message": f"🎰 {reel[0]}|{reel[1]}|{reel[2]} Победа! +{win}💰"})
        else:
            return jsonify({"success": True, "win": False, "reel": reel, "coins": user["coins"], "message": f"🎰 {reel[0]}|{reel[1]}|{reel[2]} Проигрыш!"})
    
    elif action == "guess_number":
        guess = data.get("guess", 1)
        if user["coins"] < 1:
            return jsonify({"success": False, "message": "❌ Нет монет"})
        
        user["coins"] -= 1
        user["games"] += 1
        secret = random.randint(1, 10)
        
        if guess == secret:
            win = 3
            user["coins"] += win
            user["wins"] += 1
            return jsonify({"success": True, "win": True, "secret": secret, "coins": user["coins"], "message": f"🔢 {secret} Победа! +{win}💰"})
        else:
            return jsonify({"success": True, "win": False, "secret": secret, "coins": user["coins"], "message": f"🔢 {secret} Проигрыш!"})
    
    return jsonify({"success": False, "message": "Неизвестное действие"})

# ========== ЗАПУСК ==========
def run_flask():
    flask_app.run(host='0.0.0.0', port=5000)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print(f"✅ Бот запущен! Mini App: {WEBAPP_URL}")
    bot.infinity_polling(skip_pending=True)
