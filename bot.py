import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
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

if not DATABASE_URL or not REDIS_URL:
    print("❌ DATABASE_URL или REDIS_URL не найден")
    exit(1)

bot = telebot.TeleBot(TOKEN)

games_data = {}
waiting_for_question = {}
admin_actions = {}
waiting_for_username = {}
group_bonus_tracker = {}
group_game_sessions = {}
buy_amount_buffer = {}
last_message_ids = {}
group_roles = {}
group_bans = {}
duel_requests = {}

# ========== REDIS ==========
r = redis.from_url(REDIS_URL, decode_responses=True)

def get_user_cache(uid):
    data = r.get(f"user:{uid}")
    if data:
        return json.loads(data)
    return None

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
            coins INTEGER DEFAULT 5,
            last_bonus TEXT,
            username TEXT,
            region TEXT,
            referrer TEXT,
            vip_game INTEGER DEFAULT 0,
            vip_farm INTEGER DEFAULT 0,
            daily_streak INTEGER DEFAULT 0,
            last_daily TEXT,
            total_games INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0,
            total_losses INTEGER DEFAULT 0,
            total_won_coins INTEGER DEFAULT 0,
            total_lost_coins INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            user_id TEXT,
            achievement_id TEXT,
            progress INTEGER DEFAULT 0,
            claimed BOOLEAN DEFAULT FALSE,
            PRIMARY KEY (user_id, achievement_id)
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

# ========== ДОСТИЖЕНИЯ ==========
ACHIEVEMENTS = {
    "games_10": {"name": "🎲 Новичок", "desc": "Сыграть 10 игр", "target": 10, "reward": 50},
    "games_100": {"name": "🎲 Любитель", "desc": "Сыграть 100 игр", "target": 100, "reward": 200},
    "games_1000": {"name": "🎲 Профи", "desc": "Сыграть 1000 игр", "target": 1000, "reward": 1000},
    "wins_10": {"name": "🏆 Победитель", "desc": "Выиграть 10 игр", "target": 10, "reward": 50},
    "wins_100": {"name": "🏆 Чемпион", "desc": "Выиграть 100 игр", "target": 100, "reward": 300},
    "coins_1000": {"name": "💰 Богач", "desc": "Накопить 1000 монет", "target": 1000, "reward": 100},
    "coins_10000": {"name": "💰 Миллионер", "desc": "Накопить 10000 монет", "target": 10000, "reward": 500},
    "referrals_5": {"name": "👥 Дружный", "desc": "Пригласить 5 друзей", "target": 5, "reward": 200},
    "referrals_20": {"name": "👥 Лидер", "desc": "Пригласить 20 друзей", "target": 20, "reward": 1000},
    "farm_5": {"name": "🏭 Фермер", "desc": "Купить 5 ферм", "target": 5, "reward": 500},
    "farm_10": {"name": "🏭 Магнат", "desc": "Купить 10 ферм", "target": 10, "reward": 2000}
}

def update_achievement(uid, ach_id, progress_add=1):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT progress, claimed FROM achievements WHERE user_id = %s AND achievement_id = %s", (str(uid), ach_id))
    r = cur.fetchone()
    if r and r[1]:
        cur.close()
        conn.close()
        return False
    if r:
        new_progress = min(r[0] + progress_add, ACHIEVEMENTS[ach_id]["target"])
        cur.execute("UPDATE achievements SET progress = %s WHERE user_id = %s AND achievement_id = %s", (new_progress, str(uid), ach_id))
    else:
        new_progress = min(progress_add, ACHIEVEMENTS[ach_id]["target"])
        cur.execute("INSERT INTO achievements (user_id, achievement_id, progress) VALUES (%s, %s, %s)", (str(uid), ach_id, new_progress))
    conn.commit()
    if new_progress >= ACHIEVEMENTS[ach_id]["target"] and (not r or not r[1]):
        reward = ACHIEVEMENTS[ach_id]["reward"]
        add_coins(uid, reward)
        cur.execute("UPDATE achievements SET claimed = TRUE WHERE user_id = %s AND achievement_id = %s", (str(uid), ach_id))
        conn.commit()
        cur.close()
        conn.close()
        bot.send_message(int(uid), f"🏆 *Достижение получено!*\n{ACHIEVEMENTS[ach_id]['name']}\n+{reward}💰", parse_mode="Markdown")
        return True
    cur.close()
    conn.close()
    return False

def get_achievements_progress(uid):
    conn = get_db_connection()
    cur = conn.cursor()
    result = []
    for ach_id, ach in ACHIEVEMENTS.items():
        cur.execute("SELECT progress, claimed FROM achievements WHERE user_id = %s AND achievement_id = %s", (str(uid), ach_id))
        r = cur.fetchone()
        if r:
            progress = r[0]
            claimed = r[1]
        else:
            progress = 0
            claimed = False
        status = "✅" if claimed else f"{progress}/{ach['target']}"
        result.append((ach["name"], ach["desc"], status, claimed))
    cur.close()
    conn.close()
    return result

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def delete_previous_message(chat_id, user_id):
    if user_id in last_message_ids:
        try:
            bot.delete_message(chat_id, last_message_ids[user_id])
        except:
            pass
    return True

def send_and_track(chat_id, text, reply_markup=None, parse_mode="Markdown", user_id=None):
    msg = bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    if user_id:
        last_message_ids[user_id] = msg.message_id
    return msg

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
        cur.execute("INSERT INTO users (user_id) VALUES (%s)", (uid,))
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
    clan_id = get_user_clan(uid)
    clan_info = get_clan_info(clan_id) if clan_id else None
    clan_str = f"\n│  👑 Клан: {clan_info['emoji']} {clan_info['name']}" if clan_info else "\n│  👑 Клан: нет"
    vip_game = "👑 VIP игры" if u.get("vip_game") else ""
    vip_farm = "💎 VIP фермы" if u.get("vip_farm") else ""
    vip_str = f"\n│  ✨ Статус: {vip_game} {vip_farm}".strip() if (vip_game or vip_farm) else ""
    return (f"┌─────────────────────┐\n"
            f"│  👤 *{u.get('username') or 'Игрок'}*\n"
            f"│  💰 Баланс: `{u['coins']}` монет\n"
            f"│  📍 Регион: {region}\n"
            f"{clan_str}{vip_str}\n"
            f"└─────────────────────┘")

# ========== ВИП СТАТУС ==========
def buy_vip_game(uid):
    if remove_coins(uid, 5000):
        update_user(uid, vip_game=1)
        return True, "✅ Ты купил VIP статус для игр! +10% к выигрышам"
    return False, "❌ Нужно 5000💰"

def buy_vip_farm(uid):
    if remove_coins(uid, 50000):
        update_user(uid, vip_farm=1)
        return True, "✅ Ты купил VIP статус для ферм! +10% к доходу"
    return False, "❌ Нужно 50000💰"

def apply_vip_bonus(uid, amount, bonus_type):
    u = get_user(uid)
    if bonus_type == "game" and u.get("vip_game"):
        return int(amount * 1.1)
    if bonus_type == "farm" and u.get("vip_farm"):
        return int(amount * 1.1)
    return amount

# ========== ЕЖЕДНЕВНЫЙ СТРЕЙК ==========
def daily_streak_bonus(uid):
    u = get_user(uid)
    today = datetime.now().date()
    last = u.get("last_daily")
    if last:
        last_date = datetime.fromisoformat(last).date()
        if last_date == today:
            return False, "⏳ Ты уже получал бонус сегодня!"
        elif last_date == today - timedelta(days=1):
            streak = u.get("daily_streak", 0) + 1
        else:
            streak = 1
    else:
        streak = 1
    bonus = min(streak * 5, 100)  # макс 100💰
    add_coins(uid, bonus)
    update_user(uid, daily_streak=streak, last_daily=datetime.now().isoformat())
    return True, f"🎁 Ежедневный бонус! День {streak} → +{bonus}💰"

# ========== СТАТИСТИКА ИГРОКА ==========
def update_game_stats(uid, won, win_amount):
    u = get_user(uid)
    new_games = u.get("total_games", 0) + 1
    new_wins = u.get("total_wins", 0) + (1 if won else 0)
    new_losses = u.get("total_losses", 0) + (0 if won else 1)
    new_won = u.get("total_won_coins", 0) + (win_amount if won else 0)
    new_lost = u.get("total_lost_coins", 0) + (abs(win_amount) if not won else 0)
    update_user(uid, total_games=new_games, total_wins=new_wins, total_losses=new_losses,
                total_won_coins=new_won, total_lost_coins=new_lost)
    update_achievement(uid, "games_10")
    update_achievement(uid, "games_100")
    update_achievement(uid, "games_1000")
    if won:
        update_achievement(uid, "wins_10")
        update_achievement(uid, "wins_100")
    u2 = get_user(uid)
    if u2["coins"] >= 1000:
        update_achievement(uid, "coins_1000")
    if u2["coins"] >= 10000:
        update_achievement(uid, "coins_10000")

def get_player_stats(uid):
    u = get_user(uid)
    return (f"📊 *Твоя статистика*\n\n"
            f"🎮 Всего игр: {u.get('total_games', 0)}\n"
            f"🏆 Побед: {u.get('total_wins', 0)}\n"
            f"💀 Поражений: {u.get('total_losses', 0)}\n"
            f"💰 Выиграно монет: {u.get('total_won_coins', 0)}\n"
            f"💸 Проиграно монет: {u.get('total_lost_coins', 0)}\n"
            f"📈 Процент побед: {round(u.get('total_wins', 0) / max(1, u.get('total_games', 0)) * 100, 1)}%")

# ========== РУЛЕТКА ==========
def roulette_play(uid, bet, bet_type, bet_value):
    if not remove_coins(uid, bet):
        return False, "❌ Нет монет!"
    number = random.randint(0, 36)
    color = "зелёный" if number == 0 else "красный" if number % 2 == 0 else "чёрный"
    win = 0
    if bet_type == "number" and bet_value == number:
        win = bet * 36
    elif bet_type == "color" and bet_value == color:
        win = bet * 2
    if win > 0:
        win = apply_vip_bonus(uid, win, "game")
        add_coins(uid, win)
        update_game_stats(uid, True, win)
        return True, f"🎲 Выпало {number} ({color}). Ты выиграл {win}💰!"
    else:
        update_game_stats(uid, False, -bet)
        return False, f"🎲 Выпало {number} ({color}). Ты проиграл {bet}💰!"

# ========== PVP ДУЭЛЬ ==========
def duel_request(from_uid, to_uid, amount):
    if from_uid == to_uid:
        return False, "❌ Нельзя играть с самим собой!"
    if not remove_coins(from_uid, amount):
        return False, "❌ У тебя нет монет!"
    duel_requests[to_uid] = {"from": from_uid, "amount": amount}
    return True, f"⚔️ Запрос на дуэль отправлен! Сумма: {amount}💰"

def duel_accept(uid):
    if uid not in duel_requests:
        return False, "❌ Нет активных запросов на дуэль!"
    req = duel_requests.pop(uid)
    from_uid = req["from"]
    amount = req["amount"]
    if not remove_coins(uid, amount):
        add_coins(from_uid, amount)
        return False, "❌ У тебя нет монет для дуэли!"
    roll1 = random.randint(1, 6)
    roll2 = random.randint(1, 6)
    if roll1 > roll2:
        win_amount = apply_vip_bonus(from_uid, amount * 2, "game")
        add_coins(from_uid, win_amount)
        update_game_stats(from_uid, True, win_amount)
        update_game_stats(uid, False, -amount)
        return True, f"⚔️ @{get_user(from_uid)['username']} кинул {roll1}, @{get_user(uid)['username']} кинул {roll2}. Победил @{get_user(from_uid)['username']}! +{win_amount}💰"
    elif roll2 > roll1:
        win_amount = apply_vip_bonus(uid, amount * 2, "game")
        add_coins(uid, win_amount)
        update_game_stats(uid, True, win_amount)
        update_game_stats(from_uid, False, -amount)
        return True, f"⚔️ @{get_user(from_uid)['username']} кинул {roll1}, @{get_user(uid)['username']} кинул {roll2}. Победил @{get_user(uid)['username']}! +{win_amount}💰"
    else:
        add_coins(from_uid, amount)
        add_coins(uid, amount)
        return True, f"⚔️ Ничья! {roll1}:{roll2}. Монеты возвращены."

# ========== ФЕРМЫ (10 ШТУК) ==========
BUSINESSES = {
    "🌾 Ферма": {"price": 5000, "base_income": 50, "upgrade_income": 50},
    "⛏️ Шахта": {"price": 15000, "base_income": 150, "upgrade_income": 100},
    "🏭 Фабрика": {"price": 50000, "base_income": 500, "upgrade_income": 250},
    "💻 IT-компания": {"price": 200000, "base_income": 2000, "upgrade_income": 500},
    "🚀 Космодром": {"price": 1000000, "base_income": 10000, "upgrade_income": 1000},
    "🌿 Ферма трав": {"price": 3000, "base_income": 30, "upgrade_income": 30},
    "🐄 Скотный двор": {"price": 8000, "base_income": 80, "upgrade_income": 60},
    "🍷 Винодельня": {"price": 25000, "base_income": 250, "upgrade_income": 150},
    "🔬 Лаборатория": {"price": 100000, "base_income": 1000, "upgrade_income": 400},
    "🏦 Банк": {"price": 500000, "base_income": 5000, "upgrade_income": 800}
}
SPEED_LEVELS = [60, 30, 15, 10, 5, 1]
AMOUNT_UPGRADE_COST = 1000

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

def get_business_amount(biz_type, amount_level, speed_level):
    d = BUSINESSES[biz_type]
    iv = SPEED_LEVELS[speed_level - 1]
    base = d["base_income"] + (amount_level - 1) * d["upgrade_income"]
    amount_per_interval = int(base * iv / 60)
    hourly = int(amount_per_interval * 60 / iv)
    return amount_per_interval, iv, hourly

def get_pending_income(uid, biz_type):
    b = get_business(uid, biz_type)
    if not b:
        return 0
    amt, iv, _ = get_business_amount(biz_type, b["amount_level"], b["speed_level"])
    el = (datetime.now() - b["last_collect"]).total_seconds() / 60
    return int(el // iv) * amt

def collect_income(uid, biz_type):
    b = get_business(uid, biz_type)
    if not b:
        return 0
    amt, iv, _ = get_business_amount(biz_type, b["amount_level"], b["speed_level"])
    last = b["last_collect"]
    now = datetime.now()
    el = (now - last).total_seconds() / 60
    inter = int(el // iv)
    if inter == 0:
        return 0
    earn = inter * amt
    earn = apply_vip_bonus(uid, earn, "farm")
    add_coins(uid, earn)
    new_last = last + timedelta(minutes=inter * iv)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE businesses SET last_collect = %s WHERE user_id = %s AND business_type = %s", (new_last, str(uid), biz_type))
    conn.commit()
    cur.close()
    conn.close()
    update_achievement(uid, "farm_5")
    update_achievement(uid, "farm_10")
    return earn

def buy_business(uid, biz_type):
    if get_business(uid, biz_type):
        return False, "❌ У тебя уже есть эта ферма!"
    price = BUSINESSES[biz_type]["price"]
    if not remove_coins(uid, price):
        return False, f"❌ Нужно {price}💰"
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO businesses (user_id, business_type, amount_level, speed_level, last_collect) VALUES (%s, %s, 1, 1, NOW())", (str(uid), biz_type))
    conn.commit()
    cur.close()
    conn.close()
    businesses = get_user_businesses(uid)
    update_achievement(uid, "farm_5", len(businesses))
    update_achievement(uid, "farm_10", len(businesses))
    return True, f"✅ {biz_type} куплена!"

def upgrade_business_amount(uid, biz_type, levels=1):
    b = get_business(uid, biz_type)
    if not b:
        return False, "❌ Нет такой фермы"
    total_cost = AMOUNT_UPGRADE_COST * levels
    if not remove_coins(uid, total_cost):
        return False, f"❌ Нужно {total_cost}💰"
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE businesses SET amount_level = amount_level + %s WHERE user_id = %s AND business_type = %s", (levels, str(uid), biz_type))
    conn.commit()
    cur.close()
    conn.close()
    return True, f"✅ +{levels} уровень(ей) количества!"

def upgrade_business_speed(uid, biz_type):
    b = get_business(uid, biz_type)
    if not b:
        return False, "❌ Нет такой фермы"
    if b["speed_level"] >= len(SPEED_LEVELS):
        return False, "❌ Максимальная скорость!"
    price = int(BUSINESSES[biz_type]["price"] * 0.5)
    if not remove_coins(uid, price):
        return False, f"❌ Нужно {price}💰"
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE businesses SET speed_level = speed_level + 1 WHERE user_id = %s AND business_type = %s", (str(uid), biz_type))
    conn.commit()
    cur.close()
    conn.close()
    return True, "✅ Скорость увеличена!"

def get_business_info(uid, biz_type):
    b = get_business(uid, biz_type)
    if not b:
        return None
    amt, iv, hr = get_business_amount(biz_type, b["amount_level"], b["speed_level"])
    pending = get_pending_income(uid, biz_type)
    speed_price = int(BUSINESSES[biz_type]["price"] * 0.5)
    return (f"🏭 *{biz_type}*\n\n"
            f"📊 Уровень количества: {b['amount_level']}\n"
            f"💰 Доход за интервал: +{amt}💰\n"
            f"⏱️ Интервал: {iv} мин\n"
            f"📈 Примерно {hr}💰/час\n\n"
            f"💎 Накоплено: {pending}💰\n\n"
            f"🔧 *Апгрейды:*\n"
            f"📈 +{BUSINESSES[biz_type]['upgrade_income']}💰 к доходу — {AMOUNT_UPGRADE_COST}💰\n"
            f"⚡ Ускорить — {speed_price}💰\n\n"
            f"💾 Собрать доход — нажми кнопку ниже")

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
    add_coins(new_uid, 5)
    add_coins(ref_id, 10)
    conn.commit()
    cur.close()
    conn.close()
    update_achievement(ref_id, "referrals_5")
    update_achievement(ref_id, "referrals_20")
    return True

def get_referral_stats(uid):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = %s", (str(uid),))
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count

# ========== КЛАНЫ ==========
def create_clan(uid, name, emoji):
    if len(name) > 20 or not emoji:
        return False, "❌ Название до 20 символов, эмодзи обязательно"
    if not remove_coins(uid, 1000):
        return False, "❌ Нужно 1000💰"
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO clans (name, emoji, owner_id) VALUES (%s,%s,%s) RETURNING clan_id", (name, emoji, str(uid)))
        cid = cur.fetchone()[0]
        cur.execute("INSERT INTO clan_members (user_id, clan_id) VALUES (%s,%s)", (str(uid), cid))
        conn.commit()
        return True, f"✅ Клан {emoji} {name} создан!"
    except:
        return False, "❌ Ошибка, имя занято"
    finally:
        cur.close()
        conn.close()

def join_clan(uid, cid):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM clan_members WHERE user_id = %s", (str(uid),))
    if cur.fetchone():
        cur.close()
        conn.close()
        return False, "❌ Вы уже в клане"
    cur.execute("INSERT INTO clan_members (user_id, clan_id) VALUES (%s,%s)", (str(uid), cid))
    conn.commit()
    cur.close()
    conn.close()
    return True, "✅ Вы вступили в клан"

def get_clan_info(cid):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, emoji, owner_id FROM clans WHERE clan_id = %s", (cid,))
    c = cur.fetchone()
    if not c:
        cur.close()
        conn.close()
        return None
    cur.execute("SELECT COUNT(*) FROM clan_members WHERE clan_id = %s", (cid,))
    members = cur.fetchone()[0]
    cur.execute("SELECT SUM(u.coins) FROM users u JOIN clan_members cm ON u.user_id = cm.user_id WHERE cm.clan_id = %s", (cid,))
    total_coins = cur.fetchone()[0] or 0
    cur.close()
    conn.close()
    return {"name": c[0], "emoji": c[1], "owner": c[2], "members": members, "total_coins": total_coins}

def get_user_clan(uid):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT clan_id FROM clan_members WHERE user_id = %s", (str(uid),))
    r = cur.fetchone()
    cur.close()
    conn.close()
    return r[0] if r else None

def top_clans(limit=10):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT c.clan_id, c.name, c.emoji, COUNT(cm.user_id), COALESCE(SUM(u.coins),0)
        FROM clans c
        LEFT JOIN clan_members cm ON c.clan_id = cm.clan_id
        LEFT JOIN users u ON cm.user_id = u.user_id
        GROUP BY c.clan_id
        ORDER BY COALESCE(SUM(u.coins),0) DESC
        LIMIT %s
    """, (limit,))
    return cur.fetchall()

# ========== КЛАВИАТУРЫ ==========
REGIONS = ["🇷🇺 Россия", "🇺🇦 Украина", "🇧🇾 Беларусь", "🇰🇿 Казахстан"]

def region_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(*[KeyboardButton(r) for r in REGIONS])
    return kb

def main_keyboard(uid):
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton("🎮 Игры"),
        KeyboardButton("💰 Пассивный доход"),
        KeyboardButton("👤 Профиль"),
        KeyboardButton("🎁 Бонус"),
        KeyboardButton("👥 Рефералы"),
        KeyboardButton("❓ Вопрос"),
        KeyboardButton("👑 Кланы"),
        KeyboardButton("🏆 Достижения"),
        KeyboardButton("📊 Статистика"),
        KeyboardButton("👑 VIP статус"),
        KeyboardButton("🎲 Рулетка"),
        KeyboardButton("⚔️ PvP дуэль")
    )
    if uid == ADMIN_ID:
        kb.add(KeyboardButton("🔧 Админ"))
    return kb

def menu_button():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔙 Меню", callback_data="back_main"))
    return kb

def dice_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎲 1 кубик", callback_data="dice_1"),
        InlineKeyboardButton("🎲🎲 2 кубика", callback_data="dice_2"),
        InlineKeyboardButton("🎲🎲🎲 3 кубика", callback_data="dice_3"),
        InlineKeyboardButton("🎲 x5 5 кубиков", callback_data="dice_5"),
        InlineKeyboardButton("🎲 x10 10 кубиков", callback_data="dice_10"),
        InlineKeyboardButton("🎲💰 Кости на удачу", callback_data="dice_luck"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    return kb

def games_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🔢 Угадай число", callback_data="gamble_number"),
        InlineKeyboardButton("✂️ Камень-ножницы", callback_data="gamble_rps"),
        InlineKeyboardButton("🎴 Карты и Джокер", callback_data="gamble_cards"),
        InlineKeyboardButton("🎰 Слоты", callback_data="gamble_slots"),
        InlineKeyboardButton("💎 Камень-мешок-монета", callback_data="gamble_rps2"),
        InlineKeyboardButton("🎯 Угадай цвет", callback_data="gamble_color"),
        InlineKeyboardButton("📈 Выше/Ниже", callback_data="gamble_highlow"),
        InlineKeyboardButton("🔫 Русская рулетка", callback_data="gamble_roulette"),
        InlineKeyboardButton("🎲 Чет/Нечет", callback_data="gamble_evenodd"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    return kb

def admin_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton("💰 Выдать монеты"),
        KeyboardButton("🔻 Забрать монеты"),
        KeyboardButton("👥 Все пользователи"),
        KeyboardButton("📢 Рассылка"),
        KeyboardButton("🎁 Подарить ферму"),
        KeyboardButton("🔙 Меню")
    )
    return kb

# ========== ОСТАЛЬНЫЕ ИГРЫ ==========
def play_again_keyboard(game_callback):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎮 Сыграть ещё", callback_data=game_callback),
        InlineKeyboardButton("🔙 Меню", callback_data="back_main")
    )
    return kb

def dice_game_play(m, uid, num, mn, mx, win_exact_min, win_exact_max, game_callback):
    delete_previous_message(m.chat.id, uid)
    try:
        bet = int(m.text)
        if bet < mn or bet > mx:
            send_and_track(m.chat.id, f"❌ {mn}–{mx}", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
            return
        rolls = [random.randint(1,6) for _ in range(num)]
        total = sum(rolls)
        if bet == total:
            win = random.randint(win_exact_min, win_exact_max)
            win = apply_vip_bonus(uid, win, "game")
            add_coins(uid, win)
            text = f"🎲 {total}. Победа! +{win}💰"
            update_game_stats(uid, True, win)
        else:
            text = f"🎲 {total}. Проигрыш! -1💰"
            update_game_stats(uid, False, -1)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard(game_callback), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(m.chat.id, "❌ Введи число", user_id=uid)

def dice_luck_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    if not remove_coins(uid, 2):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
        return
    rolls = [random.randint(1,6) for _ in range(3)]
    total = sum(rolls)
    if total >= 15:
        win = apply_vip_bonus(uid, 10, "game")
        add_coins(uid, win)
        text = f"🎲💰 {total}. Победа! +{win}💰"
        update_game_stats(uid, True, win)
    else:
        text = f"🎲💰 {total}. Проигрыш! -2💰"
        update_game_stats(uid, False, -2)
    send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("dice_luck"), parse_mode="Markdown", user_id=uid)

def gamble_number_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    try:
        bet = int(m.text)
        if bet < 1 or bet > 20:
            send_and_track(m.chat.id, "❌ 1–20", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
            return
        secret = random.randint(1,20)
        if bet == secret:
            win = random.randint(5,12)
            win = apply_vip_bonus(uid, win, "game")
            add_coins(uid, win)
            text = f"🔢 {secret}. Победа! +{win}💰"
            update_game_stats(uid, True, win)
        else:
            text = f"🔢 {secret}. Проигрыш! -1💰"
            update_game_stats(uid, False, -1)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("gamble_number"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(m.chat.id, "❌ Введи число", user_id=uid)

def gamble_rps_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    choice = m.text.lower()
    if choice not in ["камень","ножницы","бумага"]:
        send_and_track(m.chat.id, "❌ камень/ножницы/бумага", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
        return
    bot_choice = random.choice(["камень","ножницы","бумага"])
    if choice == bot_choice:
        add_coins(uid, 2)
        text = "🤝 Ничья! +2💰"
        update_game_stats(uid, False, 2)
    elif (choice=="камень" and bot_choice=="ножницы") or (choice=="ножницы" and bot_choice=="бумага") or (choice=="бумага" and bot_choice=="камень"):
        win = random.randint(3,7)
        win = apply_vip_bonus(uid, win, "game")
        add_coins(uid, win)
        text = f"🎉 Победа! +{win}💰"
        update_game_stats(uid, True, win)
    else:
        text = f"💀 Поражение! -1💰"
        update_game_stats(uid, False, -1)
    send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("gamble_rps"), parse_mode="Markdown", user_id=uid)

def gamble_cards_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    try:
        ch = int(m.text)
        if ch < 1 or ch > 5:
            send_and_track(m.chat.id, "❌ 1–5", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
            return
        joker_pos = random.randint(1, 5)
        if ch == joker_pos:
            win = apply_vip_bonus(uid, 10, "game")
            add_coins(uid, win)
            text = f"🎴 *ДЖОКЕР!* +{win}💰"
            update_game_stats(uid, True, win)
        else:
            text = f"🎴 Масть... -1💰"
            update_game_stats(uid, False, -1)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("gamble_cards"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(m.chat.id, "❌ Введи число", user_id=uid)

def gamble_slots_play(uid):
    delete_previous_message(uid, uid)
    if not remove_coins(uid, 1):
        send_and_track(uid, "❌ Нет монет", user_id=uid)
        return
    r = [random.choice(["🍒","🍊","🍋","🔔","💎","7️⃣"]) for _ in range(3)]
    if r[0]==r[1]==r[2]=="7️⃣":
        win = apply_vip_bonus(uid, 50, "game")
    elif r[0]==r[1]==r[2]:
        win = apply_vip_bonus(uid, 20, "game")
    elif r[0]==r[1] or r[1]==r[2] or r[0]==r[2]:
        win = apply_vip_bonus(uid, 5, "game")
    else:
        win = 0
    if win:
        add_coins(uid, win)
        text = f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n🎉 +{win}💰"
        update_game_stats(uid, True, win)
    else:
        text = f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n💀 -1💰"
        update_game_stats(uid, False, -1)
    send_and_track(uid, text, reply_markup=play_again_keyboard("gamble_slots"), parse_mode="Markdown", user_id=uid)

def gamble_rps2_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    ch = m.text.lower()
    if ch not in ["камень","мешок","монета"]:
        send_and_track(m.chat.id, "❌ камень/мешок/монета", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
        return
    bot_ch = random.choice(["камень","мешок","монета"])
    rules = {"камень":"мешок","мешок":"монета","монета":"камень"}
    if ch == bot_ch:
        add_coins(uid, 2)
        text = "🤝 Ничья! +2💰"
        update_game_stats(uid, False, 2)
    elif rules[ch] == bot_ch:
        win = random.randint(3,7)
        win = apply_vip_bonus(uid, win, "game")
        add_coins(uid, win)
        text = f"🎉 Победа! +{win}💰"
        update_game_stats(uid, True, win)
    else:
        text = f"💀 Поражение! -1💰"
        update_game_stats(uid, False, -1)
    send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("gamble_rps2"), parse_mode="Markdown", user_id=uid)

def gamble_color_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    ch = m.text.lower()
    if ch not in ["красный","чёрный"]:
        send_and_track(m.chat.id, "❌ красный или чёрный", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
        return
    color = random.choice(["🔴 красный","⚫ чёрный"])
    user_color = "красный" if "красн" in ch else "чёрный"
    if user_color in color:
        win = apply_vip_bonus(uid, 3, "game")
        add_coins(uid, win)
        text = f"🎯 {color}. Победа! +{win}💰"
        update_game_stats(uid, True, win)
    else:
        text = f"🎯 {color}. Поражение! -1💰"
        update_game_stats(uid, False, -1)
    send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("gamble_color"), parse_mode="Markdown", user_id=uid)

def gamble_highlow_play(m, uid, first):
    delete_previous_message(m.chat.id, uid)
    ch = m.text.lower()
    if ch not in ["выше","ниже"]:
        send_and_track(m.chat.id, "❌ выше или ниже", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
        return
    second = random.randint(1,10)
    if (ch=="выше" and second>first) or (ch=="ниже" and second<first):
        win = random.randint(4,8)
        win = apply_vip_bonus(uid, win, "game")
        add_coins(uid, win)
        text = f"📈 {first}→{second}. Победа! +{win}💰"
        update_game_stats(uid, True, win)
    elif second == first:
        add_coins(uid, 2)
        text = f"📈 {first}→{second}. Ничья! +2💰"
        update_game_stats(uid, False, 2)
    else:
        text = f"📈 {first}→{second}. Поражение! -1💰"
        update_game_stats(uid, False, -1)
    send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("gamble_highlow"), parse_mode="Markdown", user_id=uid)

def gamble_roulette_play(uid):
    delete_previous_message(uid, uid)
    if not remove_coins(uid, 5):
        send_and_track(uid, "❌ Нет монет", user_id=uid)
        return
    if random.randint(1,6) == 1:
        text = "🔫 *Русская рулетка*\n💀 БАХ! -5💰"
        update_game_stats(uid, False, -5)
    else:
        win = apply_vip_bonus(uid, 25, "game")
        add_coins(uid, win)
        text = f"🔫 *Русская рулетка*\n🎉 ЩЁЛК! +{win}💰"
        update_game_stats(uid, True, win)
    send_and_track(uid, text, reply_markup=play_again_keyboard("gamble_roulette"), parse_mode="Markdown", user_id=uid)

def gamble_evenodd_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    ch = m.text.lower()
    if ch not in ["чётное","нечётное","четное","нечетное"]:
        send_and_track(m.chat.id, "❌ чётное или нечётное", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
        return
    num = random.randint(1,10)
    is_even = num % 2 == 0
    correct = "чётное" if is_even else "нечётное"
    if (ch in ["чётное","четное"] and is_even) or (ch in ["нечётное","нечетное"] and not is_even):
        win = random.randint(3,5)
        win = apply_vip_bonus(uid, win, "game")
        add_coins(uid, win)
        text = f"🎲 {num} ({correct}). Победа! +{win}💰"
        update_game_stats(uid, True, win)
    else:
        text = f"🎲 {num} ({correct}). Поражение! -1💰"
        update_game_stats(uid, False, -1)
    send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("gamble_evenodd"), parse_mode="Markdown", user_id=uid)

# ========== ОСНОВНЫЕ ОБРАБОТЧИКИ ==========
@bot.message_handler(commands=['start'])
def start(m):
    uid = m.chat.id
    args = m.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        process_referral(uid, args[1].split("_")[1])
    u = get_user(uid)
    if m.from_user.username:
        update_user(uid, username=m.from_user.username.lower())
    if not u.get("region"):
        send_and_track(uid, "🌍 *Выбери регион:*", reply_markup=region_keyboard(), parse_mode="Markdown", user_id=uid)
    else:
        send_and_track(uid, f"🎉 *Добро пожаловать!*\n\n{format_profile(uid)}", reply_markup=main_keyboard(uid), parse_mode="Markdown", user_id=uid)

@bot.message_handler(func=lambda m: m.text in REGIONS)
def save_region(m):
    uid = m.chat.id
    update_user(uid, region=m.text)
    send_and_track(uid, f"✅ Регион *{m.text}* сохранён!", reply_markup=menu_button(), parse_mode="Markdown", user_id=uid)
    send_and_track(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown", user_id=uid)

@bot.message_handler(func=lambda m: True)
def handle_buttons(m):
    uid = m.chat.id
    text = m.text
    u = get_user(uid)

    if text == "🎮 Игры":
        delete_previous_message(m.chat.id, uid)
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("🎲 Кубики", callback_data="dice_menu"),
            InlineKeyboardButton("🎮 Остальные игры", callback_data="games_menu"),
            InlineKeyboardButton("🔙 Меню", callback_data="back_main")
        )
        send_and_track(uid, "🎮 *Выбери категорию игр:*", reply_markup=kb, parse_mode="Markdown", user_id=uid)
    elif text == "💰 Пассивный доход":
        delete_previous_message(m.chat.id, uid)
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("🛒 Купить ферму", callback_data="buy_business_menu"),
            InlineKeyboardButton("🏭 Мои фермы", callback_data="my_businesses"),
            InlineKeyboardButton("🔙 Меню", callback_data="back_main")
        )
        send_and_track(uid, "🏭 *Пассивный доход*\nВыбери действие:", reply_markup=kb, parse_mode="Markdown", user_id=uid)
    elif text == "👤 Профиль":
        delete_previous_message(m.chat.id, uid)
        send_and_track(uid, format_profile(uid), reply_markup=menu_button(), parse_mode="Markdown", user_id=uid)
    elif text == "🎁 Бонус":
        delete_previous_message(m.chat.id, uid)
        ok, msg = daily_streak_bonus(uid)
        send_and_track(uid, msg, reply_markup=menu_button(), parse_mode="Markdown", user_id=uid)
    elif text == "👥 Рефералы":
        delete_previous_message(m.chat.id, uid)
        send_and_track(uid, f"👥 *Рефералы*\n📎 {get_referral_link(uid)}\n👥 Приглашено: {get_referral_stats(uid)}", reply_markup=menu_button(), parse_mode="Markdown", user_id=uid)
    elif text == "❓ Вопрос":
        delete_previous_message(m.chat.id, uid)
        send_and_track(uid, "✍️ Напиши вопрос:", user_id=uid)
        waiting_for_question[uid] = True
    elif text == "👑 Кланы":
        delete_previous_message(m.chat.id, uid)
        cid = get_user_clan(uid)
        kb = InlineKeyboardMarkup(row_width=2)
        if not cid:
            kb.add(InlineKeyboardButton("📝 Создать клан", callback_data="clan_create"))
            kb.add(InlineKeyboardButton("🔍 Вступить", callback_data="clan_join"))
            kb.add(InlineKeyboardButton("🏆 Топ кланов", callback_data="clan_top"))
        else:
            info = get_clan_info(cid)
            if info:
                txt = f"🏰 {info['emoji']} *{info['name']}*\n👥 {info['members']}\n💰 {info['total_coins']}💰\n👑 Владелец: {info['owner']}"
            else:
                txt = "❌ Клан не найден"
            kb.add(InlineKeyboardButton("🚪 Выйти", callback_data="clan_leave"))
            kb.add(InlineKeyboardButton("🏆 Топ кланов", callback_data="clan_top"))
            send_and_track(uid, txt, reply_markup=kb, parse_mode="Markdown", user_id=uid)
            return
        send_and_track(uid, "👑 *Кланы*", reply_markup=kb, parse_mode="Markdown", user_id=uid)
    elif text == "🏆 Достижения":
        delete_previous_message(m.chat.id, uid)
        achs = get_achievements_progress(uid)
        msg = "🏆 *Твои достижения:*\n\n"
        for name, desc, status, claimed in achs:
            msg += f"• {name}: {desc} — {status}\n"
        send_and_track(uid, msg, reply_markup=menu_button(), parse_mode="Markdown", user_id=uid)
    elif text == "📊 Статистика":
        delete_previous_message(m.chat.id, uid)
        send_and_track(uid, get_player_stats(uid), reply_markup=menu_button(), parse_mode="Markdown", user_id=uid)
    elif text == "👑 VIP статус":
        delete_previous_message(m.chat.id, uid)
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("👑 VIP игры (5000💰)", callback_data="buy_vip_game"),
            InlineKeyboardButton("💎 VIP фермы (50000💰)", callback_data="buy_vip_farm"),
            InlineKeyboardButton("🔙 Меню", callback_data="back_main")
        )
        send_and_track(uid, "👑 *VIP статус*\n\nVIP игры: +10% к выигрышам в играх (5000💰)\nVIP фермы: +10% к доходу с ферм (50000💰)", reply_markup=kb, parse_mode="Markdown", user_id=uid)
    elif text == "🎲 Рулетка":
        delete_previous_message(m.chat.id, uid)
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("🎲 Ставка на число", callback_data="roulette_number"),
            InlineKeyboardButton("🎨 Ставка на цвет", callback_data="roulette_color"),
            InlineKeyboardButton("🔙 Меню", callback_data="back_main")
        )
        send_and_track(uid, "🎲 *Рулетка*\nВыбери тип ставки:", reply_markup=kb, parse_mode="Markdown", user_id=uid)
    elif text == "⚔️ PvP дуэль":
        delete_previous_message(m.chat.id, uid)
        send_and_track(uid, "⚔️ *PvP дуэль*\n\nВызови друга на дуэль:\n`/duel @username сумма`\n\nПринять дуэль:\n`/accept`", reply_markup=menu_button(), parse_mode="Markdown", user_id=uid)
    elif text == "🔧 Админ" and uid == ADMIN_ID:
        delete_previous_message(m.chat.id, uid)
        admin_panel(uid)
    elif uid == ADMIN_ID and text in ["💰 Выдать монеты","🔻 Забрать монеты","👥 Все пользователи","📢 Рассылка","🎁 Подарить ферму","🔙 Меню"]:
        delete_previous_message(m.chat.id, uid)
        admin_commands(uid, text)
    elif waiting_for_question.get(uid):
        forward_question(uid, text)
        waiting_for_question[uid] = False
    else:
        send_and_track(uid, "❌ Используй кнопки меню 👇", user_id=uid)

@bot.message_handler(commands=['duel'])
def duel_cmd(m):
    uid = m.chat.id
    parts = m.text.split()
    if len(parts) != 3:
        send_and_track(uid, "❌ Формат: /duel @username сумма", user_id=uid)
        return
    target = parts[1].replace("@", "").lower()
    try:
        amount = int(parts[2])
    except:
        send_and_track(uid, "❌ Сумма числом", user_id=uid)
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
        send_and_track(uid, f"❌ @{target} не найден", user_id=uid)
        return
    ok, msg = duel_request(uid, target_uid, amount)
    send_and_track(uid, msg, reply_markup=menu_button(), user_id=uid)
    if ok:
        bot.send_message(int(target_uid), f"⚔️ *Запрос на дуэль!*\n@{get_user(uid)['username']} вызывает тебя на дуэль на {amount}💰\nНапиши /accept", parse_mode="Markdown")

@bot.message_handler(commands=['accept'])
def accept_cmd(m):
    uid = m.chat.id
    ok, msg = duel_accept(uid)
    send_and_track(uid, msg, reply_markup=menu_button(), parse_mode="Markdown", user_id=uid)

def admin_panel(uid):
    send_and_track(uid, "🔧 *Админ-панель*", reply_markup=admin_keyboard(), parse_mode="Markdown", user_id=uid)

def admin_commands(uid, text):
    if text == "💰 Выдать монеты":
        send_and_track(uid, "Введи ID и сумму: `123456789 100`", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, process_admin_add)
    elif text == "🔻 Забрать монеты":
        send_and_track(uid, "Введи ID и сумму: `123456789 50`", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, process_admin_remove)
    elif text == "👥 Все пользователи":
        users = all_users_list()
        msg = "👥 *Пользователи:*\n"
        for u in users[:30]:
            msg += f"🆔 {u} — {get_user(u)['coins']}💰\n"
        send_and_track(uid, msg, reply_markup=menu_button(), parse_mode="Markdown", user_id=uid)
    elif text == "📢 Рассылка":
        send_and_track(uid, "Введи сообщение:", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, broadcast_message)
    elif text == "🎁 Подарить ферму":
        send_and_track(uid, "Введи ID пользователя и название фермы через пробел:\nПример: `123456789 🚀 Космодром`", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, process_admin_gift_farm)
    elif text == "🔙 Меню":
        send_and_track(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown", user_id=uid)

def process_admin_add(m):
    uid = m.chat.id
    try:
        tid, amt = m.text.split()
        add_coins(int(tid), int(amt))
        send_and_track(uid, f"✅ Выдано {amt}💰 {tid}", reply_markup=menu_button(), user_id=uid)
    except:
        send_and_track(uid, "❌ Ошибка", user_id=uid)

def process_admin_remove(m):
    uid = m.chat.id
    try:
        tid, amt = m.text.split()
        if remove_coins(int(tid), int(amt)):
            send_and_track(uid, f"✅ Забрано {amt}💰 у {tid}", reply_markup=menu_button(), user_id=uid)
        else:
            send_and_track(uid, f"❌ У {tid} нет {amt}💰", reply_markup=menu_button(), user_id=uid)
    except:
        send_and_track(uid, "❌ Ошибка", user_id=uid)

def process_admin_gift_farm(m):
    uid = m.chat.id
    try:
        parts = m.text.split()
        target_id = int(parts[0])
        biz_type = " ".join(parts[1:])
        if biz_type not in BUSINESSES:
            send_and_track(uid, f"❌ Ферма '{biz_type}' не найдена", user_id=uid)
            return
        if get_business(target_id, biz_type):
            send_and_track(uid, f"❌ У пользователя уже есть {biz_type}", user_id=uid)
            return
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO businesses (user_id, business_type, amount_level, speed_level, last_collect) VALUES (%s, %s, 1, 1, NOW())", (str(target_id), biz_type))
        conn.commit()
        cur.close()
        conn.close()
        send_and_track(uid, f"✅ Подарена ферма {biz_type} пользователю {target_id}", reply_markup=menu_button(), user_id=uid)
        bot.send_message(target_id, f"🎁 *Создатель бота подарил тебе ферму {biz_type}!* Теперь ты можешь её прокачивать!", parse_mode="Markdown")
    except:
        send_and_track(uid, "❌ Ошибка. Пример: `123456789 🚀 Космодром`", user_id=uid)

def broadcast_message(m):
    if m.chat.id != ADMIN_ID:
        return
    text = m.text
    sent = 0
    for uid in all_users_list():
        try:
            bot.send_message(int(uid), f"📢 *Рассылка:*\n{text}", parse_mode="Markdown")
            sent += 1
        except:
            pass
    send_and_track(ADMIN_ID, f"✅ Отправлено {sent}", reply_markup=menu_button(), user_id=ADMIN_ID)

def forward_question(uid, q):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✍️ Ответить", callback_data=f"answer_{uid}"))
    bot.send_message(ADMIN_ID, f"📩 *Вопрос от* `{uid}`:\n{q}", reply_markup=kb, parse_mode="Markdown")

# ========== CALLBACK ==========
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    uid = call.message.chat.id
    data = call.data

    if data == "back_main":
        delete_previous_message(uid, uid)
        send_and_track(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown", user_id=uid)
    elif data == "dice_menu":
        delete_previous_message(uid, uid)
        send_and_track(uid, "🎲 *Выбери количество кубиков:*", reply_markup=dice_keyboard(), parse_mode="Markdown", user_id=uid)
    elif data == "games_menu":
        delete_previous_message(uid, uid)
        send_and_track(uid, "🎮 *Выбери игру:*", reply_markup=games_keyboard(), parse_mode="Markdown", user_id=uid)

    elif data.startswith("dice_"):
        delete_previous_message(uid, uid)
        if data == "dice_1":
            send_and_track(uid, "🎲 Введи число от 1 до 6:", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: dice_game_play(m, uid, 1, 1, 6, 2, 5, "dice_1"))
        elif data == "dice_2":
            send_and_track(uid, "🎲🎲 Введи сумму от 2 до 12:", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: dice_game_play(m, uid, 2, 2, 12, 4, 10, "dice_2"))
        elif data == "dice_3":
            send_and_track(uid, "🎲🎲🎲 Введи сумму от 3 до 18:", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: dice_game_play(m, uid, 3, 3, 18, 8, 15, "dice_3"))
        elif data == "dice_5":
            send_and_track(uid, "🎲 x5 Введи сумму от 5 до 30:", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: dice_game_play(m, uid, 5, 5, 30, 15, 25, "dice_5"))
        elif data == "dice_10":
            send_and_track(uid, "🎲 x10 Введи сумму от 10 до 60:", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: dice_game_play(m, uid, 10, 10, 60, 30, 50, "dice_10"))
        elif data == "dice_luck":
            send_and_track(uid, "🎲💰 Кости на удачу (3 кубика, сумма ≥15). Ставка 2💰. Готов? Напиши 'да'", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: dice_luck_play(m, uid))
    elif data.startswith("gamble_"):
        delete_previous_message(uid, uid)
        if data == "gamble_number":
            send_and_track(uid, "🔢 Введи число от 1 до 20:", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_number_play(m, uid))
        elif data == "gamble_rps":
            send_and_track(uid, "✂️ камень, ножницы, бумага:", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_rps_play(m, uid))
        elif data == "gamble_cards":
            send_and_track(uid, "🎴 *Карты и Джокер*\n1️⃣♠️ 2️⃣♥️ 3️⃣♣️ 4️⃣♦️ 5️⃣🃏\nВведи номер (1–5):", parse_mode="Markdown", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_cards_play(m, uid))
        elif data == "gamble_slots":
            gamble_slots_play(uid)
        elif data == "gamble_rps2":
            send_and_track(uid, "💎 *Камень-мешок-монета*\nВыбери: камень, мешок, монета", parse_mode="Markdown", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_rps2_play(m, uid))
        elif data == "gamble_color":
            send_and_track(uid, "🎯 *Угадай цвет*\n🔴 Красный или ⚫ Чёрный?", parse_mode="Markdown", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_color_play(m, uid))
        elif data == "gamble_highlow":
            first = random.randint(1,10)
            send_and_track(uid, f"📈 *Выше/Ниже*\nТекущее число: {first}\nСледующее будет *выше* или *ниже*?", parse_mode="Markdown", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_highlow_play(m, uid, first))
        elif data == "gamble_roulette":
            gamble_roulette_play(uid)
        elif data == "gamble_evenodd":
            send_and_track(uid, "🎲 *Чет/Нечет*\nЧисло 1–10, угадай чётное или нечётное", parse_mode="Markdown", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_evenodd_play(m, uid))

    elif data == "buy_business_menu":
        delete_previous_message(uid, uid)
        kb = InlineKeyboardMarkup(row_width=1)
        for name, d in BUSINESSES.items():
            kb.add(InlineKeyboardButton(f"{name} ({d['price']}💰)", callback_data=f"buy_business_{name}"))
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_main"))
        send_and_track(uid, "🏭 *Купить ферму*\nВыбери ферму:", reply_markup=kb, parse_mode="Markdown", user_id=uid)
    elif data == "my_businesses":
        delete_previous_message(uid, uid)
        businesses = get_user_businesses(uid)
        if not businesses:
            send_and_track(uid, "❌ У тебя нет ферм. Купи их в разделе 'Купить ферму'", user_id=uid)
            return
        kb = InlineKeyboardMarkup(row_width=2)
        for b in businesses:
            kb.add(InlineKeyboardButton(f"📊 {b['business_type']}", callback_data=f"select_business_{b['business_type']}"))
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_main"))
        send_and_track(uid, "🏭 *Твои фермы*\nВыбери для управления:", reply_markup=kb, parse_mode="Markdown", user_id=uid)
    elif data.startswith("buy_business_"):
        biz = data.replace("buy_business_", "")
        ok, msg = buy_business(uid, biz)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        if ok:
            delete_previous_message(uid, uid)
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(
                InlineKeyboardButton("🛒 Купить ферму", callback_data="buy_business_menu"),
                InlineKeyboardButton("🏭 Мои фермы", callback_data="my_businesses"),
                InlineKeyboardButton("◀️ Назад", callback_data="back_main")
            )
            send_and_track(uid, "🏭 *Пассивный доход*\nВыбери действие:", reply_markup=kb, parse_mode="Markdown", user_id=uid)
    elif data.startswith("select_business_"):
        biz = data.replace("select_business_", "")
        info = get_business_info(uid, biz)
        if info:
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("📈 +💰 (апгрейд)", callback_data=f"upgrade_amount_{biz}"))
            kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data=f"upgrade_speed_{biz}"))
            kb.add(InlineKeyboardButton("💾 Собрать", callback_data=f"collect_business_{biz}"))
            kb.add(InlineKeyboardButton("◀️ Назад", callback_data="my_businesses"))
            send_and_track(uid, info, reply_markup=kb, parse_mode="Markdown", user_id=uid)
    elif data.startswith("upgrade_amount_"):
        biz = data.replace("upgrade_amount_", "")
        buy_amount_buffer[uid] = biz
        send_and_track(uid, "💰 Сколько уровней апгрейда купить? (1–100)", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: process_amount_upgrade(m, uid, biz, call))
    elif data.startswith("upgrade_speed_"):
        biz = data.replace("upgrade_speed_", "")
        ok, msg = upgrade_business_speed(uid, biz)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        if ok:
            info = get_business_info(uid, biz)
            if info:
                kb = InlineKeyboardMarkup(row_width=2)
                kb.add(InlineKeyboardButton("📈 +💰 (апгрейд)", callback_data=f"upgrade_amount_{biz}"))
                kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data=f"upgrade_speed_{biz}"))
                kb.add(InlineKeyboardButton("💾 Собрать", callback_data=f"collect_business_{biz}"))
                kb.add(InlineKeyboardButton("◀️ Назад", callback_data="my_businesses"))
                send_and_track(uid, info, reply_markup=kb, parse_mode="Markdown", user_id=uid)
    elif data.startswith("collect_business_"):
        biz = data.replace("collect_business_", "")
        earned = collect_income(uid, biz)
        bot.answer_callback_query(call.id, f"✅ Собрано {earned}💰", show_alert=True)
        info = get_business_info(uid, biz)
        if info:
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("📈 +💰 (апгрейд)", callback_data=f"upgrade_amount_{biz}"))
            kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data=f"upgrade_speed_{biz}"))
            kb.add(InlineKeyboardButton("💾 Собрать", callback_data=f"collect_business_{biz}"))
            kb.add(InlineKeyboardButton("◀️ Назад", callback_data="my_businesses"))
            send_and_track(uid, info, reply_markup=kb, parse_mode="Markdown", user_id=uid)

    elif data == "clan_create":
        send_and_track(uid, "📝 *Создание клана*\nВведи название и эмодзи: `Воины ⚔️`", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: process_clan_create(m, uid))
    elif data == "clan_join":
        send_and_track(uid, "🔍 Введи ID клана:", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: process_clan_join(m, uid))
    elif data == "clan_leave":
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM clan_members WHERE user_id = %s", (str(uid),))
        conn.commit()
        cur.close()
        conn.close()
        bot.answer_callback_query(call.id, "✅ Вы вышли из клана", show_alert=True)
        send_and_track(uid, "👑 Кланы", reply_markup=main_keyboard(uid), parse_mode="Markdown", user_id=uid)
    elif data == "clan_top":
        top = top_clans(10)
        if not top:
            text = "🏆 Топ кланов пуст"
        else:
            text = "🏆 *Топ кланов:*\n"
            for i, (cid, name, emoji, members, coins) in enumerate(top, 1):
                text += f"{i}. {emoji} {name} — 👥{members}, 💰{coins}💰\n"
        send_and_track(uid, text, parse_mode="Markdown", user_id=uid)

    elif data == "roulette_number":
        send_and_track(uid, "🎲 Введи число (0–36) и ставку через пробел:\nПример: `17 100`", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: roulette_number_play(m, uid))
    elif data == "roulette_color":
        send_and_track(uid, "🎲 Введи цвет (красный/чёрный/зелёный) и ставку через пробел:\nПример: `красный 100`", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: roulette_color_play(m, uid))

    elif data == "buy_vip_game":
        ok, msg = buy_vip_game(uid)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        if ok:
            send_and_track(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown", user_id=uid)
    elif data == "buy_vip_farm":
        ok, msg = buy_vip_farm(uid)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        if ok:
            send_and_track(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown", user_id=uid)

    elif data.startswith("answer_"):
        uid_q = data.split("_")[1]
        send_and_track(ADMIN_ID, f"✍️ Ответ для {uid_q}:", user_id=ADMIN_ID)
        bot.register_next_step_handler(call.message, lambda m: send_answer(m, uid_q))

def roulette_number_play(m, uid):
    try:
        parts = m.text.split()
        number = int(parts[0])
        bet = int(parts[1])
        if number < 0 or number > 36:
            send_and_track(uid, "❌ Число от 0 до 36", user_id=uid)
            return
        ok, msg = roulette_play(uid, bet, "number", number)
        send_and_track(uid, msg, reply_markup=menu_button(), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(uid, "❌ Пример: `17 100`", user_id=uid)

def roulette_color_play(m, uid):
    try:
        parts = m.text.split()
        color = parts[0].lower()
        bet = int(parts[1])
        if color not in ["красный", "чёрный", "зелёный"]:
            send_and_track(uid, "❌ красный/чёрный/зелёный", user_id=uid)
            return
        ok, msg = roulette_play(uid, bet, "color", color)
        send_and_track(uid, msg, reply_markup=menu_button(), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(uid, "❌ Пример: `красный 100`", user_id=uid)

def process_amount_upgrade(m, uid, biz_type, call):
    try:
        levels = int(m.text)
        if levels < 1 or levels > 100:
            send_and_track(uid, "❌ От 1 до 100", user_id=uid)
            return
        ok, msg = upgrade_business_amount(uid, biz_type, levels)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        if ok:
            info = get_business_info(uid, biz_type)
            if info:
                kb = InlineKeyboardMarkup(row_width=2)
                kb.add(InlineKeyboardButton("📈 +💰 (апгрейд)", callback_data=f"upgrade_amount_{biz_type}"))
                kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data=f"upgrade_speed_{biz_type}"))
                kb.add(InlineKeyboardButton("💾 Собрать", callback_data=f"collect_business_{biz_type}"))
                kb.add(InlineKeyboardButton("◀️ Назад", callback_data="my_businesses"))
                send_and_track(uid, info, reply_markup=kb, parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(uid, "❌ Введи число", user_id=uid)

def process_clan_create(m, uid):
    parts = m.text.strip().split()
    if len(parts) < 2:
        send_and_track(uid, "❌ Нужно название и эмодзи", user_id=uid)
        return
    name = " ".join(parts[:-1])[:20]
    emoji = parts[-1]
    ok, msg = create_clan(uid, name, emoji)
    send_and_track(uid, msg, parse_mode="Markdown", user_id=uid)
    if ok:
        send_and_track(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown", user_id=uid)

def process_clan_join(m, uid):
    try:
        cid = int(m.text.strip())
        ok, msg = join_clan(uid, cid)
        send_and_track(uid, msg, parse_mode="Markdown", user_id=uid)
        if ok:
            send_and_track(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(uid, "❌ Введи число", user_id=uid)

def send_answer(m, target_id):
    if m.chat.id != ADMIN_ID:
        return
    bot.send_message(int(target_id), f"📬 *Ответ:*\n{m.text}", parse_mode="Markdown")
    send_and_track(ADMIN_ID, f"✅ Ответ отправлен {target_id}", reply_markup=menu_button(), user_id=ADMIN_ID)

if __name__ == "__main__":
    print("✅ ФИНАЛЬНЫЙ БОТ ЗАПУЩЕН!")
    print("📊 10 ферм, 30 игр, достижения, VIP статус, рулетка, PvP дуэль, ежедневный стрейк, статистика")
    bot.infinity_polling(skip_pending=True)
