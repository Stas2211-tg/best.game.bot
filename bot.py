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
waiting_for_username = {}

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
            active_theme TEXT DEFAULT '🎲',
            active_effect TEXT,
            active_language TEXT DEFAULT 'normal',
            referrer TEXT,
            owned_themes TEXT DEFAULT '🎲',
            owned_effects TEXT DEFAULT '',
            owned_languages TEXT DEFAULT 'normal'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            user_id TEXT,
            referrer_id TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# ========== ТЕМЫ (10 для теста) ==========
THEMES = {
    "🎲": "Классика",
    "🌌": "Космос",
    "🔥": "Огонь",
    "💎": "Драгоценности",
    "👑": "Королевская",
    "🌙": "Мистическая",
    "🤖": "Киберпанк",
    "✨": "Золотая",
    "❄️": "Ледяная",
    "🌊": "Морская"
}
THEMES_PRICE = {"🌌": 20, "🔥": 25, "💎": 30, "👑": 80, "🌙": 90, "🤖": 100, "✨": 120, "❄️": 80, "🌊": 95}
THEMES_PRICE["🎲"] = 0

# ========== ЭФФЕКТЫ (10 для теста) ==========
EFFECTS = {
    "⚡": "Молния",
    "🌟": "Звезда",
    "💫": "Комета",
    "🌀": "Вихрь",
    "🌈": "Радуга",
    "💡": "Неон",
    "🔮": "Магия",
    "🔥": "Огонь",
    "❄️": "Лёд",
    "👑": "Корона"
}
EFFECTS_PRICE = {"⚡": 30, "🌟": 25, "💫": 35, "🌀": 30, "🌈": 50, "💡": 60, "🔮": 70, "🔥": 90, "❄️": 100, "👑": 100}

# ========== ЯЗЫКИ ==========
LANGUAGES = {
    "normal": "Обычный",
    "royal": "👑 Королевский",
    "sassy": "🔥 Дерзкий",
    "evil": "😈 Злой",
    "mystic": "🎭 Таинственный"
}
LANGUAGES_PRICE = {"royal": 200, "sassy": 250, "evil": 300, "mystic": 350}

def get_phrase(lang, phrase_key):
    phrases = {
        "normal": {"bonus": "🎁 +10 монет!", "already_bonus": "⏳ Бонус уже получен", "no_coins": "❌ Нет монет"},
        "royal": {"bonus": "👑 Вам пожаловано 10 монет!", "already_bonus": "⏳ Вы уже получали бонус", "no_coins": "❌ У вас недостаточно монет"},
        "sassy": {"bonus": "🎁 Держи 10💰!", "already_bonus": "⏳ Ты уже брал бонус", "no_coins": "❌ Эй, нет монет!"},
        "evil": {"bonus": "🎁 Получи 10💰!", "already_bonus": "⏳ Бонус уже был", "no_coins": "❌ Нет монет, иди работай"},
        "mystic": {"bonus": "🎁 Луна дарит 10💰...", "already_bonus": "⏳ Прилив энергии был...", "no_coins": "❌ Энергия монет иссякла"}
    }
    if lang not in phrases:
        return phrases["normal"].get(phrase_key, "")
    return phrases[lang].get(phrase_key, phrases["normal"].get(phrase_key, ""))

# ========== ОСНОВНЫЕ ФУНКЦИИ ==========
def get_user(uid):
    uid = str(uid)
    cached = get_user_cache(uid)
    if cached:
        return cached
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE user_id = %s", (uid,))
    user = cur.fetchone()
    if not user:
        cur.execute("""
            INSERT INTO users (user_id, coins, last_bonus, username, region, active_theme, active_effect, active_language, referrer, owned_themes, owned_effects, owned_languages)
            VALUES (%s, 5, NULL, NULL, NULL, '🎲', NULL, 'normal', NULL, '🎲', '', 'normal')
        """, (uid,))
        conn.commit()
        cur.execute("SELECT * FROM users WHERE user_id = %s", (uid,))
        user = cur.fetchone()
    cur.close()
    conn.close()
    
    set_user_cache(uid, user)
    return user

def update_user(uid, **kwargs):
    uid = str(uid)
    conn = get_db_connection()
    cur = conn.cursor()
    for key, value in kwargs.items():
        cur.execute(f"UPDATE users SET {key} = %s WHERE user_id = %s", (value, uid))
    conn.commit()
    cur.close()
    conn.close()
    delete_user_cache(uid)

def add_coins(uid, amount):
    user = get_user(uid)
    new_coins = user["coins"] + amount
    update_user(uid, coins=new_coins)
    return new_coins

def remove_coins(uid, amount):
    user = get_user(uid)
    if user["coins"] >= amount:
        new_coins = user["coins"] - amount
        update_user(uid, coins=new_coins)
        return True
    return False

def can_take_bonus(uid):
    user = get_user(uid)
    if not user["last_bonus"]:
        return True
    last = datetime.fromisoformat(user["last_bonus"])
    return datetime.now() - last >= timedelta(hours=24)

def all_users_list():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    users = [row[0] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return users

def format_profile(uid):
    user = get_user(uid)
    theme = user.get("active_theme", "🎲")
    effect = user.get("active_effect", "")
    effect_str = f" {effect}" if effect else ""
    lang = user.get("active_language", "normal")
    lang_name = LANGUAGES.get(lang, "Обычный")
    region = user.get("region") or "❓"
    return (
        f"┌─────────────────────┐\n"
        f"│  👤 *{user.get('username') or 'Игрок'}*{effect_str}\n"
        f"│  💰 Баланс: `{user['coins']}` монет\n"
        f"│  📍 Регион: {region}\n"
        f"│  🎨 Тема: {theme}\n"
        f"│  💬 Язык: {lang_name}\n"
        f"└─────────────────────┘"
    )

REGIONS = ["🇷🇺 Россия", "🇺🇦 Украина", "🇧🇾 Беларусь", "🇰🇿 Казахстан"]

def region_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(*[KeyboardButton(r) for r in REGIONS])
    return kb

# ========== КЛАВИАТУРЫ ==========
def main_keyboard(uid):
    user = get_user(uid)
    theme = user.get("active_theme", "🎲")
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton(f"{theme} Магазин"),
        KeyboardButton(f"{theme} Профиль"),
        KeyboardButton(f"{theme} Бонус"),
        KeyboardButton(f"{theme} Рефералы"),
        KeyboardButton(f"📍 Мой регион")
    )
    if uid == ADMIN_ID:
        kb.add(KeyboardButton("🔧 Админ"))
    return kb

def shop_keyboard(uid):
    user = get_user(uid)
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎨 Темы", callback_data="shop_themes"),
        InlineKeyboardButton("✨ Эффекты", callback_data="shop_effects"),
        InlineKeyboardButton("💬 Языки", callback_data="shop_languages"),
        InlineKeyboardButton("🎨 Мои покупки", callback_data="my_items"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    bot.send_message(uid, f"🛒 *Магазин*\n💰 У тебя {user['coins']} монет", reply_markup=kb, parse_mode="Markdown")

def shop_themes_keyboard(uid):
    user = get_user(uid)
    owned = user.get("owned_themes", "🎲")
    kb = InlineKeyboardMarkup(row_width=2)
    for emoji, name in THEMES.items():
        if emoji in owned:
            kb.add(InlineKeyboardButton(f"✅ {name} {emoji}", callback_data="no"))
        else:
            price = THEMES_PRICE.get(emoji, 20)
            kb.add(InlineKeyboardButton(f"🎨 {name} {emoji} ({price}💰)", callback_data=f"buy_theme_{emoji}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_shop"))
    return kb

def shop_effects_keyboard(uid):
    user = get_user(uid)
    owned = user.get("owned_effects", "")
    kb = InlineKeyboardMarkup(row_width=2)
    for emoji, name in EFFECTS.items():
        if emoji in owned:
            kb.add(InlineKeyboardButton(f"✅ {name} {emoji}", callback_data="no"))
        else:
            price = EFFECTS_PRICE.get(emoji, 30)
            kb.add(InlineKeyboardButton(f"✨ {name} {emoji} ({price}💰)", callback_data=f"buy_effect_{emoji}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_shop"))
    return kb

def shop_languages_keyboard(uid):
    user = get_user(uid)
    owned = user.get("owned_languages", "normal")
    kb = InlineKeyboardMarkup(row_width=1)
    for lang, name in LANGUAGES.items():
        if lang == "normal":
            kb.add(InlineKeyboardButton(f"✅ {name}", callback_data="no"))
        elif lang in owned:
            kb.add(InlineKeyboardButton(f"✅ {name}", callback_data="no"))
        else:
            price = LANGUAGES_PRICE.get(lang, 200)
            kb.add(InlineKeyboardButton(f"💬 {name} ({price}💰)", callback_data=f"buy_language_{lang}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_shop"))
    return kb

def my_items_keyboard(uid):
    user = get_user(uid)
    owned_themes = user.get("owned_themes", "🎲")
    owned_effects = user.get("owned_effects", "")
    owned_languages = user.get("owned_languages", "normal")
    active_theme = user.get("active_theme", "🎲")
    active_effect = user.get("active_effect", "")
    active_language = user.get("active_language", "normal")
    
    kb = InlineKeyboardMarkup(row_width=2)
    
    for emoji, name in THEMES.items():
        if emoji in owned_themes:
            marker = "✅" if emoji == active_theme else "❌"
            kb.add(InlineKeyboardButton(f"{marker} {name} {emoji}", callback_data=f"set_theme_{emoji}"))
    
    for emoji, name in EFFECTS.items():
        if emoji in owned_effects:
            marker = "✅" if emoji == active_effect else "❌"
            kb.add(InlineKeyboardButton(f"{marker} {name} {emoji}", callback_data=f"set_effect_{emoji}"))
    
    for lang, name in LANGUAGES.items():
        if lang != "normal" and lang in owned_languages:
            marker = "✅" if lang == active_language else "❌"
            kb.add(InlineKeyboardButton(f"{marker} {name}", callback_data=f"set_language_{lang}"))
    
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

# ========== ФУНКЦИИ ПОКУПОК ==========
def add_owned_theme(uid, theme):
    user = get_user(uid)
    owned = user.get("owned_themes", "🎲")
    if theme not in owned:
        update_user(uid, owned_themes=owned + theme)

def add_owned_effect(uid, effect):
    user = get_user(uid)
    owned = user.get("owned_effects", "")
    if effect not in owned:
        update_user(uid, owned_effects=owned + effect)

def add_owned_language(uid, lang):
    user = get_user(uid)
    owned = user.get("owned_languages", "normal")
    if lang not in owned:
        update_user(uid, owned_languages=owned + "," + lang)

def set_active_theme(uid, theme):
    if theme in get_user(uid).get("owned_themes", "🎲"):
        update_user(uid, active_theme=theme)
        return True
    return False

def set_active_effect(uid, effect):
    if effect in get_user(uid).get("owned_effects", ""):
        update_user(uid, active_effect=effect)
        return True
    return False

def set_active_language(uid, lang):
    if lang == "normal" or lang in get_user(uid).get("owned_languages", "normal"):
        update_user(uid, active_language=lang)
        return True
    return False

# ========== РЕФЕРАЛКА ==========
def get_referral_link(uid):
    bot_info = bot.get_me()
    return f"https://t.me/{bot_info.username}?start=ref_{uid}"

def process_referral(new_uid, referrer_id):
    if str(new_uid) == str(referrer_id):
        return False
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM referrals WHERE user_id = %s", (str(new_uid),))
    if cur.fetchone():
        cur.close()
        conn.close()
        return False
    cur.execute("INSERT INTO referrals (user_id, referrer_id) VALUES (%s, %s)", (str(new_uid), str(referrer_id)))
    add_coins(new_uid, 5)
    add_coins(referrer_id, 10)
    conn.commit()
    cur.close()
    conn.close()
    return True

def get_referral_stats(uid):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = %s", (str(uid),))
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count

# ========== ОСНОВНОЙ ОБРАБОТЧИК ==========
@bot.message_handler(commands=['start'])
def start(m):
    uid = m.chat.id
    args = m.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        referrer_id = args[1].split("_")[1]
        process_referral(uid, referrer_id)
    
    user = get_user(uid)
    if m.from_user.username:
        update_user(uid, username=m.from_user.username.lower())
    
    if not user.get("region"):
        bot.send_message(uid, "🌍 *Выбери свой регион:*", reply_markup=region_keyboard(), parse_mode="Markdown")
    else:
        bot.send_message(uid, f"🎉 *Добро пожаловать!*\n\n{format_profile(uid)}", reply_markup=main_keyboard(uid), parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text in REGIONS)
def save_region(m):
    uid = m.chat.id
    region = m.text
    update_user(uid, region=region)
    bot.send_message(uid, f"✅ Регион *{region}* сохранён!", parse_mode="Markdown")
    bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def handle_buttons(m):
    uid = m.chat.id
    text = m.text
    user = get_user(uid)
    theme = user.get("active_theme", "🎲")

    if f"{theme} Магазин" in text or "Магазин" in text:
        shop_keyboard(uid)
    elif f"{theme} Профиль" in text or "Профиль" in text:
        bot.send_message(uid, format_profile(uid), parse_mode="Markdown")
    elif f"{theme} Бонус" in text or "Бонус" in text:
        lang = user.get("active_language", "normal")
        if can_take_bonus(uid):
            add_coins(uid, 10)
            update_user(uid, last_bonus=datetime.now().isoformat())
            bot.send_message(uid, get_phrase(lang, "bonus"), parse_mode="Markdown")
        else:
            bot.send_message(uid, get_phrase(lang, "already_bonus"), parse_mode="Markdown")
    elif f"{theme} Рефералы" in text or "Рефералы" in text:
        ref_link = get_referral_link(uid)
        ref_count = get_referral_stats(uid)
        bot.send_message(uid, f"👥 *Реферальная система*\n\n💰 За каждого приглашённого ты получаешь 10 монет, друг — 5!\n\n📎 Твоя ссылка: `{ref_link}`\n👥 Приглашено: {ref_count}", parse_mode="Markdown")
    elif text == "📍 Мой регион":
        bot.send_message(uid, "🌍 *Выбери свой регион:*", reply_markup=region_keyboard(), parse_mode="Markdown")
    elif text == "🔧 Админ" and uid == ADMIN_ID:
        admin_panel(uid)
    elif uid == ADMIN_ID and text in ["💰 Выдать монеты", "🔻 Забрать монеты", "👥 Все пользователи", "📢 Рассылка", "🔙 Назад"]:
        admin_commands(uid, text)
    else:
        bot.send_message(uid, "❌ Используй кнопки меню 👇")

def admin_panel(uid):
    bot.send_message(uid, "🔧 *Админ-панель*", reply_markup=admin_keyboard(), parse_mode="Markdown")

def admin_commands(uid, text):
    if text == "💰 Выдать монеты":
        bot.send_message(uid, "Введи ID и сумму:\nПример: `123456789 100`", parse_mode="Markdown")
        bot.register_next_step_handler_by_chat_id(uid, process_admin_add)
    elif text == "🔻 Забрать монеты":
        bot.send_message(uid, "Введи ID и сумму:\nПример: `123456789 50`", parse_mode="Markdown")
        bot.register_next_step_handler_by_chat_id(uid, process_admin_remove)
    elif text == "👥 Все пользователи":
        users = all_users_list()
        msg = "👥 *Пользователи:*\n"
        for u in users[:30]:
            coins = get_user(u)["coins"]
            msg += f"🆔 {u} — {coins}💰\n"
        bot.send_message(uid, msg, parse_mode="Markdown")
    elif text == "📢 Рассылка":
        bot.send_message(uid, "Введи сообщение для рассылки:")
        bot.register_next_step_handler_by_chat_id(uid, broadcast_message)
    elif text == "🔙 Назад":
        bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")

def process_admin_add(m):
    uid = m.chat.id
    try:
        target_id, amount = m.text.split()
        add_coins(int(target_id), int(amount))
        bot.send_message(uid, f"✅ Выдано {amount} монет пользователю {target_id}")
    except:
        bot.send_message(uid, "❌ Ошибка. Пример: `123456789 100`", parse_mode="Markdown")

def process_admin_remove(m):
    uid = m.chat.id
    try:
        target_id, amount = m.text.split()
        if remove_coins(int(target_id), int(amount)):
            bot.send_message(uid, f"✅ Забрано {amount} монет у {target_id}")
        else:
            bot.send_message(uid, f"❌ Недостаточно монет у {target_id}")
    except:
        bot.send_message(uid, "❌ Ошибка. Пример: `123456789 50`", parse_mode="Markdown")

def broadcast_message(m):
    if m.chat.id != ADMIN_ID:
        return
    text = m.text
    sent = 0
    for uid in all_users_list():
        try:
            bot.send_message(int(uid), f"📢 *Рассылка:*\n\n{text}", parse_mode="Markdown")
            sent += 1
        except:
            pass
    bot.send_message(ADMIN_ID, f"✅ Отправлено {sent} пользователям")

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
        bot.edit_message_text("🎨 *Выбери тему:*", uid, call.message.message_id, reply_markup=shop_themes_keyboard(uid), parse_mode="Markdown")
    elif data == "shop_effects":
        bot.edit_message_text("✨ *Выбери эффект:*", uid, call.message.message_id, reply_markup=shop_effects_keyboard(uid), parse_mode="Markdown")
    elif data == "shop_languages":
        bot.edit_message_text("💬 *Выбери язык:*", uid, call.message.message_id, reply_markup=shop_languages_keyboard(uid), parse_mode="Markdown")
    elif data == "my_items":
        bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
    
    elif data.startswith("buy_theme_"):
        theme = data.split("_")[2]
        price = THEMES_PRICE.get(theme, 20)
        if remove_coins(uid, price):
            add_owned_theme(uid, theme)
            bot.answer_callback_query(call.id, f"✅ Тема {THEMES[theme]} куплена!")
            bot.edit_message_text("🎨 *Выбери тему:*", uid, call.message.message_id, reply_markup=shop_themes_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет")
    
    elif data.startswith("buy_effect_"):
        effect = data.split("_")[2]
        price = EFFECTS_PRICE.get(effect, 30)
        if remove_coins(uid, price):
            add_owned_effect(uid, effect)
            bot.answer_callback_query(call.id, f"✅ Эффект {EFFECTS[effect]} куплен!")
            bot.edit_message_text("✨ *Выбери эффект:*", uid, call.message.message_id, reply_markup=shop_effects_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет")
    
    elif data.startswith("buy_language_"):
        lang = data.split("_")[2]
        price = LANGUAGES_PRICE.get(lang, 200)
        if remove_coins(uid, price):
            add_owned_language(uid, lang)
            bot.answer_callback_query(call.id, f"✅ Язык {LANGUAGES[lang]} куплен!")
            bot.edit_message_text("💬 *Выбери язык:*", uid, call.message.message_id, reply_markup=shop_languages_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет")
    
    elif data.startswith("set_theme_"):
        theme = data.split("_")[2]
        if set_active_theme(uid, theme):
            bot.answer_callback_query(call.id, f"✅ Тема {THEMES[theme]} активирована!")
            bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет такой темы")
    
    elif data.startswith("set_effect_"):
        effect = data.split("_")[2]
        if set_active_effect(uid, effect):
            bot.answer_callback_query(call.id, f"✅ Эффект {EFFECTS[effect]} активирован!")
            bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет такого эффекта")
    
    elif data.startswith("set_language_"):
        lang = data.split("_")[2]
        if set_active_language(uid, lang):
            bot.answer_callback_query(call.id, f"✅ Язык {LANGUAGES[lang]} активирован!")
            bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет такого языка")
    
    elif data == "remove_effect":
        update_user(uid, active_effect=None)
        bot.answer_callback_query(call.id, "❌ Эффект снят")
        bot.edit_message_text("🎨 *Мои покупки*", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
        bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")

if __name__ == "__main__":
    print("✅ УПРОЩЁННЫЙ БОТ ЗАПУЩЕН!")
    bot.infinity_polling(skip_pending=True)
