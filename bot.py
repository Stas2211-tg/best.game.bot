import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import random
import os
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    print("❌ Токен не найден")
    exit(1)

ADMIN_ID = int(os.getenv("ADMIN_ID", 6615344173))
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌ DATABASE_URL не найден")
    exit(1)

bot = telebot.TeleBot(TOKEN)
games_data = {}
waiting_for_question = {}

# ========== РАБОТА С БАЗОЙ ДАННЫХ ==========
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
            effect TEXT
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

def get_user(uid):
    uid = str(uid)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE user_id = %s", (uid,))
    user = cur.fetchone()
    if not user:
        cur.execute("""
            INSERT INTO users (user_id, coins, last_bonus, username, region, current_game, theme, effect)
            VALUES (%s, 5, NULL, NULL, NULL, NULL, '🎲', NULL)
        """, (uid,))
        conn.commit()
        cur.execute("SELECT * FROM users WHERE user_id = %s", (uid,))
        user = cur.fetchone()
    cur.close()
    conn.close()
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
    return (
        f"┌─────────────────────┐\n"
        f"│  👤 *{user.get('username') or 'Игрок'}*\n"
        f"│  💰 Баланс: `{user['coins']}` монет\n"
        f"│  📍 Регион: {user.get('region') or '❓'}\n"
        f"│  🎮 Играет: {user.get('current_game') or 'нет'}\n"
        f"└─────────────────────┘"
    )

# ========== КЛАВИАТУРЫ ==========
def main_keyboard(uid):
    user = get_user(uid)
    theme = user.get("theme", "🎲")
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton(f"🎲 Игры на монеты"),
        KeyboardButton(f"💣 Сапёр"),
        KeyboardButton(f"❌⭕ Крестики-нолики"),
        KeyboardButton(f"🛒 Магазин"),
        KeyboardButton(f"📊 Моя статистика"),
        KeyboardButton(f"🎁 Бонус"),
        KeyboardButton(f"❓ Вопрос")
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

# ========== АДМИН-КОМАНДЫ ==========
@bot.message_handler(commands=['addcoins'])
def add_cmd(m):
    if m.chat.id != ADMIN_ID:
        return
    try:
        _, uid, amount = m.text.split()
        add_coins(int(uid), int(amount))
        bot.send_message(ADMIN_ID, f"✅ Выдано {amount} монет пользователю {uid}")
    except:
        bot.send_message(ADMIN_ID, "❌ /addcoins ID КОЛИЧЕСТВО")

@bot.message_handler(commands=['removecoins'])
def remove_cmd(m):
    if m.chat.id != ADMIN_ID:
        return
    try:
        _, uid, amount = m.text.split()
        if remove_coins(int(uid), int(amount)):
            bot.send_message(ADMIN_ID, f"✅ Забрано {amount} монет у {uid}")
        else:
            bot.send_message(ADMIN_ID, f"❌ Недостаточно монет у {uid}")
    except:
        bot.send_message(ADMIN_ID, "❌ /removecoins ID КОЛИЧЕСТВО")

# ========== ОСНОВНЫЕ КОМАНДЫ ==========
@bot.message_handler(commands=['start'])
def start(m):
    uid = m.chat.id
    user = get_user(uid)
    if m.from_user.username:
        update_user(uid, username=m.from_user.username.lower())
    bot.send_message(uid, f"🎉 *Добро пожаловать в игровой портал!*\n\n{format_profile(uid)}", reply_markup=main_keyboard(uid), parse_mode="Markdown")

def send_typo_error(uid):
    bot.send_message(uid, "❌ Пожалуйста, используй кнопки меню 👇")

@bot.message_handler(func=lambda m: True)
def handle_buttons(m):
    uid = m.chat.id
    text = m.text
    user = get_user(uid)

    if text == "🎲 Игры на монеты":
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
    elif text == "🔧 Админ" and uid == ADMIN_ID:
        admin_panel(uid)
    elif uid == ADMIN_ID and text in ["💰 Выдать монеты", "🔻 Забрать монеты", "👥 Все пользователи", "📢 Рассылка", "📊 Глобальная статистика", "🔙 Назад"]:
        admin_commands(uid, text)
    elif waiting_for_question.get(uid):
        forward_question(uid, text)
        waiting_for_question[uid] = False
    else:
        send_typo_error(uid)

def admin_commands(uid, text):
    if text == "💰 Выдать монеты":
        bot.send_message(uid, "Введи: `/addcoins ID КОЛИЧЕСТВО`", parse_mode="Markdown")
    elif text == "🔻 Забрать монеты":
        bot.send_message(uid, "Введи: `/removecoins ID КОЛИЧЕСТВО`", parse_mode="Markdown")
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

# ========== МЕНЮ ИГР ==========
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
    bot.send_message(uid, f"🛒 *Магазин*\n💰 У тебя {user['coins']} монет", reply_markup=kb, parse_mode="Markdown")

def my_stats(uid):
    user = get_user(uid)
    all_users = all_users_list()
    sorted_users = sorted(all_users, key=lambda x: get_user(x)["coins"], reverse=True)
    try:
        place = sorted_users.index(str(uid)) + 1
    except:
        place = "?"
    bot.send_message(uid, f"📊 *Твоя статистика*\n\n"
                          f"👤 Имя: {user.get('username') or 'Игрок'}\n"
                          f"📍 Регион: {user.get('region') or '?'}\n"
                          f"💰 Баланс: {user['coins']}\n"
                          f"🏆 Место: {place}\n"
                          f"🎮 Играет: {user.get('current_game') or 'нет'}", parse_mode="Markdown")

def admin_panel(uid):
    bot.send_message(uid, "🔧 *Админ-панель*", reply_markup=admin_keyboard(), parse_mode="Markdown")

# ========== ИГРЫ (Казино) ==========
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

# ========== САПЁР ==========
def mines_menu(uid):
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("5x5", callback_data="mines_5"),
        InlineKeyboardButton("8x8", callback_data="mines_8"),
        InlineKeyboardButton("10x10", callback_data="mines_10"),
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
    while len(mines) < n:
        mines.add((random.randint(0, n-1), random.randint(0, n-1)))
    games_data[uid] = {"game": "mines", "field": field, "mines": mines, "size": n, "score": 0}
    mines_show(uid)

def mines_show(uid):
    data = games_data.get(uid)
    if not data:
        return
    n = data["size"]
    field = data["field"]
    text = "```\n" + "\n".join(" ".join(row) for row in field) + "\n```"
    kb = InlineKeyboardMarkup(row_width=n)
    for i in range(n):
        row = []
        for j in range(n):
            if field[i][j] == "?":
                row.append(InlineKeyboardButton("❓", callback_data=f"mines_click_{i}_{j}"))
            else:
                row.append(InlineKeyboardButton(field[i][j], callback_data="no"))
        kb.add(*row)
    bot.send_message(uid, f"💣 Осталось: {n*n - data['score']}\n{text}", reply_markup=kb, parse_mode="Markdown")

def mines_click(uid, i, j):
    data = games_data.get(uid)
    if not data:
        return
    if (i, j) in data["mines"]:
        bot.send_message(uid, f"💥 Мина! -3💰")
        remove_coins(uid, 3)
        del games_data[uid]
        return
    if data["field"][i][j] != "?":
        return
    data["field"][i][j] = "🌿"
    data["score"] += 1
    total_cells = data["size"] * data["size"]
    if data["score"] == total_cells - len(data["mines"]):
        bot.send_message(uid, f"🏆 Победа! +5💰")
        add_coins(uid, 5)
        del games_data[uid]
        return
    mines_show(uid)

# ========== КРЕСТИКИ-НОЛИКИ ==========
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
    games_data[uid] = {"game": "tictac", "field": field, "mode": mode, "turn": "X", "players": {"X": uid}, "bet": 1}
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
        games_data[uid]["players_list"] = [uid, opp]
        bot.send_message(uid, f"✅ Противник {opp}. Твой ход X")
        bot.send_message(opp, f"🎮 Игрок {uid} вызывает на игру (X). Ты O")
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
    text = "```\n" + "\n".join("|".join(row) for row in field) + "\n```"
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
        return
    if all(data["field"][r][c] != " " for r in range(3) for c in range(3)):
        bot.send_message(uid, "Ничья! Монеты возвращены")
        add_coins(uid, 1)
        if data["mode"] == "friend" and data["players"].get("O"):
            add_coins(data["players"]["O"], 1)
            bot.send_message(data["players"]["O"], "Ничья")
        del games_data[uid]
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
            update_user(uid, theme="🌌" if theme == "space" else "🔥")
            bot.edit_message_text(f"✅ Тема куплена!", uid, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "❌ Нет монет")

    elif data == "buy_effect_lightning":
        if remove_coins(uid, 30):
            update_user(uid, effect="⚡")
            bot.edit_message_text(f"✅ Эффект куплен!", uid, call.message.message_id)
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
    print("✅ Бот с PostgreSQL запущен")
    bot.infinity_polling(skip_pending=True)
