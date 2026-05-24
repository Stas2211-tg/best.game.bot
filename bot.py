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
            task_reward_taken BOOLEAN DEFAULT FALSE
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
            user_id TEXT PRIMARY KEY,
            business_type TEXT,
            amount_level INTEGER DEFAULT 1,
            speed_level INTEGER DEFAULT 1,
            last_collect TIMESTAMP DEFAULT NOW()
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

# ========== ТЕМЫ (200) ==========
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
    "⚽": "Футбольная", "🎾": "Теннисная", "🥊": "Боксёрская", "😊": "Радостная",
    "😢": "Грустная", "😡": "Злая", "😱": "Страшная", "😎": "Крутая",
    "🥰": "Влюблённая", "🤣": "Смешная", "😴": "Сонная", "🤯": "Ошеломляющая",
    "🥳": "Праздничная", "😇": "Ангельская", "👿": "Демоническая", "🤡": "Клоунская",
    "🎃": "Хэллоуинская", "👨‍🍳": "Поварская", "👩‍⚕️": "Врачебная", "👨‍🏫": "Учительская",
    "👩‍💻": "Программистская", "👨‍🌾": "Фермерская", "👩‍🎨": "Художническая", "👨‍🚀": "Космонавта",
    "👩‍✈️": "Лётная", "👨‍🔧": "Инженерная", "👩‍🔬": "Лабораторная", "🐺": "Волчья",
    "🦊": "Лисья", "🐻": "Медвежья", "🐼": "Панды", "🐨": "Коалы",
    "🦁": "Львиная", "🐯": "Тигриная", "🐒": "Обезьянья", "🦅": "Орлиная",
    "🐬": "Дельфинья", "🦋": "Бабочка", "🐝": "Пчела", "🐞": "Божья коровка",
    "🦀": "Краб", "🐠": "Рыбка", "🐙": "Осьминог", "🦑": "Кальмар",
    "🐪": "Верблюд", "🐘": "Слон", "🦒": "Жираф", "🦓": "Зебра",
    "🦍": "Горилла", "🐊": "Крокодил", "🐢": "Черепаха", "🦎": "Ящерица",
    "🐍": "Змея", "🦚": "Павлин", "🦜": "Попугай", "🐧": "Пингвин",
    "🦉": "Сова", "🦇": "Летучая мышь", "🌹": "Роза", "🌻": "Подсолнух",
    "🌵": "Кактус", "🍄": "Гриб", "🌿": "Трава", "🍃": "Лист",
    "🍂": "Осень", "🍁": "Клён", "🌾": "Рис", "🌽": "Кукуруза",
    "🍎": "Яблоко", "🍊": "Апельсин", "🍋": "Лимон", "🍇": "Виноград",
    "🍒": "Вишня", "🍑": "Персик", "🥝": "Киви", "🥥": "Кокос",
    "🥑": "Авокадо", "🍆": "Баклажан", "🥔": "Картофель", "🥕": "Морковь",
    "🥦": "Брокколи", "🥩": "Мясо", "🍔": "Бургер", "🍕": "Пицца",
    "🌮": "Тако", "🥗": "Салат", "🍣": "Суши", "🍜": "Лапша",
    "🍰": "Торт", "🍪": "Печенье", "🍩": "Пончик", "🍫": "Шоколад",
    "🍬": "Конфета", "🍭": "Леденец", "🎂": "Пирожное", "🥧": "Пирог",
    "🍿": "Попкорн", "🥨": "Крендель", "🥪": "Сэндвич", "🥙": "Суп",
    "🍲": "Карри", "🍛": "Паста", "🥫": "Консервы", "🥟": "Пельмени",
    "🥠": "Клецки", "🥡": "Еда", "⚙️": "Шестерня", "🔧": "Гаечный ключ",
    "🔨": "Молоток", "🗝️": "Ключ", "🧲": "Магнит", "🔬": "Микроскоп",
    "🔭": "Телескоп", "📡": "Спутник", "💡": "Лампочка"
}

THEMES_PRICE = {emoji: random.randint(20, 300) if emoji != "🎲" else 0 for emoji in THEMES}
THEMES_PRICE["🎲"] = 0

# ========== ЭФФЕКТЫ (200) ==========
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
    "🦾": "Кибернетический", "😊": "Радость", "😢": "Грусть", "😡": "Гнев",
    "😱": "Страх", "😎": "Крутость", "🥰": "Любовь", "🤣": "Смех",
    "😴": "Сон", "🤯": "Шок", "🥳": "Праздник", "👨‍🍳": "Повар",
    "👩‍⚕️": "Врач", "👨‍🏫": "Учитель", "👩‍💻": "Программист", "👨‍🌾": "Фермер",
    "👩‍🎨": "Художник", "👨‍🚀": "Астронавт", "👩‍✈️": "Пилот", "👨‍🔧": "Инженер",
    "👩‍🔬": "Учёный", "🌌": "Галактика", "🪐": "Планета", "☄️": "Комета",
    "🌠": "Звездопад", "🕳️": "Чёрная дыра", "🔭": "Телескоп", "🛰️": "Спутник",
    "🚀": "Ракета", "👨‍🚀": "Астронавт2", "👩‍🚀": "Астронавтка2", "🍃": "Лист2",
    "🌿": "Трава2", "🍂": "Осень2", "🍁": "Клён2", "🌺": "Цветок",
    "🌻": "Подсолнух2", "🌵": "Кактус2", "🍄": "Гриб2", "🐚": "Ракушка",
    "🪨": "Камень", "🎮": "Геймпад", "🕹️": "Джойстик", "🎲": "Кубик",
    "🎯": "Мишень", "🎰": "Слот", "🃏": "Джокер", "♠️": "Пики",
    "♥️": "Черви", "♣️": "Трефы", "♦️": "Бубны"
}
EFFECTS_PRICE = {emoji: random.randint(25, 150) for emoji in EFFECTS}

# ========== КОМБИНАЦИИ (50) ==========
COMBOS = {
    "👑⚡": "Королевская сила", "🚀🐉": "Космический дракон", "❄️👻": "Ледяной призрак",
    "💵👑": "Денежный король", "🏆🔥": "Легендарный феникс", "💡👿": "Неоновый демон",
    "🪄🐉": "Магический дракон", "⚔️👻": "Военный призрак", "🎸🌟": "Рок-звезда",
    "😇🌈": "Ангельская радуга", "🌌👑": "Космический правитель", "⭐⚔️": "Звёздный воин",
    "❄️🐉": "Ледяной дракон", "🔥🐦": "Огненный феникс", "🌑👿": "Тёмный властелин",
    "✨😇": "Светлый ангел", "🌊👑": "Морской царь", "⛈️⚡": "Грозовой бог",
    "🪨👹": "Каменный великан", "👻👑": "Призрачный король", "🌈🦄": "Радужный единорог",
    "🔥🐉": "Огненный дракон", "❄️🧊": "Ледяной король", "🌪️🌀": "Повелитель ветра",
    "💎👑": "Алмазный король", "🌟🌙": "Звёздная ночь", "☀️🔥": "Солнечный огонь",
    "🌙🌑": "Лунная тьма", "💡⚡": "Электрический удар", "🎸🔥": "Рок-огонь",
    "🧙🔮": "Великий маг", "🧝🏹": "Лесной эльф", "🧛🩸": "Кровавый вампир",
    "👻🕯️": "Призрачный свет", "🤖⚙️": "Механический воин", "👾🛸": "Инопланетный гость",
    "🔥⚔️": "Пламенный меч", "❄️🛡️": "Ледяной щит", "🌙🔮": "Лунная магия",
    "☀️🗡️": "Солнечный клинок", "🦅👑": "Орлиный король", "🐺⚡": "Волчья молния",
    "🐉🔥": "Драконий гнев", "⭐🌠": "Звёздный дождь", "🌑🗡️": "Теневой клинок",
    "✨🌟": "Светлый луч", "⛈️🌪️": "Грозовой удар", "🌍🪨": "Землетрясение",
    "🌊🌋": "Цунами", "☄️🕳️": "Метеорит"
}
COMBOS_PRICE = {combo: random.randint(400, 1500) for combo in COMBOS}

# ========== ЯЗЫКИ (20) ==========
LANGUAGES = {
    "normal": "Обычный", "royal": "👑 Королевский", "sassy": "🔥 Дерзкий",
    "evil": "😈 Злой", "mystic": "🎭 Таинственный", "robot": "🤖 Роботизированный",
    "poetic": "📜 Поэтический", "childish": "🧸 Детский", "brutal": "💪 Брутальный",
    "intelligent": "🎓 Интеллигентный", "sarcastic": "🙃 Саркастичный", "anime": "🎌 Аниме",
    "pirate": "🏴‍☠️ Пиратский", "cowboy": "🤠 Ковбойский", "medieval": "🛡️ Средневековый",
    "future": "🔮 Будущего", "minimal": "⬜ Минималист", "emoji": "😀 Эмодзи-стиль",
    "silent": "🤫 Молчаливый", "yoda": "🧘 Мастер Йода"
}
LANGUAGES_PRICE = {
    "royal": 200, "sassy": 250, "evil": 300, "mystic": 350, "robot": 500,
    "poetic": 220, "childish": 180, "brutal": 260, "intelligent": 240, "sarcastic": 280,
    "anime": 300, "pirate": 270, "cowboy": 260, "medieval": 310, "future": 340,
    "minimal": 200, "emoji": 400, "silent": 450, "yoda": 500
}

# ========== ФРАЗЫ ==========
def get_phrase(lang, key):
    p = {
        "normal": {"win": "🎉 Победа! +{}💰", "lose": "💀 Поражение. -{}💰", "draw": "🤝 Ничья! +2💰",
                   "welcome": "🎉 Добро пожаловать!", "bonus": "🎁 +10 монет!", "bonus_word": "🎁 Бонус",
                   "no_coins": "❌ Нет монет", "already_bonus": "⏳ Бонус уже получен",
                   "profile": "Профиль", "find": "Найти игрока", "games": "Игры", "shop": "Магазин",
                   "referrals": "Рефералы", "question": "Вопрос", "commands": "Все команды",
                   "admin": "Админ", "my_items": "Мои покупки", "back": "Назад"},
        "royal": {"win": "👑 Победа! +{}💰", "lose": "💎 Поражение. -{}💰", "draw": "🤝 Ничья! +2💰",
                  "welcome": "👑 Добро пожаловать!", "bonus": "🎁 Пожаловано 10 монет!", "bonus_word": "👑 Пожалование",
                  "no_coins": "❌ Нет монет", "already_bonus": "⏳ Бонус уже получен",
                  "profile": "Особа", "find": "Сыскать", "games": "Сыграть", "shop": "Лавка",
                  "referrals": "Подданные", "question": "Прошение", "commands": "Указы",
                  "admin": "Канцлер", "my_items": "Сокровища", "back": "Вернуться"},
        "sassy": {"win": "🎉 Угадал! +{}💰", "lose": "💀 Проиграл! -{}💰", "draw": "🤝 Ничья! +2💰",
                  "welcome": "🎉 О, новый игрок!", "bonus": "🎁 Держи 10💰!", "bonus_word": "🔥 Халява",
                  "no_coins": "❌ Нет монет!", "already_bonus": "⏳ Бонус уже был!",
                  "profile": "Поглядим", "find": "Кого ищем?", "games": "Замутим?", "shop": "Купи что-то",
                  "referrals": "Зови друзей", "question": "Чё надо?", "commands": "Чё умею?",
                  "admin": "Для своих", "my_items": "Моё добро", "back": "Вали отсюда"}
    }
    if lang not in p:
        return p["normal"].get(key, "")
    return p[lang].get(key, p["normal"].get(key, ""))

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

def format_profile(uid, target=None):
    u = get_user(target if target else uid)
    theme = u.get("active_theme", "🎲")
    effect = u.get("active_effect", "")
    effect_str = f" {effect}" if effect else ""
    region = u.get("region") or "❓"
    lang = LANGUAGES.get(u.get("active_language", "normal"), "Обычный")
    if not target:
        task = get_user_task(uid)
        task_status = "✅" if task["completed"] and not task["reward_taken"] else "❌" if not task["completed"] else "🎁"
        task_line = f"\n│  📋 Задание: {task['name']} {task_status}"
    else:
        task_line = ""
    return (f"┌─────────────────────┐\n"
            f"│  👤 *{u.get('username') or 'Игрок'}*{effect_str}\n"
            f"│  💰 Баланс: `{u['coins']}` монет\n"
            f"│  📍 Регион: {region}\n"
            f"│  🎨 Тема: {theme}\n"
            f"│  💬 Язык: {lang}{task_line}\n"
            f"└─────────────────────┘")

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
    cur.execute("INSERT INTO referrals (user_id, referrer_id) VALUES (%s, %s)", (str(new_uid), str(ref_id)))
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

# ========== ЗАДАНИЯ ==========
TASKS = [
    {"name": "🎲 1 кубик", "reward": 5, "game": "dice1"},
    {"name": "🎲🎲 2 кубика", "reward": 5, "game": "dice2"},
    {"name": "🎲🎲🎲 3 кубика", "reward": 8, "game": "dice3"},
    {"name": "🎲🎲🎲🎲🎲 5 кубиков", "reward": 10, "game": "dice5"},
    {"name": "🎲 x10 10 кубиков", "reward": 15, "game": "dice10"},
    {"name": "🎲💰 Кости на удачу", "reward": 12, "game": "diceluck"},
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
    {"name": "🎲 Чет/Нечет", "reward": 8, "game": "evenodd"},
    {"name": "🃏 Блэкджек", "reward": 20, "game": "blackjack"},
    {"name": "🎲 Покер на костях", "reward": 15, "game": "dicepoker"},
    {"name": "🍀 Клевер", "reward": 8, "game": "clover"},
    {"name": "💣 Мина", "reward": 12, "game": "mine"},
    {"name": "🎰 Джекпот", "reward": 25, "game": "jackpot"},
    {"name": "🎲 Свинья", "reward": 15, "game": "pig"},
    {"name": "🎲 Риск", "reward": 10, "game": "risk"},
    {"name": "🃑 Дурак", "reward": 15, "game": "fool"},
    {"name": "🃟 Меморина", "reward": 12, "game": "memory"},
    {"name": "🎲 Больше/Меньше", "reward": 8, "game": "moreless"},
    {"name": "🎲 Счастливое число", "reward": 8, "game": "luckynum"},
    {"name": "🎴 Пьяница", "reward": 10, "game": "drunkard"},
    {"name": "🎯 Угадай карту", "reward": 10, "game": "guesscard"}
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

# ========== МАГАЗИН ==========
def add_owned_item(uid, itype, iid):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO user_items (user_id, item_type, item_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", (str(uid), itype, iid))
    conn.commit()
    cur.close()
    conn.close()
    delete_user_cache(uid)

def is_owned(uid, itype, iid):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM user_items WHERE user_id=%s AND item_type=%s AND item_id=%s", (str(uid), itype, iid))
    r = cur.fetchone()
    cur.close()
    conn.close()
    return r is not None

def set_active_theme(uid, theme):
    if is_owned(uid, 'theme', theme):
        update_user(uid, active_theme=theme)
        return True
    return False

def set_active_effect(uid, effect):
    if is_owned(uid, 'effect', effect):
        update_user(uid, active_effect=effect)
        return True
    return False

def set_active_language(uid, lang):
    if lang == "normal" or is_owned(uid, 'language', lang):
        update_user(uid, active_language=lang)
        return True
    return False

def set_active_combo(uid, combo):
    if is_owned(uid, 'combo', combo) and len(combo) >= 2:
        set_active_theme(uid, combo[0])
        set_active_effect(uid, combo[1])
        return True
    return False

# ========== БИЗНЕС ==========
BUSINESSES = {
    "🌾 Ферма": {"price": 5000, "hourly_rate": 14},
    "⛏️ Шахта": {"price": 15000, "hourly_rate": 42},
    "🏭 Фабрика": {"price": 50000, "hourly_rate": 139},
    "💻 IT-компания": {"price": 200000, "hourly_rate": 556},
    "🚀 Космодром": {"price": 1000000, "hourly_rate": 2778}
}
SPEED_LEVELS = [60, 30, 15, 10, 5, 1]
AMOUNT_UPGRADE_COST = 1000

def get_business(uid):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM businesses WHERE user_id = %s", (str(uid),))
    b = cur.fetchone()
    cur.close()
    conn.close()
    return b

def get_business_amount(uid):
    b = get_business(uid)
    if not b:
        return 0, 0, 0
    d = BUSINESSES[b["business_type"]]
    iv = SPEED_LEVELS[b["speed_level"]-1]
    bonus = (b["amount_level"]-1)*50
    amt = int(d["hourly_rate"] * iv / 60) + bonus
    return amt, iv, int(amt * 60 / iv)

def get_pending_income(uid):
    b = get_business(uid)
    if not b:
        return 0
    amt, iv, _ = get_business_amount(uid)
    el = (datetime.now() - b["last_collect"]).total_seconds() / 60
    return int(el // iv) * amt

def collect_income(uid):
    b = get_business(uid)
    if not b:
        return 0
    amt, iv, _ = get_business_amount(uid)
    last = b["last_collect"]
    now = datetime.now()
    el = (now - last).total_seconds() / 60
    inter = int(el // iv)
    if inter == 0:
        return 0
    earn = inter * amt
    add_coins(uid, earn)
    new_last = last + timedelta(minutes=inter * iv)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE businesses SET last_collect = %s WHERE user_id = %s", (new_last, str(uid)))
    conn.commit()
    cur.close()
    conn.close()
    return earn

def create_business(uid, biz_type):
    if get_business(uid):
        return False, "❌ У тебя уже есть ферма!"
    price = BUSINESSES[biz_type]["price"]
    if not remove_coins(uid, price):
        return False, f"❌ Нужно {price}💰"
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO businesses (user_id, business_type) VALUES (%s,%s)", (str(uid), biz_type))
    conn.commit()
    cur.close()
    conn.close()
    return True, f"✅ Куплена {biz_type}!"

def upgrade_business_amount(uid):
    b = get_business(uid)
    if not b:
        return False, "❌ Нет фермы"
    if not remove_coins(uid, AMOUNT_UPGRADE_COST):
        return False, f"❌ Нужно {AMOUNT_UPGRADE_COST}💰"
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE businesses SET amount_level = amount_level+1 WHERE user_id = %s", (str(uid),))
    conn.commit()
    cur.close()
    conn.close()
    return True, "✅ Количество увеличено!"

def upgrade_business_speed(uid):
    b = get_business(uid)
    if not b:
        return False, "❌ Нет фермы"
    if b["speed_level"] >= len(SPEED_LEVELS):
        return False, "❌ Максимальная скорость!"
    price = int(BUSINESSES[b["business_type"]]["price"] * 0.5)
    if not remove_coins(uid, price):
        return False, f"❌ Нужно {price}💰"
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE businesses SET speed_level = speed_level+1 WHERE user_id = %s", (str(uid),))
    conn.commit()
    cur.close()
    conn.close()
    return True, "✅ Скорость увеличена!"

def get_business_info(uid):
    b = get_business(uid)
    if not b:
        text = "🏭 *Фермы/Бизнес*\n\n"
        for name, d in BUSINESSES.items():
            text += f"• {name}: {d['price']}💰 → {d['hourly_rate']}💰/час\n"
        text += "\n💰 Купи ферму для пассивного дохода!"
        return text
    amt, iv, hr = get_business_amount(uid)
    pending = get_pending_income(uid)
    speed_price = int(BUSINESSES[b["business_type"]]["price"] * 0.5)
    return (f"🏭 *{b['business_type']}*\n\n"
            f"📊 Уровень количества: {b['amount_level']}\n"
            f"💰 Доход за интервал: +{amt}💰\n"
            f"⏱️ Интервал: {iv} мин\n"
            f"📈 Примерно {hr}💰/час\n\n"
            f"💎 Накоплено: {pending}💰\n\n"
            f"🔧 *Апгрейды:*\n"
            f"📈 +50💰 к доходу — {AMOUNT_UPGRADE_COST}💰\n"
            f"⚡ Ускорить — {speed_price}💰\n\n"
            f"💾 Собрать доход — /collect")

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

def top_players(limit=10):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, username, coins FROM users ORDER BY coins DESC LIMIT %s", (limit,))
    return cur.fetchall()

REGIONS = ["🇷🇺 Россия", "🇺🇦 Украина", "🇧🇾 Беларусь", "🇰🇿 Казахстан", "🇦🇲 Армения", "🇬🇪 Грузия"]

def region_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(*[KeyboardButton(r) for r in REGIONS])
    return kb

# ========== КЛАВИАТУРЫ ==========
def main_keyboard(uid):
    u = get_user(uid)
    theme = u.get("active_theme", "🎲")
    lang = u.get("active_language", "normal")
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton(f"{theme} Кубики"),
        KeyboardButton(f"{theme} Игры"),
        KeyboardButton(f"{theme} Магазин"),
        KeyboardButton(f"{theme} Профиль"),
        KeyboardButton(f"{theme} Найти игрока"),
        KeyboardButton(f"{theme} {get_phrase(lang, 'bonus_word')}"),
        KeyboardButton(f"{theme} Рефералы"),
        KeyboardButton(f"{theme} Вопрос"),
        KeyboardButton(f"{theme} Все команды"),
        KeyboardButton(f"{theme} 💰 Пассивный доход"),
        KeyboardButton(f"{theme} 👑 Кланы"),
        KeyboardButton(f"{theme} 🏆 Топ игроков")
    )
    if uid == ADMIN_ID:
        kb.add(KeyboardButton(f"{theme} 🔧 Админ"))
    return kb

def dice_keyboard():
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("🎲 1 кубик", callback_data="dice_1"),
        InlineKeyboardButton("🎲🎲 2 кубика", callback_data="dice_2"),
        InlineKeyboardButton("🎲🎲🎲 3 кубика", callback_data="dice_3"),
        InlineKeyboardButton("🎲🎲🎲🎲🎲 5 кубиков", callback_data="dice_5"),
        InlineKeyboardButton("🎲 x10 10 кубиков", callback_data="dice_10"),
        InlineKeyboardButton("🎲💰 Кости на удачу", callback_data="dice_luck"),
        InlineKeyboardButton("🎲 Свинья", callback_data="game_pig"),
        InlineKeyboardButton("🎲 Риск", callback_data="game_risk"),
        InlineKeyboardButton("🎲 Больше/Меньше", callback_data="game_moreless"),
        InlineKeyboardButton("🎲 Покер на костях", callback_data="game_dicepoker"),
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
        InlineKeyboardButton("🔥 Горячо/Холодно", callback_data="gamble_hotcold"),
        InlineKeyboardButton("🎯 Быки и коровы", callback_data="gamble_bullscows"),
        InlineKeyboardButton("🎲 Чет/Нечет", callback_data="gamble_evenodd"),
        InlineKeyboardButton("🃏 Блэкджек", callback_data="game_blackjack"),
        InlineKeyboardButton("🃑 Дурак", callback_data="game_fool"),
        InlineKeyboardButton("🃟 Меморина", callback_data="game_memory"),
        InlineKeyboardButton("🎴 Пьяница", callback_data="game_drunkard"),
        InlineKeyboardButton("🎯 Угадай карту", callback_data="game_guesscard"),
        InlineKeyboardButton("🍀 Клевер", callback_data="game_clover"),
        InlineKeyboardButton("💣 Мина", callback_data="game_mine"),
        InlineKeyboardButton("🎰 Джекпот", callback_data="game_jackpot"),
        InlineKeyboardButton("🎲 Счастливое число", callback_data="game_luckynum"),
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
    owned = get_owned_items(uid, 'theme')
    kb = InlineKeyboardMarkup(row_width=2)
    for emoji, name in list(THEMES.items())[:50]:
        if emoji in owned:
            kb.add(InlineKeyboardButton(f"✅ {name} {emoji}", callback_data="no"))
        else:
            kb.add(InlineKeyboardButton(f"🎨 {name} {emoji} ({THEMES_PRICE[emoji]}💰)", callback_data=f"buy_theme_{emoji}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_shop"))
    return kb

def shop_effects_keyboard(uid):
    owned = get_owned_items(uid, 'effect')
    kb = InlineKeyboardMarkup(row_width=2)
    for emoji, name in list(EFFECTS.items())[:50]:
        if emoji in owned:
            kb.add(InlineKeyboardButton(f"✅ {name} {emoji}", callback_data="no"))
        else:
            kb.add(InlineKeyboardButton(f"✨ {name} {emoji} ({EFFECTS_PRICE[emoji]}💰)", callback_data=f"buy_effect_{emoji}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_shop"))
    return kb

def shop_combos_keyboard(uid):
    owned = get_owned_items(uid, 'combo')
    kb = InlineKeyboardMarkup(row_width=1)
    for combo, name in COMBOS.items():
        if combo in owned:
            kb.add(InlineKeyboardButton(f"✅ {name} {combo}", callback_data="no"))
        else:
            kb.add(InlineKeyboardButton(f"🔥 {name} {combo} ({COMBOS_PRICE[combo]}💰)", callback_data=f"buy_combo_{combo}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_shop"))
    return kb

def shop_languages_keyboard(uid):
    owned = get_owned_items(uid, 'language')
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
    owned_themes = get_owned_items(uid, 'theme')
    owned_effects = get_owned_items(uid, 'effect')
    owned_combos = get_owned_items(uid, 'combo')
    owned_languages = get_owned_items(uid, 'language')
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
        KeyboardButton("📊 Глобальная статистика"),
        KeyboardButton("📈 Топ игроков"),
        KeyboardButton("🔙 Назад")
    )
    return kb

# ========== ИГРЫ ==========
def dice_game(uid, num, mn, mx, win_exact_min, win_exact_max, win_near1_min=None, win_near1_max=None, win_near5_min=None, win_near5_max=None):
    bot.send_message(uid, f"🎲 *{num} кубик(а)*\nВведи сумму от {mn} до {mx}:", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: dice_game_play(m, uid, num, mn, mx, win_exact_min, win_exact_max, win_near1_min, win_near1_max, win_near5_min, win_near5_max))

def dice_game_play(m, uid, num, mn, mx, win_exact_min, win_exact_max, win_near1_min, win_near1_max, win_near5_min, win_near5_max):
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
        diff = abs(bet - total)
        rolls_str = " + ".join(map(str, rolls))
        if diff == 0:
            win = random.randint(win_exact_min, win_exact_max)
            add_coins(uid, win)
            bot.send_message(uid, f"🎲 {rolls_str} = {total}. {get_phrase(lang, 'win').format(win)}")
        elif win_near1_min and diff == 1:
            win = random.randint(win_near1_min, win_near1_max)
            add_coins(uid, win)
            bot.send_message(uid, f"🎲 {rolls_str} = {total}. Почти угадал! {get_phrase(lang, 'win').format(win)}")
        elif win_near5_min and 2 <= diff <= 5:
            win = random.randint(win_near5_min, win_near5_max)
            add_coins(uid, win)
            bot.send_message(uid, f"🎲 {rolls_str} = {total}. Близко! {get_phrase(lang, 'win').format(win)}")
        else:
            remove_coins(uid, 1)
            bot.send_message(uid, f"🎲 {rolls_str} = {total}. {get_phrase(lang, 'lose').format(2)}")
        complete_task(uid, f"dice{num}")
    except:
        bot.send_message(uid, "❌ Введи число")

def dice_luck_handler(uid):
    lang = get_user(uid).get("active_language", "normal")
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

def gamble_number_handler(uid):
    bot.send_message(uid, "🔢 Введи число от 1 до 20:")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_number_play(m, uid))

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
            remove_coins(uid, 1)
            bot.send_message(uid, f"🔢 {secret}. {get_phrase(lang, 'lose').format(2)}")
        complete_task(uid, "number")
    except:
        bot.send_message(uid, "❌ Введи число")

def gamble_rps_handler(uid):
    bot.send_message(uid, "✂️ камень, ножницы, бумага:")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_rps_play(m, uid))

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
        remove_coins(uid, 1)
        bot.send_message(uid, get_phrase(lang, "lose").format(2))
    complete_task(uid, "rps")

def gamble_cards_handler(uid):
    bot.send_message(uid, "🎴 *Карты и Джокер*\n1️⃣♠️ 2️⃣♥️ 3️⃣♣️ 4️⃣♦️ 5️⃣🃏\nВведи номер (1–5):", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_cards_play(m, uid))

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
            win = 10
            add_coins(uid, win)
            bot.send_message(uid, f"🎴 *ДЖОКЕР!* {get_phrase(lang, 'win').format(win)}", parse_mode="Markdown")
        else:
            remove_coins(uid, 1)
            bot.send_message(uid, f"🎴 Масть... {get_phrase(lang, 'lose').format(2)}")
        complete_task(uid, "cards")
    except:
        bot.send_message(uid, "❌ Введи число")

def gamble_slots_handler(uid):
    lang = get_user(uid).get("active_language", "normal")
    if not remove_coins(uid, 1):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    r = [random.choice(["🍒","🍊","🍋","🔔","💎","7️⃣"]) for _ in range(3)]
    if r[0]==r[1]==r[2]=="7️⃣":
        win = 50
        add_coins(uid, win)
        bot.send_message(uid, f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n🎉 ДЖЕКПОТ! {get_phrase(lang, 'win').format(win)}", parse_mode="Markdown")
    elif r[0]==r[1]==r[2]:
        win = 20
        add_coins(uid, win)
        bot.send_message(uid, f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n🎉 ТРИ В РЯД! {get_phrase(lang, 'win').format(win)}", parse_mode="Markdown")
    elif r[0]==r[1] or r[1]==r[2] or r[0]==r[2]:
        win = 5
        add_coins(uid, win)
        bot.send_message(uid, f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n🎉 ДВА В РЯД! {get_phrase(lang, 'win').format(win)}", parse_mode="Markdown")
    else:
        bot.send_message(uid, f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n💀 Ничего... -1💰", parse_mode="Markdown")
    complete_task(uid, "slots")

def gamble_rps2_handler(uid):
    bot.send_message(uid, "💎 *Камень-мешок-монета*\nВыбери: камень, мешок, монета", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_rps2_play(m, uid))

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
        remove_coins(uid, 1)
        bot.send_message(uid, get_phrase(lang, "lose").format(2))
    complete_task(uid, "rps2")

def gamble_color_handler(uid):
    bot.send_message(uid, "🎯 *Угадай цвет*\n🔴 Красный или ⚫ Чёрный?", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_color_play(m, uid))

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
        remove_coins(uid, 1)
        bot.send_message(uid, f"🎯 {color}. {get_phrase(lang, 'lose').format(2)}")
    complete_task(uid, "color")

def gamble_highlow_handler(uid):
    num = random.randint(1,10)
    bot.send_message(uid, f"📈 *Выше/Ниже*\nТекущее число: {num}\nСледующее будет *выше* или *ниже*?", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_highlow_play(m, uid, num))

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
        bot.send_message(uid, f"📈 {first} → {second}. {get_phrase(lang, 'win').format(win)}")
    elif second == first:
        add_coins(uid, 2)
        bot.send_message(uid, f"📈 {first} → {second}. Ничья! +2💰")
    else:
        remove_coins(uid, 1)
        bot.send_message(uid, f"📈 {first} → {second}. {get_phrase(lang, 'lose').format(2)}")
    complete_task(uid, "highlow")

def gamble_roulette_handler(uid):
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

def gamble_hotcold_handler(uid):
    number = random.randint(1,100)
    hotcold_games[uid] = {"number": number, "attempts": 0}
    bot.send_message(uid, "🔥 *Горячо/Холодно*\nЧисло 1–100. 3 попытки!", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_hotcold_play(m, uid))

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
            bot.send_message(uid, f"❌ Не угадал. Было {g['number']}. -2💰")
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

def gamble_bullscows_handler(uid):
    digits = random.sample("0123456789",4)
    if digits[0] == "0":
        digits[0], digits[1] = digits[1], digits[0]
    secret = "".join(digits)
    bullscows_games[uid] = {"secret": secret, "attempts": 0}
    bot.send_message(uid, "🎯 *Быки и коровы*\n4-значное число без повторений!", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_bullscows_play(m, uid))

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

def gamble_evenodd_handler(uid):
    bot.send_message(uid, "🎲 *Чет/Нечет*\nЧисло 1–10, угадай чётное или нечётное", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_evenodd_play(m, uid))

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
        remove_coins(uid, 1)
        bot.send_message(uid, f"🎲 {num} ({correct}). {get_phrase(lang, 'lose').format(2)}")
    complete_task(uid, "evenodd")

# ========== НОВЫЕ ИГРЫ (13 штук) ==========
def game_blackjack_handler(uid):
    bot.send_message(uid, "🃏 *Блэкджек*\nВведи ставку (мин 5💰):", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: game_blackjack_play(m, uid))

def game_blackjack_play(m, uid):
    lang = get_user(uid).get("active_language", "normal")
    try:
        bet = int(m.text)
        if bet < 5:
            bot.send_message(uid, "❌ Минимум 5💰")
            return
        if not remove_coins(uid, bet):
            bot.send_message(uid, get_phrase(lang, "no_coins"))
            return
        player = [random.randint(1,11), random.randint(1,11)]
        dealer = [random.randint(1,11)]
        if sum(player) == 21:
            win = bet * 2
            add_coins(uid, win)
            bot.send_message(uid, f"🃏 Блэкджек! +{win}💰")
        else:
            bot.send_message(uid, f"Твои карты: {player} ({sum(player)})\nКарты дилера: {dealer}")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: game_blackjack_step(m, uid, player, dealer, bet))
        complete_task(uid, "blackjack")
    except:
        bot.send_message(uid, "❌ Введи число")

def game_blackjack_step(m, uid, player, dealer, bet):
    lang = get_user(uid).get("active_language", "normal")
    ch = m.text.lower()
    if ch == "ещё":
        player.append(random.randint(1,11))
        if sum(player) > 21:
            bot.send_message(uid, f"Перебор! {player} = {sum(player)}. -{bet}💰")
        elif sum(player) == 21:
            add_coins(uid, bet*2)
            bot.send_message(uid, f"21! +{bet*2}💰")
        else:
            bot.send_message(uid, f"Твои карты: {player} = {sum(player)}")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: game_blackjack_step(m, uid, player, dealer, bet))
    elif ch == "хватит":
        while sum(dealer) < 17:
            dealer.append(random.randint(1,11))
        if sum(dealer) > 21 or sum(player) > sum(dealer):
            add_coins(uid, bet*2)
            bot.send_message(uid, f"Победа! {player} vs {dealer}. +{bet*2}💰")
        elif sum(player) == sum(dealer):
            add_coins(uid, bet)
            bot.send_message(uid, f"Ничья! {player} vs {dealer}. Возвращено {bet}💰")
        else:
            bot.send_message(uid, f"Поражение! {player} vs {dealer}. -{bet}💰")

def game_dicepoker_handler(uid):
    lang = get_user(uid).get("active_language", "normal")
    if not remove_coins(uid, 2):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    rolls = [random.randint(1,6) for _ in range(5)]
    counts = [rolls.count(i) for i in range(1,7)]
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
        bot.send_message(uid, f"🎲 {rolls}\nКомбинация! +{win}💰")
    else:
        bot.send_message(uid, f"🎲 {rolls}\nНичего... -2💰")
    complete_task(uid, "dicepoker")

def game_clover_handler(uid):
    lang = get_user(uid).get("active_language", "normal")
    if not remove_coins(uid, 1):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    r = random.randint(1,10)
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
        bot.send_message(uid, f"🍀 Тебе повезло! +{win}💰")
    else:
        bot.send_message(uid, f"🍀 Не повезло... -1💰")
    complete_task(uid, "clover")

def game_mine_handler(uid):
    lang = get_user(uid).get("active_language", "normal")
    if not remove_coins(uid, 2):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    mines = random.randint(1,6)
    bot.send_message(uid, f"💣 *Мина*\nВыбери ячейку (1–6):", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: game_mine_play(m, uid, mines))

def game_mine_play(m, uid, mines):
    lang = get_user(uid).get("active_language", "normal")
    try:
        choice = int(m.text)
        if choice < 1 or choice > 6:
            bot.send_message(uid, "❌ 1–6")
            return
        if choice == mines:
            bot.send_message(uid, f"💣 БАХ! Ты наступил на мину! -2💰")
        else:
            add_coins(uid, 10)
            bot.send_message(uid, f"✅ Повезло! +10💰")
        complete_task(uid, "mine")
    except:
        bot.send_message(uid, "❌ Введи число")

def game_jackpot_handler(uid):
    lang = get_user(uid).get("active_language", "normal")
    if not remove_coins(uid, 5):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    r = random.randint(1,100)
    if r == 1:
        win = 1000
    elif r <= 5:
        win = 100
    elif r <= 20:
        win = 50
    elif r <= 50:
        win = 20
    else:
        win = 0
    if win:
        add_coins(uid, win)
        bot.send_message(uid, f"🎰 *Джекпот!* +{win}💰", parse_mode="Markdown")
    else:
        bot.send_message(uid, f"🎰 Не повезло... -5💰")
    complete_task(uid, "jackpot")

def game_pig_handler(uid):
    lang = get_user(uid).get("active_language", "normal")
    if not remove_coins(uid, 1):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    score = 0
    while True:
        roll = random.randint(1,6)
        if roll == 1:
            bot.send_message(uid, f"🎲 Выпало 1! Ты теряешь всё. -1💰")
            return
        score += roll
        bot.send_message(uid, f"🎲 Выпало {roll}. Твой счёт: {score}. Бросаешь ещё? (да/нет)")
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_pig_step(m, uid, score))
        break

def game_pig_step(m, uid, score):
    lang = get_user(uid).get("active_language", "normal")
    ch = m.text.lower()
    if ch == "да":
        roll = random.randint(1,6)
        if roll == 1:
            bot.send_message(uid, f"🎲 Выпало 1! Ты теряешь всё. -1💰")
            return
        score += roll
        bot.send_message(uid, f"🎲 Выпало {roll}. Твой счёт: {score}. Бросаешь ещё? (да/нет)")
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_pig_step(m, uid, score))
    else:
        add_coins(uid, score)
        bot.send_message(uid, f"🎲 Ты собрал {score}💰!")
        complete_task(uid, "pig")

def game_risk_handler(uid):
    lang = get_user(uid).get("active_language", "normal")
    bot.send_message(uid, "🎲 *Риск*\nВведи ставку (мин 5💰):", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: game_risk_play(m, uid))

def game_risk_play(m, uid):
    lang = get_user(uid).get("active_language", "normal")
    try:
        bet = int(m.text)
        if bet < 5:
            bot.send_message(uid, "❌ Минимум 5💰")
            return
        if not remove_coins(uid, bet):
            bot.send_message(uid, get_phrase(lang, "no_coins"))
            return
        number = random.randint(1,6)
        bot.send_message(uid, f"Угадай число (1–6):")
        bot.register_next_step_handler_by_chat_id(uid, lambda m: game_risk_guess(m, uid, number, bet))
    except:
        bot.send_message(uid, "❌ Введи число")

def game_risk_guess(m, uid, number, bet):
    lang = get_user(uid).get("active_language", "normal")
    try:
        guess = int(m.text)
        if guess < 1 or guess > 6:
            bot.send_message(uid, "❌ 1–6")
            return
        if guess == number:
            add_coins(uid, bet*2)
            bot.send_message(uid, f"🎲 Выпало {number}. Угадал! +{bet*2}💰")
        else:
            bot.send_message(uid, f"🎲 Выпало {number}. Не угадал. -{bet}💰")
        complete_task(uid, "risk")
    except:
        bot.send_message(uid, "❌ Введи число")

def game_fool_handler(uid):
    lang = get_user(uid).get("active_language", "normal")
    if not remove_coins(uid, 2):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    cards = ["6","7","8","9","10","В","Д","К","Т"]
    player_card = random.choice(cards)
    bot_card = random.choice(cards)
    if cards.index(player_card) > cards.index(bot_card):
        win = 10
        add_coins(uid, win)
        bot.send_message(uid, f"🃑 Твоя карта: {player_card}, у бота: {bot_card}. Победа! +{win}💰")
    elif player_card == bot_card:
        add_coins(uid, 2)
        bot.send_message(uid, f"🃑 Ничья! +2💰")
    else:
        bot.send_message(uid, f"🃑 Твоя карта: {player_card}, у бота: {bot_card}. Поражение. -2💰")
    complete_task(uid, "fool")

def game_memory_handler(uid):
    lang = get_user(uid).get("active_language", "normal")
    if not remove_coins(uid, 1):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    numbers = [random.randint(1,10) for _ in range(5)]
    bot.send_message(uid, f"🃟 *Меморина*\nЗапомни числа: {numbers}\nВведи их через пробел:", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: game_memory_play(m, uid, numbers))

def game_memory_play(m, uid, numbers):
    lang = get_user(uid).get("active_language", "normal")
    try:
        guess = list(map(int, m.text.split()))
        if guess == numbers:
            add_coins(uid, 10)
            bot.send_message(uid, f"🎉 Идеально! +10💰")
        else:
            bot.send_message(uid, f"❌ Было {numbers}. -1💰")
        complete_task(uid, "memory")
    except:
        bot.send_message(uid, "❌ Введи 5 чисел")

def game_moreless_handler(uid):
    lang = get_user(uid).get("active_language", "normal")
    if not remove_coins(uid, 1):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    total = random.randint(2,12)
    bot.send_message(uid, f"🎲 Сумма двух кубиков: {total}. Следующая будет *больше* или *меньше*?", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: game_moreless_play(m, uid, total))

def game_moreless_play(m, uid, first):
    lang = get_user(uid).get("active_language", "normal")
    ch = m.text.lower()
    if ch not in ["больше","меньше"]:
        bot.send_message(uid, "❌ больше или меньше")
        return
    total = random.randint(2,12)
    if (ch == "больше" and total > first) or (ch == "меньше" and total < first):
        win = random.randint(4,8)
        add_coins(uid, win)
        bot.send_message(uid, f"🎲 {first} → {total}. Угадал! +{win}💰")
    elif total == first:
        add_coins(uid, 2)
        bot.send_message(uid, f"🎲 {first} → {total}. Ничья! +2💰")
    else:
        bot.send_message(uid, f"🎲 {first} → {total}. Не угадал. -1💰")
    complete_task(uid, "moreless")

def game_luckynum_handler(uid):
    lang = get_user(uid).get("active_language", "normal")
    if not remove_coins(uid, 1):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    number = random.randint(1,10)
    bot.send_message(uid, f"🎲 *Счастливое число*\nУгадай число (1–10):", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: game_luckynum_play(m, uid, number))

def game_luckynum_play(m, uid, number):
    lang = get_user(uid).get("active_language", "normal")
    try:
        guess = int(m.text)
        if guess < 1 or guess > 10:
            bot.send_message(uid, "❌ 1–10")
            return
        if guess == number:
            win = random.randint(5,10)
            add_coins(uid, win)
            bot.send_message(uid, f"🎲 Загадано {number}. Угадал! +{win}💰")
        else:
            bot.send_message(uid, f"🎲 Загадано {number}. Не угадал. -1💰")
        complete_task(uid, "luckynum")
    except:
        bot.send_message(uid, "❌ Введи число")

def game_drunkard_handler(uid):
    lang = get_user(uid).get("active_language", "normal")
    if not remove_coins(uid, 1):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    cards = ["6","7","8","9","10","В","Д","К","Т"]
    player = random.choice(cards)
    bot_card = random.choice(cards)
    if cards.index(player) > cards.index(bot_card):
        add_coins(uid, 4)
        bot.send_message(uid, f"🎴 {player} vs {bot_card}. Победа! +4💰")
    elif player == bot_card:
        add_coins(uid, 2)
        bot.send_message(uid, f"🎴 Ничья! +2💰")
    else:
        bot.send_message(uid, f"🎴 {player} vs {bot_card}. Поражение. -1💰")
    complete_task(uid, "drunkard")

def game_guesscard_handler(uid):
    lang = get_user(uid).get("active_language", "normal")
    if not remove_coins(uid, 1):
        bot.send_message(uid, get_phrase(lang, "no_coins"))
        return
    cards = ["♠️", "♥️", "♣️", "♦️"]
    card = random.choice(cards)
    bot.send_message(uid, f"🎯 *Угадай масть*\nКакая масть выпадет? {cards}", parse_mode="Markdown")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: game_guesscard_play(m, uid, card))

def game_guesscard_play(m, uid, card):
    lang = get_user(uid).get("active_language", "normal")
    ch = m.text.strip()
    if ch not in ["♠️", "♥️", "♣️", "♦️"]:
        bot.send_message(uid, "❌ ♠️ ♥️ ♣️ ♦️")
        return
    if ch == card:
        win = random.randint(5,10)
        add_coins(uid, win)
        bot.send_message(uid, f"🎯 Выпала {card}. Угадал! +{win}💰")
    else:
        bot.send_message(uid, f"🎯 Выпала {card}. Не угадал. -1💰")
    complete_task(uid, "guesscard")

# ========== ГРУППОВЫЕ ФУНКЦИИ ==========
@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "команды")
def group_commands(m):
    bot.send_message(m.chat.id, "📋 *Команды группы:*\n• топ\n• подарок @user 10\n• бонус\n• статистика\n• 1 кубик, 2 кубика, 3 кубика, 5 кубиков, 10 кубиков\n• кости на удачу\n• угадай число\n• камень-ножницы\n• слоты\n• камень-мешок-монета\n• угадай цвет\n• выше/ниже\n• русская рулетка\n• чет/нечет\n• горячо/холодно", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "топ")
def group_top(m):
    chat_id = m.chat.id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, coins, username FROM users ORDER BY coins DESC LIMIT 5")
    top = cur.fetchall()
    cur.close()
    conn.close()
    if not top:
        bot.send_message(chat_id, "📊 Нет данных")
        return
    text = "🏆 *Топ-5:*\n"
    for i, (uid, coins, name) in enumerate(top, 1):
        text += f"{i}. {name or uid[:8]} — {coins}💰\n"
    bot.send_message(chat_id, text, parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower().startswith("подарить"))
def group_gift(m):
    chat_id = m.chat.id
    from_uid = m.from_user.id
    parts = m.text.split()
    if len(parts) != 3:
        bot.send_message(chat_id, "❌ Формат: подарок @username 10")
        return
    target_name = parts[1].replace("@", "").lower()
    try:
        amount = int(parts[2])
    except:
        bot.send_message(chat_id, "❌ Сумма числом")
        return
    target_uid = None
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE username = %s", (target_name,))
    r = cur.fetchone()
    cur.close()
    conn.close()
    if r:
        target_uid = r[0]
    if not target_uid:
        bot.send_message(chat_id, f"❌ @{target_name} не найден")
        return
    if not remove_coins(from_uid, amount):
        bot.send_message(chat_id, f"❌ У тебя нет {amount}💰")
        return
    add_coins(target_uid, amount)
    bot.send_message(chat_id, f"✅ @{m.from_user.username} подарил {amount}💰 @{target_name}")

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

@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"] and m.text.lower() == "статистика")
def group_stats(m):
    chat_id = m.chat.id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    cur.execute("SELECT SUM(coins) FROM users")
    coins = cur.fetchone()[0] or 0
    cur.close()
    conn.close()
    avg = coins / total if total else 0
    bot.send_message(chat_id, f"📊 *Статистика*\n👥 {total}\n💰 {coins}\n📈 {avg:.2f}", parse_mode="Markdown")

# ========== ГРУППОВЫЕ ИГРЫ ==========
def group_game_start(m, game_name, handler):
    chat_id = m.chat.id
    from_uid = m.from_user.id
    if from_uid in group_game_sessions:
        bot.send_message(chat_id, "❌ Игра уже идёт")
        return
    handler(m, chat_id, from_uid)

def group_dice_game(m, chat_id, from_uid, num):
    roll = sum(random.randint(1,6) for _ in range(num))
    group_game_sessions[from_uid] = {"game": "dice", "roll": roll, "num": num}
    bot.send_message(chat_id, f"🎲 @{m.from_user.username} кинул {num} кубик(а), сумма {roll}. Кто хочет перебросить? Напишите '{m.text}'")

def group_luck_game(m, chat_id, from_uid):
    roll = sum(random.randint(1,6) for _ in range(3))
    group_game_sessions[from_uid] = {"game": "luck", "roll": roll}
    bot.send_message(chat_id, f"🎲💰 @{m.from_user.username} кинул 3 кубика, сумма {roll}. Кто больше?")

def group_guess_game(m, chat_id, from_uid):
    number = random.randint(1,20)
    group_game_sessions[from_uid] = {"game": "guess", "number": number}
    bot.send_message(chat_id, f"🔢 @{m.from_user.username} начал игру. Я загадал число 1–20. Угадайте!")

def group_rps_game(m, chat_id, from_uid):
    bot_choice = random.choice(["камень","ножницы","бумага"])
    group_game_sessions[from_uid] = {"game": "rps", "bot_choice": bot_choice}
    bot.send_message(chat_id, f"✂️ @{m.from_user.username} играет против бота. Напишите 'камень', 'ножницы' или 'бумага'")

def group_slots_game(m, chat_id, from_uid):
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
        add_coins(from_uid, win)
        bot.send_message(chat_id, f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n🎉 @{m.from_user.username} выиграл {win}💰!")
    else:
        bot.send_message(chat_id, f"🎰 |{r[0]}|{r[1]}|{r[2]}|\n💀 Проигрыш")
    complete_task(from_uid, "slots")

def group_rps2_game(m, chat_id, from_uid):
    bot_choice = random.choice(["камень","мешок","монета"])
    group_game_sessions[from_uid] = {"game": "rps2", "bot_choice": bot_choice}
    bot.send_message(chat_id, f"💎 @{m.from_user.username} играет против бота. Напишите 'камень', 'мешок' или 'монета'")

def group_color_game(m, chat_id, from_uid):
    color = random.choice(["🔴 красный","⚫ чёрный"])
    group_game_sessions[from_uid] = {"game": "color", "color": color}
    bot.send_message(chat_id, f"🎯 @{m.from_user.username} угадывает цвет. Напишите 'красный' или 'чёрный'")

def group_highlow_game(m, chat_id, from_uid):
    first = random.randint(1,10)
    group_game_sessions[from_uid] = {"game": "highlow", "first": first}
    bot.send_message(chat_id, f"📈 @{m.from_user.username} играет. Число {first}. Следующее *выше* или *ниже*?", parse_mode="Markdown")

def group_roulette_game(m, chat_id, from_uid):
    if random.randint(1,6) == 1:
        remove_coins(from_uid, 5)
        bot.send_message(chat_id, f"🔫 @{m.from_user.username} проиграл 5💰 в русской рулетке!")
    else:
        add_coins(from_uid, 25)
        bot.send_message(chat_id, f"🔫 @{m.from_user.username} выиграл 25💰 в русской рулетке!")
    complete_task(from_uid, "roulette")

def group_evenodd_game(m, chat_id, from_uid):
    number = random.randint(1,10)
    is_even = number % 2 == 0
    group_game_sessions[from_uid] = {"game": "evenodd", "number": number, "is_even": is_even}
    bot.send_message(chat_id, f"🎲 @{m.from_user.username} угадывает. Число *чётное* или *нечётное*?", parse_mode="Markdown")

def group_hotcold_game(m, chat_id, from_uid):
    number = random.randint(1,100)
    group_game_sessions[from_uid] = {"game": "hotcold", "number": number, "attempts": 0}
    bot.send_message(chat_id, f"🔥 @{m.from_user.username} начал. Число 1–100, 3 попытки!")

# Обработчики групповых игр
for game_name, num in [("1 кубик",1),("2 кубика",2),("3 кубика",3),("5 кубиков",5),("10 кубиков",10)]:
    @bot.message_handler(func=lambda m, n=num: m.chat.type in ["group","supergroup"] and m.text.lower() == game_name)
    def handler(m, n=num):
        group_dice_game(m, m.chat.id, m.from_user.id, n)

@bot.message_handler(func=lambda m: m.chat.type in ["group","supergroup"] and m.text.lower() == "кости на удачу")
def h_luck(m): group_luck_game(m, m.chat.id, m.from_user.id)
@bot.message_handler(func=lambda m: m.chat.type in ["group","supergroup"] and m.text.lower() == "угадай число")
def h_guess(m): group_guess_game(m, m.chat.id, m.from_user.id)
@bot.message_handler(func=lambda m: m.chat.type in ["group","supergroup"] and m.text.lower() == "камень-ножницы")
def h_rps(m): group_rps_game(m, m.chat.id, m.from_user.id)
@bot.message_handler(func=lambda m: m.chat.type in ["group","supergroup"] and m.text.lower() == "слоты")
def h_slots(m): group_slots_game(m, m.chat.id, m.from_user.id)
@bot.message_handler(func=lambda m: m.chat.type in ["group","supergroup"] and m.text.lower() == "камень-мешок-монета")
def h_rps2(m): group_rps2_game(m, m.chat.id, m.from_user.id)
@bot.message_handler(func=lambda m: m.chat.type in ["group","supergroup"] and m.text.lower() == "угадай цвет")
def h_color(m): group_color_game(m, m.chat.id, m.from_user.id)
@bot.message_handler(func=lambda m: m.chat.type in ["group","supergroup"] and m.text.lower() == "выше/ниже")
def h_highlow(m): group_highlow_game(m, m.chat.id, m.from_user.id)
@bot.message_handler(func=lambda m: m.chat.type in ["group","supergroup"] and m.text.lower() == "русская рулетка")
def h_roulette(m): group_roulette_game(m, m.chat.id, m.from_user.id)
@bot.message_handler(func=lambda m: m.chat.type in ["group","supergroup"] and m.text.lower() == "чет/нечет")
def h_evenodd(m): group_evenodd_game(m, m.chat.id, m.from_user.id)
@bot.message_handler(func=lambda m: m.chat.type in ["group","supergroup"] and m.text.lower() == "горячо/холодно")
def h_hotcold(m): group_hotcold_game(m, m.chat.id, m.from_user.id)

@bot.message_handler(func=lambda m: m.chat.type in ["group","supergroup"])
def group_msg_handler(m):
    chat_id = m.chat.id
    text = m.text.lower()
    from_uid = m.from_user.id
    if from_uid in group_game_sessions:
        g = group_game_sessions[from_uid]
        if g["game"] == "dice":
            try:
                roll = sum(random.randint(1,6) for _ in range(g["num"]))
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
                roll = sum(random.randint(1,6) for _ in range(3))
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

@bot.message_handler(commands=['collect'])
def collect_cmd(m):
    uid = m.chat.id
    earned = collect_income(uid)
    if earned:
        bot.send_message(uid, f"💾 Собрано {earned}💰")
    else:
        bot.send_message(uid, "⏳ Накоплений нет")

@bot.message_handler(commands=['take_reward'])
def take_reward_cmd(m):
    uid = m.chat.id
    rew = take_task_reward(uid)
    if rew:
        bot.send_message(uid, f"🎁 +{rew}💰 за задание!")
        bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
    else:
        bot.send_message(uid, "❌ Задание не выполнено")

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

    if f"{theme} Кубики" in text or "Кубики" in text:
        bot.send_message(uid, "🎲 *Выбери кубики:*", reply_markup=dice_keyboard(), parse_mode="Markdown")
    elif f"{theme} Игры" in text or "Игры" in text:
        bot.send_message(uid, "🎮 *Выбери игру:*", reply_markup=games_keyboard(), parse_mode="Markdown")
    elif f"{theme} Магазин" in text or "Магазин" in text:
        shop_keyboard(uid)
    elif f"{theme} Профиль" in text or "Профиль" in text:
        bot.send_message(uid, format_profile(uid), parse_mode="Markdown")
    elif f"{theme} Найти игрока" in text or "Найти игрока" in text:
        bot.send_message(uid, "✍️ Введи @username:")
        waiting_for_username[uid] = True
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
    elif f"{theme} Все команды" in text or "Все команды" in text:
        bot.send_message(uid, "📋 *Команды:*\n🎲 Кубики\n🎮 Игры\n🛒 Магазин\n👤 Профиль\n🔍 Найти игрока\n🎁 Бонус\n👥 Рефералы\n❓ Вопрос\n💰 Пассивный доход\n👑 Кланы\n🏆 Топ игроков", parse_mode="Markdown")
    elif "Пассивный доход" in text:
        info = get_business_info(uid)
        kb = InlineKeyboardMarkup(row_width=2)
        if not get_business(uid):
            for name, d in BUSINESSES.items():
                kb.add(InlineKeyboardButton(f"{name} ({d['price']}💰)", callback_data=f"buy_business_{name}"))
        else:
            kb.add(InlineKeyboardButton("📈 +50💰", callback_data="upgrade_amount"))
            kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data="upgrade_speed"))
            kb.add(InlineKeyboardButton("💾 Собрать", callback_data="collect_income"))
        bot.send_message(uid, info, reply_markup=kb, parse_mode="Markdown")
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
    elif f"{theme} 🔧 Админ" in text and uid == ADMIN_ID:
        admin_panel(uid)
    elif uid == ADMIN_ID and text in ["💰 Выдать монеты","🔻 Забрать монеты","👥 Все пользователи","📢 Рассылка","📊 Глобальная статистика","📈 Топ игроков","🔙 Назад"]:
        admin_commands(uid, text)
    elif waiting_for_question.get(uid):
        forward_question(uid, text)
        waiting_for_question[uid] = False
    elif waiting_for_username.get(uid):
        target = None
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM users WHERE username = %s", (text.replace("@","").lower(),))
        r = cur.fetchone()
        cur.close()
        conn.close()
        if r:
            target = r[0]
        if target:
            bot.send_message(uid, format_profile(uid, target), parse_mode="Markdown")
        else:
            bot.send_message(uid, f"❌ {text} не найден")
        waiting_for_username[uid] = False
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
    elif text == "📊 Глобальная статистика":
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
        bot.send_message(uid, f"📊 *Статистика*\n👥 {total}\n💰 {coins}\n📈 {avg:.2f}\n\n🏆 *Топ-10:*\n{top_text}", parse_mode="Markdown")
    elif text == "📈 Топ игроков":
        top = top_players(10)
        msg = "🏆 *Топ-10:*\n"
        for i, (uid, name, coins) in enumerate(top, 1):
            msg += f"{i}. {name or uid[:8]} — {coins}💰\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
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
            add_owned_item(uid, 'theme', theme)
            bot.answer_callback_query(call.id, f"✅ {THEMES[theme]} куплена!")
            bot.edit_message_text("🎨 *Темы*", uid, call.message.message_id, reply_markup=shop_themes_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет")
    elif data.startswith("buy_effect_"):
        effect = data.split("_")[2]
        price = EFFECTS_PRICE.get(effect, 30)
        if remove_coins(uid, price):
            add_owned_item(uid, 'effect', effect)
            bot.answer_callback_query(call.id, f"✅ {EFFECTS[effect]} куплен!")
            bot.edit_message_text("✨ *Эффекты*", uid, call.message.message_id, reply_markup=shop_effects_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет")
    elif data.startswith("buy_combo_"):
        combo = data.split("_")[2]
        price = COMBOS_PRICE.get(combo, 500)
        if remove_coins(uid, price):
            add_owned_item(uid, 'combo', combo)
            bot.answer_callback_query(call.id, f"✅ {COMBOS[combo]} куплена!")
            bot.edit_message_text("🔥 *Комбинации*", uid, call.message.message_id, reply_markup=shop_combos_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет")
    elif data.startswith("buy_language_"):
        lang = data.split("_")[2]
        price = LANGUAGES_PRICE.get(lang, 200)
        if remove_coins(uid, price):
            add_owned_item(uid, 'language', lang)
            bot.answer_callback_query(call.id, f"✅ {LANGUAGES[lang]} куплен!")
            bot.edit_message_text("💬 *Языки*", uid, call.message.message_id, reply_markup=shop_languages_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет")

    elif data.startswith("set_theme_"):
        theme = data.split("_")[2]
        if set_active_theme(uid, theme):
            bot.answer_callback_query(call.id, f"✅ {THEMES[theme]} активирована!")
            bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет такой темы")
    elif data.startswith("set_effect_"):
        effect = data.split("_")[2]
        if set_active_effect(uid, effect):
            bot.answer_callback_query(call.id, f"✅ {EFFECTS[effect]} активирован!")
            bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет эффекта")
    elif data.startswith("set_combo_"):
        combo = data.split("_")[2]
        if set_active_combo(uid, combo):
            bot.answer_callback_query(call.id, f"✅ {COMBOS[combo]} активирована!")
            bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет комбинации")
    elif data.startswith("set_language_"):
        lang = data.split("_")[2]
        if set_active_language(uid, lang):
            bot.answer_callback_query(call.id, f"✅ {LANGUAGES[lang]} активирован!")
            bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет языка")
    elif data == "remove_effect":
        update_user(uid, active_effect=None)
        bot.answer_callback_query(call.id, "❌ Эффект снят")
        bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
        bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")

    elif data.startswith("dice_"):
        if data == "dice_1":
            dice_game(uid,1,1,6,2,5,1,2,None,None)
        elif data == "dice_2":
            dice_game(uid,2,2,12,4,10,2,5,None,None)
        elif data == "dice_3":
            dice_game(uid,3,3,18,8,15,4,7,2,3)
        elif data == "dice_5":
            dice_game(uid,5,5,30,15,25,7,12,3,6)
        elif data == "dice_10":
            dice_game(uid,10,10,60,30,50,15,25,8,12)
        elif data == "dice_luck":
            dice_luck_handler(uid)
    elif data.startswith("gamble_"):
        if data == "gamble_number":
            gamble_number_handler(uid)
        elif data == "gamble_rps":
            gamble_rps_handler(uid)
        elif data == "gamble_cards":
            gamble_cards_handler(uid)
        elif data == "gamble_slots":
            gamble_slots_handler(uid)
        elif data == "gamble_rps2":
            gamble_rps2_handler(uid)
        elif data == "gamble_color":
            gamble_color_handler(uid)
        elif data == "gamble_highlow":
            gamble_highlow_handler(uid)
        elif data == "gamble_roulette":
            gamble_roulette_handler(uid)
        elif data == "gamble_hotcold":
            gamble_hotcold_handler(uid)
        elif data == "gamble_bullscows":
            gamble_bullscows_handler(uid)
        elif data == "gamble_evenodd":
            gamble_evenodd_handler(uid)
    elif data.startswith("game_"):
        if data == "game_blackjack":
            game_blackjack_handler(uid)
        elif data == "game_dicepoker":
            game_dicepoker_handler(uid)
        elif data == "game_clover":
            game_clover_handler(uid)
        elif data == "game_mine":
            game_mine_handler(uid)
        elif data == "game_jackpot":
            game_jackpot_handler(uid)
        elif data == "game_pig":
            game_pig_handler(uid)
        elif data == "game_risk":
            game_risk_handler(uid)
        elif data == "game_fool":
            game_fool_handler(uid)
        elif data == "game_memory":
            game_memory_handler(uid)
        elif data == "game_moreless":
            game_moreless_handler(uid)
        elif data == "game_luckynum":
            game_luckynum_handler(uid)
        elif data == "game_drunkard":
            game_drunkard_handler(uid)
        elif data == "game_guesscard":
            game_guesscard_handler(uid)

    elif data.startswith("buy_business_"):
        biz = data.replace("buy_business_","")
        ok, msg = create_business(uid, biz)
        bot.answer_callback_query(call.id, msg[:200])
        if ok:
            info = get_business_info(uid)
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("📈 +50💰", callback_data="upgrade_amount"))
            kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data="upgrade_speed"))
            kb.add(InlineKeyboardButton("💾 Собрать", callback_data="collect_income"))
            bot.edit_message_text(info, uid, call.message.message_id, reply_markup=kb, parse_mode="Markdown")
    elif data == "upgrade_amount":
        ok, msg = upgrade_business_amount(uid)
        bot.answer_callback_query(call.id, msg[:200])
        if ok:
            info = get_business_info(uid)
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("📈 +50💰", callback_data="upgrade_amount"))
            kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data="upgrade_speed"))
            kb.add(InlineKeyboardButton("💾 Собрать", callback_data="collect_income"))
            bot.edit_message_text(info, uid, call.message.message_id, reply_markup=kb, parse_mode="Markdown")
    elif data == "upgrade_speed":
        ok, msg = upgrade_business_speed(uid)
        bot.answer_callback_query(call.id, msg[:200])
        if ok:
            info = get_business_info(uid)
            kb = InlineKeyboardMarkup(row_width=2)
            kb.add(InlineKeyboardButton("📈 +50💰", callback_data="upgrade_amount"))
            kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data="upgrade_speed"))
            kb.add(InlineKeyboardButton("💾 Собрать", callback_data="collect_income"))
            bot.edit_message_text(info, uid, call.message.message_id, reply_markup=kb, parse_mode="Markdown")
    elif data == "collect_income":
        earned = collect_income(uid)
        bot.answer_callback_query(call.id, f"✅ Собрано {earned}💰")
        info = get_business_info(uid)
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(InlineKeyboardButton("📈 +50💰", callback_data="upgrade_amount"))
        kb.add(InlineKeyboardButton("⚡ Ускорить", callback_data="upgrade_speed"))
        kb.add(InlineKeyboardButton("💾 Собрать", callback_data="collect_income"))
        bot.edit_message_text(info, uid, call.message.message_id, reply_markup=kb, parse_mode="Markdown")

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
        bot.answer_callback_query(call.id, "✅ Вы вышли из клана")
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
    print("📊 200 тем, 200 эффектов, 50 комбинаций, 20 языков, 30 игр")
    bot.infinity_polling(skip_pending=True)
