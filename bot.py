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
waiting_for_username = {}  # для поиска игрока по юзернейму

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
    {"name": "🎴 Сыграй в 'Карты и Джокер'", "reward": 10, "game": "cards"}
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
            INSERT INTO users (user_id, coins, last_bonus, username, region, current_game, theme, effect, referrer)
            VALUES (%s, 5, NULL, NULL, NULL, NULL, '🎲', NULL, NULL)
        """, (uid,))
        conn.commit()
        cur.execute("SELECT * FROM users WHERE user_id = %s", (uid,))
        user = cur.fetchone()
    cur.close()
    conn.close()
    
    set_user_cache(uid, user)
    return user

def get_user_by_username(username):
    username = username.lower().replace("@", "")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE username = %s", (username,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    if result:
        return result[0]
    return None

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

def format_profile(uid, target_uid=None):
    if target_uid:
        user = get_user(target_uid)
        own_profile = False
    else:
        user = get_user(uid)
        own_profile = True
    
    theme = user.get("theme", "🎲")
    effect = user.get("effect", "")
    effect_str = f" {effect}" if effect else ""
    region = user.get("region") or "Не выбран"
    
    if own_profile:
        task = get_user_task(uid)
        task_status = "✅" if task["completed"] and not task["reward_taken"] else "❌" if not task["completed"] else "🎁"
        task_line = f"\n│  📋 Задание: {task['name']} {task_status}"
    else:
        task_line = ""
    
    return (
        f"┌─────────────────────┐\n"
        f"│  👤 *{user.get('username') or 'Игрок'}*{effect_str}\n"
        f"│  💰 Баланс: `{user['coins']}` монет\n"
        f"│  📍 Регион: {region}\n"
        f"│  🎮 Играет: {user.get('current_game') or 'нет'}\n"
        f"│  🎨 Тема: {theme}{task_line}\n"
        f"└─────────────────────┘"
    )

def commands_list():
    return (
        "📋 *Список всех команд и кнопок:*\n\n"
        "🎮 *Игры:*\n"
        "• 🎲 Угадай кубик — угадай число 1–6\n"
        "• 🎲🎲 Угадай сумму — угадай сумму 2–12\n"
        "• 🔢 Угадай число — угадай число 1–20\n"
        "• ✂️ Камень-ножницы — игра против бота\n"
        "• 🔮 Оракул — ответ да/нет\n"
        "• 🎴 Карты и Джокер — найди джокера\n\n"
        "💰 *Финансы:*\n"
        "• 🎁 Бонус — +10 монет раз в день\n"
        "• 👥 Рефералы — пригласи друга, получи 10 монет\n"
        "• 🛒 Магазин — купить темы и эффекты\n\n"
        "👤 *Профиль:*\n"
        "• 👤 Профиль — твоя статистика\n"
        "• 🔍 Найти игрока — показать профиль другого\n\n"
        "ℹ️ *Прочее:*\n"
        "• ❓ Вопрос — написать админу\n"
        "• 📋 Все команды — это меню"
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
        KeyboardButton(f"{theme} Игры"),
        KeyboardButton(f"🛒 Магазин"),
        KeyboardButton(f"👤 Профиль"),
        KeyboardButton(f"🔍 Найти игрока"),
        KeyboardButton(f"🎁 Бонус"),
        KeyboardButton(f"👥 Рефералы"),
        KeyboardButton(f"❓ Вопрос"),
        KeyboardButton(f"📋 Все команды")
    )
    if uid == ADMIN_ID:
        kb.add(KeyboardButton(f"🔧 Админ"))
    return kb

def games_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🎲 Угадай кубик", callback_data="gamble_dice1"),
        InlineKeyboardButton("🎲🎲 Угадай сумму", callback_data="gamble_dice2"),
        InlineKeyboardButton("🔢 Угадай число", callback_data="gamble_number"),
        InlineKeyboardButton("✂️ Камень-ножницы", callback_data="gamble_rps"),
        InlineKeyboardButton("🔮 Оракул", callback_data="gamble_oracle"),
        InlineKeyboardButton("🎴 Карты и Джокер", callback_data="gamble_cards"),
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

# ========== ВЫБОР РЕГИОНА ==========
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

# ========== ПРОФИЛЬ И ПОИСК ИГРОКА ==========
@bot.message_handler(func=lambda m: m.text == "👤 Профиль")
def my_profile(m):
    uid = m.chat.id
    bot.send_message(uid, format_profile(uid), parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "🔍 Найти игрока")
def find_player(m):
    uid = m.chat.id
    bot.send_message(uid, "✍️ Введи @username игрока, которого хочешь найти (например @durov):")
    waiting_for_username[uid] = True

@bot.message_handler(func=lambda m: waiting_for_username.get(m.chat.id, False))
def process_find_player(m):
    uid = m.chat.id
    username = m.text.strip().replace("@", "")
    target_uid = get_user_by_username(username)
    
    if target_uid:
        bot.send_message(uid, format_profile(uid, target_uid), parse_mode="Markdown")
    else:
        bot.send_message(uid, f"❌ Игрок с username @{username} не найден. Убедись, что он запускал бота хотя бы раз.", parse_mode="Markdown")
    
    waiting_for_username[uid] = False

# ========== ВСЕ КОМАНДЫ ==========
@bot.message_handler(func=lambda m: m.text == "📋 Все команды")
def show_commands(m):
    uid = m.chat.id
    bot.send_message(uid, commands_list(), parse_mode="Markdown")

# ========== ОСНОВНОЙ ОБРАБОТЧИК КНОПОК ==========
@bot.message_handler(func=lambda m: True)
def handle_buttons(m):
    uid = m.chat.id
    text = m.text

    if "Игры" in text:
        bot.send_message(uid, "🎮 *Выбери игру:*", reply_markup=games_keyboard(), parse_mode="Markdown")
    elif text == "🛒 Магазин":
        shop_menu(uid)
    elif text == "🎁 Бонус":
        if can_take_bonus(uid):
            add_coins(uid, 10)
            update_user(uid, last_bonus=datetime.now().isoformat())
            bot.send_message(uid, "🎁 *+10 монет!* Завтра приходи ещё!", parse_mode="Markdown")
        else:
            bot.send_message(uid, "⏳ *Бонус уже получен.* Возвращайся завтра!", parse_mode="Markdown")
    elif text == "👥 Рефералы":
        ref_link = get_referral_link(uid)
        ref_count = get_referral_stats(uid)
        bot.send_message(uid, f"👥 *Реферальная система*\n\n"
                              f"💰 За каждого приглашённого друга ты получаешь 10 монет, друг — 5 монет!\n\n"
                              f"📎 Твоя ссылка: `{ref_link}`\n"
                              f"👥 Приглашено друзей: {ref_count}\n\n"
                              f"Поделись ссылкой с друзьями!", parse_mode="Markdown")
    elif text == "❓ Вопрос":
        bot.send_message(uid, "✍️ Напиши свой вопрос. Админ ответит.")
        waiting_for_question[uid] = True
    elif text == "🔧 Админ" and uid == ADMIN_ID:
        admin_panel(uid)
    elif uid == ADMIN_ID and text in ["💰 Выдать монеты", "🔻 Забрать монеты", "👥 Все пользователи", "📢 Рассылка", "📊 Глобальная статистика", "🔙 Назад"]:
        admin_commands(uid, text)
    elif waiting_for_question.get(uid):
        forward_question(uid, text)
        waiting_for_question[uid] = False
    else:
        bot.send_message(uid, "❌ Используй кнопки меню 👇")

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

# ========== ИГРЫ ==========
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
            bot.send_message(uid, f"🎲 Выпало {roll}. Угадал! +{win}💰")
        else:
            remove_coins(uid, 1)
            bot.send_message(uid, f"🎲 Выпало {roll}. Проиграл 2💰")
        if complete_task(uid, "dice1"):
            bot.send_message(uid, "🎉 *Задание выполнено!* Напиши /take_reward, чтобы получить награду!", parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ Введи число")

def gamble_dice2_handler(uid):
    bot.send_message(uid, "🎲🎲 Введи сумму от 2 до 12:")
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
        bot.send_message(uid, "❌ Введи число")

def gamble_number_handler(uid):
    bot.send_message(uid, "🔢 Введи число от 1 до 20:")
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
            bot.send_message(uid, f"🔢 Загадано {secret}. Угадал! +{win}💰")
        else:
            remove_coins(uid, 1)
            bot.send_message(uid, f"🔢 Загадано {secret}. Проиграл 2💰")
        if complete_task(uid, "number"):
            bot.send_message(uid, "🎉 *Задание выполнено!* Напиши /take_reward, чтобы получить награду!", parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ Введи число")

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
        bot.send_message(uid, f"🔮 Оракул сказал {oracle}. Угадал! +3💰")
    else:
        remove_coins(uid, 1)
        bot.send_message(uid, f"🔮 Оракул сказал {oracle}. Ошибка. -2💰")
    if complete_task(uid, "oracle"):
        bot.send_message(uid, "🎉 *Задание выполнено!* Напиши /take_reward, чтобы получить награду!", parse_mode="Markdown")

def gamble_cards_handler(uid):
    bot.send_message(uid, "🎴 *Карты и Джокер*\n\n"
                          "Перед тобой 5 карт:\n"
                          "1️⃣ ♠️ Пики\n"
                          "2️⃣ ♥️ Черви\n"
                          "3️⃣ ♣️ Трефы\n"
                          "4️⃣ ♦️ Бубны\n"
                          "5️⃣ 🃏 Джокер\n\n"
                          "Введи номер карты (1–5):")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_cards_play(m, uid))

def gamble_cards_play(m, uid):
    try:
        choice = int(m.text)
        if choice < 1 or choice > 5:
            bot.send_message(uid, "❌ Введи число от 1 до 5")
            return
        if not remove_coins(uid, 1):
            bot.send_message(uid, "❌ Нет монет")
            return
        
        # Карты: 1-4 масти, 5 - джокер
        cards = ["♠️ Пики", "♥️ Черви", "♣️ Трефы", "♦️ Бубны", "🃏 Джокер"]
        selected = cards[choice - 1]
        
        if choice == 5:  # Джокер
            win = 10
            add_coins(uid, win)
            bot.send_message(uid, f"🎴 Тебе выпала карта: {selected}\n\n🎉 *ДЖОКЕР!* Ты выиграл {win}💰", parse_mode="Markdown")
        else:
            remove_coins(uid, 1)
            bot.send_message(uid, f"🎴 Тебе выпала карта: {selected}\n\n💀 *Это масть!* Ты проиграл 2💰", parse_mode="Markdown")
        
        if complete_task(uid, "cards"):
            bot.send_message(uid, "🎉 *Задание выполнено!* Напиши /take_reward, чтобы получить награду!", parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ Введи число 1–5")

@bot.message_handler(commands=['take_reward'])
def take_reward(m):
    uid = m.chat.id
    reward = take_task_reward(uid)
    if reward > 0:
        bot.send_message(uid, f"🎁 Ты получил {reward}💰 за выполнение задания!")
        bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
    else:
        bot.send_message(uid, "❌ Задание ещё не выполнено или награда уже получена!")

# ========== CALLBACK ==========
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
            bot.edit_message_text(f"✅ Тема куплена!", uid, call.message.message_id)
            bot.send_message(uid, format_profile(uid), reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет")
    elif data == "buy_effect_lightning":
        if remove_coins(uid, 30):
            update_user(uid, effect="⚡")
            bot.edit_message_text(f"✅ Эффект куплен!", uid, call.message.message_id)
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
        elif data == "gamble_cards":
            gamble_cards_handler(uid)

if __name__ == "__main__":
    print("✅ Бот с новыми играми и профилем запущен")
    bot.infinity_polling(skip_pending=True)
