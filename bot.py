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
    return (f"┌─────────────────────┐\n"
            f"│  👤 *{u.get('username') or 'Игрок'}*\n"
            f"│  💰 Баланс: `{u['coins']}` монет\n"
            f"│  📍 Регион: {region}\n"
            f"│  🎮 Всего игр: {u.get('total_games', 0)}\n"
            f"│  🏆 Побед: {u.get('total_wins', 0)}\n"
            f"└─────────────────────┘")

def menu_button():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔙 Меню", callback_data="back_main"))
    return kb

def play_again_keyboard(game_callback):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎮 Сыграть ещё", callback_data=game_callback),
        InlineKeyboardButton("🎮 Меню игр", callback_data="games_menu_after"),
        InlineKeyboardButton("🔙 Главное меню", callback_data="back_main")
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
    return amount_per_interval, iv

def get_pending_income(uid, biz_type):
    b = get_business(uid, biz_type)
    if not b:
        return 0
    amt, iv = get_business_amount(biz_type, b["amount_level"], b["speed_level"])
    last = b["last_collect"]
    elapsed = (datetime.now() - last).total_seconds() / 60
    intervals = int(elapsed // iv)
    return intervals * amt

def collect_income(uid, biz_type):
    b = get_business(uid, biz_type)
    if not b:
        return 0, "❌ У тебя нет такой фермы"
    amt, iv = get_business_amount(biz_type, b["amount_level"], b["speed_level"])
    last = b["last_collect"]
    elapsed = (datetime.now() - last).total_seconds() / 60
    intervals = int(elapsed // iv)
    if intervals == 0:
        return 0, "⏳ Накоплений нет"
    earned = intervals * amt
    add_coins(uid, earned)
    new_last = last + timedelta(minutes=intervals * iv)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE businesses SET last_collect = %s WHERE user_id = %s AND business_type = %s", (new_last, str(uid), biz_type))
    conn.commit()
    cur.close()
    conn.close()
    return earned, f"✅ Собрано {earned}💰 с {biz_type}"

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
    amt, iv = get_business_amount(biz_type, b["amount_level"], b["speed_level"])
    pending = get_pending_income(uid, biz_type)
    speed_price = int(BUSINESSES[biz_type]["price"] * 0.5)
    return (f"🏭 *{biz_type}*\n\n"
            f"📊 Уровень количества: {b['amount_level']}\n"
            f"💰 Доход за интервал: +{amt}💰\n"
            f"⏱️ Интервал: {iv} мин\n"
            f"📈 Примерно {int(amt * 60 / iv)}💰/час\n\n"
            f"💎 Накоплено: {pending}💰\n\n"
            f"🔧 *Апгрейды:*\n"
            f"📈 +{BUSINESSES[biz_type]['upgrade_income']}💰 к доходу — {AMOUNT_UPGRADE_COST}💰\n"
            f"⚡ Ускорить — {speed_price}💰")

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
def set_group_role(chat_id, user_id, role):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO group_roles (group_id, user_id, role) VALUES (%s,%s,%s) ON CONFLICT (group_id, user_id) DO UPDATE SET role = EXCLUDED.role", (str(chat_id), str(user_id), role))
    conn.commit()
    cur.close()
    conn.close()

def get_group_role(chat_id, user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT role FROM group_roles WHERE group_id = %s AND user_id = %s", (str(chat_id), str(user_id)))
    r = cur.fetchone()
    cur.close()
    conn.close()
    return r[0] if r else "member"

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
        KeyboardButton("❓ Вопрос")
    )
    if uid == ADMIN_ID:
        kb.add(KeyboardButton("🔧 Админ"))
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
        InlineKeyboardButton("🎲 Счастливое число", callback_data="game_luckynum"),
        InlineKeyboardButton("🍀 Клевер", callback_data="game_clover"),
        InlineKeyboardButton("💣 Мина", callback_data="game_mine"),
        InlineKeyboardButton("🎲 Покер на костях", callback_data="game_dicepoker"),
        InlineKeyboardButton("🃏 Блэкджек", callback_data="game_blackjack"),
        InlineKeyboardButton("🎲 Кости (2 куб.)", callback_data="game_dice2"),
        InlineKeyboardButton("🎴 Угадай карту", callback_data="game_guesscard"),
        InlineKeyboardButton("🎴 Пьяница", callback_data="game_drunkard"),
        InlineKeyboardButton("🃑 Дурак", callback_data="game_fool"),
        InlineKeyboardButton("🃟 Меморина", callback_data="game_memory"),
        InlineKeyboardButton("📈 Больше/Меньше", callback_data="game_moreless"),
        InlineKeyboardButton("🎲 Риск", callback_data="game_risk"),
        InlineKeyboardButton("🎲 Свинья", callback_data="game_pig"),
        InlineKeyboardButton("🎰 Джекпот", callback_data="game_jackpot"),
        InlineKeyboardButton("🎲 Рулетка", callback_data="game_roulette"),
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

# ========== НОВЫЕ ИГРЫ ==========
def game_luckynum_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    try:
        bet = int(m.text)
        if bet < 1 or bet > 10:
            send_and_track(m.chat.id, "❌ 1–10", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
            return
        num = random.randint(1, 10)
        if bet == num:
            win = random.randint(5, 10)
            add_coins(uid, win)
            text = f"🎲 {num}. Победа! +{win}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
        else:
            text = f"🎲 {num}. Проигрыш! -1💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_luckynum"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(m.chat.id, "❌ Введи число", user_id=uid)

def game_clover_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    if not remove_coins(uid, 1):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
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
        update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
    else:
        text = f"🍀 Не повезло... -1💰"
        update_user(uid, total_games=get_user(uid)["total_games"]+1)
    send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_clover"), parse_mode="Markdown", user_id=uid)

def game_mine_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    try:
        ch = int(m.text)
        if ch < 1 or ch > 6:
            send_and_track(m.chat.id, "❌ 1–6", user_id=uid)
            return
        if not remove_coins(uid, 2):
            send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
            return
        mine = random.randint(1, 6)
        if ch == mine:
            text = f"💣 БАХ! Ты наступил на мину! -2💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1)
        else:
            add_coins(uid, 10)
            text = f"✅ Повезло! +10💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_mine"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(m.chat.id, "❌ Введи число", user_id=uid)

def game_dicepoker_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    if not remove_coins(uid, 2):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
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
        update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
    else:
        text = f"🎲 {rolls}\nНичего... -2💰"
        update_user(uid, total_games=get_user(uid)["total_games"]+1)
    send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_dicepoker"), parse_mode="Markdown", user_id=uid)

def game_blackjack_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    try:
        bet = int(m.text)
        if bet < 5:
            send_and_track(m.chat.id, "❌ Минимум 5💰", user_id=uid)
            return
        if not remove_coins(uid, bet):
            send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
            return
        player = [random.randint(1, 11), random.randint(1, 11)]
        dealer = [random.randint(1, 11)]
        if sum(player) == 21:
            win = bet * 2
            add_coins(uid, win)
            text = f"🃏 Блэкджек! +{win}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
            send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_blackjack"), parse_mode="Markdown", user_id=uid)
            return
        send_and_track(m.chat.id, f"Твои карты: {player} ({sum(player)})\nКарты дилера: {dealer}\n\nВведи 'ещё' или 'хватит':", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_blackjack_step(m, uid, player, dealer, bet))
    except:
        send_and_track(m.chat.id, "❌ Введи число", user_id=uid)

def game_blackjack_step(m, uid, player, dealer, bet):
    delete_previous_message(m.chat.id, uid)
    ch = m.text.lower()
    if ch == "ещё":
        player.append(random.randint(1, 11))
        if sum(player) > 21:
            text = f"Перебор! {player} = {sum(player)}. -{bet}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1)
            send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_blackjack"), parse_mode="Markdown", user_id=uid)
        elif sum(player) == 21:
            win = bet * 2
            add_coins(uid, win)
            text = f"21! +{win}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
            send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_blackjack"), parse_mode="Markdown", user_id=uid)
        else:
            send_and_track(m.chat.id, f"Твои карты: {player} = {sum(player)}", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: game_blackjack_step(m, uid, player, dealer, bet))
    elif ch == "хватит":
        while sum(dealer) < 17:
            dealer.append(random.randint(1, 11))
        if sum(dealer) > 21 or sum(player) > sum(dealer):
            win = bet * 2
            add_coins(uid, win)
            text = f"Победа! {player} vs {dealer}. +{win}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
        elif sum(player) == sum(dealer):
            add_coins(uid, bet)
            text = f"Ничья! {player} vs {dealer}. Возвращено {bet}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1)
        else:
            text = f"Поражение! {player} vs {dealer}. -{bet}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_blackjack"), parse_mode="Markdown", user_id=uid)
    else:
        send_and_track(m.chat.id, "❌ 'ещё' или 'хватит'", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_blackjack_step(m, uid, player, dealer, bet))

def game_dice2_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    try:
        bet = int(m.text)
        if bet < 2 or bet > 12:
            send_and_track(m.chat.id, "❌ 2–12", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
            return
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2
        if bet == total:
            win = random.randint(4, 10)
            add_coins(uid, win)
            text = f"🎲 {d1}+{d2}={total}. Победа! +{win}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
        else:
            text = f"🎲 {d1}+{d2}={total}. Проигрыш! -1💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_dice2"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(m.chat.id, "❌ Введи число", user_id=uid)

def game_guesscard_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    try:
        ch = m.text.lower()
        if ch not in ["♠️", "♥️", "♣️", "♦️"]:
            send_and_track(m.chat.id, "❌ ♠️ ♥️ ♣️ ♦️", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
            return
        card = random.choice(["♠️", "♥️", "♣️", "♦️"])
        if ch == card:
            win = random.randint(5, 10)
            add_coins(uid, win)
            text = f"🎴 Выпала {card}. Угадал! +{win}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
        else:
            text = f"🎴 Выпала {card}. Не угадал. -1💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_guesscard"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(m.chat.id, "❌ Ошибка", user_id=uid)

def game_drunkard_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    if not remove_coins(uid, 1):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
        return
    cards = ["6", "7", "8", "9", "10", "В", "Д", "К", "Т"]
    player = random.choice(cards)
    bot_card = random.choice(cards)
    if cards.index(player) > cards.index(bot_card):
        add_coins(uid, 4)
        text = f"🎴 {player} vs {bot_card}. Победа! +4💰"
        update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
    elif player == bot_card:
        add_coins(uid, 2)
        text = f"🎴 Ничья! +2💰"
        update_user(uid, total_games=get_user(uid)["total_games"]+1)
    else:
        text = f"🎴 {player} vs {bot_card}. Поражение. -1💰"
        update_user(uid, total_games=get_user(uid)["total_games"]+1)
    send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_drunkard"), parse_mode="Markdown", user_id=uid)

def game_fool_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    if not remove_coins(uid, 2):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
        return
    cards = ["6", "7", "8", "9", "10", "В", "Д", "К", "Т"]
    player = random.choice(cards)
    bot_card = random.choice(cards)
    if cards.index(player) > cards.index(bot_card):
        win = 10
        add_coins(uid, win)
        text = f"🃑 {player} vs {bot_card}. Победа! +{win}💰"
        update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
    elif player == bot_card:
        add_coins(uid, 2)
        text = f"🃑 Ничья! +2💰"
        update_user(uid, total_games=get_user(uid)["total_games"]+1)
    else:
        text = f"🃑 {player} vs {bot_card}. Поражение. -2💰"
        update_user(uid, total_games=get_user(uid)["total_games"]+1)
    send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_fool"), parse_mode="Markdown", user_id=uid)

def game_memory_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    if not remove_coins(uid, 1):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
        return
    numbers = [random.randint(1, 10) for _ in range(5)]
    send_and_track(m.chat.id, f"🃟 *Меморина*\nЗапомни числа: {numbers}\nВведи их через пробел:", parse_mode="Markdown", user_id=uid)
    bot.register_next_step_handler_by_chat_id(uid, lambda m: game_memory_check(m, uid, numbers))

def game_memory_check(m, uid, numbers):
    delete_previous_message(m.chat.id, uid)
    try:
        guess = list(map(int, m.text.split()))
        if guess == numbers:
            add_coins(uid, 10)
            text = f"🎉 Идеально! +10💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
        else:
            text = f"❌ Было {numbers}. -1💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_memory"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(m.chat.id, "❌ Введи 5 чисел", user_id=uid)

def game_moreless_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    try:
        bet = int(m.text)
        if bet < 2 or bet > 12:
            send_and_track(m.chat.id, "❌ 2–12", user_id=uid)
            return
        if not remove_coins(uid, 1):
            send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
            return
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2
        if bet > total:
            win = random.randint(4, 8)
            add_coins(uid, win)
            text = f"🎲 {total}. Угадал (больше)! +{win}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
        elif bet < total:
            win = random.randint(4, 8)
            add_coins(uid, win)
            text = f"🎲 {total}. Угадал (меньше)! +{win}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
        else:
            text = f"🎲 {total}. Ничья. -1💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_moreless"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(m.chat.id, "❌ Введи число", user_id=uid)

def game_risk_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    try:
        bet = int(m.text)
        if bet < 5:
            send_and_track(m.chat.id, "❌ Минимум 5💰", user_id=uid)
            return
        if not remove_coins(uid, bet):
            send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
            return
        number = random.randint(1, 6)
        send_and_track(m.chat.id, f"🎲 *Риск*\nУгадай число (1–6):", parse_mode="Markdown", user_id=uid)
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_risk_check(m, uid, number, bet))
    except:
        send_and_track(m.chat.id, "❌ Введи число", user_id=uid)

def game_risk_check(m, uid, number, bet):
    delete_previous_message(m.chat.id, uid)
    try:
        guess = int(m.text)
        if guess < 1 or guess > 6:
            send_and_track(m.chat.id, "❌ 1–6", user_id=uid)
            return
        if guess == number:
            win = bet * 2
            add_coins(uid, win)
            text = f"🎲 Выпало {number}. Угадал! +{win}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
        else:
            text = f"🎲 Выпало {number}. Не угадал. -{bet}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_risk"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(m.chat.id, "❌ Введи число", user_id=uid)

def game_pig_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    if not remove_coins(uid, 1):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
        return
    score = 0
    game_pig_roll(m, uid, score)

def game_pig_roll(m, uid, score):
    roll = random.randint(1, 6)
    if roll == 1:
        send_and_track(m.chat.id, f"🎲 Выпало 1! Ты теряешь всё. -1💰", reply_markup=play_again_keyboard("game_pig"), parse_mode="Markdown", user_id=uid)
        update_user(uid, total_games=get_user(uid)["total_games"]+1)
        return
    score += roll
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("🎲 Бросить ещё", callback_data=f"pig_continue_{score}"),
        InlineKeyboardButton("💰 Забрать", callback_data=f"pig_take_{score}"),
        InlineKeyboardButton("🔙 Меню", callback_data="back_main")
    )
    send_and_track(m.chat.id, f"🎲 Выпало {roll}. Твой счёт: {score}. Что делаешь?", reply_markup=kb, parse_mode="Markdown", user_id=uid)

def game_jackpot_play(uid):
    delete_previous_message(uid, uid)
    if not remove_coins(uid, 5):
        send_and_track(uid, "❌ Нет монет", user_id=uid)
        return
    jackpot_data["total"] += 5
    r = random.randint(1, 100)
    if r == 1:
        win = jackpot_data["total"]
        add_coins(uid, win)
        jackpot_data["total"] = 0
        text = f"🎰 *ДЖЕКПОТ!* Ты выиграл {win}💰"
        update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
    else:
        text = f"🎰 Не повезло. Джекпот уже {jackpot_data['total']}💰"
        update_user(uid, total_games=get_user(uid)["total_games"]+1)
    send_and_track(uid, text, reply_markup=play_again_keyboard("game_jackpot"), parse_mode="Markdown", user_id=uid)

def game_roulette_play(uid):
    delete_previous_message(uid, uid)
    send_and_track(uid, "🎲 *Рулетка*\nВведи ставку (число 0–36) и сумму через пробел:\nПример: `17 100`", parse_mode="Markdown", user_id=uid)
    bot.register_next_step_handler_by_chat_id(uid, lambda m: game_roulette_spin(m, uid))

def game_roulette_spin(m, uid):
    delete_previous_message(m.chat.id, uid)
    try:
        parts = m.text.split()
        number = int(parts[0])
        bet = int(parts[1])
        if number < 0 or number > 36:
            send_and_track(m.chat.id, "❌ 0–36", user_id=uid)
            return
        if not remove_coins(uid, bet):
            send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
            return
        result = random.randint(0, 36)
        if result == number:
            win = bet * 36
            add_coins(uid, win)
            text = f"🎲 Выпало {result}. Угадал! +{win}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)
        else:
            text = f"🎲 Выпало {result}. Не угадал. -{bet}💰"
            update_user(uid, total_games=get_user(uid)["total_games"]+1)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("game_roulette"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(m.chat.id, "❌ Пример: `17 100`", user_id=uid)

# ========== ОСНОВНЫЕ ИГРЫ ==========
def update_game_stats(uid, won):
    u = get_user(uid)
    new_games = u.get("total_games", 0) + 1
    new_wins = u.get("total_wins", 0) + (1 if won else 0)
    update_user(uid, total_games=new_games, total_wins=new_wins)

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
        rolls = [random.randint(1, 6) for _ in range(num)]
        total = sum(rolls)
        if bet == total:
            win = random.randint(win_exact_min, win_exact_max)
            add_coins(uid, win)
            text = f"🎲 {total}. Победа! +{win}💰"
            update_game_stats(uid, True)
        else:
            text = f"🎲 {total}. Проигрыш! -1💰"
            update_game_stats(uid, False)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard(game_callback), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(m.chat.id, "❌ Введи число", user_id=uid)

def dice_luck_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    if not remove_coins(uid, 2):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
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
        secret = random.randint(1, 20)
        if bet == secret:
            win = random.randint(5, 12)
            add_coins(uid, win)
            text = f"🔢 {secret}. Победа! +{win}💰"
            update_game_stats(uid, True)
        else:
            text = f"🔢 {secret}. Проигрыш! -1💰"
            update_game_stats(uid, False)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("gamble_number"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(m.chat.id, "❌ Введи число", user_id=uid)

def gamble_rps_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    choice = m.text.lower()
    if choice not in ["камень", "ножницы", "бумага"]:
        send_and_track(m.chat.id, "❌ камень/ножницы/бумага", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
        return
    bot_choice = random.choice(["камень", "ножницы", "бумага"])
    if choice == bot_choice:
        add_coins(uid, 2)
        text = "🤝 Ничья! +2💰"
        update_game_stats(uid, False)
    elif (choice == "камень" and bot_choice == "ножницы") or (choice == "ножницы" and bot_choice == "бумага") or (choice == "бумага" and bot_choice == "камень"):
        win = random.randint(3, 7)
        add_coins(uid, win)
        text = f"🎉 Победа! +{win}💰"
        update_game_stats(uid, True)
    else:
        text = f"💀 Поражение! -1💰"
        update_game_stats(uid, False)
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
            add_coins(uid, 10)
            text = f"🎴 *ДЖОКЕР!* +10💰"
            update_game_stats(uid, True)
        else:
            text = f"🎴 Масть... -1💰"
            update_game_stats(uid, False)
        send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("gamble_cards"), parse_mode="Markdown", user_id=uid)
    except:
        send_and_track(m.chat.id, "❌ Введи число", user_id=uid)

def gamble_slots_play(uid):
    delete_previous_message(uid, uid)
    if not remove_coins(uid, 1):
        send_and_track(uid, "❌ Нет монет", user_id=uid)
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
    send_and_track(uid, text, reply_markup=play_again_keyboard("gamble_slots"), parse_mode="Markdown", user_id=uid)

def gamble_rps2_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    ch = m.text.lower()
    if ch not in ["камень", "мешок", "монета"]:
        send_and_track(m.chat.id, "❌ камень/мешок/монета", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
        return
    bot_ch = random.choice(["камень", "мешок", "монета"])
    rules = {"камень": "мешок", "мешок": "монета", "монета": "камень"}
    if ch == bot_ch:
        add_coins(uid, 2)
        text = "🤝 Ничья! +2💰"
        update_game_stats(uid, False)
    elif rules[ch] == bot_ch:
        win = random.randint(3, 7)
        add_coins(uid, win)
        text = f"🎉 Победа! +{win}💰"
        update_game_stats(uid, True)
    else:
        text = f"💀 Поражение! -1💰"
        update_game_stats(uid, False)
    send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("gamble_rps2"), parse_mode="Markdown", user_id=uid)

def gamble_color_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    ch = m.text.lower()
    if ch not in ["красный", "чёрный"]:
        send_and_track(m.chat.id, "❌ красный или чёрный", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
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
    send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("gamble_color"), parse_mode="Markdown", user_id=uid)

def gamble_highlow_play(m, uid, first):
    delete_previous_message(m.chat.id, uid)
    ch = m.text.lower()
    if ch not in ["выше", "ниже"]:
        send_and_track(m.chat.id, "❌ выше или ниже", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
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
    send_and_track(m.chat.id, text, reply_markup=play_again_keyboard("gamble_highlow"), parse_mode="Markdown", user_id=uid)

def gamble_roulette_play(uid):
    delete_previous_message(uid, uid)
    if not remove_coins(uid, 5):
        send_and_track(uid, "❌ Нет монет", user_id=uid)
        return
    if random.randint(1, 6) == 1:
        text = "🔫 *Русская рулетка*\n💀 БАХ! -5💰"
        update_game_stats(uid, False)
    else:
        add_coins(uid, 25)
        text = f"🔫 *Русская рулетка*\n🎉 ЩЁЛК! +25💰"
        update_game_stats(uid, True)
    send_and_track(uid, text, reply_markup=play_again_keyboard("gamble_roulette"), parse_mode="Markdown", user_id=uid)

def gamble_evenodd_play(m, uid):
    delete_previous_message(m.chat.id, uid)
    ch = m.text.lower()
    if ch not in ["чётное", "нечётное", "четное", "нечетное"]:
        send_and_track(m.chat.id, "❌ чётное или нечётное", user_id=uid)
        return
    if not remove_coins(uid, 1):
        send_and_track(m.chat.id, "❌ Нет монет", user_id=uid)
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
        if can_take_bonus(uid):
            add_coins(uid, 10)
            update_user(uid, last_bonus=datetime.now().isoformat())
            send_and_track(uid, "🎁 +10 монет!", reply_markup=menu_button(), parse_mode="Markdown", user_id=uid)
        else:
            send_and_track(uid, "⏳ Бонус уже получен. Завтра!", reply_markup=menu_button(), parse_mode="Markdown", user_id=uid)
    elif text == "👥 Рефералы":
        delete_previous_message(m.chat.id, uid)
        send_and_track(uid, f"👥 *Рефералы*\n📎 {get_referral_link(uid)}\n👥 Приглашено: {get_referral_stats(uid)}", reply_markup=menu_button(), parse_mode="Markdown", user_id=uid)
    elif text == "❓ Вопрос":
        delete_previous_message(m.chat.id, uid)
        send_and_track(uid, "✍️ Напиши вопрос:", user_id=uid)
        waiting_for_question[uid] = True
    elif text == "🔧 Админ" and uid == ADMIN_ID:
        delete_previous_message(m.chat.id, uid)
        admin_panel(uid)
    elif uid == ADMIN_ID and text in ["💰 Выдать монеты", "🔻 Забрать монеты", "👥 Все пользователи", "📢 Рассылка", "🎁 Подарить ферму", "🔙 Меню"]:
        delete_previous_message(m.chat.id, uid)
        admin_commands(uid, text)
    elif waiting_for_question.get(uid):
        forward_question(uid, text)
        waiting_for_question[uid] = False
    else:
        send_and_track(uid, "❌ Используй кнопки меню 👇", user_id=uid)

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
        send_and_track(uid, "Введи ID и название фермы:\nПример: `123456789 🚀 Космодром`", user_id=uid)
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

# ========== ГРУППОВЫЕ КОМАНДЫ ==========
@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "топ")
def group_top(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, coins, username FROM users ORDER BY coins DESC LIMIT 5")
    top = cur.fetchall()
    cur.close()
    conn.close()
    if not top:
        send_and_track(chat_id, "📊 Нет данных", user_id=user_id)
        return
    text = "🏆 *Топ-5 игроков:*\n"
    for i, (uid, coins, name) in enumerate(top, 1):
        text += f"{i}. {name or uid[:8]} — {coins}💰\n"
    send_and_track(chat_id, text, parse_mode="Markdown", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower().startswith("подарить"))
def group_gift(m):
    chat_id = m.chat.id
    from_uid = m.from_user.id
    if is_banned(chat_id, from_uid):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=from_uid)
        return
    parts = m.text.split()
    if len(parts) != 3:
        send_and_track(chat_id, "❌ Формат: подарок @username 10", user_id=from_uid)
        return
    target = parts[1].replace("@", "").lower()
    try:
        amount = int(parts[2])
    except:
        send_and_track(chat_id, "❌ Сумма числом", user_id=from_uid)
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
        send_and_track(chat_id, f"❌ @{target} не найден", user_id=from_uid)
        return
    if not remove_coins(from_uid, amount):
        send_and_track(chat_id, f"❌ У тебя нет {amount}💰", user_id=from_uid)
        return
    add_coins(target_uid, amount)
    send_and_track(chat_id, f"✅ @{m.from_user.username} подарил {amount}💰 @{target}", user_id=from_uid)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "бонус")
def group_bonus(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
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
            add_coins(int(uid), 100)
        except:
            pass
    send_and_track(chat_id, "🎁 *Групповой бонус!* Все получили +100💰", parse_mode="Markdown", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "1 кубик")
def g_dice1(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
    roll = random.randint(1, 6)
    send_and_track(chat_id, f"🎲 @{m.from_user.username} кинул {roll}!", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "2 кубика")
def g_dice2(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
    d1, d2 = random.randint(1, 6), random.randint(1, 6)
    send_and_track(chat_id, f"🎲 @{m.from_user.username} кинул {d1}+{d2}={d1+d2}!", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "3 кубика")
def g_dice3(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
    d1, d2, d3 = random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)
    send_and_track(chat_id, f"🎲 @{m.from_user.username} кинул {d1}+{d2}+{d3}={d1+d2+d3}!", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "кости на удачу")
def g_luck(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
    d1, d2, d3 = random.randint(1, 6), random.randint(1, 6), random.randint(1, 6)
    send_and_track(chat_id, f"🎲💰 @{m.from_user.username} кинул {d1}+{d2}+{d3}={d1+d2+d3}!", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "угадай число")
def g_guess(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
    num = random.randint(1, 20)
    group_game_sessions[user_id] = {"game": "guess", "number": num}
    send_and_track(chat_id, f"🔢 @{m.from_user.username} начал. Я загадал число 1–20. Угадайте!", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "камень-ножницы")
def g_rps(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
    bot_choice = random.choice(["камень", "ножницы", "бумага"])
    group_game_sessions[user_id] = {"game": "rps", "bot_choice": bot_choice}
    send_and_track(chat_id, f"✂️ @{m.from_user.username} против бота. Бот выбрал {bot_choice}. Пиши 'камень', 'ножницы' или 'бумага'", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "слоты")
def g_slots(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
    r = [random.choice(["🍒", "🍊", "🍋", "🔔", "💎", "7️⃣"]) for _ in range(3)]
    send_and_track(chat_id, f"🎰 |{r[0]}|{r[1]}|{r[2]}|", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "камень-мешок-монета")
def g_rps2(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
    bot_choice = random.choice(["камень", "мешок", "монета"])
    group_game_sessions[user_id] = {"game": "rps2", "bot_choice": bot_choice}
    send_and_track(chat_id, f"💎 @{m.from_user.username} против бота. Бот выбрал {bot_choice}. Пиши 'камень', 'мешок' или 'монета'", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "угадай цвет")
def g_color(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
    color = random.choice(["🔴 красный", "⚫ чёрный"])
    group_game_sessions[user_id] = {"game": "color", "color": color}
    send_and_track(chat_id, f"🎯 @{m.from_user.username} угадывает цвет. Выпал {color}. Пиши 'красный' или 'чёрный'", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "выше/ниже")
def g_highlow(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
    first = random.randint(1, 10)
    second = random.randint(1, 10)
    send_and_track(chat_id, f"📈 @{m.from_user.username} играет. Было {first}, стало {second}!", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "русская рулетка")
def g_roulette(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
    if random.randint(1, 6) == 1:
        send_and_track(chat_id, f"🔫 @{m.from_user.username} проиграл в русской рулетке!", user_id=user_id)
    else:
        send_and_track(chat_id, f"🔫 @{m.from_user.username} выиграл в русской рулетке!", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "чет/нечет")
def g_evenodd(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
    num = random.randint(1, 10)
    is_even = num % 2 == 0
    group_game_sessions[user_id] = {"game": "evenodd", "number": num, "is_even": is_even}
    send_and_track(chat_id, f"🎲 @{m.from_user.username} угадывает. Число {num} ({'чётное' if is_even else 'нечётное'})", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "горячо/холодно")
def g_hotcold(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    if is_banned(chat_id, user_id):
        send_and_track(chat_id, "❌ Вы забанены!", user_id=user_id)
        return
    num = random.randint(1, 100)
    group_game_sessions[user_id] = {"game": "hotcold", "number": num, "attempts": 0}
    send_and_track(chat_id, f"🔥 @{m.from_user.username} начал. Число 1–100, 3 попытки!", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"])
def group_msg_handler(m):
    chat_id = m.chat.id
    text = m.text.lower()
    user_id = m.from_user.id
    if user_id in group_game_sessions:
        g = group_game_sessions[user_id]
        if g["game"] == "guess":
            try:
                guess = int(text)
                if guess == g["number"]:
                    send_and_track(chat_id, f"🎉 @{m.from_user.username} угадал число {g['number']}!", user_id=user_id)
                    del group_game_sessions[user_id]
            except:
                pass
        elif g["game"] == "rps":
            if text in ["камень", "ножницы", "бумага"]:
                if text == g["bot_choice"]:
                    send_and_track(chat_id, f"🤝 Ничья!", user_id=user_id)
                elif (text == "камень" and g["bot_choice"] == "ножницы") or (text == "ножницы" and g["bot_choice"] == "бумага") or (text == "бумага" and g["bot_choice"] == "камень"):
                    send_and_track(chat_id, f"🎉 @{m.from_user.username} победил!", user_id=user_id)
                else:
                    send_and_track(chat_id, f"💀 @{m.from_user.username} проиграл", user_id=user_id)
                del group_game_sessions[user_id]
        elif g["game"] == "rps2":
            if text in ["камень", "мешок", "монета"]:
                rules = {"камень": "мешок", "мешок": "монета", "монета": "камень"}
                if text == g["bot_choice"]:
                    send_and_track(chat_id, f"🤝 Ничья!", user_id=user_id)
                elif rules[text] == g["bot_choice"]:
                    send_and_track(chat_id, f"🎉 @{m.from_user.username} победил!", user_id=user_id)
                else:
                    send_and_track(chat_id, f"💀 @{m.from_user.username} проиграл", user_id=user_id)
                del group_game_sessions[user_id]
        elif g["game"] == "color":
            if text in ["красный", "чёрный"]:
                user_c = "красный" if "красн" in text else "чёрный"
                if user_c in g["color"]:
                    send_and_track(chat_id, f"🎯 Угадал! {g['color']}", user_id=user_id)
                else:
                    send_and_track(chat_id, f"🎯 Не угадал. {g['color']}", user_id=user_id)
                del group_game_sessions[user_id]
        elif g["game"] == "evenodd":
            if text in ["чётное", "нечётное", "четное", "нечетное"]:
                user_even = text in ["чётное", "четное"]
                if user_even == g["is_even"]:
                    send_and_track(chat_id, f"🎲 Угадал! {g['number']} — {'чётное' if g['is_even'] else 'нечётное'}", user_id=user_id)
                else:
                    send_and_track(chat_id, f"🎲 Не угадал. {g['number']} — {'чётное' if g['is_even'] else 'нечётное'}", user_id=user_id)
                del group_game_sessions[user_id]
        elif g["game"] == "hotcold":
            try:
                guess = int(text)
                g["attempts"] += 1
                diff = abs(guess - g["number"])
                if guess == g["number"]:
                    send_and_track(chat_id, f"🎉 @{m.from_user.username} угадал число {g['number']}!", user_id=user_id)
                    del group_game_sessions[user_id]
                elif g["attempts"] >= 3:
                    send_and_track(chat_id, f"❌ Не угадал. Было {g['number']}", user_id=user_id)
                    del group_game_sessions[user_id]
                else:
                    if diff <= 10:
                        hint = "🔥 Горячо!"
                    elif diff <= 30:
                        hint = "🌡️ Тепло..."
                    else:
                        hint = "❄️ Холодно..."
                    send_and_track(chat_id, f"{hint} Осталось {3 - g['attempts']} попытки", user_id=user_id)
            except:
                pass

# ========== ГРУППОВЫЕ РОЛИ (КОМАНДЫ) ==========
@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower().startswith("назначить"))
def assign_role(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    parts = m.text.split()
    if len(parts) != 3:
        send_and_track(chat_id, "❌ Формат: назначить @username роль", user_id=user_id)
        return
    target = parts[1].replace("@", "").lower()
    role = parts[2].lower()
    if role not in ["вице-президент", "админ"]:
        send_and_track(chat_id, "❌ Роль: вице-президент или админ", user_id=user_id)
        return
    user_role = get_group_role(chat_id, user_id)
    if user_role != "президент":
        send_and_track(chat_id, "❌ Только президент может назначать роли!", user_id=user_id)
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

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower().startswith("забрать роль"))
def remove_role(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    parts = m.text.split()
    if len(parts) != 2:
        send_and_track(chat_id, "❌ Формат: забрать роль @username", user_id=user_id)
        return
    target = parts[1].replace("@", "").lower()
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM group_roles WHERE group_id = %s AND user_id = %s", (str(chat_id), str(target_uid)))
    conn.commit()
    cur.close()
    conn.close()
    send_and_track(chat_id, f"✅ У пользователя @{target} забрана роль", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower().startswith("запретить"))
def ban_cmd(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    parts = m.text.split()
    if len(parts) < 2:
        send_and_track(chat_id, "❌ Формат: запретить @username [время] [причина]", user_id=user_id)
        return
    target = parts[1].replace("@", "").lower()
    duration = -1
    reason = "Нарушение правил"
    if len(parts) >= 3:
        if parts[2].isdigit():
            duration = int(parts[2]) * 3600
            if len(parts) >= 4:
                reason = " ".join(parts[3:])
        else:
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
    ban_user(chat_id, target_uid, duration, reason)
    if duration == -1:
        send_and_track(chat_id, f"🚫 @{target} забанен навсегда. Причина: {reason}", user_id=user_id)
    else:
        hours = duration // 3600
        send_and_track(chat_id, f"🚫 @{target} забанен на {hours} ч. Причина: {reason}", user_id=user_id)

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower().startswith("разрешить"))
def unban_cmd(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    parts = m.text.split()
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

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower().startswith("выдать монеты"))
def group_give_coins(m):
    chat_id = m.chat.id
    user_id = m.from_user.id
    parts = m.text.split()
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
    add_coins(target_uid, amount)
    send_and_track(chat_id, f"✅ Выдано {amount}💰 @{target}", user_id=user_id)

# ========== CALLBACK ==========
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    uid = call.message.chat.id
    data = call.data

    if data == "back_main":
        delete_previous_message(uid, uid)
        send_and_track(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown", user_id=uid)
    elif data == "games_menu_after":
        delete_previous_message(uid, uid)
        send_and_track(uid, "🎮 *Выбери игру:*", reply_markup=games_keyboard(), parse_mode="Markdown", user_id=uid)
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
            send_and_track(uid, "🎲💰 Кости на удачу (3 кубика, сумма ≥15). Ставка 2💰. Напиши 'да'", user_id=uid)
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
            first = random.randint(1, 10)
            send_and_track(uid, f"📈 *Выше/Ниже*\nТекущее число: {first}\nСледующее будет *выше* или *ниже*?", parse_mode="Markdown", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_highlow_play(m, uid, first))
        elif data == "gamble_roulette":
            gamble_roulette_play(uid)
        elif data == "gamble_evenodd":
            send_and_track(uid, "🎲 *Чет/Нечет*\nЧисло 1–10, угадай чётное или нечётное", parse_mode="Markdown", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_evenodd_play(m, uid))
    elif data.startswith("game_"):
        delete_previous_message(uid, uid)
        if data == "game_luckynum":
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
        elif data == "game_dice2":
            send_and_track(uid, "🎲 *Кости (2 кубика)*\nВведи сумму от 2 до 12:", parse_mode="Markdown", user_id=uid)
            bot.register_next_step_handler_by_chat_id(uid, lambda m: game_dice2_play(m, uid))
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
            game_jackpot_play(uid)
        elif data == "game_roulette":
            game_roulette_play(uid)

    elif data.startswith("pig_continue_"):
        score = int(data.split("_")[2])
        roll = random.randint(1, 6)
        if roll == 1:
            send_and_track(uid, f"🎲 Выпало 1! Ты теряешь всё. -1💰", reply_markup=play_again_keyboard("game_pig"), parse_mode="Markdown", user_id=uid)
            update_user(uid, total_games=get_user(uid)["total_games"]+1)
            return
        score += roll
        kb = InlineKeyboardMarkup()
        kb.add(
            InlineKeyboardButton("🎲 Бросить ещё", callback_data=f"pig_continue_{score}"),
            InlineKeyboardButton("💰 Забрать", callback_data=f"pig_take_{score}"),
            InlineKeyboardButton("🔙 Меню", callback_data="back_main")
        )
        send_and_track(uid, f"🎲 Выпало {roll}. Твой счёт: {score}. Что делаешь?", reply_markup=kb, parse_mode="Markdown", user_id=uid)
    elif data.startswith("pig_take_"):
        score = int(data.split("_")[2])
        add_coins(uid, score)
        send_and_track(uid, f"💰 Ты забрал {score}💰!", reply_markup=play_again_keyboard("game_pig"), parse_mode="Markdown", user_id=uid)
        update_user(uid, total_games=get_user(uid)["total_games"]+1, total_wins=get_user(uid)["total_wins"]+1)

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
        send_and_track(uid, "💰 Сколько уровней апгрейда купить? (1–1000)", user_id=uid)
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
        earned, msg = collect_income(uid, biz)
        bot.answer_callback_query(call.id, msg, show_alert=True)
        info = get_business_info(uid, biz)
        if info:
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("📈 +💰 (апгрейд)", callback_data=f"upgrade_amount_{biz}"))
            kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data=f"upgrade_speed_{biz}"))
            kb.add(InlineKeyboardButton("💾 Собрать", callback_data=f"collect_business_{biz}"))
            kb.add(InlineKeyboardButton("◀️ Назад", callback_data="my_businesses"))
            send_and_track(uid, info, reply_markup=kb, parse_mode="Markdown", user_id=uid)

    elif data.startswith("answer_"):
        uid_q = data.split("_")[1]
        send_and_track(ADMIN_ID, f"✍️ Ответ для {uid_q}:", user_id=ADMIN_ID)
        bot.register_next_step_handler(call.message, lambda m: send_answer(m, uid_q))

def process_amount_upgrade(m, uid, biz_type, call):
    try:
        levels = int(m.text)
        if levels < 1 or levels > 1000:
            send_and_track(uid, "❌ От 1 до 1000", user_id=uid)
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

def send_answer(m, target_id):
    if m.chat.id != ADMIN_ID:
        return
    bot.send_message(int(target_id), f"📬 *Ответ:*\n{m.text}", parse_mode="Markdown")
    send_and_track(ADMIN_ID, f"✅ Ответ отправлен {target_id}", reply_markup=menu_button(), user_id=ADMIN_ID)

if __name__ == "__main__":
    print("✅ ФИНАЛЬНЫЙ БОТ ЗАПУЩЕН!")
    print("📊 30+ игр, 10 ферм, групповые роли, админ-панель с подарком фермы")
    bot.infinity_polling(skip_pending=True)
