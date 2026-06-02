import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from flask import Flask, send_from_directory, request, jsonify
import threading
import random
import os
import json
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import redis

# ========== НАСТРОЙКИ ==========
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    print("❌ Токен не найден")
    exit(1)

ADMIN_ID = int(os.getenv("ADMIN_ID", 123456789))
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")
DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN", "localhost:5000")
WEBAPP_URL = f"https://{DOMAIN}/web_app/index.html"

bot = telebot.TeleBot(TOKEN)
flask_app = Flask(__name__, static_folder='web_app', static_url_path='')

# ========== БАЗА ДАННЫХ ==========
r = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            coins INTEGER DEFAULT 100,
            last_bonus TEXT,
            username TEXT,
            region TEXT,
            referrer TEXT,
            total_games INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            user_id TEXT,
            referrer_id TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clans (
            clan_id SERIAL PRIMARY KEY,
            name TEXT UNIQUE,
            emoji TEXT,
            owner_id TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clan_members (
            user_id TEXT PRIMARY KEY,
            clan_id INTEGER,
            joined_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS group_roles (
            group_id TEXT,
            user_id TEXT,
            role TEXT,
            PRIMARY KEY (group_id, user_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS group_bans (
            group_id TEXT,
            user_id TEXT,
            banned_until TIMESTAMP,
            reason TEXT,
            PRIMARY KEY (group_id, user_id)
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# ========== ВСПОМОГАТЕЛЬНЫЕ ==========
def get_user(uid):
    uid = str(uid)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    if not u:
        cur.execute("INSERT INTO users (user_id, coins) VALUES (%s, 100)", (uid,))
        conn.commit()
        cur.execute("SELECT * FROM users WHERE user_id = %s", (uid,))
        u = cur.fetchone()
    cur.close()
    conn.close()
    return u

def update_user(uid, **kwargs):
    uid = str(uid)
    conn = get_db_connection()
    cur = conn.cursor()
    for k, v in kwargs.items():
        cur.execute(f"UPDATE users SET {k} = %s WHERE user_id = %s", (v, uid))
    conn.commit()
    cur.close()
    conn.close()

def add_coins(uid, amount):
    u = get_user(uid)
    new = u["coins"] + amount
    update_user(uid, coins=new)
    return new

def remove_coins(uid, amount):
    u = get_user(uid)
    if u["coins"] >= amount:
        update_user(uid, coins=u["coins"] - amount)
        return True
    return False

def can_take_bonus(uid):
    u = get_user(uid)
    if not u["last_bonus"]:
        return True
    return datetime.now() - datetime.fromisoformat(u["last_bonus"]) >= timedelta(hours=24)

def all_users_list():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    return [row[0] for row in cur.fetchall()]

# ========== КЛАНЫ ==========
def create_clan(owner_id, name, emoji):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO clans (name, emoji, owner_id) VALUES (%s, %s, %s) RETURNING clan_id", (name, emoji, str(owner_id)))
        clan_id = cur.fetchone()[0]
        cur.execute("INSERT INTO clan_members (user_id, clan_id) VALUES (%s, %s)", (str(owner_id), clan_id))
        conn.commit()
        cur.close()
        conn.close()
        return clan_id
    except:
        conn.rollback()
        cur.close()
        conn.close()
        return None

def get_user_clan(user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT clan_id FROM clan_members WHERE user_id = %s", (str(user_id),))
    m = cur.fetchone()
    cur.close()
    conn.close()
    if not m:
        return None
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM clans WHERE clan_id = %s", (m["clan_id"],))
    clan = cur.fetchone()
    cur.close()
    conn.close()
    return clan

def join_clan(user_id, clan_id):
    if get_user_clan(user_id):
        return False, "❌ Ты уже в клане"
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO clan_members (user_id, clan_id) VALUES (%s, %s)", (str(user_id), clan_id))
        conn.commit()
        cur.close()
        conn.close()
        return True, "✅ Ты вступил в клан!"
    except:
        conn.rollback()
        cur.close()
        conn.close()
        return False, "❌ Ошибка"

def leave_clan(user_id):
    if not get_user_clan(user_id):
        return False, "❌ Ты не в клане"
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM clan_members WHERE user_id = %s", (str(user_id),))
    conn.commit()
    cur.close()
    conn.close()
    return True, "✅ Ты покинул клан!"

# ========== РЕФЕРАЛЫ ==========
def get_referral_link(uid):
    return f"https://t.me/{bot.get_me().username}?start=ref_{uid}"

def process_referral(new_uid, ref_id):
    if str(new_uid) == str(ref_id):
        return False
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM referrals WHERE user_id = %s", (str(new_uid),))
    if cur.fetchone():
        cur.close()
        conn.close()
        return False
    cur.execute("INSERT INTO referrals (user_id, referrer_id) VALUES (%s,%s)", (str(new_uid), str(ref_id)))
    add_coins(new_uid, 10)
    add_coins(ref_id, 20)
    conn.commit()
    cur.close()
    conn.close()
    return True

def get_referral_stats(uid):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = %s", (str(uid),))
    return cur.fetchone()[0]

# ========== ГРУППОВЫЕ РОЛИ ==========
def get_group_role(chat_id, user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT role FROM group_roles WHERE group_id = %s AND user_id = %s", (str(chat_id), str(user_id)))
    r = cur.fetchone()
    cur.close()
    conn.close()
    return r[0] if r else "member"

def set_group_role(chat_id, user_id, role):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO group_roles (group_id, user_id, role) VALUES (%s,%s,%s) ON CONFLICT (group_id, user_id) DO UPDATE SET role = EXCLUDED.role", (str(chat_id), str(user_id), role))
    conn.commit()
    cur.close()
    conn.close()

def remove_group_role(chat_id, user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM group_roles WHERE group_id = %s AND user_id = %s", (str(chat_id), str(user_id)))
    conn.commit()
    cur.close()
    conn.close()

def ban_user(chat_id, user_id, duration, reason=""):
    conn = get_db_connection()
    cur = conn.cursor()
    banned_until = datetime.now() + timedelta(seconds=duration) if duration != -1 else None
    cur.execute("INSERT INTO group_bans (group_id, user_id, banned_until, reason) VALUES (%s,%s,%s,%s) ON CONFLICT (group_id, user_id) DO UPDATE SET banned_until = EXCLUDED.banned_until, reason = EXCLUDED.reason", (str(chat_id), str(user_id), banned_until, reason))
    conn.commit()
    cur.close()
    conn.close()

def is_banned(chat_id, user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT banned_until FROM group_bans WHERE group_id = %s AND user_id = %s", (str(chat_id), str(user_id)))
    r = cur.fetchone()
    cur.close()
    conn.close()
    if not r:
        return False
    if r[0] is None:
        return True
    return datetime.now() < r[0]

def unban_user(chat_id, user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM group_bans WHERE group_id = %s AND user_id = %s", (str(chat_id), str(user_id)))
    conn.commit()
    cur.close()
    conn.close()

# ========== ОСНОВНЫЕ КОМАНДЫ ==========
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.chat.id
    name = message.from_user.first_name
    args = message.text.split()
    
    if len(args) > 1 and args[1].startswith("ref_"):
        process_referral(uid, args[1].split("_")[1])
    
    u = get_user(uid)
    
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🎮 ОТКРЫТЬ ИГРУ", web_app=WebAppInfo(url=WEBAPP_URL)))
    
    bot.send_message(uid, 
        f"🎮 *НИКСАР ГЕЙМ*\n\n"
        f"Привет, {name}! 👋\n"
        f"💰 Твой баланс: {u['coins']} монет\n\n"
        f"🚀 Нажми на кнопку ниже,\n"
        f"чтобы начать играть!",
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
    
    user = get_user(uid)
    
    # Профиль
    if action == "profile":
        return jsonify({
            "coins": user["coins"],
            "total_games": user.get("total_games", 0),
            "total_wins": user.get("total_wins", 0),
            "username": user.get("username", "Игрок")
        })
    
    # Бонус
    elif action == "bonus":
        if can_take_bonus(uid):
            add_coins(uid, 25)
            update_user(uid, last_bonus=datetime.now().isoformat())
            u = get_user(uid)
            return jsonify({"success": True, "coins": u["coins"], "message": "🎁 +25 монет!"})
        else:
            return jsonify({"success": False, "message": "⏳ Бонус уже получен"})
    
    # ИГРА: 1 кубик
    elif action == "dice1":
        bet = data.get("bet", 1)
        guess = data.get("guess", 1)
        
        if not remove_coins(uid, bet):
            return jsonify({"success": False, "message": "❌ Нет монет"})
        
        roll = random.randint(1, 6)
        user = get_user(uid)
        new_games = user.get("total_games", 0) + 1
        
        if guess == roll:
            win = bet * 2
            add_coins(uid, win)
            update_user(uid, total_games=new_games, total_wins=user.get("total_wins", 0) + 1)
            user = get_user(uid)
            return jsonify({
                "success": True, 
                "win": True, 
                "roll": roll, 
                "coins": user["coins"],
                "message": f"🎲 {roll} Победа! +{win}💰"
            })
        else:
            update_user(uid, total_games=new_games)
            user = get_user(uid)
            return jsonify({
                "success": True, 
                "win": False, 
                "roll": roll, 
                "coins": user["coins"],
                "message": f"🎲 {roll} Проигрыш! -{bet}💰"
            })
    
    # ИГРА: 2 кубика
    elif action == "dice2":
        bet = data.get("bet", 1)
        guess = data.get("guess", 2)
        
        if not remove_coins(uid, bet):
            return jsonify({"success": False, "message": "❌ Нет монет"})
        
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2
        user = get_user(uid)
        new_games = user.get("total_games", 0) + 1
        
        if guess == total:
            win = bet * 3
            add_coins(uid, win)
            update_user(uid, total_games=new_games, total_wins=user.get("total_wins", 0) + 1)
            user = get_user(uid)
            return jsonify({
                "success": True, "win": True, "roll": total, "dice": [d1, d2],
                "coins": user["coins"],
                "message": f"🎲 {d1}+{d2}={total} Победа! +{win}💰"
            })
        else:
            update_user(uid, total_games=new_games)
            user = get_user(uid)
            return jsonify({
                "success": True, "win": False, "roll": total, "dice": [d1, d2],
                "coins": user["coins"],
                "message": f"🎲 {d1}+{d2}={total} Проигрыш! -{bet}💰"
            })
    
    # ИГРА: Камень-ножницы-бумага
    elif action == "rps":
        choice = data.get("choice", "")
        choices = ["камень", "ножницы", "бумага"]
        
        if choice not in choices:
            return jsonify({"success": False, "message": "❌ Неверный выбор"})
        
        if not remove_coins(uid, 1):
            return jsonify({"success": False, "message": "❌ Нет монет"})
        
        bot_choice = random.choice(choices)
        user = get_user(uid)
        new_games = user.get("total_games", 0) + 1
        
        if choice == bot_choice:
            add_coins(uid, 1)
            update_user(uid, total_games=new_games)
            user = get_user(uid)
            return jsonify({
                "success": True, "win": False, "bot": bot_choice,
                "coins": user["coins"],
                "message": f"🤝 Ничья! Бот выбрал {bot_choice}"
            })
        elif (choice == "камень" and bot_choice == "ножницы") or \
             (choice == "ножницы" and bot_choice == "бумага") or \
             (choice == "бумага" and bot_choice == "камень"):
            win = random.randint(3, 7)
            add_coins(uid, win)
            update_user(uid, total_games=new_games, total_wins=user.get("total_wins", 0) + 1)
            user = get_user(uid)
            return jsonify({
                "success": True, "win": True, "bot": bot_choice,
                "coins": user["coins"],
                "message": f"🎉 Победа! Бот выбрал {bot_choice} +{win}💰"
            })
        else:
            update_user(uid, total_games=new_games)
            user = get_user(uid)
            return jsonify({
                "success": True, "win": False, "bot": bot_choice,
                "coins": user["coins"],
                "message": f"💀 Поражение! Бот выбрал {bot_choice}"
            })
    
    # ИГРА: Слоты
    elif action == "slots":
        if not remove_coins(uid, 1):
            return jsonify({"success": False, "message": "❌ Нет монет"})
        
        reel = [random.choice(["🍒", "🍊", "🍋", "🔔", "💎", "7️⃣"]) for _ in range(3)]
        user = get_user(uid)
        new_games = user.get("total_games", 0) + 1
        
        if reel[0] == reel[1] == reel[2] == "7️⃣":
            win = 50
        elif reel[0] == reel[1] == reel[2]:
            win = 20
        elif reel[0] == reel[1] or reel[1] == reel[2] or reel[0] == reel[2]:
            win = 5
        else:
            win = 0
        
        if win > 0:
            add_coins(uid, win)
            update_user(uid, total_games=new_games, total_wins=user.get("total_wins", 0) + 1)
            user = get_user(uid)
            return jsonify({
                "success": True, "win": True, "reel": reel, "coins": user["coins"],
                "message": f"🎰 {reel[0]}|{reel[1]}|{reel[2]} Победа! +{win}💰"
            })
        else:
            update_user(uid, total_games=new_games)
            user = get_user(uid)
            return jsonify({
                "success": True, "win": False, "reel": reel, "coins": user["coins"],
                "message": f"🎰 {reel[0]}|{reel[1]}|{reel[2]} Проигрыш!"
            })
    
    # ИГРА: Угадай число (1-10)
    elif action == "guess_number":
        bet = data.get("bet", 1)
        guess = data.get("guess", 1)
        
        if not remove_coins(uid, bet):
            return jsonify({"success": False, "message": "❌ Нет монет"})
        
        secret = random.randint(1, 10)
        user = get_user(uid)
        new_games = user.get("total_games", 0) + 1
        
        if guess == secret:
            win = bet * 3
            add_coins(uid, win)
            update_user(uid, total_games=new_games, total_wins=user.get("total_wins", 0) + 1)
            user = get_user(uid)
            return jsonify({
                "success": True, "win": True, "secret": secret, "coins": user["coins"],
                "message": f"🔢 {secret} Победа! +{win}💰"
            })
        else:
            update_user(uid, total_games=new_games)
            user = get_user(uid)
            return jsonify({
                "success": True, "win": False, "secret": secret, "coins": user["coins"],
                "message": f"🔢 {secret} Проигрыш! -{bet}💰"
            })
    
    # КЛАНЫ
    elif action == "get_clan":
        clan = get_user_clan(uid)
        if clan:
            return jsonify({
                "success": True,
                "has_clan": True,
                "clan": {"name": clan["name"], "emoji": clan["emoji"], "owner_id": clan["owner_id"]}
            })
        else:
            return jsonify({"success": True, "has_clan": False})
    
    elif action == "create_clan":
        name = data.get("name", "")
        emoji = data.get("emoji", "")
        
        if get_user_clan(uid):
            return jsonify({"success": False, "message": "❌ Ты уже в клане"})
        
        clan_id = create_clan(uid, name, emoji)
        if clan_id:
            return jsonify({"success": True, "message": f"✅ Клан {name} создан!"})
        else:
            return jsonify({"success": False, "message": "❌ Клан с таким названием уже существует"})
    
    elif action == "join_clan":
        clan_id = data.get("clan_id")
        ok, msg = join_clan(uid, clan_id)
        return jsonify({"success": ok, "message": msg})
    
    elif action == "leave_clan":
        ok, msg = leave_clan(uid)
        return jsonify({"success": ok, "message": msg})
    
    # РЕФЕРАЛЫ
    elif action == "referrals":
        link = get_referral_link(uid)
        count = get_referral_stats(uid)
        return jsonify({"success": True, "link": link, "count": count})
    
    return jsonify({"success": False, "message": "Неизвестное действие"})

# ========== ЗАПУСК ==========
def run_flask():
    flask_app.run(host='0.0.0.0', port=5000)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print(f"✅ Бот запущен! Mini App: {WEBAPP_URL}")
    bot.infinity_polling(skip_pending=True)
