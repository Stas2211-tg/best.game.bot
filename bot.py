import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import random
import os
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor
import redis
import json

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
jackpot_data = {"total": 0}
pig_scores = {}

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
            coins INTEGER DEFAULT 5,
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

def send_and_track(chat_id, text, reply_markup=None, parse_mode="Markdown", user_id=None):
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
    return (f"┌─────────────────────┐\n"
            f"│  👤 *{u.get('username') or 'Игрок'}*\n"
            f"│  💰 Баланс: `{u['coins']}` монет\n"
            f"│  📍 Регион: {region}\n"
            f"│  🎮 Всего игр: {u.get('total_games', 0)}\n"
            f"│  🏆 Побед: {u.get('total_wins', 0)}\n"
            f"└─────────────────────┘")

# ========== ИНЛАЙН-КЛАВИАТУРЫ ==========
REGIONS = ["🇷🇺 Россия", "🇺🇦 Украина", "🇧🇾 Беларусь", "🇰🇿 Казахстан"]

def main_menu_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎮 Игры", callback_data="games_menu"),
        InlineKeyboardButton("💰 Пассивный доход", callback_data="income_menu"),
        InlineKeyboardButton("👤 Профиль", callback_data="profile"),
        InlineKeyboardButton("🎁 Бонус", callback_data="bonus"),
        InlineKeyboardButton("👥 Рефералы", callback_data="referrals"),
        InlineKeyboardButton("👥 Кланы", callback_data="clans_menu"),
        InlineKeyboardButton("❓ Вопрос", callback_data="ask_question")
    )
    if str(uid) == str(ADMIN_ID):
        kb.add(InlineKeyboardButton("🔧 Админ-панель", callback_data="admin_panel"))
    return kb

def games_menu_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎲 Кубики", callback_data="dice_menu"),
        InlineKeyboardButton("🔢 Угадай число", callback_data="gamble_number"),
        InlineKeyboardButton("✂️ Камень-ножницы", callback_data="gamble_rps"),
        InlineKeyboardButton("🎴 Карты и Джокер", callback_data="gamble_cards"),
        InlineKeyboardButton("🎰 Слоты", callback_data="gamble_slots"),
        InlineKeyboardButton("💎 Камень-мешок-монета", callback_data="gamble_rps2"),
        InlineKeyboardButton("🎯 Угадай цвет", callback_data="gamble_color"),
        InlineKeyboardButton("📈 Выше/Ниже", callback_data="gamble_highlow"),
        InlineKeyboardButton("🔫 Русская рулетка", callback_data="gamble_roulette"),
        InlineKeyboardButton("🎲 Чет/Нечет", callback_data="gamble_evenodd"),
        InlineKeyboardButton("🎲 Счастливое число", callback_data="game_luckynum"),
        InlineKeyboardButton("🍀 Клевер", callback_data="game_clover"),
        InlineKeyboardButton("💣 Мина", callback_data="game_mine"),
        InlineKeyboardButton("🎲 Покер на костях", callback_data="game_dicepoker"),
        InlineKeyboardButton("🃏 Блэкджек", callback_data="game_blackjack"),
        InlineKeyboardButton("🎴 Угадай карту", callback_data="game_guesscard"),
        InlineKeyboardButton("🎴 Пьяница", callback_data="game_drunkard"),
        InlineKeyboardButton("🃑 Дурак", callback_data="game_fool"),
        InlineKeyboardButton("🃟 Меморина", callback_data="game_memory"),
        InlineKeyboardButton("📈 Больше/Меньше", callback_data="game_moreless"),
        InlineKeyboardButton("🎲 Риск", callback_data="game_risk"),
        InlineKeyboardButton("🎲 Свинья", callback_data="game_pig"),
        InlineKeyboardButton("🎰 Джекпот", callback_data="game_jackpot"),
        InlineKeyboardButton("🎲 Рулетка", callback_data="game_roulette"),
        InlineKeyboardButton("◀️ Главное меню", callback_data="back_main")
    )
    return kb

def dice_menu_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎲 1 кубик", callback_data="dice_1"),
        InlineKeyboardButton("🎲🎲 2 кубика", callback_data="dice_2"),
        InlineKeyboardButton("🎲🎲🎲 3 кубика", callback_data="dice_3"),
        InlineKeyboardButton("🎲 x5 5 кубиков", callback_data="dice_5"),
        InlineKeyboardButton("🎲 x10 10 кубиков", callback_data="dice_10"),
        InlineKeyboardButton("🎲💰 Кости на удачу", callback_data="dice_luck"),
        InlineKeyboardButton("◀️ Назад к играм", callback_data="games_menu")
    )
    return kb

def income_menu_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🛒 Купить ферму", callback_data="buy_business_menu"),
        InlineKeyboardButton("🏭 Мои фермы", callback_data="my_businesses"),
        InlineKeyboardButton("◀️ Главное меню", callback_data="back_main")
    )
    return kb

def clans_menu_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📋 Создать клан", callback_data="clan_create"),
        InlineKeyboardButton("🔍 Вступить в клан", callback_data="clan_join"),
        InlineKeyboardButton("📊 Мой клан", callback_data="clan_info"),
        InlineKeyboardButton("🚪 Покинуть клан", callback_data="clan_leave"),
        InlineKeyboardButton("◀️ Главное меню", callback_data="back_main")
    )
    return kb

def admin_panel_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("💰 Выдать монеты", callback_data="admin_add_coins"),
        InlineKeyboardButton("🔻 Забрать монеты", callback_data="admin_remove_coins"),
        InlineKeyboardButton("👥 Все пользователи", callback_data="admin_all_users"),
        InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast"),
        InlineKeyboardButton("🎁 Подарить ферму", callback_data="admin_gift_farm"),
        InlineKeyboardButton("◀️ Главное меню", callback_data="back_main")
    )
    return kb

def play_again_keyboard(game_callback):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎮 Сыграть ещё", callback_data=game_callback),
        InlineKeyboardButton("🎮 Меню игр", callback_data="games_menu"),
        InlineKeyboardButton("◀️ Главное меню", callback_data="back_main")
    )
    return kb

# ========== ФЕРМЫ ==========
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

def get_pending_income(uid, biz_type):
    b = get_business(uid, biz_type)
    if not b:
        return 0
    last = b["last_collect"]
    now = datetime.now()
    hours = (now - last).total_seconds() / 3600
    if hours < 0:
        return 0
    base = BUSINESSES[biz_type]["base_income"] + (b["amount_level"] - 1) * BUSINESSES[biz_type]["upgrade_income"]
    speed_mult = 1 + (b["speed_level"] - 1) * 0.2
    per_hour = int(base * speed_mult)
    total = int(per_hour * min(hours, 24))
    return total

def collect_income(uid, biz_type):
    b = get_business(uid, biz_type)
    if not b:
        return 0, "❌ У тебя нет такой фермы"
    last = b["last_collect"]
    now = datetime.now()
    hours = (now - last).total_seconds() / 3600
    if hours < 0.1:
        return 0, "⏳ Накоплений нет"
    base = BUSINESSES[biz_type]["base_income"] + (b["amount_level"] - 1) * BUSINESSES[biz_type]["upgrade_income"]
    speed_mult = 1 + (b["speed_level"] - 1) * 0.2
    per_hour = int(base * speed_mult)
    total = int(per_hour * min(hours, 24))
    add_coins(uid, total)
    new_last = last + timedelta(hours=min(hours, 24))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE businesses SET last_collect = %s WHERE user_id = %s AND business_type = %s", (new_last, str(uid), biz_type))
    conn.commit()
    cur.close()
    conn.close()
    return total, f"✅ Собрано {total}💰 с {biz_type}"

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
    if b["speed_level"] >= 5:
        return False, "❌ Максимальная скорость (x2)!"
    price = BUSINESSES[biz_type]["price"] // 2
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
    base = BUSINESSES[biz_type]["base_income"] + (b["amount_level"] - 1) * BUSINESSES[biz_type]["upgrade_income"]
    speed_mult = 1 + (b["speed_level"] - 1) * 0.2
    per_hour = int(base * speed_mult)
    pending = get_pending_income(uid, biz_type)
    speed_price = BUSINESSES[biz_type]["price"] // 2
    return (f"🏭 *{biz_type}*\n\n"
            f"📊 Уровень количества: {b['amount_level']}\n"
            f"⚡ Уровень скорости: {b['speed_level']} (x{speed_mult})\n"
            f"💰 Доход в час: +{per_hour}💰\n\n"
            f"💎 Накоплено: {pending}💰\n\n"
            f"🔧 *Апгрейды:*\n"
            f"📈 +{BUSINESSES[biz_type]['upgrade_income']}💰 к доходу — {AMOUNT_UPGRADE_COST}💰\n"
            f"⚡ Ускорить (x0.2) — {speed_price}💰")

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
    return get_clan(m["clan_id"])

def get_clan(clan_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM clans WHERE clan_id = %s", (clan_id,))
    clan = cur.fetchone()
    cur.close()
    conn.close()
    return clan

def get_clan_members(clan_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM clan_members WHERE clan_id = %s", (clan_id,))
    members = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return members

def join_clan(user_id, clan_id):
    if get_user_clan(user_id):
        return False, "❌ Ты уже в клане!"
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
        return False, "❌ Ты не в клане!"
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM clan_members WHERE user_id = %s", (str(user_id),))
    conn.commit()
    cur.close()
    conn.close()
    return True, "✅ Ты покинул клан!"

def clan_info_text(user_id):
    clan = get_user_clan(user_id)
    if not clan:
        return "❌ Ты не состоишь в клане!"
    members = get_clan_members(clan["clan_id"])
    text = f"{clan['emoji']} *{clan['name']}*\n"
    text += f"👑 Владелец: `{clan['owner_id']}`\n"
    text += f"👥 Участников: {len(members)}\n\n"
    text += "*Участники:*\n"
    for m in members[:10]:
        u = get_user(m)
        text += f"• {u.get('username') or m[:8]} — {u['coins']}💰\n"
    return text

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
def update_game_stats(uid, won):
    u = get_user(uid)
    new_games = u.get("total_games", 0) + 1
    new_wins = u.get("total_wins", 0) + (1 if won else 0)
    update_user(uid, total_games=new_games, total_wins=new_wins)

def dice_game_play(message, uid, num, mn, mx, win_min, win_max, game_callback):
    delete_previous_message(message.chat.id, uid)
    try:
        bet = int(message.text)
        if bet < mn or bet > mx:
            send_and_track(message.chat.id, f"❌ Введи число от {mn} до {mx}", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
            return
        rolls = [random.randint(1, 6) for _ in range(num)]
        total = sum(rolls)
        if bet == total:
            win = random.randint(win_min, win_max)
            add_coins(uid, win)
            text = f"🎲 {total}. Победа! +{win}💰"
            update_game_stats(uid, True)
        else:
            text = f"🎲 {total}. Проигрыш! -1💰"
            update_game_stats(uid, False)
        send_and_track(message.chat.id, text, reply_markup=play_again_keyboard(game_callback), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(message.chat.id, "❌ Введи число", user_id=uid)

def dice_luck_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    if not remove_coins(uid, 2):
        send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    rolls = [random.randint(1, 6) for _ in range(3)]
    total = sum(rolls)
    if total >= 15:
        add_coins(uid, 10)
        text = f"🎲💰 {total}. Победа! +10💰"
        update_game_stats(uid, True)
    else:
        text = f"🎲💰 {total}. Проигрыш! -2💰"
        update_game_stats(uid, False)
    send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("dice_luck"), parse_mode="Markdown", user_id=uid)

def gamble_number_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    try:
        bet = int(message.text)
        if bet < 1 or bet > 20:
            send_and_track(message.chat.id, "❌ 1–20", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
            return
        secret = random.randint(1, 20)
        if bet == secret:
            win = random.randint(5, 12)
            add_coins(uid, win)
            text = f"🔢 {secret}. Победа! +{win}💰"
            update_game_stats(uid, True)
        else:
            text = f"🔢 {secret}. Проигрыш! -1💰"
            update_game_stats(uid, False)
        send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("gamble_number"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(message.chat.id, "❌ Введи число", user_id=uid)

def gamble_rps_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    choice = message.text.lower()
    if choice not in ["камень", "ножницы", "бумага"]:
        send_and_track(message.chat.id, "❌ камень/ножницы/бумага", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    bot_choice = random.choice(["камень", "ножницы", "бумага"])
    if choice == bot_choice:
        add_coins(uid, 2)
        text = f"🤝 Ничья! +2💰"
        update_game_stats(uid, False)
    elif (choice == "камень" and bot_choice == "ножницы") or (choice == "ножницы" and bot_choice == "бумага") or (choice == "бумага" and bot_choice == "камень"):
        win = random.randint(3, 7)
        add_coins(uid, win)
        text = f"🎉 Победа! +{win}💰"
        update_game_stats(uid, True)
    else:
        text = f"💀 Поражение! -1💰"
        update_game_stats(uid, False)
    send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("gamble_rps"), parse_mode="Markdown", user_id=uid)

def gamble_cards_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    try:
        ch = int(message.text)
        if ch < 1 or ch > 5:
            send_and_track(message.chat.id, "❌ 1–5", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
            return
        joker_pos = random.randint(1, 5)
        if ch == joker_pos:
            add_coins(uid, 10)
            text = f"🎴 *ДЖОКЕР!* +10💰"
            update_game_stats(uid, True)
        else:
            text = f"🎴 Масть... -1💰"
            update_game_stats(uid, False)
        send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("gamble_cards"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(message.chat.id, "❌ Введи число", user_id=uid)

def gamble_slots_play(uid, message_id=None, chat_id=None):
    if chat_id is None:
        chat_id = uid
    delete_previous_message(chat_id, uid)
    if not remove_coins(uid, 1):
        send_and_track(chat_id, "❌ Нет монет", user_id=uid)
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
        update_game_stats(uid, True)
    else:
        text = f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n💀 -1💰"
        update_game_stats(uid, False)
    send_and_track(chat_id, text, reply_markup=play_again_keyboard("gamble_slots"), parse_mode="Markdown", user_id=uid)

def gamble_rps2_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    ch = message.text.lower()
    if ch not in ["камень", "мешок", "монета"]:
        send_and_track(message.chat.id, "❌ камень/мешок/монета", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    bot_ch = random.choice(["камень", "мешок", "монета"])
    rules = {"камень": "мешок", "мешок": "монета", "монета": "камень"}
    if ch == bot_ch:
        add_coins(uid, 2)
        text = f"🤝 Ничья! +2💰"
        update_game_stats(uid, False)
    elif rules[ch] == bot_ch:
        win = random.randint(3, 7)
        add_coins(uid, win)
        text = f"🎉 Победа! +{win}💰"
        update_game_stats(uid, True)
    else:
        text = f"💀 Поражение! -1💰"
        update_game_stats(uid, False)
    send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("gamble_rps2"), parse_mode="Markdown", user_id=uid)

def gamble_color_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    ch = message.text.lower()
    if ch not in ["красный", "чёрный"]:
        send_and_track(message.chat.id, "❌ красный или чёрный", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    color = random.choice(["🔴 красный", "⚫ чёрный"])
    user_color = "красный" if "красн" in ch else "чёрный"
    if user_color in color:
        add_coins(uid, 3)
        text = f"🎯 {color}. Победа! +3💰"
        update_game_stats(uid, True)
    else:
        text = f"🎯 {color}. Поражение! -1💰"
        update_game_stats(uid, False)
    send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("gamble_color"), parse_mode="Markdown", user_id=uid)

def gamble_highlow_play(message, uid, first):
    delete_previous_message(message.chat.id, uid)
    ch = message.text.lower()
    if ch not in ["выше", "ниже"]:
        send_and_track(message.chat.id, "❌ выше или ниже", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    second = random.randint(1, 10)
    if (ch == "выше" and second > first) or (ch == "ниже" and second < first):
        win = random.randint(4, 8)
        add_coins(uid, win)
        text = f"📈 {first}→{second}. Победа! +{win}💰"
        update_game_stats(uid, True)
    elif second == first:
        add_coins(uid, 2)
        text = f"📈 {first}→{second}. Ничья! +2💰"
        update_game_stats(uid, False)
    else:
        text = f"📈 {first}→{second}. Поражение! -1💰"
        update_game_stats(uid, False)
    send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("gamble_highlow"), parse_mode="Markdown", user_id=uid)

def gamble_roulette_play(uid, message_id=None, chat_id=None):
    if chat_id is None:
        chat_id = uid
    delete_previous_message(chat_id, uid)
    if not remove_coins(uid, 5):
        send_and_track(chat_id, "❌ Нет монет", user_id=uid)
        return
    if random.randint(1, 6) == 1:
        text = "🔫 *Русская рулетка*\n💀 БАХ! -5💰"
        update_game_stats(uid, False)
    else:
        add_coins(uid, 25)
        text = f"🔫 *Русская рулетка*\n🎉 ЩЁЛК! +25💰"
        update_game_stats(uid, True)
    send_and_track(chat_id, text, reply_markup=play_again_keyboard("gamble_roulette"), parse_mode="Markdown", user_id=uid)

def gamble_evenodd_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    ch = message.text.lower()
    if ch not in ["чётное", "нечётное", "четное", "нечетное"]:
        send_and_track(message.chat.id, "❌ чётное или нечётное", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    num = random.randint(1, 10)
    is_even = num % 2 == 0
    correct = "чётное" if is_even else "нечётное"
    if (ch in ["чётное", "четное"] and is_even) or (ch in ["нечётное", "нечетное"] and not is_even):
        win = random.randint(3, 5)
        add_coins(uid, win)
        text = f"🎲 {num} ({correct}). Победа! +{win}💰"
        update_game_stats(uid, True)
    else:
        text = f"🎲 {num} ({correct}). Поражение! -1💰"
        update_game_stats(uid, False)
    send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("gamble_evenodd"), parse_mode="Markdown", user_id=uid)

def game_luckynum_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    try:
        bet = int(message.text)
        if bet < 1 or bet > 10:
            send_and_track(message.chat.id, "❌ 1–10", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
            return
        num = random.randint(1, 10)
        if bet == num:
            win = random.randint(5, 10)
            add_coins(uid, win)
            text = f"🎲 {num}. Победа! +{win}💰"
            update_game_stats(uid, True)
        else:
            text = f"🎲 {num}. Проигрыш! -1💰"
            update_game_stats(uid, False)
        send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_luckynum"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(message.chat.id, "❌ Введи число", user_id=uid)

def game_clover_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    if not remove_coins(uid, 1):
        send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    r = random.randint(1, 10)
    if r == 1:
        win = 20
    elif r <= 3:
        win = 10
    elif r <= 6:
        win = 5
    else:
        win = 0
    if win:
        add_coins(uid, win)
        text = f"🍀 Тебе повезло! +{win}💰"
        update_game_stats(uid, True)
    else:
        text = f"🍀 Не повезло... -1💰"
        update_game_stats(uid, False)
    send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_clover"), parse_mode="Markdown", user_id=uid)

def game_mine_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    try:
        ch = int(message.text)
        if ch < 1 or ch > 6:
            send_and_track(message.chat.id, "❌ 1–6", user_id=uid)
            return
        if not remove_coins(uid, 2):
            send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
            return
        mine = random.randint(1, 6)
        if ch == mine:
            text = f"💣 БАХ! Ты наступил на мину! -2💰"
            update_game_stats(uid, False)
        else:
            add_coins(uid, 10)
            text = f"✅ Повезло! +10💰"
            update_game_stats(uid, True)
        send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_mine"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(message.chat.id, "❌ Введи число", user_id=uid)

def game_dicepoker_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    if not remove_coins(uid, 2):
        send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    rolls = [random.randint(1, 6) for _ in range(5)]
    counts = [rolls.count(i) for i in range(1, 7)]
    if 5 in counts:
        win = 50
    elif 4 in counts:
        win = 20
    elif 3 in counts and 2 in counts:
        win = 15
    elif 3 in counts:
        win = 10
    elif counts.count(2) == 2:
        win = 8
    elif 2 in counts:
        win = 5
    else:
        win = 0
    if win:
        add_coins(uid, win)
        text = f"🎲 {rolls}\nКомбинация! +{win}💰"
        update_game_stats(uid, True)
    else:
        text = f"🎲 {rolls}\nНичего... -2💰"
        update_game_stats(uid, False)
    send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_dicepoker"), parse_mode="Markdown", user_id=uid)

def game_blackjack_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    try:
        bet = int(message.text)
        if bet < 5:
            send_and_track(message.chat.id, "❌ Минимум 5💰", user_id=uid)
            return
        if not remove_coins(uid, bet):
            send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
            return
        player = [random.randint(1, 11), random.randint(1, 11)]
        dealer = [random.randint(1, 11)]
        if sum(player) == 21:
            win = bet * 2
            add_coins(uid, win)
            text = f"🃏 Блэкджек! +{win}💰"
            update_game_stats(uid, True)
            send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_blackjack"), parse_mode="Markdown", user_id=uid)
            return
        send_and_track(message.chat.id, f"Твои карты: {player} ({sum(player)})\nКарты дилера: {dealer}\n\nВведи 'ещё' или 'хватит':", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_blackjack_step(m, uid, player, dealer, bet))
    except:
        send_and_track(message.chat.id, "❌ Введи число", user_id=uid)

def game_blackjack_step(message, uid, player, dealer, bet):
    delete_previous_message(message.chat.id, uid)
    ch = message.text.lower()
    if ch == "ещё":
        player.append(random.randint(1, 11))
        if sum(player) > 21:
            text = f"Перебор! {player} = {sum(player)}. -{bet}💰"
            update_game_stats(uid, False)
            send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_blackjack"), parse_mode="Markdown", user_id=uid)
        elif sum(player) == 21:
            win = bet * 2
            add_coins(uid, win)
            text = f"21! +{win}💰"
            update_game_stats(uid, True)
            send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_blackjack"), parse_mode="Markdown", user_id=uid)
        else:
            send_and_track(message.chat.id, f"Твои карты: {player} = {sum(player)}", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: game_blackjack_step(m, uid, player, dealer, bet))
    elif ch == "хватит":
        while sum(dealer) < 17:
            dealer.append(random.randint(1, 11))
        if sum(dealer) > 21 or sum(player) > sum(dealer):
            win = bet * 2
            add_coins(uid, win)
            text = f"Победа! {player} vs {dealer}. +{win}💰"
            update_game_stats(uid, True)
        elif sum(player) == sum(dealer):
            add_coins(uid, bet)
            text = f"Ничья! {player} vs {dealer}. Возвращено {bet}💰"
            update_game_stats(uid, False)
        else:
            text = f"Поражение! {player} vs {dealer}. -{bet}💰"
            update_game_stats(uid, False)
        send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_blackjack"), parse_mode="Markdown", user_id=uid)
    else:
        send_and_track(message.chat.id, "❌ 'ещё' или 'хватит'", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_blackjack_step(m, uid, player, dealer, bet))

def game_guesscard_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    try:
        ch = message.text.lower()
        if ch not in ["♠️", "♥️", "♣️", "♦️"]:
            send_and_track(message.chat.id, "❌ ♠️ ♥️ ♣️ ♦️", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
            return
        card = random.choice(["♠️", "♥️", "♣️", "♦️"])
        if ch == card:
            win = random.randint(5, 10)
            add_coins(uid, win)
            text = f"🎴 Выпала {card}. Угадал! +{win}💰"
            update_game_stats(uid, True)
        else:
            text = f"🎴 Выпала {card}. Не угадал. -1💰"
            update_game_stats(uid, False)
        send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_guesscard"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(message.chat.id, "❌ Ошибка", user_id=uid)

def game_drunkard_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    if not remove_coins(uid, 1):
        send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    cards = ["6", "7", "8", "9", "10", "В", "Д", "К", "Т"]
    player = random.choice(cards)
    bot_card = random.choice(cards)
    if cards.index(player) > cards.index(bot_card):
        add_coins(uid, 4)
        text = f"🎴 {player} vs {bot_card}. Победа! +4💰"
        update_game_stats(uid, True)
    elif player == bot_card:
        add_coins(uid, 2)
        text = f"🎴 Ничья! +2💰"
        update_game_stats(uid, False)
    else:
        text = f"🎴 {player} vs {bot_card}. Поражение. -1💰"
        update_game_stats(uid, False)
    send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_drunkard"), parse_mode="Markdown", user_id=uid)

def game_fool_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    if not remove_coins(uid, 2):
        send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    cards = ["6", "7", "8", "9", "10", "В", "Д", "К", "Т"]
    player = random.choice(cards)
    bot_card = random.choice(cards)
    if cards.index(player) > cards.index(bot_card):
        win = 10
        add_coins(uid, win)
        text = f"🃑 {player} vs {bot_card}. Победа! +{win}💰"
        update_game_stats(uid, True)
    elif player == bot_card:
        add_coins(uid, 2)
        text = f"🃑 Ничья! +2💰"
        update_game_stats(uid, False)
    else:
        text = f"🃑 {player} vs {bot_card}. Поражение. -2💰"
        update_game_stats(uid, False)
    send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_fool"), parse_mode="Markdown", user_id=uid)

def game_memory_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    if not remove_coins(uid, 1):
        send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    numbers = [random.randint(1, 10) for _ in range(5)]
    send_and_track(message.chat.id, f"🃟 *Меморина*\nЗапомни числа: {numbers}\nВведи их через пробел:", parse_mode="Markdown", user_id=uid)
    bot.register_next_step_handler_by_chat_id(uid, lambda m: game_memory_check(m, uid, numbers))

def game_memory_check(message, uid, numbers):
    delete_previous_message(message.chat.id, uid)
    try:
        guess = list(map(int, message.text.split()))
        if guess == numbers:
            add_coins(uid, 10)
            text = f"🎉 Идеально! +10💰"
            update_game_stats(uid, True)
        else:
            text = f"❌ Было {numbers}. -1💰"
            update_game_stats(uid, False)
        send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_memory"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(message.chat.id, "❌ Введи 5 чисел", user_id=uid)

def game_moreless_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    try:
        bet = int(message.text)
        if bet < 2 or bet > 12:
            send_and_track(message.chat.id, "❌ 2–12", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
            return
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2
        if bet > total:
            win = random.randint(4, 8)
            add_coins(uid, win)
            text = f"🎲 {total}. Угадал (больше)! +{win}💰"
            update_game_stats(uid, True)
        elif bet < total:
            win = random.randint(4, 8)
            add_coins(uid, win)
            text = f"🎲 {total}. Угадал (меньше)! +{win}💰"
            update_game_stats(uid, True)
        else:
            text = f"🎲 {total}. Ничья. -1💰"
            update_game_stats(uid, False)
        send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_moreless"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(message.chat.id, "❌ Введи число", user_id=uid)

def game_risk_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    try:
        bet = int(message.text)
        if bet < 5:
            send_and_track(message.chat.id, "❌ Минимум 5💰", user_id=uid)
            return
        if not remove_coins(uid, bet):
            send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
            return
        number = random.randint(1, 6)
        send_and_track(message.chat.id, f"🎲 *Риск*\nУгадай число (1–6):", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_risk_check(m, uid, number, bet))
    except:
        send_and_track(message.chat.id, "❌ Введи число", user_id=uid)

def game_risk_check(message, uid, number, bet):
    delete_previous_message(message.chat.id, uid)
    try:
        guess = int(message.text)
        if guess < 1 or guess > 6:
            send_and_track(message.chat.id, "❌ 1–6", user_id=uid)
            return
        if guess == number:
            win = bet * 2
            add_coins(uid, win)
            text = f"🎲 Выпало {number}. Угадал! +{win}💰"
            update_game_stats(uid, True)
        else:
            text = f"🎲 Выпало {number}. Не угадал. -{bet}💰"
            update_game_stats(uid, False)
        send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_risk"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(message.chat.id, "❌ Введи число", user_id=uid)

def game_pig_play(message, uid):
    delete_previous_message(message.chat.id, uid)
    if not remove_coins(uid, 1):
        send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
        return
    pig_scores[uid] = 0
    game_pig_roll(message, uid)

def game_pig_roll(message, uid):
    roll = random.randint(1, 6)
    if roll == 1:
        del pig_scores[uid]
        send_and_track(message.chat.id, f"🎲 Выпало 1! Ты теряешь всё. -1💰", reply_markup=play_again_keyboard("game_pig"), parse_mode="Markdown", user_id=uid)
        return
    pig_scores[uid] += roll
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("🎲 Бросить ещё", callback_data="pig_continue"),
        InlineKeyboardButton("💰 Забрать", callback_data="pig_take"),
        InlineKeyboardButton("◀️ Меню игр", callback_data="games_menu")
    )
    send_and_track(message.chat.id, f"🎲 Выпало {roll}. Твой счёт: {pig_scores[uid]}. Что делаешь?", reply_markup=kb, parse_mode="Markdown", user_id=message.chat.id)

def game_jackpot_play(uid, message_id=None, chat_id=None):
    if chat_id is None:
        chat_id = uid
    delete_previous_message(chat_id, uid)
    if not remove_coins(uid, 5):
        send_and_track(chat_id, "❌ Нет монет", user_id=uid)
        return
    jackpot_data["total"] += 5
    r = random.randint(1, 100)
    if r <= 2:
        win = jackpot_data["total"]
        add_coins(uid, win)
        jackpot_data["total"] = 0
        text = f"🎰 *ДЖЕКПОТ!* Ты выиграл {win}💰"
        update_game_stats(uid, True)
    else:
        text = f"🎰 Не повезло. Джекпот уже {jackpot_data['total']}💰"
        update_game_stats(uid, False)
    send_and_track(chat_id, text, reply_markup=play_again_keyboard("game_jackpot"), parse_mode="Markdown", user_id=uid)

def game_roulette_play(uid, message_id=None, chat_id=None):
    if chat_id is None:
        chat_id = uid
    delete_previous_message(chat_id, uid)
    send_and_track(chat_id, "🎲 *Рулетка*\nВведи ставку (число 0–36) и сумму через пробел:\nПример: `17 100`", parse_mode="Markdown", user_id=uid)
    bot.register_next_step_handler_by_chat_id(uid, lambda m: game_roulette_spin(m, uid))

def game_roulette_spin(message, uid):
    delete_previous_message(message.chat.id, uid)
    try:
        parts = message.text.split()
        number = int(parts[0])
        bet = int(parts[1])
        if number < 0 or number > 36:
            send_and_track(message.chat.id, "❌ 0–36", user_id=uid)
            return
        if not remove_coins(uid, bet):
            send_and_track(message.chat.id, "❌ Нет монет", user_id=uid)
            return
        result = random.randint(0, 36)
        if result == number:
            win = bet * 36
            add_coins(uid, win)
            text = f"🎲 Выпало {result}. Угадал! +{win}💰"
            update_game_stats(uid, True)
        else:
            text = f"🎲 Выпало {result}. Не угадал. -{bet}💰"
            update_game_stats(uid, False)
        send_and_track(message.chat.id, text, reply_markup=play_again_keyboard("game_roulette"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(message.chat.id, "❌ Пример: `17 100`", user_id=uid)

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
        send_and_track(uid, "🌍 *Выбери регион:*", reply_markup=kb, parse_mode="Markdown", user_id=uid)
    else:
        send_and_track(uid, f"🎉 *Добро пожаловать!*\n\n{format_profile(uid)}", reply_markup=main_menu_keyboard(), parse_mode="Markdown", user_id=uid)

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    uid = call.message.chat.id
    data = call.data
    msg_id = call.message.message_id

    # Регионы
    if data.startswith("region_"):
        region = data.replace("region_", "")
        update_user(uid, region=region)
        edit_message(uid, msg_id, f"✅ Регион *{region}* сохранён!\n\n{format_profile(uid)}", reply_markup=main_menu_keyboard(), parse_mode="Markdown")
        return

    # Главное меню
    elif data == "back_main":
        edit_message(uid, msg_id, format_profile(uid), reply_markup=main_menu_keyboard(), parse_mode="Markdown")

    elif data == "profile":
        edit_message(uid, msg_id, format_profile(uid), reply_markup=main_menu_keyboard(), parse_mode="Markdown")

    elif data == "bonus":
        if can_take_bonus(uid):
            add_coins(uid, 10)
            update_user(uid, last_bonus=datetime.now().isoformat())
            text = "🎁 +10 монет!"
        else:
            text = "⏳ Бонус уже получен. Завтра!"
        edit_message(uid, msg_id, text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")

    elif data == "referrals":
        text = f"👥 *Рефералы*\n📎 {get_referral_link(uid)}\n👥 Приглашено: {get_referral_stats(uid)}"
        edit_message(uid, msg_id, text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")

    elif data == "ask_question":
        send_and_track(uid, "✍️ Напиши вопрос:", user_id=uid)
        waiting_for_question[uid] = True

    # Игры
    elif data == "games_menu":
        edit_message(uid, msg_id, "🎮 *Выбери игру:*", reply_markup=games_menu_keyboard(), parse_mode="Markdown")

    elif data == "dice_menu":
        edit_message(uid, msg_id, "🎲 *Выбери количество кубиков:*", reply_markup=dice_menu_keyboard(), parse_mode="Markdown")

    elif data.startswith("dice_"):
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
            send_and_track(uid, "🎲💰 Кости на удачу (3 кубика, сумма ≥15). Ставка 2💰. Напиши 'да'", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: dice_luck_play(m, uid))

    elif data == "gamble_number":
        send_and_track(uid, "🔢 Введи число от 1 до 20:", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_number_play(m, uid))
    elif data == "gamble_rps":
        send_and_track(uid, "✂️ камень, ножницы, бумага:", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_rps_play(m, uid))
    elif data == "gamble_cards":
        send_and_track(uid, "🎴 *Карты и Джокер*\n1️⃣♠️ 2️⃣♥️ 3️⃣♣️ 4️⃣♦️ 5️⃣🃏\nВведи номер (1–5):", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_cards_play(m, uid))
    elif data == "gamble_slots":
        gamble_slots_play(uid, msg_id, uid)
    elif data == "gamble_rps2":
        send_and_track(uid, "💎 *Камень-мешок-монета*\nВыбери: камень, мешок, монета", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_rps2_play(m, uid))
    elif data == "gamble_color":
        send_and_track(uid, "🎯 *Угадай цвет*\n🔴 Красный или ⚫ Чёрный?", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_color_play(m, uid))
    elif data == "gamble_highlow":
        first = random.randint(1, 10)
        send_and_track(uid, f"📈 *Выше/Ниже*\nТекущее число: {first}\nСледующее будет *выше* или *ниже*?", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_highlow_play(m, uid, first))
    elif data == "gamble_roulette":
        gamble_roulette_play(uid, msg_id, uid)
    elif data == "gamble_evenodd":
        send_and_track(uid, "🎲 *Чет/Нечет*\nЧисло 1–10, угадай чётное или нечётное", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_evenodd_play(m, uid))
    elif data == "game_luckynum":
        send_and_track(uid, "🎲 *Счастливое число*\nВведи число от 1 до 10:", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_luckynum_play(m, uid))
    elif data == "game_clover":
        send_and_track(uid, "🍀 *Клевер*\nНапиши 'да'", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_clover_play(m, uid))
    elif data == "game_mine":
        send_and_track(uid, "💣 *Мина*\nВведи число от 1 до 6:", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_mine_play(m, uid))
    elif data == "game_dicepoker":
        send_and_track(uid, "🎲 *Покер на костях*\nНапиши 'да'", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_dicepoker_play(m, uid))
    elif data == "game_blackjack":
        send_and_track(uid, "🃏 *Блэкджек*\nВведи ставку (мин 5💰):", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_blackjack_play(m, uid))
    elif data == "game_guesscard":
        send_and_track(uid, "🎴 *Угадай карту*\nВведи масть: ♠️ ♥️ ♣️ ♦️", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_guesscard_play(m, uid))
    elif data == "game_drunkard":
        send_and_track(uid, "🎴 *Пьяница*\nНапиши 'да'", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_drunkard_play(m, uid))
    elif data == "game_fool":
        send_and_track(uid, "🃑 *Дурак*\nНапиши 'да'", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_fool_play(m, uid))
    elif data == "game_memory":
        send_and_track(uid, "🃟 *Меморина*\nГотов? Напиши 'да'", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_memory_play(m, uid))
    elif data == "game_moreless":
        send_and_track(uid, "📈 *Больше/Меньше*\nВведи число от 2 до 12:", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_moreless_play(m, uid))
    elif data == "game_risk":
        send_and_track(uid, "🎲 *Риск*\nВведи ставку (мин 5💰):", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_risk_play(m, uid))
    elif data == "game_pig":
        game_pig_play(call.message, uid)
    elif data == "game_jackpot":
        game_jackpot_play(uid, msg_id, uid)
    elif data == "game_roulette":
        game_roulette_play(uid, msg_id, uid)

    elif data == "pig_continue":
        game_pig_roll(call.message, uid)
    elif data == "pig_take":
        score = pig_scores.get(uid, 0)
        if score > 0:
            add_coins(uid, score)
            text = f"💰 Ты забрал {score}💰!"
            update_game_stats(uid, True)
        else:
            text = "❌ Нет очков"
        if uid in pig_scores:
            del pig_scores[uid]
        edit_message(uid, msg_id, text, reply_markup=play_again_keyboard("game_pig"), parse_mode="Markdown")

    # Пассивный доход
    elif data == "income_menu":
        edit_message(uid, msg_id, "🏭 *Пассивный доход*\nВыбери действие:", reply_markup=income_menu_keyboard(), parse_mode="Markdown")

    elif data == "buy_business_menu":
        kb = InlineKeyboardMarkup(row_width=1)
        for name, d in BUSINESSES.items():
            kb.add(InlineKeyboardButton(f"{name} ({d['price']}💰)", callback_data=f"buy_business_{name}"))
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data="income_menu"))
        edit_message(uid, msg_id, "🏭 *Купить ферму*\nВыбери ферму:", reply_markup=kb, parse_mode="Markdown")

    elif data == "my_businesses":
        businesses = get_user_businesses(uid)
        if not businesses:
            edit_message(uid, msg_id, "❌ У тебя нет ферм. Купи их в разделе 'Купить ферму'", reply_markup=income_menu_keyboard(), parse_mode="Markdown")
            return
        kb = InlineKeyboardMarkup(row_width=2)
        for b in businesses:
            kb.add(InlineKeyboardButton(f"📊 {b['business_type']}", callback_data=f"select_business_{b['business_type']}"))
        kb.add(InlineKeyboardButton("◀️ Назад", callback_data="income_menu"))
        edit_message(uid, msg_id, "🏭 *Твои фермы*\nВыбери для управления:", reply_markup=kb, parse_mode="Markdown")

    elif data.startswith("buy_business_"):
        biz = data.replace("buy_business_", "")
        ok, msg = buy_business(uid, biz)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        if ok:
            edit_message(uid, msg_id, "🏭 *Пассивный доход*\nВыбери действие:", reply_markup=income_menu_keyboard(), parse_mode="Markdown")

    elif data.startswith("select_business_"):
        biz = data.replace("select_business_", "")
        info = get_business_info(uid, biz)
        if info:
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("📈 +💰 (апгрейд)", callback_data=f"upgrade_amount_{biz}"))
            kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data=f"upgrade_speed_{biz}"))
            kb.add(InlineKeyboardButton("💾 Собрать", callback_data=f"collect_business_{biz}"))
            kb.add(InlineKeyboardButton("◀️ Назад", callback_data="my_businesses"))
            edit_message(uid, msg_id, info, reply_markup=kb, parse_mode="Markdown")

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
                edit_message(uid, msg_id, info, reply_markup=kb, parse_mode="Markdown")

    elif data.startswith("collect_business_"):
        biz = data.replace("collect_business_", "")
        earned, msg = collect_income(uid, biz)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        info = get_business_info(uid, biz)
        if info:
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("📈 +💰 (апгрейд)", callback_data=f"upgrade_amount_{biz}"))
            kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data=f"upgrade_speed_{biz}"))
            kb.add(InlineKeyboardButton("💾 Собрать", callback_data=f"collect_business_{biz}"))
            kb.add(InlineKeyboardButton("◀️ Назад", callback_data="my_businesses"))
            edit_message(uid, msg_id, info, reply_markup=kb, parse_mode="Markdown")

    # Кланы
    elif data == "clans_menu":
        edit_message(uid, msg_id, "👥 *Кланы*\nВыбери действие:", reply_markup=clans_menu_keyboard(), parse_mode="Markdown")

    elif data == "clan_create":
        if get_user_clan(uid):
            edit_message(uid, msg_id, "❌ Ты уже в клане!", reply_markup=clans_menu_keyboard(), parse_mode="Markdown")
            return
        send_and_track(uid, "📋 *Создание клана*\nВведи название клана:", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: clan_create_name(m, uid))

    elif data == "clan_join":
        if get_user_clan(uid):
            edit_message(uid, msg_id, "❌ Ты уже в клане!", reply_markup=clans_menu_keyboard(), parse_mode="Markdown")
            return
        send_and_track(uid, "🔍 *Вступление в клан*\nВведи ID клана:", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: clan_join_id(m, uid))

    elif data == "clan_info":
        text = clan_info_text(uid)
        edit_message(uid, msg_id, text, reply_markup=clans_menu_keyboard(), parse_mode="Markdown")

    elif data == "clan_leave":
        ok, msg = leave_clan(uid)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        edit_message(uid, msg_id, format_profile(uid), reply_markup=main_menu_keyboard(), parse_mode="Markdown")

    # Админ-панель
    elif data == "admin_panel":
        if uid != ADMIN_ID:
            return
        edit_message(uid, msg_id, "🔧 *Админ-панель*", reply_markup=admin_panel_keyboard(), parse_mode="Markdown")

    elif data == "admin_add_coins":
        if uid != ADMIN_ID:
            return
        send_and_track(uid, "Введи ID и сумму: `123456789 100`", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, process_admin_add)

    elif data == "admin_remove_coins":
        if uid != ADMIN_ID:
            return
        send_and_track(uid, "Введи ID и сумму: `123456789 50`", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, process_admin_remove)

    elif data == "admin_all_users":
        if uid != ADMIN_ID:
            return
        users = all_users_list()
        msg = "👥 *Пользователи:*\n"
        for u in users[:30]:
            msg += f"🆔 {u} — {get_user(u)['coins']}💰\n"
        send_and_track(uid, msg, parse_mode="Markdown", user_id=uid)

    elif data == "admin_broadcast":
        if uid != ADMIN_ID:
            return
        send_and_track(uid, "📢 Введи сообщение для рассылки:", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, broadcast_message)

    elif data == "admin_gift_farm":
        if uid != ADMIN_ID:
            return
        send_and_track(uid, "🎁 Введи ID и название фермы:\nПример: `123456789 🚀 Космодром`", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, process_admin_gift_farm)

    # Ответ на вопрос
    elif data.startswith("answer_"):
        uid_q = data.split("_")[1]
        send_and_track(ADMIN_ID, f"✍️ Ответ для {uid_q}:", user_id=ADMIN_ID)
        bot.register_next_step_handler(call.message, lambda m: send_answer(m, uid_q))

def process_amount_upgrade(message, uid, biz_type, call):
    try:
        levels = int(message.text)
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

def clan_create_name(message, uid):
    name = message.text.strip()
    if len(name) > 20:
        send_and_track(uid, "❌ Название слишком длинное (макс 20 символов)", user_id=uid)
        return
    send_and_track(uid, "📋 Введи эмодзи для клана (1 символ):", user_id=uid)
    bot.register_next_step_handler_by_chat_id(uid, lambda m: clan_create_emoji(m, uid, name))

def clan_create_emoji(message, uid, name):
    emoji = message.text.strip()[:2]
    clan_id = create_clan(uid, name, emoji)
    if clan_id:
        send_and_track(uid, f"✅ Клан *{name}* создан! ID: {clan_id}", reply_markup=main_menu_keyboard(), parse_mode="Markdown", user_id=uid)
    else:
        send_and_track(uid, "❌ Клан с таким названием уже существует", user_id=uid)

def clan_join_id(message, uid):
    try:
        clan_id = int(message.text.strip())
        ok, msg = join_clan(uid, clan_id)
        send_and_track(uid, msg, reply_markup=main_menu_keyboard(), user_id=uid)
    except:
        send_and_track(uid, "❌ Введи числовой ID клана", user_id=uid)

def process_admin_add(message):
    uid = message.chat.id
    try:
        tid, amt = message.text.split()
        add_coins(int(tid), int(amt))
        send_and_track(uid, f"✅ Выдано {amt}💰 {tid}", reply_markup=admin_panel_keyboard(), user_id=uid)
    except:
        send_and_track(uid, "❌ Ошибка", user_id=uid)

def process_admin_remove(message):
    uid = message.chat.id
    try:
        tid, amt = message.text.split()
        if remove_coins(int(tid), int(amt)):
            send_and_track(uid, f"✅ Забрано {amt}💰 у {tid}", reply_markup=admin_panel_keyboard(), user_id=uid)
        else:
            send_and_track(uid, f"❌ У {tid} нет {amt}💰", reply_markup=admin_panel_keyboard(), user_id=uid)
    except:
        send_and_track(uid, "❌ Ошибка", user_id=uid)

def process_admin_gift_farm(message):
    uid = message.chat.id
    try:
        parts = message.text.split()
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
        send_and_track(uid, f"✅ Подарена ферма {biz_type} пользователю {target_id}", reply_markup=admin_panel_keyboard(), user_id=uid)
        bot.send_message(target_id, f"🎁 *Создатель бота подарил тебе ферму {biz_type}!* Теперь ты можешь её прокачивать!", parse_mode="Markdown")
    except:
        send_and_track(uid, "❌ Ошибка. Пример: `123456789 🚀 Космодром`", user_id=uid)

def broadcast_message(message):
    if message.chat.id != ADMIN_ID:
        return
    text = message.text
    sent = 0
    for uid in all_users_list():
        try:
            bot.send_message(int(uid), f"📢 *Рассылка:*\n{text}", parse_mode="Markdown")
            sent += 1
        except:
            pass
    send_and_track(ADMIN_ID, f"✅ Отправлено {sent}", reply_markup=admin_panel_keyboard(), user_id=ADMIN_ID)

def forward_question(uid, q):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✍️ Ответить", callback_data=f"answer_{uid}"))
    bot.send_message(ADMIN_ID, f"📩 *Вопрос от* `{uid}`:\n{q}", reply_markup=kb, parse_mode="Markdown")

def send_answer(message, target_id):
    if message.chat.id != ADMIN_ID:
        return
    bot.send_message(int(target_id), f"📬 *Ответ:*\n{message.text}", parse_mode="Markdown")
    send_and_track(ADMIN_ID, f"✅ Ответ отправлен {target_id}", reply_markup=admin_panel_keyboard(), user_id=ADMIN_ID)

# ========== ГРУППОВЫЕ КОМАНДЫ ==========
@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"])
def group_handlers(message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    text = message.text.lower()

    # Проверка бана
    if is_banned(chat_id, user_id):
        return

    # Топ игроков
    if text == "топ":
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id, coins, username FROM users ORDER BY coins DESC LIMIT 5")
        top = cur.fetchall()
        cur.close()
        conn.close()
        if not top:
            send_and_track(chat_id, "📊 Нет данных", user_id=user_id)
            return
        msg = "🏆 *Топ-5 игроков:*\n"
        for i, (uid, coins, name) in enumerate(top, 1):
            msg += f"{i}. {name or uid[:8]} — {coins}💰\n"
        send_and_track(chat_id, msg, parse_mode="Markdown", user_id=user_id)

    # Подарок монет
    elif text.startswith("подарить"):
        parts = message.text.split()
        if len(parts) != 3:
            send_and_track(chat_id, "❌ Формат: подарок @username 10", user_id=user_id)
            return
        target = parts[1].replace("@", "").lower()
        try:
            amount = int(parts[2])
        except:
            send_and_track(chat_id, "❌ Сумма числом", user_id=user_id)
            return
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE username = %s", (target,))
        r = cur.fetchone()
        cur.close()
        conn.close()
        if not r:
            send_and_track(chat_id, f"❌ @{target} не найден", user_id=user_id)
            return
        target_uid = r[0]
        if not remove_coins(user_id, amount):
            send_and_track(chat_id, f"❌ У тебя нет {amount}💰", user_id=user_id)
            return
        add_coins(target_uid, amount)
        send_and_track(chat_id, f"✅ @{message.from_user.username} подарил {amount}💰 @{target}", user_id=user_id)

    # Групповой бонус
    elif text == "бонус":
        now = datetime.now()
        if chat_id in group_bonus_tracker and group_bonus_tracker[chat_id] > now - timedelta(hours=6):
            rem = timedelta(hours=6) - (now - group_bonus_tracker[chat_id])
            hours = rem.seconds // 3600
            minutes = (rem.seconds % 3600) // 60
            send_and_track(chat_id, f"⏳ Бонус через {hours}ч {minutes}мин", user_id=user_id)
            return
        group_bonus_tracker[chat_id] = now
        for uid in all_users_list():
            try:
                add_coins(int(uid), 50)
            except:
                pass
        send_and_track(chat_id, "🎁 *Групповой бонус!* Все получили +50💰", parse_mode="Markdown", user_id=user_id)

    # НАЗНАЧЕНИЕ РОЛЕЙ
    elif text.startswith("назначить"):
        parts = message.text.split()
        if len(parts) != 3:
            send_and_track(chat_id, "❌ Формат: назначить @username роль\nДоступные роли: вице-президент, админ", user_id=user_id)
            return
        target = parts[1].replace("@", "").lower()
        role = parts[2].lower()
        if role not in ["вице-президент", "админ"]:
            send_and_track(chat_id, "❌ Роль: вице-президент или админ", user_id=user_id)
            return

        user_role = get_group_role(chat_id, user_id)
        # Проверка прав
        if user_role == "member":
            # Если в группе нет президента, первый назначивший становится президентом
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM group_roles WHERE group_id = %s AND role = 'президент'", (str(chat_id),))
            has_president = cur.fetchone()
            cur.close()
            conn.close()
            if not has_president:
                set_group_role(chat_id, user_id, "президент")
                user_role = "президент"
                send_and_track(chat_id, f"👑 @{message.from_user.username} стал президентом группы!", user_id=user_id)
            else:
                send_and_track(chat_id, "❌ Ты не можешь назначать роли! Только президент или вице-президент.", user_id=user_id)
                return

        if user_role not in ["президент", "вице-президент"]:
            send_and_track(chat_id, "❌ Только президент или вице-президент могут назначать роли!", user_id=user_id)
            return

        # Вице-президент может назначать только админов
        if user_role == "вице-президент" and role != "админ":
            send_and_track(chat_id, "❌ Вице-президент может назначать только админов!", user_id=user_id)
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
            send_and_track(chat_id, f"❌ @{target} не найден", user_id=user_id)
            return

        set_group_role(chat_id, target_uid, role)
        send_and_track(chat_id, f"✅ Пользователю @{target} назначена роль {role}", user_id=user_id)

    # ЗАБРАТЬ РОЛЬ (только президент)
    elif text.startswith("забрать роль"):
        parts = message.text.split()
        if len(parts) != 3:
            send_and_track(chat_id, "❌ Формат: забрать роль @username", user_id=user_id)
            return
        target = parts[2].replace("@", "").lower()
        user_role = get_group_role(chat_id, user_id)
        if user_role != "президент":
            send_and_track(chat_id, "❌ Только президент может забирать роли!", user_id=user_id)
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
            send_and_track(chat_id, f"❌ @{target} не найден", user_id=user_id)
            return
        remove_group_role(chat_id, target_uid)
        send_and_track(chat_id, f"✅ У пользователя @{target} забрана роль", user_id=user_id)

    # ЗАПРЕТИТЬ (бан)
    elif text.startswith("запретить"):
        parts = message.text.split()
        if len(parts) < 2:
            send_and_track(chat_id, "❌ Формат: запретить @username [время в часах] [причина]", user_id=user_id)
            return
        target = parts[1].replace("@", "").lower()
        duration = -1
        reason = "Нарушение правил"
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
            send_and_track(chat_id, "❌ Недостаточно прав для бана!", user_id=user_id)
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
            send_and_track(chat_id, f"❌ @{target} не найден", user_id=user_id)
            return
        target_role = get_group_role(chat_id, target_uid)
        # Нельзя банить вышестоящих
        if target_role == "президент":
            send_and_track(chat_id, "❌ Нельзя забанить президента!", user_id=user_id)
            return
        if user_role == "админ" and target_role in ["вице-президент", "админ"]:
            send_and_track(chat_id, "❌ Админ не может банить других админов или вице-президента!", user_id=user_id)
            return
        if user_role == "вице-президент" and target_role == "вице-президент":
            send_and_track(chat_id, "❌ Вице-президент не может банить другого вице-президента!", user_id=user_id)
            return
        ban_user(chat_id, target_uid, duration, reason)
        if duration == -1:
            send_and_track(chat_id, f"🚫 @{target} забанен навсегда. Причина: {reason}", user_id=user_id)
        else:
            hours = duration // 3600
            send_and_track(chat_id, f"🚫 @{target} забанен на {hours} ч. Причина: {reason}", user_id=user_id)

    # РАЗРЕШИТЬ (разбан)
    elif text.startswith("разрешить"):
        parts = message.text.split()
        if len(parts) != 2:
            send_and_track(chat_id, "❌ Формат: разрешить @username", user_id=user_id)
            return
        target = parts[1].replace("@", "").lower()
        user_role = get_group_role(chat_id, user_id)
        if user_role not in ["президент", "вице-президент", "админ"]:
            send_and_track(chat_id, "❌ Недостаточно прав для разбана!", user_id=user_id)
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
            send_and_track(chat_id, f"❌ @{target} не найден", user_id=user_id)
            return
        unban_user(chat_id, target_uid)
        send_and_track(chat_id, f"✅ @{target} разбанен", user_id=user_id)

    # ВЫДАТЬ МОНЕТЫ (только президент)
    elif text.startswith("выдать монеты"):
        parts = message.text.split()
        if len(parts) != 3:
            send_and_track(chat_id, "❌ Формат: выдать монеты @username сумма", user_id=user_id)
            return
        target = parts[1].replace("@", "").lower()
        try:
            amount = int(parts[2])
        except:
            send_and_track(chat_id, "❌ Сумма числом", user_id=user_id)
            return
        user_role = get_group_role(chat_id, user_id)
        if user_role != "президент":
            send_and_track(chat_id, "❌ Только президент может выдавать монеты!", user_id=user_id)
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
            send_and_track(chat_id, f"❌ @{target} не найден", user_id=user_id)
            return
        if not remove_coins(user_id, amount):
            send_and_track(chat_id, f"❌ У тебя нет {amount}💰", user_id=user_id)
            return
        add_coins(target_uid, amount)
        send_and_track(chat_id, f"✅ Выдано {amount}💰 @{target}", user_id=user_id)

    # Групповые игры
    elif text in ["1 кубик", "2 кубика", "3 кубика", "кости на удачу"]:
        if text == "1 кубик":
            roll = random.randint(1, 6)
            send_and_track(chat_id, f"🎲 @{message.from_user.username} кинул {roll}!", user_id=user_id)
        elif text == "2 кубика":
            d1, d2 = random.randint(1, 6), random.randint(1, 6)
            send_and_track(chat_id, f"🎲 @{message.from_user.username} кинул {d1}+{d2}={d1+d2}!", user_id=user_id)
        elif text == "3 кубика":
            d1, d2, d3 = random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)
            send_and_track(chat_id, f"🎲 @{message.from_user.username} кинул {d1}+{d2}+{d3}={d1+d2+d3}!", user_id=user_id)
        elif text == "кости на удачу":
            d1, d2, d3 = random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)
            send_and_track(chat_id, f"🎲💰 @{message.from_user.username} кинул {d1}+{d2}+{d3}={d1+d2+d3}!", user_id=user_id)

    elif text == "камень-ножницы":
        bot_choice = random.choice(["камень", "ножницы", "бумага"])
        group_game_sessions[user_id] = {"game": "rps", "bot_choice": bot_choice}
        send_and_track(chat_id, f"✂️ @{message.from_user.username} против бота. Бот выбрал {bot_choice}. Пиши 'камень', 'ножницы' или 'бумага'", user_id=user_id)

    elif text == "слоты":
        r = [random.choice(["🍒", "🍊", "🍋", "🔔", "💎", "7️⃣"]) for _ in range(3)]
        send_and_track(chat_id, f"🎰 |{r[0]}|{r[1]}|{r[2]}|", user_id=user_id)

    elif text == "камень-мешок-монета":
        bot_choice = random.choice(["камень", "мешок", "монета"])
        group_game_sessions[user_id] = {"game": "rps2", "bot_choice": bot_choice}
        send_and_track(chat_id, f"💎 @{message.from_user.username} против бота. Бот выбрал {bot_choice}. Пиши 'камень', 'мешок' или 'монета'", user_id=user_id)

    elif text == "угадай цвет":
        color = random.choice(["🔴 красный", "⚫ чёрный"])
        group_game_sessions[user_id] = {"game": "color", "color": color}
        send_and_track(chat_id, f"🎯 @{message.from_user.username} угадывает цвет. Выпал {color}. Пиши 'красный' или 'чёрный'", user_id=user_id)

    elif text == "выше/ниже":
        first = random.randint(1, 10)
        second = random.randint(1, 10)
        send_and_track(chat_id, f"📈 @{message.from_user.username} играет. Было {first}, стало {second}!", user_id=user_id)

    elif text == "русская рулетка":
        if random.randint(1, 6) == 1:
            send_and_track(chat_id, f"🔫 @{message.from_user.username} проиграл в русской рулетке!", user_id=user_id)
        else:
            send_and_track(chat_id, f"🔫 @{message.from_user.username} выиграл в русской рулетке!", user_id=user_id)

    elif text == "чет/нечет":
        num = random.randint(1, 10)
        is_even = num % 2 == 0
        group_game_sessions[user_id] = {"game": "evenodd", "number": num, "is_even": is_even}
        send_and_track(chat_id, f"🎲 @{message.from_user.username} угадывает. Число {num} ({'чётное' if is_even else 'нечётное'})", user_id=user_id)

    # Обработка ответов в групповых играх
    elif user_id in group_game_sessions:
        g = group_game_sessions[user_id]
        if g["game"] == "rps" and text in ["камень", "ножницы", "бумага"]:
            if text == g["bot_choice"]:
                send_and_track(chat_id, f"🤝 Ничья!", user_id=user_id)
            elif (text == "камень" and g["bot_choice"] == "ножницы") or (text == "ножницы" and g["bot_choice"] == "бумага") or (text == "бумага" and g["bot_choice"] == "камень"):
                send_and_track(chat_id, f"🎉 @{message.from_user.username} победил!", user_id=user_id)
            else:
                send_and_track(chat_id, f"💀 @{message.from_user.username} проиграл", user_id=user_id)
            del group_game_sessions[user_id]
        elif g["game"] == "rps2" and text in ["камень", "мешок", "монета"]:
            rules = {"камень": "мешок", "мешок": "монета", "монета": "камень"}
            if text == g["bot_choice"]:
                send_and_track(chat_id, f"🤝 Ничья!", user_id=user_id)
            elif rules[text] == g["bot_choice"]:
                send_and_track(chat_id, f"🎉 @{message.from_user.username} победил!", user_id=user_id)
            else:
                send_and_track(chat_id, f"💀 @{message.from_user.username} проиграл", user_id=user_id)
            del group_game_sessions[user_id]
        elif g["game"] == "color" and text in ["красный", "чёрный"]:
            user_c = "красный" if "красн" in text else "чёрный"
            if user_c in g["color"]:
                send_and_track(chat_id, f"🎯 Угадал! {g['color']}", user_id=user_id)
            else:
                send_and_track(chat_id, f"🎯 Не угадал. {g['color']}", user_id=user_id)
            del group_game_sessions[user_id]
        elif g["game"] == "evenodd" and text in ["чётное", "нечётное", "четное", "нечетное"]:
            user_even = text in ["чётное", "четное"]
            if user_even == g["is_even"]:
                send_and_track(chat_id, f"🎲 Угадал! {g['number']} — {'чётное' if g['is_even'] else 'нечётное'}", user_id=user_id)
            else:
                send_and_track(chat_id, f"🎲 Не угадал. {g['number']} — {'чётное' if g['is_even'] else 'нечётное'}", user_id=user_id)
            del group_game_sessions[user_id]

@bot.message_handler(func=lambda m: m.chat.type == "private" and waiting_for_question.get(m.chat.id))
def handle_question(message):
    uid = message.chat.id
    forward_question(uid, message.text)
    waiting_for_question[uid] = False
    send_and_track(uid, "✅ Вопрос отправлен администратору!", reply_markup=main_menu_keyboard(), user_id=uid)

if __name__ == "__main__":
    print("✅ БОТ ЗАПУЩЕН!")
    print("📊 30+ игр, 10 ферм, кланы, групповые роли, админ-панель")
    print("🎨 ВСЕ КНОПКИ — ИНЛАЙН!")
    bot.infinity_polling(skip_pending=True)
