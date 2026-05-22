import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
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
            active_theme TEXT DEFAULT '🎲',
            owned_themes TEXT DEFAULT '🎲'
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# ========== ТЕМЫ ==========
THEMES = {
    "🎲": "Классика",
    "🌌": "Космос",
    "🔥": "Огонь",
    "💎": "Драгоценности"
}
THEMES_PRICE = {"🌌": 20, "🔥": 25, "💎": 30}
THEMES_PRICE["🎲"] = 0

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
        cur.execute("INSERT INTO users (user_id) VALUES (%s)", (uid,))
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

def remove_coins(uid, amount):
    user = get_user(uid)
    if user["coins"] >= amount:
        new_coins = user["coins"] - amount
        update_user(uid, coins=new_coins)
        return True
    return False

def add_owned_theme(uid, theme):
    user = get_user(uid)
    owned = user.get("owned_themes", "🎲")
    if theme not in owned:
        update_user(uid, owned_themes=owned + theme)

def set_active_theme(uid, theme):
    if theme in get_user(uid).get("owned_themes", "🎲"):
        update_user(uid, active_theme=theme)

def format_profile(uid):
    user = get_user(uid)
    return f"💰 Баланс: {user['coins']}\n🎨 Тема: {user.get('active_theme', '🎲')}"

# ========== КЛАВИАТУРЫ ==========
def main_keyboard(uid):
    user = get_user(uid)
    theme = user.get("active_theme", "🎲")
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton(f"{theme} Профиль"),
        KeyboardButton(f"{theme} Бонус"),
        KeyboardButton(f"{theme} Магазин")
    )
    if uid == ADMIN_ID:
        kb.add(KeyboardButton("🔧 Админ"))
    return kb

def shop_keyboard(uid):
    user = get_user(uid)
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎨 Темы", callback_data="shop_themes"),
        InlineKeyboardButton("🎨 Мои покупки", callback_data="my_items"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    bot.send_message(uid, f"💰 У тебя {user['coins']} монет", reply_markup=kb, parse_mode="Markdown")

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

def my_items_keyboard(uid):
    user = get_user(uid)
    owned_themes = user.get("owned_themes", "🎲")
    active_theme = user.get("active_theme", "🎲")
    kb = InlineKeyboardMarkup(row_width=2)
    for emoji, name in THEMES.items():
        if emoji in owned_themes:
            marker = "✅" if emoji == active_theme else "❌"
            kb.add(InlineKeyboardButton(f"{marker} {name} {emoji}", callback_data=f"set_theme_{emoji}"))
    kb.add(InlineKeyboardButton("◀️ Назад", callback_data="back_shop"))
    return kb

def admin_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton("💰 Выдать монеты"),
        KeyboardButton("🔻 Забрать монеты"),
        KeyboardButton("👥 Все пользователи"),
        KeyboardButton("🔙 Назад")
    )
    return kb

# ========== ОБРАБОТЧИКИ ==========
@bot.message_handler(commands=['start'])
def start(m):
    uid = m.chat.id
    get_user(uid)
    if m.from_user.username:
        update_user(uid, username=m.from_user.username.lower())
    bot.send_message(uid, f"🎉 Добро пожаловать!\n\n{format_profile(uid)}", reply_markup=main_keyboard(uid), parse_mode="Markdown")

@bot.message_handler(func=lambda m: True)
def handle_buttons(m):
    uid = m.chat.id
    text = m.text
    user = get_user(uid)
    theme = user.get("active_theme", "🎲")

    if f"{theme} Профиль" in text or "Профиль" in text:
        bot.send_message(uid, format_profile(uid), parse_mode="Markdown")
    
    elif f"{theme} Бонус" in text or "Бонус" in text:
        user = get_user(uid)
        if not user.get("last_bonus") or datetime.fromisoformat(user["last_bonus"]) < datetime.now() - timedelta(hours=24):
            add_coins(uid, 10)
            update_user(uid, last_bonus=datetime.now().isoformat())
            bot.send_message(uid, "🎁 +10 монет!")
        else:
            bot.send_message(uid, "⏳ Бонус уже получен. Завтра!")
    
    elif f"{theme} Магазин" in text or "Магазин" in text:
        shop_keyboard(uid)
    
    elif text == "🔧 Админ" and uid == ADMIN_ID:
        bot.send_message(uid, "🔧 Админ-панель", reply_markup=admin_keyboard(), parse_mode="Markdown")
    
    elif uid == ADMIN_ID:
        if text == "💰 Выдать монеты":
            bot.send_message(uid, "Введи ID и сумму:")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: process_admin_add(m, uid))
        elif text == "🔻 Забрать монеты":
            bot.send_message(uid, "Введи ID и сумму:")
            bot.register_next_step_handler_by_chat_id(uid, lambda m: process_admin_remove(m, uid))
        elif text == "👥 Все пользователи":
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT user_id, coins FROM users")
            users = cur.fetchall()
            cur.close()
            conn.close()
            msg = "👥 Пользователи:\n"
            for u, coins in users[:20]:
                msg += f"🆔 {u} — {coins}💰\n"
            bot.send_message(uid, msg)
        elif text == "🔙 Назад":
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")

def process_admin_add(m, uid):
    try:
        target_id, amount = m.text.split()
        add_coins(int(target_id), int(amount))
        bot.send_message(uid, f"✅ Выдано {amount} монет")
    except:
        bot.send_message(uid, "❌ Ошибка")

def process_admin_remove(m, uid):
    try:
        target_id, amount = m.text.split()
        if remove_coins(int(target_id), int(amount)):
            bot.send_message(uid, f"✅ Забрано {amount} монет")
        else:
            bot.send_message(uid, f"❌ Недостаточно монет")
    except:
        bot.send_message(uid, "❌ Ошибка")

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
        bot.edit_message_text("🎨 Выбери тему:", uid, call.message.message_id, reply_markup=shop_themes_keyboard(uid), parse_mode="Markdown")
    elif data == "my_items":
        bot.edit_message_text("🎨 Мои покупки:", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
    
    elif data.startswith("buy_theme_"):
        theme = data.split("_")[2]
        price = THEMES_PRICE.get(theme, 20)
        if remove_coins(uid, price):
            add_owned_theme(uid, theme)
            bot.answer_callback_query(call.id, f"✅ Тема куплена!")
            bot.edit_message_text("🎨 Выбери тему:", uid, call.message.message_id, reply_markup=shop_themes_keyboard(uid), parse_mode="Markdown")
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет")
    
    elif data.startswith("set_theme_"):
        theme = data.split("_")[2]
        set_active_theme(uid, theme)
        bot.answer_callback_query(call.id, f"✅ Тема активирована!")
        bot.edit_message_text("🎨 Мои покупки:", uid, call.message.message_id, reply_markup=my_items_keyboard(uid), parse_mode="Markdown")
        bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")

if __name__ == "__main__":
    print("✅ ТЕСТОВЫЙ БОТ ЗАПУЩЕН!")
    bot.infinity_polling(skip_pending=True)
