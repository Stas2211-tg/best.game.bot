import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
import random
import json
import os
from datetime import datetime, timedelta

TOKEN = os.getenv("TOKEN")
if not TOKEN:
    print("❌ Токен не найден")
    exit(1)

ADMIN_ID = 6615344173  # ЗАМЕНИ НА СВОЙ TELEGRAM ID

bot = telebot.TeleBot(TOKEN)
DATA_FILE = "user_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(user_data, f, ensure_ascii=False, indent=2)

user_data = load_data()
waiting_for_question = {}
games_data = {}

REGIONS = ["🌍 Европа", "🌏 Азия", "🌎 Америка", "🇷🇺 Россия", "🌏 Другие"]

def region_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(*[KeyboardButton(r) for r in REGIONS])
    return kb

def get_user(uid):
    uid = str(uid)
    if uid not in user_data:
        user_data[uid] = {
            "coins": 5,
            "last_bonus": None,
            "username": None,
            "region": None,
            "current_game": None,
            "theme": "🎲",
            "effect": None
        }
        save_data()
    return user_data[uid]

def add_coins(uid, amount):
    u = get_user(uid)
    u["coins"] += amount
    save_data()

def remove_coins(uid, amount):
    u = get_user(uid)
    if u["coins"] >= amount:
        u["coins"] -= amount
        save_data()
        return True
    return False

def can_take_bonus(uid):
    u = get_user(uid)
    if not u["last_bonus"]:
        return True
    last = datetime.fromisoformat(u["last_bonus"])
    return datetime.now() - last >= timedelta(hours=24)

def all_users_list():
    return list(user_data.keys())

def global_stats():
    users = user_data.values()
    total_coins = sum(u["coins"] for u in users)
    total_users = len(users)
    avg = total_coins / total_users if total_users else 0
    top = sorted(user_data.items(), key=lambda x: x[1]["coins"], reverse=True)[:10]
    top_text = "\n".join([f"{i+1}. {u[1].get('username', u[0])} — {u[1]['coins']}💰" for i, u in enumerate(top)])
    return total_users, total_coins, avg, top_text

def region_stats():
    stats = {r: {"users": 0, "coins": 0} for r in REGIONS}
    for uid, data in user_data.items():
        reg = data.get("region")
        if reg in stats:
            stats[reg]["users"] += 1
            stats[reg]["coins"] += data["coins"]
    return stats

def active_players():
    active = []
    for uid, data in user_data.items():
        if data.get("current_game"):
            active.append((uid, data["current_game"]))
    return active

def format_profile(uid):
    user = get_user(uid)
    return (
        f"┌─────────────────────┐\n"
        f"│  👤 *{user.get('username', 'Игрок')}*\n"
        f"│  💰 Баланс: `{user['coins']}` монет\n"
        f"│  📍 Регион: {user.get('region', '❓')}\n"
        f"│  🎮 Играет: {user.get('current_game') or 'нет'}\n"
        f"└─────────────────────┘"
    )

def main_keyboard(uid):
    user = get_user(uid)
    theme = user.get("theme", "🎲")
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton(f"🎲 Игры на монеты"),
        KeyboardButton(f"💣 Сапёр (Мина)"),
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
        KeyboardButton("🎮 Активные игроки"),
        KeyboardButton("🔙 Назад")
    )
    return kb

@bot.message_handler(commands=['start'])
def start(m):
    uid = m.chat.id
    user = get_user(uid)
    if m.from_user.username:
        user["username"] = m.from_user.username.lower()
        save_data()
    if not user.get("region"):
        bot.send_message(uid, "🌍 *Выбери свой регион:*", reply_markup=region_keyboard(), parse_mode="Markdown")
    else:
        bot.send_message(uid, f"🎉 *Добро пожаловать в игровой портал!*\n\n{format_profile(uid)}", reply_markup=main_keyboard(uid), parse_mode="Markdown")

@bot.message_handler(func=lambda m: user_data.get(str(m.chat.id), {}).get("region") is None)
def set_region(m):
    uid = m.chat.id
    if m.text in REGIONS:
        user = get_user(uid)
        user["region"] = m.text
        save_data()
        bot.send_message(uid, f"✅ Регион *{m.text}* сохранён!", parse_mode="Markdown")
        bot.send_message(uid, f"🎉 *Добро пожаловать!*\n\n{format_profile(uid)}", reply_markup=main_keyboard(uid), parse_mode="Markdown")
    else:
        bot.send_message(uid, "Пожалуйста, выбери регион из кнопок 👇", reply_markup=region_keyboard())

@bot.message_handler(func=lambda m: True)
def handle_buttons(m):
    uid = m.chat.id
    text = m.text
    user = get_user(uid)

    if text == "🎲 Игры на монеты":
        gamble_menu(uid)
    elif text == "💣 Сапёр (Мина)":
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
            user["last_bonus"] = datetime.now().isoformat()
            save_data()
            bot.send_message(uid, "🎁 *+10 монет!* Завтра приходи ещё!", parse_mode="Markdown")
        else:
            bot.send_message(uid, "⏳ *Бонус уже получен.* Возвращайся завтра!", parse_mode="Markdown")
    elif text == "❓ Вопрос":
        bot.send_message(uid, "✍️ Напиши свой вопрос. Админ ответит в ближайшее время.")
        waiting_for_question[uid] = True
    elif text == "🔧 Админ" and uid == ADMIN_ID:
        admin_panel(uid)
    elif waiting_for_question.get(uid):
        forward_question(uid, text)
        waiting_for_question[uid] = False
    elif uid == ADMIN_ID:
        if text == "💰 Выдать монеты":
            bot.send_message(uid, "/addcoins ID КОЛИЧЕСТВО")
        elif text == "🔻 Забрать монеты":
            bot.send_message(uid, "/removecoins ID КОЛИЧЕСТВО")
        elif text == "👥 Все пользователи":
            users = all_users_list()
            msg = "👥 *Пользователи:*\n"
            for u in users[:30]:
                region = user_data.get(u, {}).get("region", "?")
                msg += f"🆔 {u} — {get_user(u)['coins']}💰 ({region})\n"
            bot.send_message(uid, msg, parse_mode="Markdown")
        elif text == "📢 Рассылка":
            bot.send_message(uid, "Введи сообщение для рассылки:")
            bot.register_next_step_handler(m, broadcast_message)
        elif text == "📊 Глобальная статистика":
            total_u, total_c, avg_c, top = global_stats()
            region_stats_data = region_stats()
            region_text = "\n".join([f"{r}: {v['users']} игроков, {v['coins']}💰" for r, v in region_stats_data.items()])
            bot.send_message(uid, f"📊 *Глобальная статистика*\n"
                                  f"👥 Всего игроков: {total_u}\n"
                                  f"💰 Всего монет: {total_c}\n"
                                  f"📈 Средний баланс: {avg_c:.2f}\n\n"
                                  f"🏆 *Топ-10:*\n{top}\n\n"
                                  f"🌍 *По регионам:*\n{region_text}",
                                  parse_mode="Markdown")
        elif text == "🎮 Активные игроки":
            active = active_players()
            if not active:
                bot.send_message(uid, "Сейчас никто не играет")
            else:
                msg = "🎮 *Сейчас играют:*\n"
                for uid_a, game in active:
                    msg += f"🆔 {uid_a} — {game}\n"
                bot.send_message(uid, msg, parse_mode="Markdown")
        elif text == "🔙 Назад":
            bot.send_message(uid, f"{format_profile(uid)}", reply_markup=main_keyboard(uid), parse_mode="Markdown")

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
    bot.send_message(uid, "🎲 *Казино (игры на монеты)*\n⚠️ Вход 1 монета, при проигрыше штраф -1", reply_markup=kb, parse_mode="Markdown")

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
                          f"🌟 Космос — 20 монет\n🔥 Огонь — 25 монет\n✨ Молния — 30 монет",
                          reply_markup=kb, parse_mode="Markdown")

def my_stats(uid):
    user = get_user(uid)
    region = user.get("region") or "❓"
    all_users = all_users_list()
    sorted_users = sorted(all_users, key=lambda x: user_data[x]["coins"], reverse=True)
    try:
        place = sorted_users.index(str(uid)) + 1
    except:
        place = "?"
    bot.send_message(uid, f"📊 *Твоя статистика*\n\n"
                          f"👤 Имя: {user.get('username', 'Игрок')}\n"
                          f"📍 Регион: {region}\n"
                          f"💰 Баланс: {user['coins']}\n"
                          f"🏆 Место в мире: {place}\n"
                          f"🎮 Активная игра: {user.get('current_game') or 'нет'}",
                          parse_mode="Markdown")

def admin_panel(uid):
    bot.send_message(uid, "🔧 *Админ-панель*", reply_markup=admin_keyboard(), parse_mode="Markdown")

def broadcast_message(m):
    if m.chat.id != ADMIN_ID:
        return
    text = m.text
    sent = 0
    for uid in all_users_list():
        try:
            bot.send_message(int(uid), f"📢 *Рассылка от администратора:*\n\n{text}", parse_mode="Markdown")
            sent += 1
        except:
            pass
    bot.send_message(ADMIN_ID, f"✅ Отправлено {sent} пользователям")

def forward_question(user_id, q):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("✍️ Ответить", callback_data=f"answer_{user_id}"))
    bot.send_message(ADMIN_ID, f"📩 *Вопрос от пользователя* `{user_id}`:\n\n{q}", reply_markup=kb, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("answer_"))
def answer_prompt(call):
    if call.message.chat.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Нет прав")
        return
    user_id = call.data.split("_")[1]
    bot.send_message(ADMIN_ID, f"✍️ Введи ответ для пользователя {user_id}:")
    bot.register_next_step_handler(call.message, lambda m: send_answer(m, user_id))

def send_answer(m, target_id):
    if m.chat.id != ADMIN_ID:
        return
    bot.send_message(int(target_id), f"📬 *Ответ от администратора:*\n\n{m.text}", parse_mode="Markdown")
    bot.send_message(ADMIN_ID, f"✅ Ответ отправлен пользователю {target_id}")

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

# ========== АЗАРТНЫЕ ИГРЫ ==========
def gamble_dice1_handler(uid):
    bot.send_message(uid, "🎲 Введи число от 1 до 6:")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_dice1_play(m, uid))

def gamble_dice1_play(m, uid):
    try:
        bet = int(m.text)
        if bet < 1 or bet > 6:
            bot.send_message(uid, "❌ Число должно быть от 1 до 6")
            return
        if not remove_coins(uid, 1):
            bot.send_message(uid, "❌ Недостаточно монет")
            return
        roll = random.randint(1, 6)
        if bet == roll:
            win = random.randint(2, 5)
            add_coins(uid, win)
            bot.send_message(uid, f"🎲 Выпало *{roll}*. Ты угадал! +{win} монет", parse_mode="Markdown")
        else:
            remove_coins(uid, 1)
            bot.send_message(uid, f"🎲 Выпало *{roll}*. Ты проиграл 2 монеты", parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ Введи число")

def gamble_dice2_handler(uid):
    bot.send_message(uid, "🎲🎲 Введи сумму от 2 до 12:")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_dice2_play(m, uid))

def gamble_dice2_play(m, uid):
    try:
        bet = int(m.text)
        if bet < 2 or bet > 12:
            bot.send_message(uid, "❌ Сумма должна быть от 2 до 12")
            return
        if not remove_coins(uid, 1):
            bot.send_message(uid, "❌ Недостаточно монет")
            return
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2
        if bet == total:
            win = random.randint(4, 10)
            add_coins(uid, win)
            bot.send_message(uid, f"🎲 {d1}+{d2}={total}. Угадал! +{win} монет", parse_mode="Markdown")
        else:
            remove_coins(uid, 1)
            bot.send_message(uid, f"🎲 {d1}+{d2}={total}. Проиграл 2 монеты", parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ Введи число")

def gamble_number_handler(uid):
    bot.send_message(uid, "🔢 Введи число от 1 до 20:")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_number_play(m, uid))

def gamble_number_play(m, uid):
    try:
        bet = int(m.text)
        if bet < 1 or bet > 20:
            bot.send_message(uid, "❌ Число должно быть от 1 до 20")
            return
        if not remove_coins(uid, 1):
            bot.send_message(uid, "❌ Недостаточно монет")
            return
        secret = random.randint(1, 20)
        if bet == secret:
            win = random.randint(5, 12)
            add_coins(uid, win)
            bot.send_message(uid, f"🔢 Загадано *{secret}*. Угадал! +{win} монет", parse_mode="Markdown")
        else:
            remove_coins(uid, 1)
            bot.send_message(uid, f"🔢 Загадано *{secret}*. Проиграл 2 монеты", parse_mode="Markdown")
    except:
        bot.send_message(uid, "❌ Введи число")

def gamble_rps_handler(uid):
    bot.send_message(uid, "✂️ Введи: камень, ножницы или бумага")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_rps_play(m, uid))

def gamble_rps_play(m, uid):
    choice = m.text.lower()
    if choice not in ["камень", "ножницы", "бумага"]:
        bot.send_message(uid, "❌ Напиши: камень, ножницы или бумага")
        return
    if not remove_coins(uid, 1):
        bot.send_message(uid, "❌ Недостаточно монет")
        return
    bot_choice = random.choice(["камень", "ножницы", "бумага"])
    if choice == bot_choice:
        add_coins(uid, 2)
        bot.send_message(uid, f"Ничья! +2 монеты")
    elif (choice == "камень" and bot_choice == "ножницы") or (choice == "ножницы" and bot_choice == "бумага") or (choice == "бумага" and bot_choice == "камень"):
        win = random.randint(3, 7)
        add_coins(uid, win)
        bot.send_message(uid, f"Победа! +{win} монет")
    else:
        remove_coins(uid, 1)
        bot.send_message(uid, f"Поражение. -2 монеты")

def gamble_oracle_handler(uid):
    bot.send_message(uid, "🔮 Оракул. Введи 'Да' или 'Нет':")
    bot.register_next_step_handler_by_chat_id(uid, lambda m: gamble_oracle_play(m, uid))

def gamble_oracle_play(m, uid):
    user_ans = m.text.lower()
    if user_ans not in ["да", "нет"]:
        bot.send_message(uid, "❌ Напиши: Да или Нет")
        return
    if not remove_coins(uid, 1):
        bot.send_message(uid, "❌ Недостаточно монет")
        return
    oracle = random.choice(["да", "нет"])
    if user_ans == oracle:
        add_coins(uid, 3)
        bot.send_message(uid, f"🔮 Оракул сказал: *{oracle}*. Ты угадал! +3 монеты", parse_mode="Markdown")
    else:
        remove_coins(uid, 1)
        bot.send_message(uid, f"🔮 Оракул сказал: *{oracle}*. Ты ошибся. -2 монеты", parse_mode="Markdown")

# ========== САПЁР (МИНА) ==========
def mines_menu(uid):
    kb = InlineKeyboardMarkup(row_width=3)
    kb.add(
        InlineKeyboardButton("5x5", callback_data="mines_5"),
        InlineKeyboardButton("8x8", callback_data="mines_8"),
        InlineKeyboardButton("10x10", callback_data="mines_10"),
        InlineKeyboardButton("◀️ Назад", callback_data="back_main")
    )
    bot.send_message(uid, "💣 *Сапёр (Мина)*\n⚠️ Вход 1 монета. Наступил на мину → -3 монеты. Прошёл все → +5 монет\nВыбери размер поля:", reply_markup=kb, parse_mode="Markdown")

def mines_start(uid, size):
    if not remove_coins(uid, 1):
        bot.send_message(uid, "❌ Недостаточно монет для игры")
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
    text = "```\n"
    for row in field:
        text += " ".join(row) + "\n"
    text += "```"
    kb = InlineKeyboardMarkup(row_width=n)
    for i in range(n):
        row_btns = []
        for j in range(n):
            if field[i][j] == "?":
                row_btns.append(InlineKeyboardButton("❓", callback_data=f"mines_click_{i}_{j}"))
            else:
                row_btns.append(InlineKeyboardButton(field[i][j], callback_data="no"))
        kb.add(*row_btns)
    bot.send_message(uid, f"💣 Осталось закрытых: {n*n - data['score']}\n{text}", reply_markup=kb, parse_mode="Markdown")

def mines_click(uid, i, j):
    data = games_data.get(uid)
    if not data:
        return
    if (i, j) in data["mines"]:
        bot.send_message(uid, f"💥 Ты подорвался на мине! -3 монеты")
        remove_coins(uid, 3)
        del games_data[uid]
        return
    if data["field"][i][j] != "?":
        return
    data["field"][i][j] = "🌿"
    data["score"] += 1
    if data["score"] == data["size"] * data["size"] - len(data["mines"]):
        bot.send_message(uid, f"🏆 Победа! +5 монет")
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
    bot.send_message(uid, "❌⭕ *Крестики-нолики*\n⚠️ Вход 1 монета. Победитель получает +3 монеты\nВыбери режим:", reply_markup=kb, parse_mode="Markdown")

def tictac_start(uid, mode):
    if not remove_coins(uid, 1):
        bot.send_message(uid, "❌ Недостаточно монет для игры")
        return
    field = [[" " for _ in range(3)] for _ in range(3)]
    games_data[uid] = {"game": "tictac", "field": field, "mode": mode, "turn": "X", "players": {"X": uid}, "bet": 1}
    if mode == "friend":
        bot.send_message(uid, "Введи ID противника (число):")
        bot.register_next_step_handler_by_chat_id(uid, lambda m: set_opponent(m, uid))
    else:
        tictac_show(uid)

def set_opponent(m, uid):
    try:
        opp = int(m.text)
        if opp == uid:
            bot.send_message(uid, "❌ Нельзя играть с самим собой")
            add_coins(uid, 1)
            del games_data[uid]
            return
        if not remove_coins(opp, 1):
            bot.send_message(uid, f"❌ У пользователя {opp} недостаточно монет")
            add_coins(uid, 1)
            del games_data[uid]
            return
        games_data[uid]["players"]["O"] = opp
        games_data[uid]["players_list"] = [uid, opp]
        bot.send_message(uid, f"✅ Противник {opp} добавлен. Твой ход (X)")
        bot.send_message(opp, f"🎮 Игрок {uid} вызывает тебя на крестики-нолики (1 монета). Твои ходы (O)")
        tictac_show(uid)
    except:
        bot.send_message(uid, "❌ Введи числовой ID")
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
        row_btns = []
        for j in range(3):
            if field[i][j] == " ":
                row_btns.append(InlineKeyboardButton("⬜", callback_data=f"tictac_move_{i}_{j}"))
            else:
                row_btns.append(InlineKeyboardButton(field[i][j], callback_data="no"))
        kb.add(*row_btns)
    bot.send_message(uid, f"Ход: {data['turn']}\n{text}", reply_markup=kb, parse_mode="Markdown")
    if data["mode"] == "friend" and data.get("players", {}).get("O"):
        opp = data["players"]["O"]
        bot.send_message(opp, f"Ход: {data['turn']}\n{text}", reply_markup=kb, parse_mode="Markdown")

def tictac_move(uid, i, j):
    data = games_data.get(uid)
    if not data:
        return
    current_player = uid if data["turn"] == "X" else data["players"].get("O")
    if current_player != uid:
        return
    if data["field"][i][j] != " ":
        return
    data["field"][i][j] = data["turn"]
    winner = check_winner(data["field"])
    if winner:
        win_amount = 3
        add_coins(uid, win_amount)
        bot.send_message(uid, f"🏆 Победил {winner}! +{win_amount} монет")
        if data["mode"] == "friend" and data.get("players", {}).get("O"):
            bot.send_message(data["players"]["O"], f"🏆 Победил {winner}!")
        del games_data[uid]
        return
    if all(data["field"][r][c] != " " for r in range(3) for c in range(3)):
        bot.send_message(uid, "Ничья! Монеты возвращены")
        add_coins(uid, 1)
        if data["mode"] == "friend" and data.get("players", {}).get("O"):
            add_coins(data["players"]["O"], 1)
            bot.send_message(data["players"]["O"], "Ничья! Монеты возвращены")
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

# ========== ОБРАБОТЧИК CALLBACK ==========
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    uid = call.message.chat.id
    data = call.data

    if data == "back_main":
        bot.edit_message_text("🎮 Главное меню", uid, call.message.message_id)
        bot.send_message(uid, f"{format_profile(uid)}", reply_markup=main_keyboard(uid), parse_mode="Markdown")
    elif data.startswith("buy_theme_"):
        theme = data.split("_")[2]
        price = {"space": 20, "fire": 25}.get(theme, 0)
        if remove_coins(uid, price):
            user = get_user(uid)
            user["theme"] = "🌌" if theme == "space" else "🔥"
            save_data()
            bot.edit_message_text(f"✅ Тема '{'Космос' if theme == 'space' else 'Огонь'}' куплена!", uid, call.message.message_id)
            bot.send_message(uid, f"{format_profile(uid)}", reply_markup=main_keyboard(uid), parse_mode="Markdown")
        else:
            bot.answer_callback_query(call.id, "❌ Недостаточно монет")
    elif data == "buy_effect_lightning":
        if remove_coins(uid, 30):
            user = get_user(uid)
            user["effect"] = "⚡"
            save_data()
            bot.edit_message_text("✅ Эффект 'Молния' активирован!", uid, call.message.message_id)
        else:
            bot.answer_callback_query(call.id, "❌ Недостаточно монет")
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
    elif data == "tictac_bot":
        tictac_start(uid, "bot")
    elif data == "tictac_friend":
        tictac_start(uid, "friend")
    elif data.startswith("tictac_move_"):
        _, _, i, j = data.split("_")
        tictac_move(uid, int(i), int(j))
    elif data.startswith("mines_"):
        if data == "mines_5":
            mines_start(uid, 5)
        elif data == "mines_8":
            mines_start(uid, 8)
        elif data == "mines_10":
            mines_start(uid, 10)
    elif data.startswith("mines_click_"):
        _, _, i, j = data.split("_")
        mines_click(uid, int(i), int(j))

if __name__ == "__main__":
    print("✅ Бот с платными играми и без канала запущен")
    bot.infinity_polling(skip_pending=True)
