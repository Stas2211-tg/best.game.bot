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

# ========== РАБОТА С REDIS ==========
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
            theme TEXT DEFAULT '🎲',
            effect TEXT,
            referrer TEXT,
            daily_task TEXT,
            task_completed BOOLEAN DEFAULT FALSE,
            task_reward_taken BOOLEAN DEFAULT FALSE
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

# ========== ЕЖЕДНЕВНЫЕ ЗАДАНИЯ ==========
TASKS = [
    {"name": "🎲 Сыграй в 'Угадай кубик'", "reward": 5, "game": "dice1"},
    {"name": "🎲🎲 Сыграй в 'Угадай сумму'", "reward": 5, "game": "dice2"},
    {"name": "🔢 Сыграй в 'Угадай число'", "reward": 5, "game": "number"},
    {"name": "✂️ Сыграй в 'Камень-ножницы'", "reward": 5, "game": "rps"},
    {"name": "🔮 Спроси оракула", "reward": 5, "game": "oracle"},
    {"name": "💣 Сыграй в Сапёр", "reward": 10, "game": "mines"},
    {"name": "❌⭕ Сыграй в Крестики-нолики", "reward": 10, "game": "tictac"}
]

def get_random_task():
    return random.choice(TASKS)

def get_user_task(uid):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT daily_task, task_completed, task_reward_taken FROM users WHERE user_id = %s", (str(uid),))
    result = cur.fetchone()
    cur.close()
    conn.close()
    
    if result and result[0]:
        return {"name": result[0], "completed": result[1], "reward_taken": result[2]}
    else:
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
    result = cur.fetchone()
    if result and not result[1] and not result[2]:
        task_name = result[0]
        for task in TASKS:
            if task["name"] == task_name:
                if (task["game"] == game_name) or (game_name == "any" and task["game"]):
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
    result = cur.fetchone()
    if result and result[0] and not result[1]:
        task_name = result[2]
        reward = 0
        for task in TASKS:
            if task["name"] == task_name:
                reward = task["reward"]
                break
        if reward > 0:
            add_coins(uid, reward)
            cur.execute("UPDATE users SET task_reward_taken = TRUE WHERE user_id = %s", (str(uid),))
            conn.commit()
            cur.close()
            conn.close()
            return reward
    cur.close()
    conn.close()
    return 0

# ========== РЕФЕРАЛЬНАЯ СИСТЕМА ==========
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

# ========== СТАТИСТИКА ПО РЕГИОНУ ==========
def get_region_stats(region):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE region = %s", (region,))
    total_users = cur.fetchone()[0]
    cur.execute("SELECT SUM(coins) FROM users WHERE region = %s", (region,))
    total_coins = cur.fetchone()[0] or 0
    avg_coins = total_coins / total_users if total_users > 0 else 0
    cur.execute("SELECT user_id, coins, username FROM users WHERE region = %s ORDER BY coins DESC LIMIT 3", (region,))
    top = cur.fetchall()
    top_text = "\n".join([f"{i+1}. {row[2] or row[0][:8]} — {row[1]}💰" for i, row in enumerate(top)])
    cur.close()
    conn.close()
    return total_users, total_coins, avg_coins, top_text

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
            INSERT INTO users (user_id, coins, last_bonus, username, region, current_game, theme, effect, referrer, daily_task, task_completed, task_reward_taken)
            VALUES (%s, 5, NULL, NULL, NULL, NULL, '🎲', NULL, NULL, NULL, FALSE, FALSE)
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

def global_stats():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT SUM(coins) as total_coins, COUNT(*) as total_users FROM users")
    stats = cur.fetchone()
    total_coins = stats[0] or 0
    total_users = stats[1]
    avg = total_coins / total_users if total_users else 0
    cur.execute("SELECT user_id, coins, username FROM users ORDER BY coins DESC LIMIT 10")
    top = cur.fetchall()
    top_text = "\n".join([f"{i+1}. {row[2] or row[0][:8]} — {row[1]}💰" for i, row in enumerate(top)])
    cur.close()
    conn.close()
    return total_users, total_coins, avg, top_text

def format_profile(uid):
    user = get_user(uid)
    theme = user.get("theme", "🎲")
    effect = user.get("effect", "")
    effect_str = f" {effect}" if effect else ""
    region = user.get("region") or "Не выбран"
    task = get_user_task(uid)
    task_status = "✅" if task["completed"] and not task["reward_taken"] else "❌" if not task["completed"] else "🎁"
    return (
        f"┌─────────────────────┐\n"
        f"│  👤 *{user.get('username') or 'Игрок'}*{effect_str}\n"
        f"│  💰 Баланс: `{user['coins']}` монет\n"
        f"│  📍 Регион: {region}\n"
        f"│  🎮 Играет: {user.get('current_game') or 'нет'}\n"
        f"│  🎨 Тема: {theme}\n"
        f"│  📋 Задание: {task['name']} {task_status}\n"
        f"└─────────────────────┘"
    )

REGIONS = ["🇷🇺 Россия", "🇺🇦 Украина", "🇧🇾 Беларусь", "🇰🇿 Казахстан", "🇦🇲 Армения", "🇬🇪 Грузия", "🇺🇿 Узбекистан"]

def region_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(*[KeyboardButton(r) for r in REGIONS])
    return kb

def main_keyboard(uid):
    user = get_user(uid)
    theme = user.get("theme", "🎲")
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton(f"{theme} Игры на монеты"),
        KeyboardButton(f"💣 Сапёр"),
        KeyboardButton(f"❌⭕ Крестики-нолики"),
        KeyboardButton(f"🛒 Магазин"),
        KeyboardButton(f"📊 Моя статистика"),
        KeyboardButton(f"📍 Мой регион"),
        KeyboardButton(f"📈 Статистика региона"),
        KeyboardButton(f"🎁 Бонус"),
        KeyboardButton(f"❓ Вопрос"),
        KeyboardButton(f"👥 Рефералы")
    )
    if uid == ADMIN_ID:
        kb.add(KeyboardButton(f"🔧 Админ"))
    return kb

def admin_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton("💰 Выдать монеты"),
        KeyboardButton("🔻 Забрать монеты"),
        KeyboardButton("👥 Все пользователи"),
        KeyboardButton("📢 Рассылка"),
        KeyboardButton("📊 Глобальная статистика"),
        KeyboardButton("🔙 Назад")
    )
    return kb

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
    
    bot.send_message(uid, f"🎉 *Добро пожаловать в игровой портал!*\n\n{format_profile(uid)}", reply_markup=main_keyboard(uid), parse_mode="Markdown")

# ========== ВЫБОР РЕГИОНА (свободный, без принуждения) ==========
@bot.message_handler(func=lambda m: m.text == "📍 Мой регион")
def choose_region(m):
    uid = m.chat.id
    bot.send_message(uid, "🌍 *Выбери свой регион:*", reply_markup=region_keyboard(), parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text in REGIONS)
def save_region(m):
    uid = m.chat.id
    region = m.text
    update_user(uid, region=region)
    bot.send_message(uid, f"✅ Регион *{region}* сохранён!", parse_mode="Markdown")
    bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")

# ========== СТАТИСТИКА РЕГИОНА ==========
@bot.message_handler(func=lambda m: m.text == "📈 Статистика региона")
def show_region_stats(m):
    uid = m.chat.id
    user = get_user(uid)
    region = user.get("region")
    if not region:
        bot.send_message(uid, "❌ *Сначала выбери свой регион!*\nНажми на кнопку *📍 Мой регион*", parse_mode="Markdown")
        return
    
    total_users, total_coins, avg_coins, top_text = get_region_stats(region)
    if total_users == 0:
        bot.send_message(uid, f"📊 *Статистика региона {region}*\n\nПока нет игроков в этом регионе", parse_mode="Markdown")
    else:
        bot.send_message(uid, f"📊 *Статистика региона {region}*\n\n"
                              f"👥 Игроков: {total_users}\n"
                              f"💰 Всего монет: {total_coins}\n"
                              f"📈 Средний баланс: {avg_coins:.2f}\n\n"
                              f"🏆 *Топ-3 игроков региона:*\n{top_text}", parse_mode="Markdown")

# ========== ОСНОВНОЙ ОБРАБОТЧИК КНОПОК ==========
@bot.message_handler(func=lambda m: True)
def handle_buttons(m):
    uid = m.chat.id
    text = m.text

    if "Игры на монеты" in text:
        gamble_menu(uid)
    elif text == "💣 Сапёр":
        mines_menu(uid)
    elif text == "❌⭕ Крестики-нолики":
        tictac_menu(uid)
    elif text == "🛒 Магазин":
        shop_menu(uid)
    elif text == "📊 Моя статистика":
        my_stats(uid)
    elif text == "🎁 Бонус":
        if can_take_bonus(uid):
            add_coins(uid, 10)
            update_user(uid, last_bonus=datetime.now().isoformat())
            bot.send_message(uid, "🎁 *+10 монет!* Завтра приходи ещё!", parse_mode="Markdown")
        else:
            bot.send_message(uid, "⏳ *Бонус уже получен.* Возвращайся завтра!", parse_mode="Markdown")
    elif text == "❓ Вопрос":
        bot.send_message(uid, "✍️ Напиши свой вопрос. Админ ответит.")
        waiting_for_question[uid] = True
    elif text == "👥 Рефералы":
        ref_link = get_referral_link(uid)
        ref_count = get_referral_stats(uid)
        bot.send_message(uid, f"👥 *Реферальная система*\n\n"
                              f"💰 За каждого приглашённого друга ты получаешь 10 монет, друг — 5 монет!\n\n"
                              f"📎 Твоя ссылка: `{ref_link}`\n"
                              f"👥 Приглашено друзей: {ref_count}\n\n"
                              f"Поделись ссылкой с друзьями!", parse_mode="Markdown")
    elif text == "🔧 Админ" and uid == ADMIN_ID:
        admin_panel(uid)
    elif uid == ADMIN_ID and text in ["💰 Выдать монеты", "🔻 Забрать монеты", "👥 Все пользователи", "📢 Рассылка", "📊 Глобальная статистика", "🔙 Назад"]:
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
        admin_actions[uid] = "add"
        bot.send_message(uid, "Введи ID пользователя и сумму через пробел:\nПример: `123456789 100`", parse_mode="Markdown")
        bot.register_next_step_handler_by_chat_id(uid, process_admin_add)
    elif text == "🔻 Забрать монеты":
        admin_actions[uid] = "remove"
        bot.send_message(uid, "Введи ID пользователя и сумму через пробел:\nПример: `123456789 50`", parse_mode="Markdown")
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
    elif text == "📊 Глобальная статистика":
        total_u, total_c, avg_c, top = global_stats()
        bot.send_message(uid, f"📊 *Глобальная статистика*\n"
                              f"👥 Всего игроков: {total_u}\n"
                              f"💰 Всего монет: {total_c}\n"
                              f"📈 Средний баланс: {avg_c:.2f}\n\n"
                              f"🏆 *Топ-10:*\n{top}", parse_mode="Markdown")
    elif text == "🔙 Назад":
        bot.send_message(uid, f"{format_profile(uid)}", reply_markup=main_keyboard(uid), parse_mode="Markdown")

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

def forward_question(user_id, q):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✍️ Ответить", callback_data=f"answer_{user_id}"))
    bot.send_message(ADMIN_ID, f"📩 *Вопрос от* `{user_id}`:\n{q}", reply_markup=kb, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("answer_"))
def answer_prompt(call):
    if call.message.chat.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Нет прав")
        return
    user_id = call.data.split("_")[1]
    bot.send_message(ADMIN_ID, f"✍️ Введи ответ для {user_id}:")
    bot.register_next_step_handler(call.message, lambda m: send_answer(m, user_id))

def send_answer(m, target_id):
    if m.chat.id != ADMIN_ID:
        return
    bot.send_message(int(target_id), f"📬 *Ответ:*\n{m.text}", parse_mode="Markdown")
    bot.send_message(ADMIN_ID, f"✅ Ответ отправлен {target_id}")

def my_stats(uid):
    user = get_user(uid)
    all_users = all_users_list()
    sorted_users = sorted(all_users, key=lambda x: get_user(x)["coins"], reverse=True)
    try:
        place = sorted_users.index(str(uid)) + 1
    except:
        place = "?"
    
    task = get_user_task(uid)
    task_reward = 0
    for t in TASKS:
        if t["name"] == task["name"]:
            task_reward = t["reward"]
            break
    
    task_btn = ""
    if task["completed"] and not task["reward_taken"]:
        task_btn = "\n\n🎁 *Задание выполнено!* Напиши /take_reward, чтобы получить награду!"
    
    region = user.get("region") or "Не выбран"
    
    bot.send_message(uid, f"📊 *Твоя статистика*\n\n"
                          f"👤 Имя: {user.get('username') or 'Игрок'}\n"
                          f"📍 Регион: {region}\n"
                          f"💰 Баланс: {user['coins']}\n"
                          f"🏆 Место в мире: {place}\n"
                          f"🎮 Играет: {user.get('current_game') or 'нет'}\n"
                          f"🎨 Тема: {user.get('theme', '🎲')}\n"
                          f"✨ Эффект: {user.get('effect') or 'нет'}\n"
                          f"📋 Задание: {task['name']} — награда {task_reward}💰\n"
                          f"Статус: {'✅ Выполнено' if task['completed'] else '❌ Не выполнено'}{task_btn}", parse_mode="Markdown")

@bot.message_handler(commands=['take_reward'])
def take_reward(m):
    uid = m.chat.id
    reward = take_task_reward(uid)
    if reward > 0:
        bot.send_message(uid, f"🎁 Ты получил {reward}💰 за выполнение задания!")
        bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
    else:
        bot.send_message(uid, "❌ Задание ещё не выполнено или награда уже получена!")

def gamble_menu(uid):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎲 Угадай кубик", callback_data="gamble_dice1"),
        InlineKeyboardButton("🎲🎲 Угадай сумму", callback_data="gamble_dice2"),
        InlineKeyboardButton("🔢 Угадай число", callback_data="gamble_number"),
        InlineKeyboardButton("✂️ Камень-ножницы", callback_data="gamble_rps"),
        InlineKeyboardButton("🔮 Оракул", callback_data="gamble_oracle"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    bot.send_message(uid, "🎲 *Казино* (1💰 вход, при проигрыше -1 штраф)", reply_markup=kb, parse_mode="Markdown")

def shop_menu(uid):
    user = get_user(uid)
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🌟 Тема 'Космос' (20💰)", callback_data="buy_theme_space"),
        InlineKeyboardButton("🔥 Тема 'Огонь' (25💰)", callback_data="buy_theme_fire"),
        InlineKeyboardButton("✨ Эффект 'Молния' (30💰)", callback_data="buy_effect_lightning"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    bot.send_message(uid, f"🛒 *Магазин*\n💰 У тебя {user['coins']} монет\n\n"
                          f"🌟 Космос — меняет иконку меню на 🌌\n"
                          f"🔥 Огонь — меняет иконку меню на 🔥\n"
                          f"✨ Молния — добавляет ⚡ в профиль", reply_markup=kb, parse_mode="Markdown")

def gamble_dice1_handler(uid):
    bot.send_message(uid, "🎲 Введи число от 1 до 6:")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_dice1_play(m, uid))

def gamble_dice1_play(m, uid):
    try:
        bet = int(m.text)
        if bet < 1 or bet > 6:
            bot.send_message(uid, "❌ 1–6")
            return
        if not remove_coins(uid, 1):
            bot.send_message(uid, "❌ Нет монет")
            return
        roll = random.randint(1, 6)
        if bet == roll:
            win = random.randint(2, 5)
            add_coins(uid, win)
            bot.send_message(uid, f"🎲 {roll}. Угадал! +{win}💰")
        else:
            remove_coins(uid, 1)
            bot.send_message(uid, f"🎲 {roll}. Проиграл 2💰")
        if complete_task(uid, "dice1"):
            bot.send_message(uid, "🎉 *Задание выполнено!* Напиши /take_reward, чтобы получить награду!", parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ Число")

def gamble_dice2_handler(uid):
    bot.send_message(uid, "🎲🎲 Сумма от 2 до 12:")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_dice2_play(m, uid))

def gamble_dice2_play(m, uid):
    try:
        bet = int(m.text)
        if bet < 2 or bet > 12:
            bot.send_message(uid, "❌ 2–12")
            return
        if not remove_coins(uid, 1):
            bot.send_message(uid, "❌ Нет монет")
            return
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2
        if bet == total:
            win = random.randint(4, 10)
            add_coins(uid, win)
            bot.send_message(uid, f"🎲 {d1}+{d2}={total}. Угадал! +{win}💰")
        else:
            remove_coins(uid, 1)
            bot.send_message(uid, f"🎲 {d1}+{d2}={total}. Проиграл 2💰")
        if complete_task(uid, "dice2"):
            bot.send_message(uid, "🎉 *Задание выполнено!* Напиши /take_reward, чтобы получить награду!", parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ Число")

def gamble_number_handler(uid):
    bot.send_message(uid, "🔢 Число от 1 до 20:")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_number_play(m, uid))

def gamble_number_play(m, uid):
    try:
        bet = int(m.text)
        if bet < 1 or bet > 20:
            bot.send_message(uid, "❌ 1–20")
            return
        if not remove_coins(uid, 1):
            bot.send_message(uid, "❌ Нет монет")
            return
        secret = random.randint(1, 20)
        if bet == secret:
            win = random.randint(5, 12)
            add_coins(uid, win)
            bot.send_message(uid, f"🔢 {secret}. Угадал! +{win}💰")
        else:
            remove_coins(uid, 1)
            bot.send_message(uid, f"🔢 {secret}. Проиграл 2💰")
        if complete_task(uid, "number"):
            bot.send_message(uid, "🎉 *Задание выполнено!* Напиши /take_reward, чтобы получить награду!", parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ Число")

def gamble_rps_handler(uid):
    bot.send_message(uid, "✂️ камень, ножницы, бумага:")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_rps_play(m, uid))

def gamble_rps_play(m, uid):
    choice = m.text.lower()
    if choice not in ["камень", "ножницы", "бумага"]:
        bot.send_message(uid, "❌ камень/ножницы/бумага")
        return
    if not remove_coins(uid, 1):
        bot.send_message(uid, "❌ Нет монет")
        return
    bot_choice = random.choice(["камень", "ножницы", "бумага"])
    if choice == bot_choice:
        add_coins(uid, 2)
        bot.send_message(uid, f"Ничья! +2💰")
    elif (choice == "камень" and bot_choice == "ножницы") or (choice == "ножницы" and bot_choice == "бумага") or (choice == "бумага" and bot_choice == "камень"):
        win = random.randint(3, 7)
        add_coins(uid, win)
        bot.send_message(uid, f"Победа! +{win}💰")
    else:
        remove_coins(uid, 1)
        bot.send_message(uid, f"Поражение. -2💰")
    if complete_task(uid, "rps"):
        bot.send_message(uid, "🎉 *Задание выполнено!* Напиши /take_reward, чтобы получить награду!", parse_mode="Markdown")

def gamble_oracle_handler(uid):
    bot.send_message(uid, "🔮 Да или Нет?")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_oracle_play(m, uid))

def gamble_oracle_play(m, uid):
    user_ans = m.text.lower()
    if user_ans not in ["да", "нет"]:
        bot.send_message(uid, "❌ Да или Нет")
        return
    if not remove_coins(uid, 1):
        bot.send_message(uid, "❌ Нет монет")
        return
    oracle = random.choice(["да", "нет"])
    if user_ans == oracle:
        add_coins(uid, 3)
        bot.send_message(uid, f"🔮 {oracle}. Угадал! +3💰")
    else:
        remove_coins(uid, 1)
        bot.send_message(uid, f"🔮 {oracle}. Ошибка. -2💰")
    if complete_task(uid, "oracle"):
        bot.send_message(uid, "🎉 *Задание выполнено!* Напиши /take_reward, чтобы получить награду!", parse_mode="Markdown")

def mines_menu(uid):
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("3x3", callback_data="mines_3"),
        InlineKeyboardButton("4x4", callback_data="mines_4"),
        InlineKeyboardButton("5x5", callback_data="mines_5"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    bot.send_message(uid, "💣 *Сапёр*\n1💰 вход. Проигрыш -3💰, победа +5💰\nВыбери поле:", reply_markup=kb, parse_mode="Markdown")

def mines_start(uid, size):
    if not remove_coins(uid, 1):
        bot.send_message(uid, "❌ Нет монет")
        return
    n = size
    field = [["?" for _ in range(n)] for _ in range(n)]
    mines = set()
    mine_count = n
    while len(mines) < mine_count:
        mines.add((random.randint(0, n-1), random.randint(0, n-1)))
    games_data[uid] = {"game": "mines", "field": field, "mines": mines, "size": n, "score": 0}
    mines_show(uid)

def mines_show(uid):
    data = games_data.get(uid)
    if not data:
        return
    n = data["size"]
    field = data["field"]
    text = "```\n"
    for row in field:
        text += " ".join(row) + "\n"
    text += "```"
    kb = InlineKeyboardMarkup(row_width=n)
    for i in range(n):
        row = []
        for j in range(n):
            if field[i][j] == "?":
                row.append(InlineKeyboardButton("❓", callback_data=f"mines_click_{i}_{j}"))
            else:
                row.append(InlineKeyboardButton(field[i][j], callback_data="no"))
        kb.add(*row)
    bot.send_message(uid, f"💣 Осталось безопасных клеток: {n*n - data['score'] - len(data['mines'])}\n{text}", reply_markup=kb, parse_mode="Markdown")

def mines_click(uid, i, j):
    data = games_data.get(uid)
    if not data:
        return
    if (i, j) in data["mines"]:
        bot.send_message(uid, f"💥 Ты наступил на мину! -3💰")
        remove_coins(uid, 3)
        del games_data[uid]
        if complete_task(uid, "mines"):
            bot.send_message(uid, "🎉 *Задание выполнено!* Напиши /take_reward, чтобы получить награду!", parse_mode="Markdown")
        return
    if data["field"][i][j] != "?":
        return
    data["field"][i][j] = "✅"
    data["score"] += 1
    total_safe = data["size"] * data["size"] - len(data["mines"])
    if data["score"] == total_safe:
        bot.send_message(uid, f"🏆 Ты прошёл всё поле! +5💰")
        add_coins(uid, 5)
        del games_data[uid]
        if complete_task(uid, "mines"):
            bot.send_message(uid, "🎉 *Задание выполнено!* Напиши /take_reward, чтобы получить награду!", parse_mode="Markdown")
        return
    mines_show(uid)

def tictac_menu(uid):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🤖 С ботом (1💰)", callback_data="tictac_bot"),
        InlineKeyboardButton("👥 С другом (1💰)", callback_data="tictac_friend"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    bot.send_message(uid, "❌⭕ *Крестики-нолики*\nПобедитель получает +3💰", reply_markup=kb, parse_mode="Markdown")

def tictac_start(uid, mode):
    if not remove_coins(uid, 1):
        bot.send_message(uid, "❌ Нет монет")
        return
    field = [[" " for _ in range(3)] for _ in range(3)]
    games_data[uid] = {"game": "tictac", "field": field, "mode": mode, "turn": "X", "players": {"X": uid}}
    if mode == "friend":
        bot.send_message(uid, "Введи ID противника:")
        bot.register_next_step_handler_by_chat_id(uid, lambda m: set_opponent(m, uid))
    else:
        tictac_show(uid)

def set_opponent(m, uid):
    try:
        opp = int(m.text)
        if opp == uid:
            bot.send_message(uid, "❌ Нельзя с собой")
            add_coins(uid, 1)
            del games_data[uid]
            return
        if not remove_coins(opp, 1):
            bot.send_message(uid, f"❌ У {opp} нет монет")
            add_coins(uid, 1)
            del games_data[uid]
            return
        games_data[uid]["players"]["O"] = opp
        bot.send_message(uid, f"✅ Противник {opp}. Твой ход X")
        bot.send_message(opp, f"🎮 Игрок {uid} вызывает на игру. Ты O")
        tictac_show(uid)
    except:
        bot.send_message(uid, "❌ Введи ID")
        add_coins(uid, 1)
        del games_data[uid]

def tictac_show(uid):
    data = games_data.get(uid)
    if not data:
        return
    field = data["field"]
    text = "```\n"
    for row in field:
        text += "|".join(row) + "\n"
    text += "```"
    kb = InlineKeyboardMarkup(row_width=3)
    for i in range(3):
        row = []
        for j in range(3):
            if field[i][j] == " ":
                row.append(InlineKeyboardButton("⬜", callback_data=f"tictac_move_{i}_{j}"))
            else:
                row.append(InlineKeyboardButton(field[i][j], callback_data="no"))
        kb.add(*row)
    bot.send_message(uid, f"Ход: {data['turn']}\n{text}", reply_markup=kb, parse_mode="Markdown")
    if data["mode"] == "friend" and data["players"].get("O"):
        opp = data["players"]["O"]
        bot.send_message(opp, f"Ход: {data['turn']}\n{text}", reply_markup=kb, parse_mode="Markdown")

def tictac_move(uid, i, j):
    data = games_data.get(uid)
    if not data:
        return
    current = uid if data["turn"] == "X" else data["players"].get("O")
    if current != uid:
        return
    if data["field"][i][j] != " ":
        return
    data["field"][i][j] = data["turn"]
    winner = check_winner(data["field"])
    if winner:
        add_coins(uid, 3)
        bot.send_message(uid, f"🏆 Победа {winner}! +3💰")
        if data["mode"] == "friend" and data["players"].get("O"):
            bot.send_message(data["players"]["O"], f"🏆 Победа {winner}!")
        del games_data[uid]
        if complete_task(uid, "tictac"):
            bot.send_message(uid, "🎉 *Задание выполнено!* Напиши /take_reward, чтобы получить награду!", parse_mode="Markdown")
        return
    if all(data["field"][r][c] != " " for r in range(3) for c in range(3)):
        bot.send_message(uid, "Ничья! Монеты возвращены")
        add_coins(uid, 1)
        if data["mode"] == "friend" and data["players"].get("O"):
            add_coins(data["players"]["O"], 1)
            bot.send_message(data["players"]["O"], "Ничья!")
        del games_data[uid]
        if complete_task(uid, "tictac"):
            bot.send_message(uid, "🎉 *Задание выполнено!* Напиши /take_reward, чтобы получить награду!", parse_mode="Markdown")
        return
    data["turn"] = "O" if data["turn"] == "X" else "X"
    tictac_show(uid)

def check_winner(f):
    for row in f:
        if row[0] == row[1] == row[2] != " ":
            return row[0]
    for col in range(3):
        if f[0][col] == f[1][col] == f[2][col] != " ":
            return f[0][col]
    if f[0][0] == f[1][1] == f[2][2] != " ":
        return f[0][0]
    if f[0][2] == f[1][1] == f[2][0] != " ":
        return f[0][2]
    return None

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    uid = call.message.chat.id
    data = call.data

    if data == "back_main":
        bot.edit_message_text("Меню", uid, call.message.message_id)
        bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
    elif data.startswith("buy_theme_"):
        theme = data.split("_")[2]
        price = {"space": 20, "fire": 25}.get(theme, 0)
        if remove_coins(uid, price):
            new_theme = "🌌" if theme == "space" else "🔥"
            update_user(uid, theme=new_theme)
            bot.edit_message_text(f"✅ Тема '{'Космос' if theme == 'space' else 'Огонь'}' куплена!", uid, call.message.message_id)
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет")
    elif data == "buy_effect_lightning":
        if remove_coins(uid, 30):
            update_user(uid, effect="⚡")
            bot.edit_message_text(f"✅ Эффект 'Молния' куплен!", uid, call.message.message_id)
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет")
    elif data.startswith("gamble_"):
        if data == "gamble_dice1":
            gamble_dice1_handler(uid)
        elif data == "gamble_dice2":
            gamble_dice2_handler(uid)
        elif data == "gamble_number":
            gamble_number_handler(uid)
        elif data == "gamble_rps":
            gamble_rps_handler(uid)
        elif data == "gamble_oracle":
            gamble_oracle_handler(uid)
    elif data.startswith("mines_"):
        size = int(data.split("_")[1])
        mines_start(uid, size)
    elif data.startswith("mines_click_"):
        _, _, i, j = data.split("_")
        mines_click(uid, int(i), int(j))
    elif data == "tictac_bot":
        tictac_start(uid, "bot")
    elif data == "tictac_friend":
        tictac_start(uid, "friend")
    elif data.startswith("tictac_move_"):
        _, _, i, j = data.split("_")
        tictac_move(uid, int(i), int(j))

if __name__ == "__main__":
    print("✅ Бот с выбором региона и статистикой по региону запущен")
    bot.infinity_polling(skip_pending=True)
