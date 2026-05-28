import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import random
import os
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import redis
import json
import threading
import time

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    print("❌ Токен не найден")
    exit(1)

ADMIN_ID = int(os.getenv("ADMIN_ID", 123456789))
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

bot = telebot.TeleBot(TOKEN)

# Хранилища
waiting_for_question = {}
group_bonus_tracker = {}
group_game_sessions = {}
buy_amount_buffer = {}
last_message_ids = {}
group_roles = {}
group_bans = {}
pig_scores = {}
jackpot_data = {"total": 0}
game_waiting = {}  # Для ожидания ввода в играх

# ========== REDIS ==========
r = redis.from_url(REDIS_URL, decode_responses=True)

def get_user_cache(uid):
    data = r.get(f"user:{uid}")
    return json.loads(data) if data else None

def set_user_cache(uid, user_data):
    r.setex(f"user:{uid}", 600, json.dumps(user_data))

def delete_user_cache(uid):
    r.delete(f"user:{uid}")

# ========== БАЗА ДАННЫХ ==========
def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            coins INTEGER DEFAULT 50,
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
        CREATE TABLE IF NOT EXISTS businesses (
            user_id TEXT,
            business_type TEXT,
            amount_level INTEGER DEFAULT 1,
            speed_level INTEGER DEFAULT 1,
            last_collect TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (user_id, business_type)
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
def delete_previous_message(chat_id, user_id):
    if user_id in last_message_ids:
        try:
            bot.delete_message(chat_id, last_message_ids[user_id])
        except:
            pass

def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown", user_id=None):
    msg = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    if user_id:
        last_message_ids[user_id] = msg.message_id
    return msg

def edit_message(chat_id, message_id, text, reply_markup=None, parse_mode="Markdown"):
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup, parse_mode=parse_mode)
    except:
        pass

def get_user(uid):
    uid = str(uid)
    cached = get_user_cache(uid)
    if cached:
        return cached
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE user_id = %s", (uid,))
    u = cur.fetchone()
    if not u:
        cur.execute("INSERT INTO users (user_id, coins, total_games, total_wins) VALUES (%s, 50, 0, 0)", (uid,))
        conn.commit()
        cur.execute("SELECT * FROM users WHERE user_id = %s", (uid,))
        u = cur.fetchone()
    cur.close()
    conn.close()
    set_user_cache(uid, u)
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
    delete_user_cache(uid)

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

def format_profile(uid):
    u = get_user(uid)
    region = u.get("region") or "❓"
    return (f"┌─────────────────────┐\n"
            f"│  👤 *{u.get('username') or 'Игрок'}*\n"
            f"│  💰 Баланс: `{u['coins']}` монет\n"
            f"│  📍 Регион: {region}\n"
            f"│  🎮 Всего игр: {u.get('total_games', 0)}\n"
            f"│  🏆 Побед: {u.get('total_wins', 0)}\n"
            f"└─────────────────────┘")

# ========== КЛАВИАТУРЫ ==========
REGIONS = ["🇷🇺 Россия", "🇺🇦 Украина", "🇧🇾 Беларусь", "🇰🇿 Казахстан"]

def main_menu(user_id=None):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎮 Игры", callback_data="menu_games"),
        InlineKeyboardButton("💰 Фермы", callback_data="menu_farms"),
        InlineKeyboardButton("👤 Профиль", callback_data="menu_profile"),
        InlineKeyboardButton("🎁 Бонус", callback_data="menu_bonus"),
        InlineKeyboardButton("👥 Рефералы", callback_data="menu_refs"),
        InlineKeyboardButton("👥 Кланы", callback_data="menu_clans"),
        InlineKeyboardButton("❓ Вопрос", callback_data="menu_question")
    )
    if user_id and str(user_id) == str(ADMIN_ID):
        kb.add(InlineKeyboardButton("🔧 Админ", callback_data="menu_admin"))
    return kb

def games_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎲 1 кубик", callback_data="game_dice1"),
        InlineKeyboardButton("🎲🎲 2 кубика", callback_data="game_dice2"),
        InlineKeyboardButton("🎲🎲🎲 3 кубика", callback_data="game_dice3"),
        InlineKeyboardButton("🔢 Угадай число", callback_data="game_number"),
        InlineKeyboardButton("✂️ Камень-ножницы", callback_data="game_rps"),
        InlineKeyboardButton("🎰 Слоты", callback_data="game_slots"),
        InlineKeyboardButton("🎲 Чет/Нечет", callback_data="game_evenodd"),
        InlineKeyboardButton("🎲 Свинья", callback_data="game_pig"),
        InlineKeyboardButton("🎰 Джекпот", callback_data="game_jackpot"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    return kb

def farms_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🛒 Купить ферму", callback_data="farm_buy"),
        InlineKeyboardButton("🏭 Мои фермы", callback_data="farm_list"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    return kb

def admin_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("💰 Выдать монеты", callback_data="admin_add"),
        InlineKeyboardButton("🔻 Забрать монеты", callback_data="admin_remove"),
        InlineKeyboardButton("👥 Все пользователи", callback_data="admin_users"),
        InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    return kb

def play_again(game):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎮 Сыграть ещё", callback_data=f"again_{game}"),
        InlineKeyboardButton("🎮 Меню игр", callback_data="menu_games"),
        InlineKeyboardButton("◀️ Главное меню", callback_data="back_main")
    )
    return kb

# ========== ФЕРМЫ ==========
BUSINESSES = {
    "🌾 Ферма": {"price": 100, "income": 10},
    "⛏️ Шахта": {"price": 500, "income": 50},
    "🏭 Фабрика": {"price": 2000, "income": 200},
    "💻 IT-компания": {"price": 10000, "income": 1000},
    "🚀 Космодром": {"price": 50000, "income": 5000}
}

def get_user_businesses(uid):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM businesses WHERE user_id = %s", (str(uid),))
    return cur.fetchall()

def get_business(uid, biz_type):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM businesses WHERE user_id = %s AND business_type = %s", (str(uid), biz_type))
    b = cur.fetchone()
    cur.close()
    conn.close()
    return b

def collect_income(uid, biz_type):
    b = get_business(uid, biz_type)
    if not b:
        return 0, "❌ Нет фермы"
    last = b["last_collect"]
    now = datetime.now()
    hours = (now - last).total_seconds() / 3600
    if hours < 1:
        return 0, f"⏳ Минимум 1 час (прошло {hours:.1f}ч)"
    income = BUSINESSES[biz_type]["income"] * b["amount_level"] * hours
    total = int(income)
    add_coins(uid, total)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE businesses SET last_collect = %s WHERE user_id = %s AND business_type = %s", (now, str(uid), biz_type))
    conn.commit()
    cur.close()
    conn.close()
    return total, f"✅ Собрано {total}💰 с {biz_type}"

def buy_business(uid, biz_type):
    if get_business(uid, biz_type):
        return False, "❌ Уже есть"
    price = BUSINESSES[biz_type]["price"]
    if not remove_coins(uid, price):
        return False, f"❌ Нужно {price}💰"
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO businesses (user_id, business_type, amount_level, speed_level, last_collect) VALUES (%s, %s, 1, 1, NOW())", (str(uid), biz_type))
    conn.commit()
    cur.close()
    conn.close()
    return True, f"✅ {biz_type} куплена!"

def upgrade_business(uid, biz_type):
    b = get_business(uid, biz_type)
    if not b:
        return False, "❌ Нет фермы"
    cost = BUSINESSES[biz_type]["price"] * b["amount_level"]
    if not remove_coins(uid, cost):
        return False, f"❌ Нужно {cost}💰"
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE businesses SET amount_level = amount_level + 1 WHERE user_id = %s AND business_type = %s", (str(uid), biz_type))
    conn.commit()
    cur.close()
    conn.close()
    return True, f"✅ Уровень {b['amount_level']+1}!"

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

# ========== ИГРЫ ==========
def update_stats(uid, won):
    u = get_user(uid)
    update_user(uid, total_games=u.get("total_games", 0) + 1, total_wins=u.get("total_wins", 0) + (1 if won else 0))

def game_dice(uid, num_dice, bet_range, win_min, win_max, game_name, message):
    try:
        bet = int(message.text)
        if bet < bet_range[0] or bet > bet_range[1]:
            send_message(message.chat.id, f"❌ Введи число от {bet_range[0]} до {bet_range[1]}", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_message(message.chat.id, "❌ Нет монет", user_id=uid)
            return
        rolls = [random.randint(1, 6) for _ in range(num_dice)]
        total = sum(rolls)
        if bet == total:
            win = random.randint(win_min, win_max)
            add_coins(uid, win)
            text = f"🎲 {total}. Победа! +{win}💰"
            update_stats(uid, True)
        else:
            text = f"🎲 {total}. Проигрыш! -1💰"
            update_stats(uid, False)
        send_message(message.chat.id, text, reply_markup=play_again(game_name), parse_mode="Markdown", user_id=uid)
    except ValueError:
        send_message(message.chat.id, "❌ Введи число!", user_id=uid)

def game_number(uid, message):
    try:
        bet = int(message.text)
        if bet < 1 or bet > 10:
            send_message(message.chat.id, "❌ 1–10", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_message(message.chat.id, "❌ Нет монет", user_id=uid)
            return
        num = random.randint(1, 10)
        if bet == num:
            win = random.randint(5, 10)
            add_coins(uid, win)
            text = f"🔢 {num}. Победа! +{win}💰"
            update_stats(uid, True)
        else:
            text = f"🔢 {num}. Проигрыш! -1💰"
            update_stats(uid, False)
        send_message(message.chat.id, text, reply_markup=play_again("game_number"), parse_mode="Markdown", user_id=uid)
    except ValueError:
        send_message(message.chat.id, "❌ Введи число!", user_id=uid)

def game_rps(uid, message):
    choice = message.text.lower()
    if choice not in ["камень", "ножницы", "бумага"]:
        send_message(message.chat.id, "❌ камень/ножницы/бумага", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_message(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    bot_choice = random.choice(["камень", "ножницы", "бумага"])
    if choice == bot_choice:
        add_coins(uid, 2)
        text = f"🤝 Ничья! +2💰"
        update_stats(uid, False)
    elif (choice == "камень" and bot_choice == "ножницы") or (choice == "ножницы" and bot_choice == "бумага") or (choice == "бумага" and bot_choice == "камень"):
        win = random.randint(3, 7)
        add_coins(uid, win)
        text = f"🎉 Победа! +{win}💰"
        update_stats(uid, True)
    else:
        text = f"💀 Поражение! -1💰"
        update_stats(uid, False)
    send_message(message.chat.id, text, reply_markup=play_again("game_rps"), parse_mode="Markdown", user_id=uid)

def game_slots(uid, message_id, chat_id):
    delete_previous_message(chat_id, uid)
    if not remove_coins(uid, 1):
        send_message(chat_id, "❌ Нет монет", user_id=uid)
        return
    r = [random.choice(["🍒", "🍊", "🍋", "🔔", "💎", "7️⃣"]) for _ in range(3)]
    if r[0] == r[1] == r[2] == "7️⃣":
        win = 50
    elif r[0] == r[1] == r[2]:
        win = 20
    elif r[0] == r[1] or r[1] == r[2] or r[0] == r[2]:
        win = 5
    else:
        win = 0
    if win:
        add_coins(uid, win)
        text = f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n🎉 +{win}💰"
        update_stats(uid, True)
    else:
        text = f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n💀 -1💰"
        update_stats(uid, False)
    send_message(chat_id, text, reply_markup=play_again("game_slots"), parse_mode="Markdown", user_id=uid)

def game_evenodd(uid, message):
    ch = message.text.lower()
    if ch not in ["чётное", "нечётное", "четное", "нечетное"]:
        send_message(message.chat.id, "❌ чётное или нечётное", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_message(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    num = random.randint(1, 10)
    is_even = num % 2 == 0
    correct = "чётное" if is_even else "нечётное"
    if (ch in ["чётное", "четное"] and is_even) or (ch in ["нечётное", "нечетное"] and not is_even):
        win = random.randint(3, 5)
        add_coins(uid, win)
        text = f"🎲 {num} ({correct}). Победа! +{win}💰"
        update_stats(uid, True)
    else:
        text = f"🎲 {num} ({correct}). Поражение! -1💰"
        update_stats(uid, False)
    send_message(message.chat.id, text, reply_markup=play_again("game_evenodd"), parse_mode="Markdown", user_id=uid)

def game_pig(uid, message):
    delete_previous_message(message.chat.id, uid)
    if not remove_coins(uid, 1):
        send_message(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    pig_scores[uid] = 0
    game_pig_roll(uid, message.chat.id)

def game_pig_roll(uid, chat_id):
    roll = random.randint(1, 6)
    if roll == 1:
        score = pig_scores.pop(uid, 0)
        send_message(chat_id, f"🎲 Выпало 1! Ты теряешь всё.", reply_markup=play_again("game_pig"), parse_mode="Markdown", user_id=uid)
        update_stats(uid, False)
        return
    pig_scores[uid] += roll
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("🎲 Бросить ещё", callback_data="pig_continue"),
        InlineKeyboardButton("💰 Забрать", callback_data="pig_take"),
        InlineKeyboardButton("◀️ Меню игр", callback_data="menu_games")
    )
    send_message(chat_id, f"🎲 Выпало {roll}. Твой счёт: {pig_scores[uid]}. Что делаешь?", reply_markup=kb, parse_mode="Markdown", user_id=uid)

def game_jackpot(uid, chat_id):
    delete_previous_message(chat_id, uid)
    if not remove_coins(uid, 5):
        send_message(chat_id, "❌ Нет монет", user_id=uid)
        return
    jackpot_data["total"] += 5
    r = random.randint(1, 100)
    if r <= 2:
        win = jackpot_data["total"]
        add_coins(uid, win)
        jackpot_data["total"] = 0
        text = f"🎰 *ДЖЕКПОТ!* Ты выиграл {win}💰"
        update_stats(uid, True)
    else:
        text = f"🎰 Не повезло. Джекпот {jackpot_data['total']}💰"
        update_stats(uid, False)
    send_message(chat_id, text, reply_markup=play_again("game_jackpot"), parse_mode="Markdown", user_id=uid)

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
@bot.message_handler(commands=['start'])
def start(message):
    uid = message.chat.id
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        process_referral(uid, args[1].split("_")[1])
    u = get_user(uid)
    if message.from_user.username:
        update_user(uid, username=message.from_user.username.lower())
    if not u.get("region"):
        kb = InlineKeyboardMarkup(row_width=2)
        for r in REGIONS:
            kb.add(InlineKeyboardButton(r, callback_data=f"region_{r}"))
        send_message(uid, "🌍 *Выбери регион:*", reply_markup=kb, parse_mode="Markdown", user_id=uid)
    else:
        send_message(uid, f"🎉 *Добро пожаловать!*\n\n{format_profile(uid)}", reply_markup=main_menu(uid), parse_mode="Markdown", user_id=uid)

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    uid = call.message.chat.id
    data = call.data
    msg_id = call.message.message_id

    # Регионы
    if data.startswith("region_"):
        region = data.replace("region_", "")
        update_user(uid, region=region)
        edit_message(uid, msg_id, f"✅ Регион *{region}* сохранён!\n\n{format_profile(uid)}", reply_markup=main_menu(uid), parse_mode="Markdown")
        return

    # Главное меню
    if data == "back_main":
        edit_message(uid, msg_id, format_profile(uid), reply_markup=main_menu(uid), parse_mode="Markdown")
        return

    if data == "menu_games":
        edit_message(uid, msg_id, "🎮 *Выбери игру:*", reply_markup=games_menu(), parse_mode="Markdown")
        return

    if data == "menu_farms":
        edit_message(uid, msg_id, "💰 *Фермы*\nКаждый час приносят доход!", reply_markup=farms_menu(), parse_mode="Markdown")
        return

    if data == "menu_profile":
        edit_message(uid, msg_id, format_profile(uid), reply_markup=main_menu(uid), parse_mode="Markdown")
        return

    if data == "menu_bonus":
        if can_take_bonus(uid):
            add_coins(uid, 25)
            update_user(uid, last_bonus=datetime.now().isoformat())
            text = "🎁 +25 монет!"
        else:
            text = "⏳ Бонус уже получен. Завтра!"
        edit_message(uid, msg_id, text, reply_markup=main_menu(uid), parse_mode="Markdown")
        return

    if data == "menu_refs":
        text = f"👥 *Рефералы*\n📎 {get_referral_link(uid)}\n👥 Приглашено: {get_referral_stats(uid)}\n\n➕ За каждого друга +10💰 тебе и +5💰 другу!"
        edit_message(uid, msg_id, text, reply_markup=main_menu(uid), parse_mode="Markdown")
        return

    if data == "menu_clans":
        edit_message(uid, msg_id, "👥 *Кланы*\nВыбери действие:", reply_markup=clans_menu(), parse_mode="Markdown")
        return

    if data == "menu_question":
        send_message(uid, "✍️ Напиши свой вопрос:", user_id=uid)
        waiting_for_question[uid] = True
        return

    if data == "menu_admin" and uid == ADMIN_ID:
        edit_message(uid, msg_id, "🔧 *Админ-панель*", reply_markup=admin_menu(), parse_mode="Markdown")
        return

    # Игры
    if data == "game_dice1":
        send_message(uid, "🎲 Введи число от 1 до 6:", user_id=uid)
        game_waiting[uid] = ("dice1", None)
        return
    if data == "game_dice2":
        send_message(uid, "🎲🎲 Введи сумму от 2 до 12:", user_id=uid)
        game_waiting[uid] = ("dice2", None)
        return
    if data == "game_dice3":
        send_message(uid, "🎲🎲🎲 Введи сумму от 3 до 18:", user_id=uid)
        game_waiting[uid] = ("dice3", None)
        return
    if data == "game_number":
        send_message(uid, "🔢 Введи число от 1 до 10:", user_id=uid)
        game_waiting[uid] = ("number", None)
        return
    if data == "game_rps":
        send_message(uid, "✂️ Введи: камень, ножницы, бумага", user_id=uid)
        game_waiting[uid] = ("rps", None)
        return
    if data == "game_slots":
        game_slots(uid, msg_id, uid)
        return
    if data == "game_evenodd":
        send_message(uid, "🎲 Введи: чётное или нечётное", user_id=uid)
        game_waiting[uid] = ("evenodd", None)
        return
    if data == "game_pig":
        game_pig(uid, call.message)
        return
    if data == "game_jackpot":
        game_jackpot(uid, uid)
        return

    # Игры "Сыграть ещё"
    if data.startswith("again_"):
        game = data.replace("again_", "")
        if game == "game_dice1":
            send_message(uid, "🎲 Введи число от 1 до 6:", user_id=uid)
            game_waiting[uid] = ("dice1", None)
        elif game == "game_dice2":
            send_message(uid, "🎲🎲 Введи сумму от 2 до 12:", user_id=uid)
            game_waiting[uid] = ("dice2", None)
        elif game == "game_dice3":
            send_message(uid, "🎲🎲🎲 Введи сумму от 3 до 18:", user_id=uid)
            game_waiting[uid] = ("dice3", None)
        elif game == "game_number":
            send_message(uid, "🔢 Введи число от 1 до 10:", user_id=uid)
            game_waiting[uid] = ("number", None)
        elif game == "game_rps":
            send_message(uid, "✂️ Введи: камень, ножницы, бумага", user_id=uid)
            game_waiting[uid] = ("rps", None)
        elif game == "game_slots":
            game_slots(uid, None, uid)
        elif game == "game_evenodd":
            send_message(uid, "🎲 Введи: чётное или нечётное", user_id=uid)
            game_waiting[uid] = ("evenodd", None)
        elif game == "game_pig":
            game_pig(uid, call.message)
        elif game == "game_jackpot":
            game_jackpot(uid, uid)
        return

    # Свинья
    if data == "pig_continue":
        game_pig_roll(uid, uid)
        return
    if data == "pig_take":
        score = pig_scores.pop(uid, 0)
        if score > 0:
            add_coins(uid, score)
            text = f"💰 Ты забрал {score}💰!"
            update_stats(uid, True)
        else:
            text = "❌ Нет очков"
        edit_message(uid, msg_id, text, reply_markup=play_again("game_pig"), parse_mode="Markdown")
        return

    # Фермы
    if data == "farm_buy":
        kb = InlineKeyboardMarkup(row_width=1)
        for name, d in BUSINESSES.items():
            kb.add(InlineKeyboardButton(f"{name} ({d['price']}💰)", callback_data=f"buy_{name}"))
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data="menu_farms"))
        edit_message(uid, msg_id, "🏭 *Купить ферму:*", reply_markup=kb, parse_mode="Markdown")
        return

    if data == "farm_list":
        businesses = get_user_businesses(uid)
        if not businesses:
            edit_message(uid, msg_id, "❌ У тебя нет ферм! Купи в разделе 'Купить ферму'", reply_markup=farms_menu(), parse_mode="Markdown")
            return
        text = "🏭 *Твои фермы:*\n\n"
        kb = InlineKeyboardMarkup(row_width=1)
        for b in businesses:
            text += f"• {b['business_type']} (ур. {b['amount_level']})\n"
            kb.add(InlineKeyboardButton(f"📊 {b['business_type']}", callback_data=f"manage_{b['business_type']}"))
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data="menu_farms"))
        edit_message(uid, msg_id, text, reply_markup=kb, parse_mode="Markdown")
        return

    if data.startswith("buy_"):
        biz = data.replace("buy_", "")
        ok, msg = buy_business(uid, biz)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        if ok:
            edit_message(uid, msg_id, "💰 *Фермы*\nКаждый час приносят доход!", reply_markup=farms_menu(), parse_mode="Markdown")
        return

    if data.startswith("manage_"):
        biz = data.replace("manage_", "")
        b = get_business(uid, biz)
        if not b:
            edit_message(uid, msg_id, "❌ Ферма не найдена", reply_markup=farms_menu(), parse_mode="Markdown")
            return
        income = BUSINESSES[biz]["income"] * b["amount_level"]
        text = f"🏭 *{biz}*\n📊 Уровень: {b['amount_level']}\n💰 Доход в час: +{income}💰\n\n💎 Накоплено: проверь сбором!"
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("📈 Апгрейд", callback_data=f"upgrade_{biz}"),
            InlineKeyboardButton("💾 Собрать", callback_data=f"collect_{biz}"),
            InlineKeyboardButton("◀️ Назад", callback_data="farm_list")
        )
        edit_message(uid, msg_id, text, reply_markup=kb, parse_mode="Markdown")
        return

    if data.startswith("upgrade_"):
        biz = data.replace("upgrade_", "")
        ok, msg = upgrade_business(uid, biz)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        if ok:
            b = get_business(uid, biz)
            income = BUSINESSES[biz]["income"] * b["amount_level"]
            text = f"🏭 *{biz}*\n📊 Уровень: {b['amount_level']}\n💰 Доход в час: +{income}💰"
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton("📈 Апгрейд", callback_data=f"upgrade_{biz}"),
                InlineKeyboardButton("💾 Собрать", callback_data=f"collect_{biz}"),
                InlineKeyboardButton("◀️ Назад", callback_data="farm_list")
            )
            edit_message(uid, msg_id, text, reply_markup=kb, parse_mode="Markdown")
        return

    if data.startswith("collect_"):
        biz = data.replace("collect_", "")
        earned, msg = collect_income(uid, biz)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        b = get_business(uid, biz)
        if b:
            income = BUSINESSES[biz]["income"] * b["amount_level"]
            text = f"🏭 *{biz}*\n📊 Уровень: {b['amount_level']}\n💰 Доход в час: +{income}💰"
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton("📈 Апгрейд", callback_data=f"upgrade_{biz}"),
                InlineKeyboardButton("💾 Собрать", callback_data=f"collect_{biz}"),
                InlineKeyboardButton("◀️ Назад", callback_data="farm_list")
            )
            edit_message(uid, msg_id, text, reply_markup=kb, parse_mode="Markdown")
        return

    # Кланы
    if data == "clan_create":
        if get_user_clan(uid):
            edit_message(uid, msg_id, "❌ Ты уже в клане!", reply_markup=clans_menu(), parse_mode="Markdown")
            return
        send_message(uid, "📋 Введи название клана:", user_id=uid)
        game_waiting[uid] = ("clan_name", None)
        return

    if data == "clan_join":
        if get_user_clan(uid):
            edit_message(uid, msg_id, "❌ Ты уже в клане!", reply_markup=clans_menu(), parse_mode="Markdown")
            return
        send_message(uid, "🔍 Введи ID клана:", user_id=uid)
        game_waiting[uid] = ("clan_join", None)
        return

    if data == "clan_info":
        clan = get_user_clan(uid)
        if not clan:
            text = "❌ Ты не в клане!"
        else:
            text = f"{clan['emoji']} *{clan['name']}*\n👑 Владелец: `{clan['owner_id']}`\n🆔 ID: {clan['clan_id']}"
        edit_message(uid, msg_id, text, reply_markup=clans_menu(), parse_mode="Markdown")
        return

    if data == "clan_leave":
        ok, msg = leave_clan(uid)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        edit_message(uid, msg_id, format_profile(uid), reply_markup=main_menu(uid), parse_mode="Markdown")
        return

    # Админ
    if data == "admin_add" and uid == ADMIN_ID:
        send_message(uid, "💰 Введи ID и сумму: `123456789 100`", parse_mode="Markdown", user_id=uid)
        game_waiting[uid] = ("admin_add", None)
        return
    if data == "admin_remove" and uid == ADMIN_ID:
        send_message(uid, "🔻 Введи ID и сумму: `123456789 50`", parse_mode="Markdown", user_id=uid)
        game_waiting[uid] = ("admin_remove", None)
        return
    if data == "admin_users" and uid == ADMIN_ID:
        users = all_users_list()
        msg = "👥 *Пользователи:*\n"
        for u in users[:20]:
            msg += f"🆔 {u} — {get_user(u)['coins']}💰\n"
        send_message(uid, msg, parse_mode="Markdown", user_id=uid)
        return
    if data == "admin_broadcast" and uid == ADMIN_ID:
        send_message(uid, "📢 Введи сообщение для рассылки:", user_id=uid)
        game_waiting[uid] = ("admin_broadcast", None)
        return

    # Ответ на вопрос
    if data.startswith("answer_"):
        uid_q = data.split("_")[1]
        send_message(ADMIN_ID, f"✍️ Ответ для {uid_q}:", user_id=ADMIN_ID)
        game_waiting[ADMIN_ID] = ("answer", uid_q)
        return

def clans_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📋 Создать клан", callback_data="clan_create"),
        InlineKeyboardButton("🔍 Вступить в клан", callback_data="clan_join"),
        InlineKeyboardButton("📊 Мой клан", callback_data="clan_info"),
        InlineKeyboardButton("🚪 Покинуть клан", callback_data="clan_leave"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    return kb

# ========== ОБРАБОТКА СООБЩЕНИЙ ==========
@bot.message_handler(func=lambda m: True)
def handle_messages(message):
    uid = message.chat.id
    text = message.text

    # Ожидание ввода для игр/админа/кланов
    if uid in game_waiting:
        action, extra = game_waiting[uid]
        del game_waiting[uid]

        if action == "dice1":
            game_dice(uid, 1, (1, 6), 2, 5, "game_dice1", message)
        elif action == "dice2":
            game_dice(uid, 2, (2, 12), 4, 10, "game_dice2", message)
        elif action == "dice3":
            game_dice(uid, 3, (3, 18), 8, 15, "game_dice3", message)
        elif action == "number":
            game_number(uid, message)
        elif action == "rps":
            game_rps(uid, message)
        elif action == "evenodd":
            game_evenodd(uid, message)
        elif action == "clan_name":
            name = text.strip()
            if len(name) > 20:
                send_message(uid, "❌ Название太长 (макс 20 символов)", user_id=uid)
                return
            send_message(uid, "📋 Введи эмодзи для клана (1 символ):", user_id=uid)
            game_waiting[uid] = ("clan_emoji", name)
        elif action == "clan_emoji":
            emoji = text.strip()[:2]
            name = extra
            clan_id = create_clan(uid, name, emoji)
            if clan_id:
                send_message(uid, f"✅ Клан *{name}* создан! ID: {clan_id}", reply_markup=main_menu(uid), parse_mode="Markdown", user_id=uid)
            else:
                send_message(uid, "❌ Клан с таким названием уже существует", user_id=uid)
        elif action == "clan_join":
            try:
                clan_id = int(text.strip())
                ok, msg = join_clan(uid, clan_id)
                send_message(uid, msg, reply_markup=main_menu(uid), user_id=uid)
            except:
                send_message(uid, "❌ Введи числовой ID", user_id=uid)
        elif action == "admin_add" and uid == ADMIN_ID:
            try:
                tid, amt = text.split()
                add_coins(int(tid), int(amt))
                send_message(uid, f"✅ Выдано {amt}💰 {tid}", reply_markup=admin_menu(), user_id=uid)
            except:
                send_message(uid, "❌ Ошибка. Формат: `123456789 100`", parse_mode="Markdown", user_id=uid)
        elif action == "admin_remove" and uid == ADMIN_ID:
            try:
                tid, amt = text.split()
                if remove_coins(int(tid), int(amt)):
                    send_message(uid, f"✅ Забрано {amt}💰 у {tid}", reply_markup=admin_menu(), user_id=uid)
                else:
                    send_message(uid, f"❌ У {tid} нет {amt}💰", reply_markup=admin_menu(), user_id=uid)
            except:
                send_message(uid, "❌ Ошибка. Формат: `123456789 50`", parse_mode="Markdown", user_id=uid)
        elif action == "admin_broadcast" and uid == ADMIN_ID:
            text_msg = text
            sent = 0
            for user in all_users_list():
                try:
                    bot.send_message(int(user), f"📢 *Рассылка:*\n{text_msg}", parse_mode="Markdown")
                    sent += 1
                except:
                    pass
            send_message(uid, f"✅ Отправлено {sent}", reply_markup=admin_menu(), user_id=uid)
        elif action == "answer" and uid == ADMIN_ID:
            target = extra
            bot.send_message(int(target), f"📬 *Ответ:*\n{text}", parse_mode="Markdown")
            send_message(ADMIN_ID, f"✅ Ответ отправлен {target}", reply_markup=admin_menu(), user_id=ADMIN_ID)
        return

    # Вопрос админу
    if uid in waiting_for_question:
        forward_question(uid, text)
        waiting_for_question[uid] = False
        send_message(uid, "✅ Вопрос отправлен администратору!", reply_markup=main_menu(uid), user_id=uid)
        return

    # Групповые команды
    if message.chat.type in ["group", "supergroup"]:
        group_handlers(message)
        return

    # Если ничего не подошло
    send_message(uid, "❌ Используй кнопки меню 👇", reply_markup=main_menu(uid), user_id=uid)

def forward_question(uid, q):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✍️ Ответить", callback_data=f"answer_{uid}"))
    bot.send_message(ADMIN_ID, f"📩 *Вопрос от* `{uid}`:\n{q}", reply_markup=kb, parse_mode="Markdown")

# ========== ГРУППОВЫЕ КОМАНДЫ ==========
def group_handlers(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    text = message.text.lower()

    if is_banned(chat_id, user_id):
        return

    if text == "топ":
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id, coins, username FROM users ORDER BY coins DESC LIMIT 5")
        top = cur.fetchall()
        cur.close()
        conn.close()
        if not top:
            send_message(chat_id, "📊 Нет данных", user_id=user_id)
            return
        msg = "🏆 *Топ-5:*\n"
        for i, (uid, coins, name) in enumerate(top, 1):
            msg += f"{i}. {name or uid[:8]} — {coins}💰\n"
        send_message(chat_id, msg, parse_mode="Markdown", user_id=user_id)

    elif text == "бонус":
        now = datetime.now()
        if chat_id in group_bonus_tracker and group_bonus_tracker[chat_id] > now - timedelta(hours=6):
            rem = timedelta(hours=6) - (now - group_bonus_tracker[chat_id])
            hours = rem.seconds // 3600
            minutes = (rem.seconds % 3600) // 60
            send_message(chat_id, f"⏳ Бонус через {hours}ч {minutes}мин", user_id=user_id)
            return
        group_bonus_tracker[chat_id] = now
        for uid in all_users_list():
            try:
                add_coins(int(uid), 50)
            except:
                pass
        send_message(chat_id, "🎁 *Групповой бонус!* Все +50💰", parse_mode="Markdown", user_id=user_id)

    elif text.startswith("назначить"):
        parts = message.text.split()
        if len(parts) != 3:
            send_message(chat_id, "❌ Формат: назначить @username вице-президент|админ", user_id=user_id)
            return
        target = parts[1].replace("@", "").lower()
        role = parts[2].lower()
        if role not in ["вице-президент", "админ"]:
            send_message(chat_id, "❌ Роль: вице-президент или админ", user_id=user_id)
            return
        user_role = get_group_role(chat_id, user_id)
        if user_role == "member":
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM group_roles WHERE group_id = %s AND role = 'президент'", (str(chat_id),))
            has_president = cur.fetchone()
            cur.close()
            conn.close()
            if not has_president:
                set_group_role(chat_id, user_id, "президент")
                user_role = "президент"
                send_message(chat_id, f"👑 @{message.from_user.username} стал президентом!", user_id=user_id)
            else:
                send_message(chat_id, "❌ Нет прав!", user_id=user_id)
                return
        if user_role not in ["президент", "вице-президент"]:
            send_message(chat_id, "❌ Нет прав!", user_id=user_id)
            return
        if user_role == "вице-президент" and role != "админ":
            send_message(chat_id, "❌ Вице-президент назначает только админов!", user_id=user_id)
            return
        target_uid = None
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE username = %s", (target,))
        r = cur.fetchone()
        cur.close()
        conn.close()
        if r:
            target_uid = r[0]
        if not target_uid:
            send_message(chat_id, f"❌ @{target} не найден", user_id=user_id)
            return
        set_group_role(chat_id, target_uid, role)
        send_message(chat_id, f"✅ @{target} назначен {role}", user_id=user_id)

    elif text.startswith("забрать роль"):
        parts = message.text.split()
        if len(parts) != 3:
            send_message(chat_id, "❌ Формат: забрать роль @username", user_id=user_id)
            return
        target = parts[2].replace("@", "").lower()
        user_role = get_group_role(chat_id, user_id)
        if user_role != "президент":
            send_message(chat_id, "❌ Только президент!", user_id=user_id)
            return
        target_uid = None
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE username = %s", (target,))
        r = cur.fetchone()
        cur.close()
        conn.close()
        if r:
            target_uid = r[0]
        if not target_uid:
            send_message(chat_id, f"❌ @{target} не найден", user_id=user_id)
            return
        remove_group_role(chat_id, target_uid)
        send_message(chat_id, f"✅ У @{target} забрана роль", user_id=user_id)

    elif text.startswith("запретить"):
        parts = message.text.split()
        if len(parts) < 2:
            send_message(chat_id, "❌ Формат: запретить @username [часы] [причина]", user_id=user_id)
            return
        target = parts[1].replace("@", "").lower()
        duration = -1
        reason = "Нарушение"
        if len(parts) >= 3:
            try:
                hours = int(parts[2])
                duration = hours * 3600
                if len(parts) >= 4:
                    reason = " ".join(parts[3:])
            except:
                reason = " ".join(parts[2:])
        user_role = get_group_role(chat_id, user_id)
        if user_role not in ["президент", "вице-президент", "админ"]:
            send_message(chat_id, "❌ Нет прав!", user_id=user_id)
            return
        target_uid = None
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE username = %s", (target,))
        r = cur.fetchone()
        cur.close()
        conn.close()
        if r:
            target_uid = r[0]
        if not target_uid:
            send_message(chat_id, f"❌ @{target} не найден", user_id=user_id)
            return
        target_role = get_group_role(chat_id, target_uid)
        if target_role == "президент":
            send_message(chat_id, "❌ Нельзя забанить президента!", user_id=user_id)
            return
        if user_role == "админ" and target_role in ["вице-президент", "админ"]:
            send_message(chat_id, "❌ Админ не может банить админов!", user_id=user_id)
            return
        ban_user(chat_id, target_uid, duration, reason)
        if duration == -1:
            send_message(chat_id, f"🚫 @{target} забанен навсегда. Причина: {reason}", user_id=user_id)
        else:
            send_message(chat_id, f"🚫 @{target} забанен на {duration//3600}ч. Причина: {reason}", user_id=user_id)

    elif text.startswith("разрешить"):
        parts = message.text.split()
        if len(parts) != 2:
            send_message(chat_id, "❌ Формат: разрешить @username", user_id=user_id)
            return
        target = parts[1].replace("@", "").lower()
        user_role = get_group_role(chat_id, user_id)
        if user_role not in ["президент", "вице-президент", "админ"]:
            send_message(chat_id, "❌ Нет прав!", user_id=user_id)
            return
        target_uid = None
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE username = %s", (target,))
        r = cur.fetchone()
        cur.close()
        conn.close()
        if r:
            target_uid = r[0]
        if not target_uid:
            send_message(chat_id, f"❌ @{target} не найден", user_id=user_id)
            return
        unban_user(chat_id, target_uid)
        send_message(chat_id, f"✅ @{target} разбанен", user_id=user_id)

    elif text.startswith("выдать монеты"):
        parts = message.text.split()
        if len(parts) != 3:
            send_message(chat_id, "❌ Формат: выдать монеты @username сумма", user_id=user_id)
            return
        target = parts[1].replace("@", "").lower()
        try:
            amount = int(parts[2])
        except:
            send_message(chat_id, "❌ Сумма числом", user_id=user_id)
            return
        user_role = get_group_role(chat_id, user_id)
        if user_role != "президент":
            send_message(chat_id, "❌ Только президент!", user_id=user_id)
            return
        target_uid = None
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE username = %s", (target,))
        r = cur.fetchone()
        cur.close()
        conn.close()
        if r:
            target_uid = r[0]
        if not target_uid:
            send_message(chat_id, f"❌ @{target} не найден", user_id=user_id)
            return
        if not remove_coins(user_id, amount):
            send_message(chat_id, f"❌ У тебя нет {amount}💰", user_id=user_id)
            return
        add_coins(target_uid, amount)
        send_message(chat_id, f"✅ Выдано {amount}💰 @{target}", user_id=user_id)

    # Групповые игры
    elif text in ["1 кубик", "2 кубика", "3 кубика"]:
        if text == "1 кубик":
            send_message(chat_id, f"🎲 @{message.from_user.username} кинул {random.randint(1, 6)}!", user_id=user_id)
        elif text == "2 кубика":
            d1, d2 = random.randint(1, 6), random.randint(1, 6)
            send_message(chat_id, f"🎲 @{message.from_user.username} кинул {d1}+{d2}={d1+d2}!", user_id=user_id)
        else:
            d1, d2, d3 = random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)
            send_message(chat_id, f"🎲 @{message.from_user.username} кинул {d1}+{d2}+{d3}={d1+d2+d3}!", user_id=user_id)

    elif text == "камень-ножницы":
        bot_choice = random.choice(["камень", "ножницы", "бумага"])
        group_game_sessions[user_id] = {"game": "rps", "bot_choice": bot_choice}
        send_message(chat_id, f"✂️ Бот выбрал {bot_choice}. Пиши 'камень', 'ножницы' или 'бумага'", user_id=user_id)

    elif user_id in group_game_sessions:
        g = group_game_sessions[user_id]
        if g["game"] == "rps" and text in ["камень", "ножницы", "бумага"]:
            if text == g["bot_choice"]:
                send_message(chat_id, f"🤝 Ничья!", user_id=user_id)
            elif (text == "камень" and g["bot_choice"] == "ножницы") or (text == "ножницы" and g["bot_choice"] == "бумага") or (text == "бумага" and g["bot_choice"] == "камень"):
                send_message(chat_id, f"🎉 @{message.from_user.username} победил!", user_id=user_id)
            else:
                send_message(chat_id, f"💀 @{message.from_user.username} проиграл", user_id=user_id)
            del group_game_sessions[user_id]

if __name__ == "__main__":
    print("✅ БОТ ЗАПУЩЕН!")
    print("🎮 Игры работают!")
    print("💰 Фермы работают!")
    print("👥 Кланы работают!")
    print("🔧 Групповые роли работают!")
    bot.infinity_polling(skip_pending=True)
