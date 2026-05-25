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
hotcold_games = {}
bullscows_games = {}
group_bonus_tracker = {}
group_game_sessions = {}
buy_amount_buffer = {}

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
            current_game TEXT,
            active_theme TEXT DEFAULT '🎲',
            active_effect TEXT,
            active_language TEXT DEFAULT 'normal',
            referrer TEXT,
            daily_task TEXT,
            task_completed BOOLEAN DEFAULT FALSE,
            task_reward_taken BOOLEAN DEFAULT FALSE,
            owned_businesses TEXT DEFAULT ''
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_items (
            user_id TEXT,
            item_type TEXT,
            item_id TEXT,
            purchased_at TIMESTAMP DEFAULT NOW(),
            PRIMARY KEY (user_id, item_type, item_id)
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
    conn.commit()
    cur.close()
    conn.close()

init_db()

# ========== 50 ТЕМ ==========
THEMES = {
    "🎲": "Классика", "🌌": "Космос", "🔥": "Огонь", "💎": "Драгоценности",
    "👾": "Ретро", "🎭": "Маскарад", "👑": "Королевская", "🌙": "Мистическая",
    "🤖": "Киберпанк", "✨": "Золотая", "❄️": "Ледяная", "🌊": "Морская",
    "🌋": "Вулкан", "🌪️": "Ураган", "🌈": "Радужная", "☀️": "Солнечная",
    "🚀": "Космическая", "🛸": "НЛО", "🧙": "Волшебная", "🧝": "Эльфийская",
    "🐉": "Драконья", "🦄": "Единорог", "🧛": "Вампирская", "👻": "Призрачная",
    "👹": "Демоническая", "👽": "Инопланетная", "🏯": "Японская", "🏛️": "Греческая",
    "🗿": "Египетская", "🏰": "Средневековая", "🎎": "Китайская", "🕌": "Арабская",
    "🪘": "Африканская", "🪶": "Индейская", "🏔️": "Горная", "🏜️": "Пустынная",
    "🏝️": "Тропическая", "🏞️": "Лесная", "💼": "Деловая", "📱": "Техно",
    "🎮": "Геймерская", "🎬": "Кино", "🎵": "Музыкальная", "🎨": "Художественная",
    "📚": "Книжная", "🧪": "Научная", "⚕️": "Медицинская", "🏀": "Спортивная",
    "⚽": "Футбольная", "🎾": "Теннисная", "🥊": "Боксёрская"
}
THEMES_PRICE = {emoji: random.randint(20, 200) if emoji != "🎲" else 0 for emoji in THEMES}
THEMES_PRICE["🎲"] = 0

# ========== 50 ЭФФЕКТОВ ==========
EFFECTS = {
    "⚡": "Молния", "🌟": "Звезда", "💫": "Комета", "🌀": "Вихрь",
    "🎪": "Цирк", "🏆": "Победитель", "🌈": "Радуга", "💡": "Неон",
    "🔮": "Магия", "🌪️": "Хаос", "🔥": "Огонь", "💧": "Вода",
    "🌍": "Земля", "🌬️": "Воздух", "❄️": "Лёд", "👑": "Корона",
    "🐉": "Дракон", "🦄": "Единорог", "👻": "Призрак", "💰": "Деньги",
    "❤️": "Сердце", "💀": "Череп", "🔑": "Ключ", "🔒": "Замок",
    "🗡️": "Меч", "🛡️": "Щит", "📖": "Книга", "🦉": "Сова",
    "🕷️": "Паук", "🌙": "Луна", "☀️": "Солнце", "⭐": "Звезда2",
    "🌑": "Тьма", "🐺": "Волк", "🦊": "Лиса", "🐻": "Медведь",
    "🦁": "Лев", "🐯": "Тигр", "🦅": "Орёл", "🐬": "Дельфин",
    "🧙": "Маг", "🧝": "Эльф", "🧌": "Тролль", "🧛": "Вампир",
    "🧟": "Зомби", "👽": "Инопланетянин", "🤖": "Робот", "👾": "Инопланетный",
    "🦾": "Кибернетический", "😊": "Радость", "😢": "Грусть", "😡": "Гнев"
}
EFFECTS_PRICE = {emoji: random.randint(25, 150) for emoji in EFFECTS}

# ========== 25 КОМБИНАЦИЙ ==========
COMBOS = {
    "👑⚡": "Королевская сила", "🚀🐉": "Космический дракон", "❄️👻": "Ледяной призрак",
    "💵👑": "Денежный король", "🏆🔥": "Легендарный феникс", "💡👿": "Неоновый демон",
    "🪄🐉": "Магический дракон", "⚔️👻": "Военный призрак", "🎸🌟": "Рок-звезда",
    "😇🌈": "Ангельская радуга", "🌌👑": "Космический правитель", "⭐⚔️": "Звёздный воин",
    "❄️🐉": "Ледяной дракон", "🔥🐦": "Огненный феникс", "🌑👿": "Тёмный властелин",
    "✨😇": "Светлый ангел", "🌊👑": "Морской царь", "⛈️⚡": "Грозовой бог",
    "🪨👹": "Каменный великан", "👻👑": "Призрачный король", "🌈🦄": "Радужный единорог",
    "🔥🐉": "Огненный дракон", "❄️🧊": "Ледяной король", "🌪️🌀": "Повелитель ветра",
    "💎👑": "Алмазный король"
}
COMBOS_PRICE = {combo: random.randint(400, 1500) for combo in COMBOS}

# ========== 10 ЯЗЫКОВ С ПОЛНЫМИ ФРАЗАМИ ==========
LANGUAGES = {
    "normal": "Обычный",
    "royal": "👑 Королевский",
    "sassy": "🔥 Дерзкий",
    "evil": "😈 Злой",
    "mystic": "🎭 Таинственный",
    "robot": "🤖 Роботизированный",
    "poetic": "📜 Поэтический",
    "childish": "🧸 Детский",
    "brutal": "💪 Брутальный",
    "intelligent": "🎓 Интеллигентный"
}
LANGUAGES_PRICE = {
    "royal": 200, "sassy": 250, "evil": 300, "mystic": 350, "robot": 500,
    "poetic": 220, "childish": 180, "brutal": 260, "intelligent": 240
}

def get_phrase(lang, key):
    phrases = {
        "normal": {
            "win": "🎉 Победа! +{}💰", "lose": "💀 Поражение. -{}💰", "draw": "🤝 Ничья! +2💰",
            "welcome": "🎉 Добро пожаловать!", "bonus": "🎁 +10 монет!", "bonus_word": "🎁 Бонус",
            "no_coins": "❌ Нет монет", "already_bonus": "⏳ Бонус уже получен",
            "profile": "Профиль", "find": "Найти игрока", "games": "Игры", "shop": "Магазин",
            "referrals": "Рефералы", "question": "Вопрос", "commands": "Команды", "admin": "Админ",
            "my_items": "Мои покупки", "back": "Назад"
        },
        "royal": {
            "win": "👑 Ваше величество победило! +{}💰", "lose": "💎 Ваше величество проиграло. -{}💰",
            "draw": "🤝 Благородная ничья! +2💰", "welcome": "👑 Добро пожаловать в королевский портал!",
            "bonus": "🎁 Вам пожаловано 10 монет!", "bonus_word": "👑 Пожалование",
            "no_coins": "❌ У вашего величества недостаточно монет", "already_bonus": "⏳ Ваше величество уже получало бонус",
            "profile": "Особа", "find": "Сыскать игрока", "games": "Сыграть", "shop": "Лавка",
            "referrals": "Подданные", "question": "Прошение", "commands": "Указы", "admin": "Канцлер",
            "my_items": "Сокровища", "back": "Вернуться"
        },
        "sassy": {
            "win": "🎉 Ого, повезло! Забирай {}💰!", "lose": "💀 Ха-ха! Проиграл {}💰!",
            "draw": "🤝 Ничья. Забирай 2💰", "welcome": "🎉 О, ещё один игрок! Ну давай!",
            "bonus": "🎁 Держи 10💰. Не опаздывай!", "bonus_word": "🔥 Халява",
            "no_coins": "❌ Эй, бездарь! У тебя нет монет!", "already_bonus": "⏳ Ты уже брал бонус сегодня",
            "profile": "Поглядим", "find": "Кого ищем?", "games": "Замутим?", "shop": "Купи что-то",
            "referrals": "Зови друзей", "question": "Чё надо?", "commands": "Чё умею?", "admin": "Для своих",
            "my_items": "Моё добро", "back": "Вали отсюда"
        },
        "evil": {
            "win": "😈 Невероятно! Ты выиграл {}💰...", "lose": "💀 Отлично! Ты проиграл {}💰!",
            "draw": "🤝 Ничья. 2💰 твои.", "welcome": "😈 Добро пожаловать в адский портал!",
            "bonus": "🎁 Получи 10💰. Это последняя подачка!", "bonus_word": "😈 Подачка",
            "no_coins": "❌ У тебя нет монет! Иди работай!", "already_bonus": "⏳ Ты уже получил подачку сегодня",
            "profile": "Жертва", "find": "Найти жертву", "games": "Играй", "shop": "Лавка дьявола",
            "referrals": "Приведи друзей", "question": "Вопрос?", "commands": "Что я умею", "admin": "Админ",
            "my_items": "Моё", "back": "Уйди"
        },
        "mystic": {
            "win": "🔮 Звёзды благоволят тебе... +{}💰", "lose": "🌙 Тьма поглощает {}💰...",
            "draw": "🤝 Равновесие. +2💰", "welcome": "🎭 Таинственный портал открыт...",
            "bonus": "🎁 Луна дарит тебе 10💰...", "bonus_word": "🌙 Лунный дар",
            "no_coins": "❌ Энергия монет иссякла...", "already_bonus": "⏳ Прилив энергии был...",
            "profile": "Лик", "find": "Найти душу", "games": "Игры судьбы", "shop": "Лавка тайн",
            "referrals": "Призвать", "question": "Вопрос", "commands": "Знания", "admin": "Хранитель",
            "my_items": "Артефакты", "back": "Назад в тень"
        },
        "robot": {
            "win": "🤖 ПОБЕДА. ЗАЧИСЛЕНО {}💰", "lose": "💀 ПОРАЖЕНИЕ. СПИСАНО {}💰",
            "draw": "🤝 НИЧЬЯ. +2💰", "welcome": "🤖 ДОБРО ПОЖАЛОВАТЬ. ЗАПУСК...",
            "bonus": "🎁 ВЫПОЛНЕНА ОПЕРАЦИЯ 'БОНУС'. +10💰", "bonus_word": "🤖 ОПЕРАЦИЯ 'БОНУС'",
            "no_coins": "❌ ОШИБКА. НЕДОСТАТОЧНО МОНЕТ", "already_bonus": "⏳ ОПЕРАЦИЯ УЖЕ ВЫПОЛНЕНА",
            "profile": "ПРОФИЛЬ", "find": "ПОИСК", "games": "ИГРЫ", "shop": "МАГАЗИН",
            "referrals": "РЕФЕРАЛЫ", "question": "ВОПРОС", "commands": "КОМАНДЫ", "admin": "АДМИН",
            "my_items": "ПОКУПКИ", "back": "НАЗАД"
        },
        "poetic": {
            "win": "🌟 Удача улыбнулась тебе! Ты обрёл {}💰", "lose": "🌧️ Судьба отвернулась... Потеряно {}💰",
            "draw": "🍃 Ветер перемен принёс ничью. +2💰", "welcome": "📜 Добро пожаловать в мир грёз и игры!",
            "bonus": "🎁 Заря нового дня дарит тебе 10💰", "bonus_word": "📜 Дар небес",
            "no_coins": "❌ Казна твоя пуста, странник...", "already_bonus": "⏳ Щедрость уже была сегодня",
            "profile": "Лик мой", "find": "Найти путника", "games": "Занятия", "shop": "Лавка чудес",
            "referrals": "Созвать друзей", "question": "Вопрос", "commands": "Свиток знаний", "admin": "Хранитель",
            "my_items": "Сокровища мои", "back": "Вернуться"
        },
        "childish": {
            "win": "🎉 Ура-ура! Ты выиграл {}💰!", "lose": "😢 Ой-ой... Ты проиграл {}💰...",
            "draw": "🤝 Ничья! Делим 2💰!", "welcome": "🧸 Привет-привет! Поиграем?",
            "bonus": "🎁 Держи 10 монеток! Ура!", "bonus_word": "🧸 Подарочек",
            "no_coins": "❌ Ой, монетки кончились...", "already_bonus": "⏳ Ты уже получал бонус сегодня!",
            "profile": "Это я", "find": "Найти друга", "games": "Поиграем", "shop": "Магазинчик",
            "referrals": "Позови друга", "question": "Спросить", "commands": "Что умею", "admin": "Дядька",
            "my_items": "Мои игрушки", "back": "Назад"
        },
        "brutal": {
            "win": "💪 Хорош! Забирай свои {}💰", "lose": "💀 Слабак! Проиграл {}💰",
            "draw": "🤝 Ничья. 2💰 твои.", "welcome": "💪 Заходи, не бойся!",
            "bonus": "🎁 На, получи 10💰. Иди играй!", "bonus_word": "💪 Награда",
            "no_coins": "❌ У тебя нет монет! Иди работай!", "already_bonus": "⏳ Бонус уже был. Жди завтра!",
            "profile": "О себе", "find": "Найти бойца", "games": "Игры", "shop": "Магаз",
            "referrals": "Зови корешей", "question": "Чё надо?", "commands": "Список", "admin": "Админ",
            "my_items": "Моё добро", "back": "Назад"
        },
        "intelligent": {
            "win": "📊 Вероятность победы составила 100%. Начислено {}💰", "lose": "📉 Статистика поражений пополнилась. Потеряно {}💰",
            "draw": "📈 Ничья. Зафиксировано +2💰", "welcome": "🎓 Рад приветствовать вас в нашем игровом заведении.",
            "bonus": "🎁 Поощрительная выплата: 10💰", "bonus_word": "🎓 Поощрение",
            "no_coins": "❌ Финансовый резерв исчерпан", "already_bonus": "⏳ Вы уже активировали бонус сегодня",
            "profile": "Профиль", "find": "Поиск", "games": "Развлечения", "shop": "Торговая лавка",
            "referrals": "Рефералы", "question": "Запрос", "commands": "Команды", "admin": "Администрирование",
            "my_items": "Приобретения", "back": "Возврат"
        }
    }
    return phrases.get(lang, phrases["normal"]).get(key, phrases["normal"][key])

# ========== ОСНОВНЫЕ ФУНКЦИИ ==========
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
        cur.execute("INSERT INTO users (user_id, coins, last_bonus, username, region, current_game, active_theme, active_effect, active_language, referrer, daily_task, task_completed, task_reward_taken) VALUES (%s, 5, NULL, NULL, NULL, NULL, '🎲', NULL, 'normal', NULL, NULL, FALSE, FALSE)", (uid,))
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

def top_players(limit=10):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, coins FROM users ORDER BY coins DESC LIMIT %s", (limit,))
    return cur.fetchall()

def global_stats():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), SUM(coins) FROM users")
    total, coins = cur.fetchone()
    coins = coins or 0
    avg = coins / total if total else 0
    cur.execute("SELECT user_id, coins, username FROM users ORDER BY coins DESC LIMIT 10")
    top = cur.fetchall()
    cur.close()
    conn.close()
    top_text = "\n".join([f"{i+1}. {row[2] or row[0][:8]} — {row[1]}💰" for i, row in enumerate(top)])
    return total, coins, avg, top_text

def format_profile(uid):
    u = get_user(uid)
    theme = u.get("active_theme", "🎲")
    effect = u.get("active_effect", "")
    effect_str = f" {effect}" if effect else ""
    region = u.get("region") or "❓"
    lang = LANGUAGES.get(u.get("active_language", "normal"), "Обычный")
    task = get_user_task(uid)
    task_status = "✅" if task["completed"] and not task["reward_taken"] else "❌" if not task["completed"] else "🎁"
    
    clan_id = get_user_clan(uid)
    clan_info = get_clan_info(clan_id) if clan_id else None
    clan_str = f"\n│  👑 Клан: {clan_info['emoji']} {clan_info['name']}" if clan_info else "\n│  👑 Клан: нет"
    
    return (f"┌─────────────────────┐\n"
            f"│  👤 *{u.get('username') or 'Игрок'}*{effect_str}\n"
            f"│  💰 Баланс: `{u['coins']}` монет\n"
            f"│  📍 Регион: {region}\n"
            f"│  🎨 Тема: {theme}\n"
            f"│  💬 Язык: {lang}\n"
            f"{clan_str}"
            f"\n│  📋 Задание: {task['name']} {task_status}\n"
            f"└─────────────────────┘")

def get_user_items(uid, itype):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT item_id FROM user_items WHERE user_id = %s AND item_type = %s", (str(uid), itype))
    items = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return items

def add_owned_item(uid, itype, iid, call=None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO user_items (user_id, item_type, item_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (str(uid), itype, iid))
    conn.commit()
    cur.close()
    conn.close()
    delete_user_cache(uid)
    if call:
        bot.answer_callback_query(call.id, f"✅ {iid} куплен!", show_alert=True)

def is_owned(uid, itype, iid):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM user_items WHERE user_id=%s AND item_type=%s AND item_id=%s", (str(uid), itype, iid))
    r = cur.fetchone()
    cur.close()
    conn.close()
    return r is not None

def set_active_theme(uid, theme, call=None):
    if is_owned(uid, 'theme', theme):
        update_user(uid, active_theme=theme)
        if call:
            bot.answer_callback_query(call.id, f"✅ Тема {THEMES[theme]} активирована!", show_alert=True)
        return True
    return False

def set_active_effect(uid, effect, call=None):
    if is_owned(uid, 'effect', effect):
        update_user(uid, active_effect=effect)
        if call:
            bot.answer_callback_query(call.id, f"✅ Эффект {EFFECTS[effect]} активирован!", show_alert=True)
        return True
    return False

def set_active_language(uid, lang, call=None):
    if lang == "normal" or is_owned(uid, 'language', lang):
        update_user(uid, active_language=lang)
        if call:
            bot.answer_callback_query(call.id, f"✅ Язык {LANGUAGES[lang]} активирован!", show_alert=True)
        return True
    return False

def set_active_combo(uid, combo, call=None):
    if is_owned(uid, 'combo', combo) and len(combo) >= 2:
        set_active_theme(uid, combo[0])
        set_active_effect(uid, combo[1])
        if call:
            bot.answer_callback_query(call.id, f"✅ Комбинация {COMBOS[combo]} активирована!", show_alert=True)
        return True
    return False

# ========== ПАССИВНЫЙ ДОХОД (10 ФЕРМ) ==========
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

def collect_income(uid, biz_type, call=None):
    b = get_business(uid, biz_type)
    if not b:
        return 0
    amt, iv, _ = get_business_amount(biz_type, b["amount_level"], b["speed_level"])
    last = b["last_collect"]
    now = datetime.now()
    el = (now - last).total_seconds() / 60
    inter = int(el // iv)
    if inter == 0:
        if call:
            bot.answer_callback_query(call.id, "⏳ Накоплений нет", show_alert=True)
        return 0
    earn = inter * amt
    add_coins(uid, earn)
    new_last = last + timedelta(minutes=inter * iv)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE businesses SET last_collect = %s WHERE user_id = %s AND business_type = %s", (new_last, str(uid), biz_type))
    conn.commit()
    cur.close()
    conn.close()
    if call:
        bot.answer_callback_query(call.id, f"✅ Собрано {earn}💰", show_alert=True)
    return earn

def buy_business(uid, biz_type, call):
    if get_business(uid, biz_type):
        bot.answer_callback_query(call.id, "❌ У тебя уже есть эта ферма!", show_alert=True)
        return False
    price = BUSINESSES[biz_type]["price"]
    if not remove_coins(uid, price):
        bot.answer_callback_query(call.id, f"❌ Нужно {price}💰", show_alert=True)
        return False
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO businesses (user_id, business_type, amount_level, speed_level, last_collect) VALUES (%s, %s, 1, 1, NOW())", (str(uid), biz_type))
    conn.commit()
    cur.close()
    conn.close()
    bot.answer_callback_query(call.id, f"✅ {biz_type} куплена!", show_alert=True)
    return True

def upgrade_business_amount(uid, biz_type, call, levels=1):
    b = get_business(uid, biz_type)
    if not b:
        bot.answer_callback_query(call.id, "❌ Нет такой фермы", show_alert=True)
        return False
    total_cost = AMOUNT_UPGRADE_COST * levels
    if not remove_coins(uid, total_cost):
        bot.answer_callback_query(call.id, f"❌ Нужно {total_cost}💰", show_alert=True)
        return False
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE businesses SET amount_level = amount_level + %s WHERE user_id = %s AND business_type = %s", (levels, str(uid), biz_type))
    conn.commit()
    cur.close()
    conn.close()
    bot.answer_callback_query(call.id, f"✅ +{levels} уровень(ей) количества!", show_alert=True)
    return True

def upgrade_business_speed(uid, biz_type, call):
    b = get_business(uid, biz_type)
    if not b:
        bot.answer_callback_query(call.id, "❌ Нет такой фермы", show_alert=True)
        return False
    if b["speed_level"] >= len(SPEED_LEVELS):
        bot.answer_callback_query(call.id, "❌ Максимальная скорость!", show_alert=True)
        return False
    price = int(BUSINESSES[biz_type]["price"] * 0.5)
    if not remove_coins(uid, price):
        bot.answer_callback_query(call.id, f"❌ Нужно {price}💰", show_alert=True)
        return False
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE businesses SET speed_level = speed_level + 1 WHERE user_id = %s AND business_type = %s", (str(uid), biz_type))
    conn.commit()
    cur.close()
    conn.close()
    bot.answer_callback_query(call.id, "✅ Скорость увеличена!", show_alert=True)
    return True

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

# ========== ЗАДАНИЯ (ТОЛЬКО СУЩЕСТВУЮЩИЕ ИГРЫ) ==========
TASKS = [
    {"name": "🎲 1 кубик", "reward": 5, "game": "dice1"},
    {"name": "🎲🎲 2 кубика", "reward": 5, "game": "dice2"},
    {"name": "🎲🎲🎲 3 кубика", "reward": 8, "game": "dice3"},
    {"name": "🎲💰 Кости на удачу", "reward": 10, "game": "diceluck"},
    {"name": "🔢 Угадай число", "reward": 5, "game": "number"},
    {"name": "✂️ Камень-ножницы", "reward": 5, "game": "rps"},
    {"name": "🎴 Карты и Джокер", "reward": 10, "game": "cards"},
    {"name": "🎰 Слоты", "reward": 10, "game": "slots"},
    {"name": "💎 Камень-мешок-монета", "reward": 5, "game": "rps2"},
    {"name": "🎯 Угадай цвет", "reward": 5, "game": "color"},
    {"name": "📈 Выше/Ниже", "reward": 8, "game": "highlow"},
    {"name": "🔫 Русская рулетка", "reward": 20, "game": "roulette"},
    {"name": "🔥 Горячо/Холодно", "reward": 15, "game": "hotcold"},
    {"name": "🎯 Быки и коровы", "reward": 20, "game": "bullscows"},
    {"name": "🎲 Чет/Нечет", "reward": 8, "game": "evenodd"}
]

def get_random_task():
    return random.choice(TASKS)

def get_user_task(uid):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT daily_task, task_completed, task_reward_taken FROM users WHERE user_id = %s", (str(uid),))
    r = cur.fetchone()
    cur.close()
    conn.close()
    if r and r[0]:
        return {"name": r[0], "completed": r[1], "reward_taken": r[2]}
    task = get_random_task()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET daily_task = %s, task_completed = FALSE, task_reward_taken = FALSE WHERE user_id = %s", (task["name"], str(uid)))
    conn.commit()
    cur.close()
    conn.close()
    return {"name": task["name"], "completed": False, "reward_taken": False}

def complete_task(uid, game_name):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT daily_task, task_completed, task_reward_taken FROM users WHERE user_id = %s", (str(uid),))
    r = cur.fetchone()
    if r and not r[1] and not r[2]:
        for task in TASKS:
            if task["name"] == r[0] and task["game"] == game_name:
                cur.execute("UPDATE users SET task_completed = TRUE WHERE user_id = %s", (str(uid),))
                conn.commit()
                cur.close()
                conn.close()
                return True
    cur.close()
    conn.close()
    return False

def take_task_reward(uid):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT task_completed, task_reward_taken, daily_task FROM users WHERE user_id = %s", (str(uid),))
    r = cur.fetchone()
    if r and r[0] and not r[1]:
        for task in TASKS:
            if task["name"] == r[2]:
                reward = task["reward"]
                add_coins(uid, reward)
                cur.execute("UPDATE users SET task_reward_taken = TRUE WHERE user_id = %s", (str(uid),))
                conn.commit()
                cur.close()
                conn.close()
                return reward
    cur.close()
    conn.close()
    return 0

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

# ========== КЛАВИАТУРЫ ==========
REGIONS = ["🇷🇺 Россия", "🇺🇦 Украина", "🇧🇾 Беларусь", "🇰🇿 Казахстан"]

def region_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(*[KeyboardButton(r) for r in REGIONS])
    return kb

def main_keyboard(uid):
    u = get_user(uid)
    theme = u.get("active_theme", "🎲")
    lang = u.get("active_language", "normal")
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton(f"{theme} Игры"),
        KeyboardButton(f"{theme} Магазин"),
        KeyboardButton(f"{theme} Профиль"),
        KeyboardButton(f"{theme} {get_phrase(lang, 'bonus_word')}"),
        KeyboardButton(f"{theme} Рефералы"),
        KeyboardButton(f"{theme} Вопрос"),
        KeyboardButton(f"{theme} Команды"),
        KeyboardButton(f"{theme} 💰 Пассивный доход"),
        KeyboardButton(f"{theme} 👑 Кланы"),
        KeyboardButton(f"{theme} 🏆 Топ игроков"),
        KeyboardButton(f"{theme} 📊 Статистика")
    )
    if uid == ADMIN_ID:
        kb.add(KeyboardButton(f"{theme} 🔧 Админ"))
    return kb

def games_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎲 1 кубик", callback_data="dice_1"),
        InlineKeyboardButton("🎲🎲 2 кубика", callback_data="dice_2"),
        InlineKeyboardButton("🎲🎲🎲 3 кубика", callback_data="dice_3"),
        InlineKeyboardButton("🎲💰 Кости на удачу", callback_data="dice_luck"),
        InlineKeyboardButton("🔢 Угадай число", callback_data="gamble_number"),
        InlineKeyboardButton("✂️ Камень-ножницы", callback_data="gamble_rps"),
        InlineKeyboardButton("🎴 Карты и Джокер", callback_data="gamble_cards"),
        InlineKeyboardButton("🎰 Слоты", callback_data="gamble_slots"),
        InlineKeyboardButton("💎 Камень-мешок-монета", callback_data="gamble_rps2"),
        InlineKeyboardButton("🎯 Угадай цвет", callback_data="gamble_color"),
        InlineKeyboardButton("📈 Выше/Ниже", callback_data="gamble_highlow"),
        InlineKeyboardButton("🔫 Русская рулетка", callback_data="gamble_roulette"),
        InlineKeyboardButton("🔥 Горячо/Холодно", callback_data="gamble_hotcold"),
        InlineKeyboardButton("🎯 Быки и коровы", callback_data="gamble_bullscows"),
        InlineKeyboardButton("🎲 Чет/Нечет", callback_data="gamble_evenodd"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    return kb

def shop_keyboard(uid):
    u = get_user(uid)
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎨 Темы", callback_data="shop_themes"),
        InlineKeyboardButton("✨ Эффекты", callback_data="shop_effects"),
        InlineKeyboardButton("🔥 Комбинации", callback_data="shop_combos"),
        InlineKeyboardButton("💬 Языки", callback_data="shop_languages"),
        InlineKeyboardButton("🎨 Мои покупки", callback_data="my_items"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    bot.send_message(uid, f"🛒 *Магазин*\n💰 У тебя {u['coins']} монет", reply_markup=kb, parse_mode="Markdown")

def shop_themes_keyboard(uid):
    owned = get_user_items(uid, 'theme')
    kb = InlineKeyboardMarkup(row_width=2)
    for emoji, name in THEMES.items():
        if emoji in owned:
            kb.add(InlineKeyboardButton(f"✅ {name} {emoji}", callback_data="no"))
        else:
            kb.add(InlineKeyboardButton(f"🎨 {name} {emoji} ({THEMES_PRICE[emoji]}💰)", callback_data=f"buy_theme_{emoji}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_shop"))
    return kb

def shop_effects_keyboard(uid):
    owned = get_user_items(uid, 'effect')
    kb = InlineKeyboardMarkup(row_width=2)
    for emoji, name in EFFECTS.items():
        if emoji in owned:
            kb.add(InlineKeyboardButton(f"✅ {name} {emoji}", callback_data="no"))
        else:
            kb.add(InlineKeyboardButton(f"✨ {name} {emoji} ({EFFECTS_PRICE[emoji]}💰)", callback_data=f"buy_effect_{emoji}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_shop"))
    return kb

def shop_combos_keyboard(uid):
    owned = get_user_items(uid, 'combo')
    kb = InlineKeyboardMarkup(row_width=1)
    for combo, name in COMBOS.items():
        if combo in owned:
            kb.add(InlineKeyboardButton(f"✅ {name} {combo}", callback_data="no"))
        else:
            kb.add(InlineKeyboardButton(f"🔥 {name} {combo} ({COMBOS_PRICE[combo]}💰)", callback_data=f"buy_combo_{combo}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_shop"))
    return kb

def shop_languages_keyboard(uid):
    owned = get_user_items(uid, 'language')
    kb = InlineKeyboardMarkup(row_width=1)
    for lang, name in LANGUAGES.items():
        if lang == "normal":
            kb.add(InlineKeyboardButton(f"✅ {name} (бесплатно)", callback_data="no"))
        elif lang in owned:
            kb.add(InlineKeyboardButton(f"✅ {name}", callback_data="no"))
        else:
            kb.add(InlineKeyboardButton(f"💬 {name} ({LANGUAGES_PRICE[lang]}💰)", callback_data=f"buy_language_{lang}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_shop"))
    return kb

def my_items_keyboard(uid):
    u = get_user(uid)
    owned_themes = get_user_items(uid, 'theme')
    owned_effects = get_user_items(uid, 'effect')
    owned_combos = get_user_items(uid, 'combo')
    owned_languages = get_user_items(uid, 'language')
    active_theme = u.get("active_theme", "🎲")
    active_effect = u.get("active_effect", "")
    active_language = u.get("active_language", "normal")
    kb = InlineKeyboardMarkup(row_width=2)
    for emoji, name in THEMES.items():
        if emoji in owned_themes:
            kb.add(InlineKeyboardButton(f"{'✅' if emoji == active_theme else '❌'} {name} {emoji}", callback_data=f"set_theme_{emoji}"))
    for emoji, name in EFFECTS.items():
        if emoji in owned_effects:
            kb.add(InlineKeyboardButton(f"{'✅' if emoji == active_effect else '❌'} {name} {emoji}", callback_data=f"set_effect_{emoji}"))
    for combo, name in COMBOS.items():
        if combo in owned_combos:
            kb.add(InlineKeyboardButton(f"{'✅' if combo[0]==active_theme and combo[1]==active_effect else '❌'} {name} {combo}", callback_data=f"set_combo_{combo}"))
    for lang, name in LANGUAGES.items():
        if lang != "normal" and lang in owned_languages:
            kb.add(InlineKeyboardButton(f"{'✅' if lang == active_language else '❌'} {name}", callback_data=f"set_language_{lang}"))
    kb.add(InlineKeyboardButton("❌ Снять эффект", callback_data="remove_effect"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_shop"))
    return kb

def admin_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton("💰 Выдать монеты"),
        KeyboardButton("🔻 Забрать монеты"),
        KeyboardButton("👥 Все пользователи"),
        KeyboardButton("📢 Рассылка"),
        KeyboardButton("🔙 Назад")
    )
    return kb

# ========== ИГРЫ ==========
def dice_game_play(m, uid, num, mn, mx, win_exact_min, win_exact_max):
    lang = get_user(uid).get("active_language", "normal")
    try:
        bet = int(m.text)
        if bet < mn or bet > mx:
            bot.send_message(uid, f"❌ {mn}–{mx}")
            return
        if not remove_coins(uid, 1):
            bot.send_message(uid, get_phrase(lang, "no_coins"))
            return
        rolls = [random.randint(1,6) for _ in range(num)]
        total = sum(rolls)
        if bet == total:
            win = random.randint(win_exact_min, win_exact_max)
            add_coins(uid, win)
            bot.send_message(uid, f"🎲 {total}. {get_phrase(lang, 'win').format(win)}")
        else:
            bot.send_message(uid, f"🎲 {total}. {get_phrase(lang, 'lose').format(1)}")
        complete_task(uid, f"dice{num}")
    except:
        bot.send_message(uid, "❌ Введи число")

def dice_luck_play(m, uid):
    lang = get_user(uid).get("active_language", "normal")
    try:
        if not remove_coins(uid, 2):
            bot.send_message(uid, get_phrase(lang, "no_coins"))
            return
        rolls = [random.randint(1,6) for _ in range(3)]
        total = sum(rolls)
        if total >= 15:
            add_coins(uid, 10)
            bot.send_message(uid, f"🎲💰 {total}. {get_phrase(lang, 'win').format(10)}")
        else:
            bot.send_message(uid, f"🎲💰 {total}. {get_phrase(lang, 'lose').format(2)}")
        complete_task(uid, "diceluck")
    except:
        bot.send_message(uid, "❌ Ошибка")

def gamble_number_play(m, uid):
    lang = get_user(uid).get("active_language", "normal")
    try:
        bet = int(m.text)
        if bet < 1 or bet > 20:
            bot.send_message(uid, "❌ 1–20")
            return
        if not remove_coins(uid, 1):
            bot.send_message(uid, get_phrase(lang, "no_coins"))
            return
        secret = random.randint(1,20)
        if bet == secret:
            win = random.randint(5,12)
            add_coins(uid, win)
            bot.send_message(uid, f"🔢 {secret}. {get_phrase(lang, 'win').format(win)}")
        else:
            bot.send_message(uid, f"🔢 {secret}. {get_phrase(lang, 'lose').format(1)}")
        complete_task(uid, "number")
    except:
        bot.send_message(uid, "❌ Введи число")

def gamble_rps_play(m, uid):
    lang = get_user(uid).get("active_language", "normal")
    choice = m.text.lower()
    if choice not in ["камень","ножницы","бумага"]:
        bot.send_message(uid, "❌ камень/ножницы/бумага")
        return
    if not remove_coins(uid, 1):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    bot_choice = random.choice(["камень","ножницы","бумага"])
    if choice == bot_choice:
        add_coins(uid, 2)
        bot.send_message(uid, get_phrase(lang, "draw"))
    elif (choice=="камень" and bot_choice=="ножницы") or (choice=="ножницы" and bot_choice=="бумага") or (choice=="бумага" and bot_choice=="камень"):
        win = random.randint(3,7)
        add_coins(uid, win)
        bot.send_message(uid, get_phrase(lang, "win").format(win))
    else:
        bot.send_message(uid, get_phrase(lang, "lose").format(1))
    complete_task(uid, "rps")

def gamble_cards_play(m, uid):
    lang = get_user(uid).get("active_language", "normal")
    try:
        ch = int(m.text)
        if ch < 1 or ch > 5:
            bot.send_message(uid, "❌ 1–5")
            return
        if not remove_coins(uid, 1):
            bot.send_message(uid, get_phrase(lang, "no_coins"))
            return
        if ch == 5:
            add_coins(uid, 10)
            bot.send_message(uid, f"🎴 *ДЖОКЕР!* {get_phrase(lang, 'win').format(10)}", parse_mode="Markdown")
        else:
            bot.send_message(uid, f"🎴 Масть... {get_phrase(lang, 'lose').format(1)}")
        complete_task(uid, "cards")
    except:
        bot.send_message(uid, "❌ Введи число")

def gamble_slots_play(m, uid):
    lang = get_user(uid).get("active_language", "normal")
    try:
        if not remove_coins(uid, 1):
            bot.send_message(uid, get_phrase(lang, "no_coins"))
            return
        r = [random.choice(["🍒","🍊","🍋","🔔","💎","7️⃣"]) for _ in range(3)]
        if r[0]==r[1]==r[2]=="7️⃣":
            win = 50
        elif r[0]==r[1]==r[2]:
            win = 20
        elif r[0]==r[1] or r[1]==r[2] or r[0]==r[2]:
            win = 5
        else:
            win = 0
        if win:
            add_coins(uid, win)
            bot.send_message(uid, f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n🎉 +{win}💰", parse_mode="Markdown")
        else:
            bot.send_message(uid, f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n💀 -1💰", parse_mode="Markdown")
        complete_task(uid, "slots")
    except:
        bot.send_message(uid, "❌ Ошибка")

def gamble_rps2_play(m, uid):
    lang = get_user(uid).get("active_language", "normal")
    ch = m.text.lower()
    if ch not in ["камень","мешок","монета"]:
        bot.send_message(uid, "❌ камень/мешок/монета")
        return
    if not remove_coins(uid, 1):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    bot_ch = random.choice(["камень","мешок","монета"])
    rules = {"камень":"мешок","мешок":"монета","монета":"камень"}
    if ch == bot_ch:
        add_coins(uid, 2)
        bot.send_message(uid, get_phrase(lang, "draw"))
    elif rules[ch] == bot_ch:
        win = random.randint(3,7)
        add_coins(uid, win)
        bot.send_message(uid, get_phrase(lang, "win").format(win))
    else:
        bot.send_message(uid, get_phrase(lang, "lose").format(1))
    complete_task(uid, "rps2")

def gamble_color_play(m, uid):
    lang = get_user(uid).get("active_language", "normal")
    ch = m.text.lower()
    if ch not in ["красный","чёрный"]:
        bot.send_message(uid, "❌ красный или чёрный")
        return
    if not remove_coins(uid, 1):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    color = random.choice(["🔴 красный","⚫ чёрный"])
    user_color = "красный" if "красн" in ch else "чёрный"
    if user_color in color:
        add_coins(uid, 3)
        bot.send_message(uid, f"🎯 {color}. {get_phrase(lang, 'win').format(3)}")
    else:
        bot.send_message(uid, f"🎯 {color}. {get_phrase(lang, 'lose').format(1)}")
    complete_task(uid, "color")

def gamble_highlow_play(m, uid, first):
    lang = get_user(uid).get("active_language", "normal")
    ch = m.text.lower()
    if ch not in ["выше","ниже"]:
        bot.send_message(uid, "❌ выше или ниже")
        return
    if not remove_coins(uid, 1):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    second = random.randint(1,10)
    if (ch=="выше" and second>first) or (ch=="ниже" and second<first):
        win = random.randint(4,8)
        add_coins(uid, win)
        bot.send_message(uid, f"📈 {first}→{second}. {get_phrase(lang, 'win').format(win)}")
    elif second == first:
        add_coins(uid, 2)
        bot.send_message(uid, f"📈 {first}→{second}. Ничья! +2💰")
    else:
        bot.send_message(uid, f"📈 {first}→{second}. {get_phrase(lang, 'lose').format(1)}")
    complete_task(uid, "highlow")

def gamble_roulette_play(uid):
    lang = get_user(uid).get("active_language", "normal")
    if not remove_coins(uid, 5):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    if random.randint(1,6) == 1:
        bot.send_message(uid, "🔫 *Русская рулетка*\n💀 БАХ! -5💰", parse_mode="Markdown")
    else:
        add_coins(uid, 25)
        bot.send_message(uid, f"🔫 *Русская рулетка*\n🎉 ЩЁЛК! {get_phrase(lang, 'win').format(25)}", parse_mode="Markdown")
    complete_task(uid, "roulette")

def gamble_hotcold_play(m, uid):
    lang = get_user(uid).get("active_language", "normal")
    g = hotcold_games.get(uid)
    if not g:
        return
    try:
        guess = int(m.text)
        if guess < 1 or guess > 100:
            bot.send_message(uid, "❌ 1–100")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_hotcold_play(m, uid))
            return
        g["attempts"] += 1
        diff = abs(guess - g["number"])
        if guess == g["number"]:
            add_coins(uid, 15)
            bot.send_message(uid, f"🎉 Угадал! {g['number']} за {g['attempts']} попыток! +15💰")
            del hotcold_games[uid]
            complete_task(uid, "hotcold")
        elif g["attempts"] >= 3:
            bot.send_message(uid, f"❌ Не угадал. Было {g['number']}. -1💰")
            remove_coins(uid, 1)
            del hotcold_games[uid]
        else:
            if diff <= 10:
                bot.send_message(uid, f"🔥 Горячо! Осталось {3-g['attempts']} попытки")
            elif diff <= 30:
                bot.send_message(uid, f"🌡️ Тепло... Осталось {3-g['attempts']} попытки")
            else:
                bot.send_message(uid, f"❄️ Холодно... Осталось {3-g['attempts']} попытки")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_hotcold_play(m, uid))
    except:
        bot.send_message(uid, "❌ Введи число")

def gamble_bullscows_play(m, uid):
    lang = get_user(uid).get("active_language", "normal")
    g = bullscows_games.get(uid)
    if not g:
        return
    guess = m.text.strip()
    if len(guess) != 4 or not guess.isdigit() or len(set(guess)) != 4:
        bot.send_message(uid, "❌ 4 цифры, все разные")
        bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_bullscows_play(m, uid))
        return
    if not remove_coins(uid, 2):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        del bullscows_games[uid]
        return
    g["attempts"] += 1
    bulls = sum(1 for i in range(4) if guess[i] == g["secret"][i])
    cows = sum(1 for i in range(4) if guess[i] in g["secret"] and guess[i] != g["secret"][i])
    if bulls == 4:
        add_coins(uid, 20)
        bot.send_message(uid, f"🎉 Угадал! {g['secret']} за {g['attempts']} попыток! +20💰")
        del bullscows_games[uid]
        complete_task(uid, "bullscows")
    else:
        bot.send_message(uid, f"🐂 Быки: {bulls}, 🐄 Коровы: {cows}")
        bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_bullscows_play(m, uid))

def gamble_evenodd_play(m, uid):
    lang = get_user(uid).get("active_language", "normal")
    ch = m.text.lower()
    if ch not in ["чётное","нечётное","четное","нечетное"]:
        bot.send_message(uid, "❌ чётное или нечётное")
        return
    if not remove_coins(uid, 1):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    num = random.randint(1,10)
    is_even = num % 2 == 0
    correct = "чётное" if is_even else "нечётное"
    if (ch in ["чётное","четное"] and is_even) or (ch in ["нечётное","нечетное"] and not is_even):
        win = random.randint(3,5)
        add_coins(uid, win)
        bot.send_message(uid, f"🎲 {num} ({correct}). {get_phrase(lang, 'win').format(win)}")
    else:
        bot.send_message(uid, f"🎲 {num} ({correct}). {get_phrase(lang, 'lose').format(1)}")
    complete_task(uid, "evenodd")

# ========== ГРУППОВЫЕ ФУНКЦИИ ==========
@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "команды")
def group_commands(m):
    bot.send_message(m.chat.id, 
        "📋 *Команды группы:*\n"
        "• топ — топ игроков\n"
        "• подарок @user 10 — подарить монеты\n"
        "• бонус — групповой бонус (+5💰 всем, раз в 6 ч)\n"
        "• статистика — статистика группы\n\n"
        "🎲 *Групповые игры:*\n"
        "• 1 кубик | 2 кубика | 3 кубика\n"
        "• кости на удачу | угадай число | камень-ножницы\n"
        "• слоты | камень-мешок-монета | угадай цвет\n"
        "• выше/ниже | русская рулетка | чет/нечет\n"
        "• горячо/холодно", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "топ")
def group_top(m):
    top = top_players(5)
    if not top:
        bot.send_message(m.chat.id, "📊 Нет данных")
        return
    text = "🏆 *Топ-5:*\n"
    for i, (uid, name, coins) in enumerate(top, 1):
        text += f"{i}. {name or uid[:8]} — {coins}💰\n"
    bot.send_message(m.chat.id, text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower().startswith("подарить"))
def group_gift(m):
    parts = m.text.split()
    if len(parts) != 3:
        bot.send_message(m.chat.id, "❌ Формат: подарок @username 10")
        return
    target = parts[1].replace("@", "").lower()
    try:
        amount = int(parts[2])
    except:
        bot.send_message(m.chat.id, "❌ Сумма числом")
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
        bot.send_message(m.chat.id, f"❌ @{target} не найден")
        return
    if not remove_coins(m.from_user.id, amount):
        bot.send_message(m.chat.id, f"❌ У тебя нет {amount}💰")
        return
    add_coins(target_uid, amount)
    bot.send_message(m.chat.id, f"✅ @{m.from_user.username} подарил {amount}💰 @{target}")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "бонус")
def group_bonus(m):
    chat_id = m.chat.id
    now = datetime.now()
    if chat_id in group_bonus_tracker and group_bonus_tracker[chat_id] > now - timedelta(hours=6):
        rem = timedelta(hours=6) - (now - group_bonus_tracker[chat_id])
        hours = rem.seconds // 3600
        minutes = (rem.seconds % 3600) // 60
        bot.send_message(chat_id, f"⏳ Бонус через {hours}ч {minutes}мин")
        return
    group_bonus_tracker[chat_id] = now
    bot.send_message(chat_id, "🎁 *Групповой бонус!* Все получили +5💰", parse_mode="Markdown")
    for uid in all_users_list():
        try:
            add_coins(int(uid), 5)
        except:
            pass

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "статистика")
def group_stats(m):
    total, coins, avg, _ = global_stats()
    bot.send_message(m.chat.id, f"📊 *Статистика*\n👥 {total}\n💰 {coins}\n📈 {avg:.2f}", parse_mode="Markdown")

# Групповые игры
@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "1 кубик")
def g_dice1(m):
    roll = random.randint(1,6)
    group_game_sessions[m.from_user.id] = {"game": "dice", "roll": roll, "num": 1}
    bot.send_message(m.chat.id, f"🎲 @{m.from_user.username} кинул {roll}. Кто больше?")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "2 кубика")
def g_dice2(m):
    roll = random.randint(2,12)
    group_game_sessions[m.from_user.id] = {"game": "dice", "roll": roll, "num": 2}
    bot.send_message(m.chat.id, f"🎲 @{m.from_user.username} кинул {roll}. Кто больше?")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "3 кубика")
def g_dice3(m):
    roll = random.randint(3,18)
    group_game_sessions[m.from_user.id] = {"game": "dice", "roll": roll, "num": 3}
    bot.send_message(m.chat.id, f"🎲 @{m.from_user.username} кинул {roll}. Кто больше?")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "кости на удачу")
def g_luck(m):
    roll = random.randint(3,18)
    group_game_sessions[m.from_user.id] = {"game": "luck", "roll": roll}
    bot.send_message(m.chat.id, f"🎲💰 @{m.from_user.username} кинул {roll}. Кто больше?")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "угадай число")
def g_guess(m):
    num = random.randint(1,20)
    group_game_sessions[m.from_user.id] = {"game": "guess", "number": num}
    bot.send_message(m.chat.id, f"🔢 @{m.from_user.username} начал. Число 1–20. Угадайте!")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "камень-ножницы")
def g_rps(m):
    bot_choice = random.choice(["камень","ножницы","бумага"])
    group_game_sessions[m.from_user.id] = {"game": "rps", "bot_choice": bot_choice}
    bot.send_message(m.chat.id, f"✂️ @{m.from_user.username} против бота. Пиши 'камень', 'ножницы' или 'бумага'")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "слоты")
def g_slots(m):
    r = [random.choice(["🍒","🍊","🍋","🔔","💎","7️⃣"]) for _ in range(3)]
    win = 0
    if r[0]==r[1]==r[2]=="7️⃣":
        win = 50
    elif r[0]==r[1]==r[2]:
        win = 20
    elif r[0]==r[1] or r[1]==r[2] or r[0]==r[2]:
        win = 5
    if win:
        add_coins(m.from_user.id, win)
        bot.send_message(m.chat.id, f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n🎉 @{m.from_user.username} выиграл {win}💰!")
    else:
        bot.send_message(m.chat.id, f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n💀 Проигрыш")
    complete_task(m.from_user.id, "slots")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "камень-мешок-монета")
def g_rps2(m):
    bot_choice = random.choice(["камень","мешок","монета"])
    group_game_sessions[m.from_user.id] = {"game": "rps2", "bot_choice": bot_choice}
    bot.send_message(m.chat.id, f"💎 @{m.from_user.username} против бота. Пиши 'камень', 'мешок' или 'монета'")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "угадай цвет")
def g_color(m):
    color = random.choice(["🔴 красный","⚫ чёрный"])
    group_game_sessions[m.from_user.id] = {"game": "color", "color": color}
    bot.send_message(m.chat.id, f"🎯 @{m.from_user.username} угадывает цвет. Пиши 'красный' или 'чёрный'")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "выше/ниже")
def g_highlow(m):
    first = random.randint(1,10)
    group_game_sessions[m.from_user.id] = {"game": "highlow", "first": first}
    bot.send_message(m.chat.id, f"📈 @{m.from_user.username} играет. Число {first}. Следующее *выше* или *ниже*?", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "русская рулетка")
def g_roulette(m):
    if random.randint(1,6) == 1:
        remove_coins(m.from_user.id, 5)
        bot.send_message(m.chat.id, f"🔫 @{m.from_user.username} проиграл 5💰 в русской рулетке!")
    else:
        add_coins(m.from_user.id, 25)
        bot.send_message(m.chat.id, f"🔫 @{m.from_user.username} выиграл 25💰 в русской рулетке!")
    complete_task(m.from_user.id, "roulette")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "чет/нечет")
def g_evenodd(m):
    num = random.randint(1,10)
    is_even = num % 2 == 0
    group_game_sessions[m.from_user.id] = {"game": "evenodd", "number": num, "is_even": is_even}
    bot.send_message(m.chat.id, f"🎲 @{m.from_user.username} угадывает. Число *чётное* или *нечётное*?", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "горячо/холодно")
def g_hotcold(m):
    number = random.randint(1,100)
    group_game_sessions[m.from_user.id] = {"game": "hotcold", "number": number, "attempts": 0}
    bot.send_message(m.chat.id, f"🔥 @{m.from_user.username} начал. Число 1–100, 3 попытки!")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"])
def group_message_handler(m):
    chat_id = m.chat.id
    text = m.text.lower()
    from_uid = m.from_user.id
    if from_uid in group_game_sessions:
        g = group_game_sessions[from_uid]
        if g["game"] == "dice":
            try:
                roll = random.randint(1,6) if g["num"] == 1 else random.randint(2,12) if g["num"] == 2 else random.randint(3,18)
                if roll > g["roll"]:
                    add_coins(from_uid, 2)
                    bot.send_message(chat_id, f"🎉 @{m.from_user.username} победил! +2💰")
                elif roll < g["roll"]:
                    bot.send_message(chat_id, f"💀 @{m.from_user.username} проиграл")
                else:
                    bot.send_message(chat_id, f"🤝 Ничья")
                del group_game_sessions[from_uid]
            except:
                pass
        elif g["game"] == "luck":
            try:
                roll = random.randint(3,18)
                if roll > g["roll"]:
                    add_coins(from_uid, 2)
                    bot.send_message(chat_id, f"🎉 @{m.from_user.username} победил! +2💰")
                else:
                    bot.send_message(chat_id, f"💀 @{m.from_user.username} проиграл")
                del group_game_sessions[from_uid]
            except:
                pass
        elif g["game"] == "guess":
            try:
                guess = int(text)
                if guess == g["number"]:
                    add_coins(from_uid, 5)
                    bot.send_message(chat_id, f"🎉 @{m.from_user.username} угадал число {g['number']}! +5💰")
                    del group_game_sessions[from_uid]
            except:
                pass
        elif g["game"] == "rps":
            if text in ["камень","ножницы","бумага"]:
                if text == g["bot_choice"]:
                    add_coins(from_uid, 2)
                    bot.send_message(chat_id, f"🤝 Ничья! +2💰")
                elif (text=="камень" and g["bot_choice"]=="ножницы") or (text=="ножницы" and g["bot_choice"]=="бумага") or (text=="бумага" and g["bot_choice"]=="камень"):
                    win = random.randint(3,7)
                    add_coins(from_uid, win)
                    bot.send_message(chat_id, f"🎉 Победа! +{win}💰")
                else:
                    bot.send_message(chat_id, f"💀 Поражение")
                complete_task(from_uid, "rps")
                del group_game_sessions[from_uid]
        elif g["game"] == "rps2":
            if text in ["камень","мешок","монета"]:
                rules = {"камень":"мешок","мешок":"монета","монета":"камень"}
                if text == g["bot_choice"]:
                    add_coins(from_uid, 2)
                    bot.send_message(chat_id, f"🤝 Ничья! +2💰")
                elif rules[text] == g["bot_choice"]:
                    win = random.randint(3,7)
                    add_coins(from_uid, win)
                    bot.send_message(chat_id, f"🎉 Победа! +{win}💰")
                else:
                    bot.send_message(chat_id, f"💀 Поражение")
                complete_task(from_uid, "rps2")
                del group_game_sessions[from_uid]
        elif g["game"] == "color":
            if text in ["красный","чёрный"]:
                user = "красный" if "красн" in text else "чёрный"
                if user in g["color"]:
                    add_coins(from_uid, 3)
                    bot.send_message(chat_id, f"🎯 {g['color']}. Угадал! +3💰")
                else:
                    bot.send_message(chat_id, f"🎯 {g['color']}. Не угадал")
                complete_task(from_uid, "color")
                del group_game_sessions[from_uid]
        elif g["game"] == "highlow":
            if text in ["выше","ниже"]:
                second = random.randint(1,10)
                if (text=="выше" and second>g["first"]) or (text=="ниже" and second<g["first"]):
                    win = random.randint(4,8)
                    add_coins(from_uid, win)
                    bot.send_message(chat_id, f"📈 {g['first']}→{second}. Угадал! +{win}💰")
                elif second == g["first"]:
                    add_coins(from_uid, 2)
                    bot.send_message(chat_id, f"📈 Ничья! +2💰")
                else:
                    bot.send_message(chat_id, f"📈 Не угадал")
                complete_task(from_uid, "highlow")
                del group_game_sessions[from_uid]
        elif g["game"] == "evenodd":
            if text in ["чётное","нечётное","четное","нечетное"]:
                user = text in ["чётное","четное"]
                if user == g["is_even"]:
                    win = random.randint(3,5)
                    add_coins(from_uid, win)
                    bot.send_message(chat_id, f"🎲 Число {g['number']}. Угадал! +{win}💰")
                else:
                    bot.send_message(chat_id, f"🎲 Число {g['number']}. Не угадал")
                complete_task(from_uid, "evenodd")
                del group_game_sessions[from_uid]
        elif g["game"] == "hotcold":
            try:
                guess = int(text)
                g["attempts"] += 1
                diff = abs(guess - g["number"])
                if guess == g["number"]:
                    add_coins(from_uid, 15)
                    bot.send_message(chat_id, f"🎉 @{m.from_user.username} угадал {g['number']}! +15💰")
                    complete_task(from_uid, "hotcold")
                    del group_game_sessions[from_uid]
                elif g["attempts"] >= 3:
                    bot.send_message(chat_id, f"❌ Не угадал. Было {g['number']}")
                    del group_game_sessions[from_uid]
                else:
                    if diff <= 10:
                        bot.send_message(chat_id, f"🔥 Горячо! Осталось {3-g['attempts']} попытки")
                    elif diff <= 30:
                        bot.send_message(chat_id, f"🌡️ Тепло... Осталось {3-g['attempts']} попытки")
                    else:
                        bot.send_message(chat_id, f"❄️ Холодно... Осталось {3-g['attempts']} попытки")
            except:
                pass

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
        bot.send_message(uid, "🌍 *Выбери регион:*", reply_markup=region_keyboard(), parse_mode="Markdown")
    else:
        bot.send_message(uid, f"🎉 *Добро пожаловать!*\n\n{format_profile(uid)}", reply_markup=main_keyboard(uid), parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text in REGIONS)
def save_region(m):
    uid = m.chat.id
    update_user(uid, region=m.text)
    bot.send_message(uid, f"✅ Регион *{m.text}* сохранён!", parse_mode="Markdown")
    bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def handle_buttons(m):
    uid = m.chat.id
    text = m.text
    u = get_user(uid)
    theme = u.get("active_theme", "🎲")
    lang = u.get("active_language", "normal")

    if f"{theme} Игры" in text or "Игры" in text:
        bot.send_message(uid, "🎮 *Выбери игру:*", reply_markup=games_keyboard(), parse_mode="Markdown")
    elif f"{theme} Магазин" in text or "Магазин" in text:
        shop_keyboard(uid)
    elif f"{theme} Профиль" in text or "Профиль" in text:
        bot.send_message(uid, format_profile(uid), parse_mode="Markdown")
    elif get_phrase(lang, 'bonus_word') in text or "Бонус" in text:
        if can_take_bonus(uid):
            add_coins(uid, 10)
            update_user(uid, last_bonus=datetime.now().isoformat())
            bot.send_message(uid, get_phrase(lang, "bonus"), parse_mode="Markdown")
        else:
            bot.send_message(uid, get_phrase(lang, "already_bonus"), parse_mode="Markdown")
    elif f"{theme} Рефералы" in text or "Рефералы" in text:
        bot.send_message(uid, f"👥 *Рефералы*\n📎 {get_referral_link(uid)}\n👥 Приглашено: {get_referral_stats(uid)}", parse_mode="Markdown")
    elif f"{theme} Вопрос" in text or "Вопрос" in text:
        bot.send_message(uid, "✍️ Напиши вопрос:")
        waiting_for_question[uid] = True
    elif f"{theme} Команды" in text or "Команды" in text:
        bot.send_message(uid, "📋 *Команды:*\n🎮 Игры\n🛒 Магазин\n👤 Профиль\n🎁 Бонус\n👥 Рефералы\n❓ Вопрос\n💰 Пассивный доход\n👑 Кланы\n🏆 Топ игроков\n📊 Статистика", parse_mode="Markdown")
    elif "Пассивный доход" in text:
        businesses = get_user_businesses(uid)
        if not businesses:
            kb = InlineKeyboardMarkup(row_width=1)
            for name, d in BUSINESSES.items():
                kb.add(InlineKeyboardButton(f"{name} ({d['price']}💰)", callback_data=f"buy_business_{name}"))
            bot.send_message(uid, "🏭 *Пассивный доход*\nВыбери ферму для покупки:", reply_markup=kb, parse_mode="Markdown")
        else:
            kb = InlineKeyboardMarkup(row_width=2)
            for b in businesses:
                kb.add(InlineKeyboardButton(f"📊 {b['business_type']}", callback_data=f"select_business_{b['business_type']}"))
            bot.send_message(uid, "🏭 *Твои фермы*\nВыбери для управления:", reply_markup=kb, parse_mode="Markdown")
    elif "Кланы" in text:
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
            bot.send_message(uid, txt, reply_markup=kb, parse_mode="Markdown")
            return
        bot.send_message(uid, "👑 *Кланы*", reply_markup=kb, parse_mode="Markdown")
    elif "Топ игроков" in text:
        top = top_players(10)
        msg = "🏆 *Топ-10 игроков:*\n"
        for i, (uid, name, coins) in enumerate(top, 1):
            msg += f"{i}. {name or uid[:8]} — {coins}💰\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
    elif "Статистика" in text:
        total, coins, avg, top = global_stats()
        bot.send_message(uid, f"📊 *Глобальная статистика*\n👥 Всего игроков: {total}\n💰 Всего монет: {coins}\n📈 Средний баланс: {avg:.2f}\n\n🏆 *Топ-10:*\n{top}", parse_mode="Markdown")
    elif f"{theme} 🔧 Админ" in text and uid == ADMIN_ID:
        admin_panel(uid)
    elif uid == ADMIN_ID and text in ["💰 Выдать монеты","🔻 Забрать монеты","👥 Все пользователи","📢 Рассылка","🔙 Назад"]:
        admin_commands(uid, text)
    elif waiting_for_question.get(uid):
        forward_question(uid, text)
        waiting_for_question[uid] = False
    else:
        bot.send_message(uid, "❌ Используй кнопки меню 👇")

def admin_panel(uid):
    bot.send_message(uid, "🔧 *Админ-панель*", reply_markup=admin_keyboard(), parse_mode="Markdown")

def admin_commands(uid, text):
    if text == "💰 Выдать монеты":
        bot.send_message(uid, "Введи ID и сумму: `123456789 100`", parse_mode="Markdown")
        bot.register_next_step_handler_by_chat_id(uid, process_admin_add)
    elif text == "🔻 Забрать монеты":
        bot.send_message(uid, "Введи ID и сумму: `123456789 50`", parse_mode="Markdown")
        bot.register_next_step_handler_by_chat_id(uid, process_admin_remove)
    elif text == "👥 Все пользователи":
        users = all_users_list()
        msg = "👥 *Пользователи:*\n"
        for u in users[:30]:
            msg += f"🆔 {u} — {get_user(u)['coins']}💰\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
    elif text == "📢 Рассылка":
        bot.send_message(uid, "Введи сообщение:")
        bot.register_next_step_handler_by_chat_id(uid, broadcast_message)
    elif text == "🔙 Назад":
        bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")

def process_admin_add(m):
    uid = m.chat.id
    try:
        tid, amt = m.text.split()
        add_coins(int(tid), int(amt))
        bot.send_message(uid, f"✅ Выдано {amt}💰 {tid}")
    except:
        bot.send_message(uid, "❌ Ошибка")

def process_admin_remove(m):
    uid = m.chat.id
    try:
        tid, amt = m.text.split()
        if remove_coins(int(tid), int(amt)):
            bot.send_message(uid, f"✅ Забрано {amt}💰 у {tid}")
        else:
            bot.send_message(uid, f"❌ У {tid} нет {amt}💰")
    except:
        bot.send_message(uid, "❌ Ошибка")

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
    bot.send_message(ADMIN_ID, f"✅ Отправлено {sent}")

def forward_question(uid, q):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✍️ Ответить", callback_data=f"answer_{uid}"))
    bot.send_message(ADMIN_ID, f"📩 *Вопрос от* `{uid}`:\n{q}", reply_markup=kb, parse_mode="Markdown")

@bot.message_handler(commands=['take_reward'])
def take_reward_cmd(m):
    uid = m.chat.id
    rew = take_task_reward(uid)
    if rew:
        bot.send_message(uid, f"🎁 +{rew}💰 за задание!")
        bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
    else:
        bot.send_message(uid, "❌ Задание не выполнено")

@bot.message_handler(commands=['collect'])
def collect_cmd(m):
    uid = m.chat.id
    args = m.text.split()
    if len(args) > 1:
        biz_type = " ".join(args[1:])
        earned = collect_income(uid, biz_type)
        if earned:
            bot.send_message(uid, f"💾 Собрано {earned}💰 с {biz_type}!")
        else:
            bot.send_message(uid, f"⏳ На {biz_type} ничего не накопилось")
    else:
        businesses = get_user_businesses(uid)
        if businesses:
            kb = InlineKeyboardMarkup(row_width=2)
            for b in businesses:
                kb.add(InlineKeyboardButton(f"📊 {b['business_type']}", callback_data=f"select_business_{b['business_type']}"))
            bot.send_message(uid, "🏭 *Твои фермы*\nВыбери для сбора:", reply_markup=kb, parse_mode="Markdown")
        else:
            bot.send_message(uid, "❌ У тебя нет ферм. Купи их в разделе 'Пассивный доход'")

# ========== CALLBACK ==========
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    uid = call.message.chat.id
    data = call.data

    if data == "back_main":
        bot.edit_message_text("Меню", uid, call.message.message_id)
        bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
    elif data == "back_shop":
        shop_keyboard(uid)
    elif data == "shop_themes":
        bot.edit_message_text("🎨 *Темы*", uid, call.message.message_id, reply_markup=shop_themes_keyboard(uid), parse_mode="Markdown")
    elif data == "shop_effects":
        bot.edit_message_text("✨ *Эффекты*", uid, call.message.message_id, reply_markup=shop_effects_keyboard(uid), parse_mode="Markdown")
    elif data == "shop_combos":
        bot.edit_message_text("🔥 *Комбинации*", uid, call.message.message_id, reply_markup=shop_combos_keyboard(uid), parse_mode="Markdown")
    elif data == "shop_languages":
        bot.edit_message_text("💬 *Языки*", uid, call.message.message_id, reply_markup=shop_languages_keyboard(uid), parse_mode="Markdown")
    elif data == "my_items":
        bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")

    elif data.startswith("buy_theme_"):
        theme = data.split("_")[2]
        price = THEMES_PRICE.get(theme, 20)
        if remove_coins(uid, price):
            add_owned_item(uid, 'theme', theme, call)
            bot.edit_message_text("🎨 *Темы*", uid, call.message.message_id, reply_markup=shop_themes_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет", show_alert=True)
    elif data.startswith("buy_effect_"):
        effect = data.split("_")[2]
        price = EFFECTS_PRICE.get(effect, 30)
        if remove_coins(uid, price):
            add_owned_item(uid, 'effect', effect, call)
            bot.edit_message_text("✨ *Эффекты*", uid, call.message.message_id, reply_markup=shop_effects_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет", show_alert=True)
    elif data.startswith("buy_combo_"):
        combo = data.split("_")[2]
        price = COMBOS_PRICE.get(combo, 500)
        if remove_coins(uid, price):
            add_owned_item(uid, 'combo', combo, call)
            bot.edit_message_text("🔥 *Комбинации*", uid, call.message.message_id, reply_markup=shop_combos_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет", show_alert=True)
    elif data.startswith("buy_language_"):
        lang = data.split("_")[2]
        price = LANGUAGES_PRICE.get(lang, 200)
        if remove_coins(uid, price):
            add_owned_item(uid, 'language', lang, call)
            bot.edit_message_text("💬 *Языки*", uid, call.message.message_id, reply_markup=shop_languages_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет", show_alert=True)

    elif data.startswith("set_theme_"):
        theme = data.split("_")[2]
        if set_active_theme(uid, theme, call):
            bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет такой темы", show_alert=True)
    elif data.startswith("set_effect_"):
        effect = data.split("_")[2]
        if set_active_effect(uid, effect, call):
            bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет эффекта", show_alert=True)
    elif data.startswith("set_combo_"):
        combo = data.split("_")[2]
        if set_active_combo(uid, combo, call):
            bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет комбинации", show_alert=True)
    elif data.startswith("set_language_"):
        lang = data.split("_")[2]
        if set_active_language(uid, lang, call):
            bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет языка", show_alert=True)
    elif data == "remove_effect":
        update_user(uid, active_effect=None)
        bot.answer_callback_query(call.id, "❌ Эффект снят", show_alert=True)
        bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
        bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")

    elif data.startswith("dice_"):
        if data == "dice_1":
            bot.send_message(uid, "🎲 Введи число от 1 до 6:")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: dice_game_play(m, uid, 1, 1, 6, 2, 5))
        elif data == "dice_2":
            bot.send_message(uid, "🎲🎲 Введи сумму от 2 до 12:")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: dice_game_play(m, uid, 2, 2, 12, 4, 10))
        elif data == "dice_3":
            bot.send_message(uid, "🎲🎲🎲 Введи сумму от 3 до 18:")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: dice_game_play(m, uid, 3, 3, 18, 8, 15))
        elif data == "dice_luck":
            bot.send_message(uid, "🎲💰 Кости на удачу (3 кубика, сумма ≥15). Ставка 2💰. Готов? Напиши 'да'")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: dice_luck_play(m, uid))
    elif data.startswith("gamble_"):
        if data == "gamble_number":
            bot.send_message(uid, "🔢 Введи число от 1 до 20:")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_number_play(m, uid))
        elif data == "gamble_rps":
            bot.send_message(uid, "✂️ камень, ножницы, бумага:")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_rps_play(m, uid))
        elif data == "gamble_cards":
            bot.send_message(uid, "🎴 *Карты и Джокер*\n1️⃣♠️ 2️⃣♥️ 3️⃣♣️ 4️⃣♦️ 5️⃣🃏\nВведи номер (1–5):", parse_mode="Markdown")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_cards_play(m, uid))
        elif data == "gamble_slots":
            gamble_slots_play(call.message, uid)
        elif data == "gamble_rps2":
            bot.send_message(uid, "💎 *Камень-мешок-монета*\nВыбери: камень, мешок, монета", parse_mode="Markdown")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_rps2_play(m, uid))
        elif data == "gamble_color":
            bot.send_message(uid, "🎯 *Угадай цвет*\n🔴 Красный или ⚫ Чёрный?", parse_mode="Markdown")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_color_play(m, uid))
        elif data == "gamble_highlow":
            first = random.randint(1,10)
            bot.send_message(uid, f"📈 *Выше/Ниже*\nТекущее число: {first}\nСледующее будет *выше* или *ниже*?", parse_mode="Markdown")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_highlow_play(m, uid, first))
        elif data == "gamble_roulette":
            gamble_roulette_play(uid)
        elif data == "gamble_hotcold":
            number = random.randint(1,100)
            hotcold_games[uid] = {"number": number, "attempts": 0}
            bot.send_message(uid, "🔥 *Горячо/Холодно*\nЧисло 1–100. 3 попытки!", parse_mode="Markdown")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_hotcold_play(m, uid))
        elif data == "gamble_bullscows":
            digits = random.sample("0123456789",4)
            if digits[0] == "0":
                digits[0], digits[1] = digits[1], digits[0]
            secret = "".join(digits)
            bullscows_games[uid] = {"secret": secret, "attempts": 0}
            bot.send_message(uid, "🎯 *Быки и коровы*\n4-значное число без повторений!", parse_mode="Markdown")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_bullscows_play(m, uid))
        elif data == "gamble_evenodd":
            bot.send_message(uid, "🎲 *Чет/Нечет*\nЧисло 1–10, угадай чётное или нечётное", parse_mode="Markdown")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_evenodd_play(m, uid))

    elif data.startswith("buy_business_"):
        biz = data.replace("buy_business_", "")
        buy_business(uid, biz, call)
        businesses = get_user_businesses(uid)
        if businesses:
            kb = InlineKeyboardMarkup(row_width=2)
            for b in businesses:
                kb.add(InlineKeyboardButton(f"📊 {b['business_type']}", callback_data=f"select_business_{b['business_type']}"))
            bot.edit_message_text("🏭 *Твои фермы*", uid, call.message.message_id, reply_markup=kb, parse_mode="Markdown")
        else:
            bot.edit_message_text("🏭 *Пассивный доход*", uid, call.message.message_id, parse_mode="Markdown")
    elif data.startswith("select_business_"):
        biz = data.replace("select_business_", "")
        info = get_business_info(uid, biz)
        if info:
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("📈 +💰 (апгрейд)", callback_data=f"upgrade_amount_{biz}"))
            kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data=f"upgrade_speed_{biz}"))
            kb.add(InlineKeyboardButton("💾 Собрать", callback_data=f"collect_business_{biz}"))
            kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_businesses"))
            bot.edit_message_text(info, uid, call.message.message_id, reply_markup=kb, parse_mode="Markdown")
    elif data.startswith("upgrade_amount_"):
        biz = data.replace("upgrade_amount_", "")
        buy_amount_buffer[uid] = biz
        bot.send_message(uid, "💰 Сколько уровней апгрейда купить? (1–100)")
        bot.register_next_step_handler_by_chat_id(uid, lambda m: process_amount_upgrade(m, uid, biz, call))
    elif data.startswith("upgrade_speed_"):
        biz = data.replace("upgrade_speed_", "")
        upgrade_business_speed(uid, biz, call)
        info = get_business_info(uid, biz)
        if info:
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("📈 +💰 (апгрейд)", callback_data=f"upgrade_amount_{biz}"))
            kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data=f"upgrade_speed_{biz}"))
            kb.add(InlineKeyboardButton("💾 Собрать", callback_data=f"collect_business_{biz}"))
            kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_businesses"))
            bot.edit_message_text(info, uid, call.message.message_id, reply_markup=kb, parse_mode="Markdown")
    elif data.startswith("collect_business_"):
        biz = data.replace("collect_business_", "")
        collect_income(uid, biz, call)
        info = get_business_info(uid, biz)
        if info:
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("📈 +💰 (апгрейд)", callback_data=f"upgrade_amount_{biz}"))
            kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data=f"upgrade_speed_{biz}"))
            kb.add(InlineKeyboardButton("💾 Собрать", callback_data=f"collect_business_{biz}"))
            kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_businesses"))
            bot.edit_message_text(info, uid, call.message.message_id, reply_markup=kb, parse_mode="Markdown")
    elif data == "back_businesses":
        businesses = get_user_businesses(uid)
        if businesses:
            kb = InlineKeyboardMarkup(row_width=2)
            for b in businesses:
                kb.add(InlineKeyboardButton(f"📊 {b['business_type']}", callback_data=f"select_business_{b['business_type']}"))
            bot.edit_message_text("🏭 *Твои фермы*", uid, call.message.message_id, reply_markup=kb, parse_mode="Markdown")
        else:
            bot.edit_message_text("🏭 *Пассивный доход*", uid, call.message.message_id, parse_mode="Markdown")

    elif data == "clan_create":
        bot.send_message(uid, "📝 *Создание клана*\nВведи название и эмодзи: `Воины ⚔️`", parse_mode="Markdown")
        bot.register_next_step_handler_by_chat_id(uid, lambda m: process_clan_create(m, uid))
    elif data == "clan_join":
        bot.send_message(uid, "🔍 Введи ID клана:")
        bot.register_next_step_handler_by_chat_id(uid, lambda m: process_clan_join(m, uid))
    elif data == "clan_leave":
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM clan_members WHERE user_id = %s", (str(uid),))
        conn.commit()
        cur.close()
        conn.close()
        bot.answer_callback_query(call.id, "✅ Вы вышли из клана", show_alert=True)
        bot.edit_message_text("👑 Кланы", uid, call.message.message_id, parse_mode="Markdown")
    elif data == "clan_top":
        top = top_clans(10)
        if not top:
            text = "🏆 Топ кланов пуст"
        else:
            text = "🏆 *Топ кланов:*\n"
            for i, (cid, name, emoji, members, coins) in enumerate(top, 1):
                text += f"{i}. {emoji} {name} — 👥{members}, 💰{coins}💰\n"
        bot.edit_message_text(text, uid, call.message.message_id, parse_mode="Markdown")

    elif data.startswith("answer_"):
        uid_q = data.split("_")[1]
        bot.send_message(ADMIN_ID, f"✍️ Ответ для {uid_q}:")
        bot.register_next_step_handler(call.message, lambda m: send_answer(m, uid_q))

def process_amount_upgrade(m, uid, biz_type, call):
    try:
        levels = int(m.text)
        if levels < 1 or levels > 100:
            bot.send_message(uid, "❌ От 1 до 100")
            return
        upgrade_business_amount(uid, biz_type, call, levels)
        info = get_business_info(uid, biz_type)
        if info:
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("📈 +💰 (апгрейд)", callback_data=f"upgrade_amount_{biz_type}"))
            kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data=f"upgrade_speed_{biz_type}"))
            kb.add(InlineKeyboardButton("💾 Собрать", callback_data=f"collect_business_{biz_type}"))
            kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_businesses"))
            bot.edit_message_text(info, uid, call.message.message_id, reply_markup=kb, parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ Введи число")

def process_clan_create(m, uid):
    parts = m.text.strip().split()
    if len(parts) < 2:
        bot.send_message(uid, "❌ Нужно название и эмодзи")
        return
    name = " ".join(parts[:-1])[:20]
    emoji = parts[-1]
    ok, msg = create_clan(uid, name, emoji)
    bot.send_message(uid, msg, parse_mode="Markdown")
    if ok:
        bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")

def process_clan_join(m, uid):
    try:
        cid = int(m.text.strip())
        ok, msg = join_clan(uid, cid)
        bot.send_message(uid, msg, parse_mode="Markdown")
        if ok:
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ Введи число")

def send_answer(m, target_id):
    if m.chat.id != ADMIN_ID:
        return
    bot.send_message(int(target_id), f"📬 *Ответ:*\n{m.text}", parse_mode="Markdown")
    bot.send_message(ADMIN_ID, f"✅ Ответ отправлен {target_id}")

if __name__ == "__main__":
    print("✅ ФИНАЛЬНЫЙ БОТ ЗАПУЩЕН!")
    print("📊 50 тем, 50 эффектов, 25 комбинаций, 10 языков, 30 игр, 10 ферм")
    bot.infinity_polling(skip_pending=True)
