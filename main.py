import asyncio
import json
import logging
import random
import os
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta, timezone
from collections import Counter
import aiofiles
from keep_alive import keep_alive  # Импорт веб-сервера для Replit

# ====================== КОНСТАНТЫ ======================
API_TOKEN = os.getenv('API_TOKEN')  # Токен из секретов Replit
ADMIN_USERNAMES = ["CO7163", "OLRMS", "nugopac2"]
FINAL_EVENT_TIME = datetime(2025, 10, 31, 21, 0, 0, tzinfo=timezone.utc)
RAID_INTERVAL = 3 * 3600
LICORICE_PRICE = 15
CLAN_LICORICE_PRICE = 30
CLAN_WAR_COST = 50
MAX_CLAN_MEMBERS = 20
SAVE_INTERVAL = 5  # Секунды для отложенного сохранения

# ====================== ЛОГИ ======================
logging.basicConfig(
    level=logging.DEBUG,
    filename="bot.log",
    filemode="a",
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ====================== ИНИЦИАЛИЗАЦИЯ ======================
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()

CANDIES_FILE = "candies.json"
PROMOS_FILE = "promos.json"
CHATS_FILE = "chats.json"
CLANS_FILE = "clans.json"

# ====================== JSON HELPERS ======================
async def load_json(file, default):
    try:
        async with aiofiles.open(file, mode="r", encoding="utf-8") as f:
            content = await f.read()
            data = json.loads(content)
            if file == CLANS_FILE:
                for clan in data.values():
                    if "licorice" not in clan:
                        clan["licorice"] = 0
            return data
    except FileNotFoundError:
        logging.warning(f"Файл {file} не найден, используется значение по умолчанию")
        return default
    except json.JSONDecodeError as e:
        logging.error(f"Ошибка декодирования JSON в {file}: {e}")
        return default
    except Exception as e:
        logging.error(f"Неизвестная ошибка при загрузке {file}: {e}")
        return default

async def save_json(file, data):
    try:
        async with aiofiles.open(file, mode="w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))
    except PermissionError:
        logging.error(f"Нет прав на запись в файл {file}")
    except Exception as e:
        logging.error(f"Ошибка сохранения {file}: {e}")

candies = await load_json(CANDIES_FILE, {})
promo_codes = await load_json(PROMOS_FILE, {})
active_chats = await load_json(CHATS_FILE, [])
clans = await load_json(CLANS_FILE, {})  # { "clan_name": { "owner": uid, "members": [], "candies": 0, "licorice": 0 } }

# Отложенное сохранение
_save_pending = False
async def save_all():
    global _save_pending
    if _save_pending:
        return
    _save_pending = True
    await asyncio.sleep(SAVE_INTERVAL)
    await save_json(CANDIES_FILE, candies)
    await save_json(PROMOS_FILE, promo_codes)
    await save_json(CHATS_FILE, active_chats)
    await save_json(CLANS_FILE, clans)
    _save_pending = False

# ====================== ЧАТЫ ======================
def add_chat(chat_id):
    if chat_id not in active_chats:
        active_chats.append(chat_id)
        asyncio.create_task(save_all())

# ====================== ПОЛЬЗОВАТЕЛЬ ======================
def get_user_data(user_id: str):
    uid = str(user_id)
    if uid not in candies:
        candies[uid] = {
            "candies": 10,
            "total_candies": 10,
            "last_claim": None,
            "costume": None,
            "owned_costumes": [],
            "active_potions": {},
            "owned_potions": [],
            "licorice": 0,
            "challenges": {"steal": 0, "give": 0, "buy": 0},
            "last_challenge_reset": None,
            "duel_wins": 0,
            "attacks_today": 0,
            "last_attack_date": None,
            "buys_today": 0,
            "last_buy_date": None,
            "gives_today": 0,
            "last_give_date": None,
            "clan": None
        }
    user = candies[uid]
    today = datetime.now().date().isoformat()
    if user.get("last_attack_date") != today:
        user["attacks_today"] = 0
        user["last_attack_date"] = today
    if user.get("last_buy_date") != today:
        user["buys_today"] = 0
        user["last_buy_date"] = today
    if user.get("last_give_date") != today:
        user["gives_today"] = 0
        user["last_give_date"] = today
    if user.get("last_challenge_reset") != today:
        user["challenges"] = {"steal": 0, "give": 0, "buy": 0}
        user["last_challenge_reset"] = today
    return user

def add_candies(user_id: str, amount: int):
    user = get_user_data(user_id)
    user["candies"] += amount
    user["total_candies"] += amount
    if user["clan"]:
        clan = clans.get(user["clan"])
        if clan:
            clan["candies"] += amount
    asyncio.create_task(save_all())

def remove_candies(user_id: str, amount: int):
    user = get_user_data(user_id)
    user["candies"] = max(0, user["candies"] - amount)
    asyncio.create_task(save_all())

def get_current_bonus(user_id: str):
    user = get_user_data(user_id)
    bonus = 0
    if user.get("costume"):
        bonus += costumes_data[user["costume"]]["bonus"]
    pots = user.get("active_potions", {})
    if "perm_boost" in pots:
        bonus += pots["perm_boost"]
    if "temp_boost" in pots:
        try:
            exp = datetime.fromisoformat(pots["temp_boost"])
            if datetime.now(timezone.utc) < exp:
                bonus += 2
            else:
                del pots["temp_boost"]
        except:
            del pots["temp_boost"]
    return bonus

# ====================== ДАННЫЕ ======================
costumes_data = {
    "ghost": {"name": "Призрак", "bonus": 3, "price": 40},
    "vampire": {"name": "Вампир", "bonus": 5, "price": 70},
    "freddy": {"name": "Фредди", "bonus": 6, "price": 90},
    "jason": {"name": "Джейсон", "bonus": 8, "price": 100},
    "barry": {"name": "Барри", "bonus": 9, "price": 0}
}

potions_data = {
    "temp_boost": {"name": "Зелье временного бонуса", "bonus": 2, "price": 50, "duration": 30},
    "perm_boost": {"name": "Зелье постоянного бонуса", "bonus": 2, "price": 100}
}

RAID_ACTIVE = {}
cooldowns = {}
clan_war_cooldowns = {}

# FSM для присоединения к клану
class ClanStates(StatesGroup):
    JOIN_CLAN = State()

# ====================== АДМИН-ПРОВЕРКА ======================
async def is_admin(user_id: int) -> bool:
    try:
        user = await bot.get_chat(user_id)
        return user.username in ADMIN_USERNAMES
    except Exception as e:
        logging.error(f"Ошибка проверки админа {user_id}: {e}")
        return False

# ====================== КОМАНДЫ ======================

@router.message(Command("start"))
async def start_cmd(message: types.Message):
    add_chat(message.chat.id)
    await message.reply("HALLOWEEN BOT\n/trickortreat — играй!\n/help — команды")

@router.message(Command("help"))
async def help_command(message: types.Message):
    add_chat(message.chat.id)
    text = (
        "HALLOWEEN CANDY BOT v2.0\n\n"
        "Цель: кидай /trickortreat другим игрокам, чтобы украсть конфеты или получить мут!\n"
        "Собирай больше всех — стань королём Хэллоуина!\n\n"
        "ОСНОВНЫЕ КОМАНДЫ:\n"
        "/daily — получить 10 конфет каждые 24 часа\n"
        "/balance — посмотреть свой баланс\n"
        "/top — топ-5 игроков по собранным конфетам\n"
        "/trickortreat — реплай на игрока → 'Сладость или гадость'\n"
        "/give N — реплай → передать N конфет\n"
        "/shop — открыть магазин\n"
        "/inventory — посмотреть и использовать инвентарь\n"
        "/profile — профиль игрока (или реплай на игрока)\n"
        "/promo CODE — активировать промокод\n"
        "/challenges — ежедневные задания\n"
        "/claim — забрать награды\n"
        "/duel — реплай → дуэль 1 на 1\n\n"
        "КЛАНЫ:\n"
        "/clan — управление кланом (создать, выйти, топ)\n"
        "/joinclan — присоединиться к клану\n"
        "/topclans — топ-5 кланов по конфетам\n"
        "/clanwar — реплай на сообщение с названием клана → война кланов\n"
        "/buyclanlicorice — купить лакрицу для клана\n\n"
        "ФИЧИ:\n"
        "• Костюмы — дают бонус к конфетам\n"
        "• Зелья — усиливают бонус\n"
        "• Лакрица — защищает от кражи\n"
        "• Групповые рейды — удвоенные конфеты каждые 3 часа\n"
        "• Финальный ивент: 31 октября 21:00 UTC — x5 конфеты!\n\n"
        "АДМИН-КОМАНДЫ:\n"
        "/admin — статистика, рассылка, управление\n"
        "/announce TEXT — рассылка по всем чатам\n"
        "/addcandies — реплай на игрока + N конфет → дать конфеты\n"
        "/removecandies — реплай на игрока + N конфет → забрать конфеты\n"
        "/createpromo CODE N — создать промокод\n"
        "/deletepromo CODE — удалить промокод\n"
        "/listpromos — список промокодов"
    )
    await message.reply(text)

@router.message(Command("daily"))
async def daily(message: types.Message):
    add_chat(message.chat.id)
    uid = str(message.from_user.id)
    user = get_user_data(uid)
    now = datetime.now(timezone.utc)
    last = user.get("last_claim")
    if last and now - datetime.fromisoformat(last) < timedelta(hours=24):
        await message.reply("Подожди 24 часа!")
        return
    add_candies(uid, 10)
    user["last_claim"] = now.isoformat()
    await message.reply("Ты получил 10 конфет!")

@router.message(Command("balance"))
async def balance(message: types.Message):
    add_chat(message.chat.id)
    uid = str(message.from_user.id)
    user = get_user_data(uid)
    await message.reply(f"Конфет: {user['candies']}\nВсего: {user['total_candies']}")

@router.message(Command("top"))
async def top(message: types.Message):
    add_chat(message.chat.id)
    sorted_users = sorted(candies.items(), key=lambda x: x[1]["total_candies"], reverse=True)[:5]
    text = "ТОП-5 ПО СОБРАННЫМ КОНФЕТАМ:\n"
    for i, (uid, data) in enumerate(sorted_users, 1):
        try:
            user = await bot.get_chat(int(uid))
            name = user.first_name
        except Exception as e:
            logging.error(f"Ошибка получения пользователя {uid}: {e}")
            name = f"User #{uid}"
        text += f"{i}. {name} — {data['total_candies']}\n"
    await message.reply(text or "Пока никто не играл.")

@router.message(Command("give"))
async def give_candies(message: types.Message):
    add_chat(message.chat.id)
    uid = str(message.from_user.id)
    if not message.reply_to_message:
        await message.reply("Реплай на пользователя: /give N")
        return
    p = message.text.split()[1:]
    if len(p) != 1 or not p[0].isdigit():
        await message.reply("Формат: /give N (реплай на пользователя)")
        return
    amt = int(p[0])
    tid = str(message.reply_to_message.from_user.id)
    tname = message.reply_to_message.from_user.first_name
    if amt <= 0 or tid == uid:
        await message.reply("Нельзя")
        return
    giver = get_user_data(uid)
    if giver["candies"] < amt:
        await message.reply("Недостаточно конфет")
        return
    try:
        await bot.get_chat(int(tid))  # Проверка существования пользователя
        get_user_data(tid)
    except Exception as e:
        logging.error(f"Ошибка получения пользователя {tid}: {e}")
        await message.reply("Пользователь не найден")
        return
    remove_candies(uid, amt)
    add_candies(tid, amt)
    giver["gives_today"] += amt
    giver["challenges"]["give"] += amt
    await save_all()
    await message.reply(f"Передано {amt} конфет → {tname}")

@router.message(Command("shop"))
async def shop(message: types.Message):
    add_chat(message.chat.id)
    uid = str(message.from_user.id)
    user = get_user_data(uid)
    kb = []
    text = "МАГАЗИН ХЭЛЛОУИНА\n\nКОСТЮМЫ:\n"
    for key, data in costumes_data.items():
        if key == "barry" and key not in user["owned_costumes"]:
            continue
        owned = "Уже куплено" if key in user["owned_costumes"] else ""
        kb.append([InlineKeyboardButton(
            text=f"{owned} {data['name']} (+{data['bonus']}) — {data['price']} конфет",
            callback_data=f"buy_costume_{key}"
        )])
    text += "\nЗЕЛЬЯ:\n"
    for key, data in potions_data.items():
        kb.append([InlineKeyboardButton(
            text=f"{data['name']} (+{data['bonus']}) — {data['price']} конфет",
            callback_data=f"buy_potion_{key}"
        )])
    text += f"\nЛакрица (личная) — {LICORICE_PRICE} конфет\n"
    text += f"Лакрица (для клана) — {CLAN_LICORICE_PRICE} конфет\n"
    kb.append([InlineKeyboardButton(text="Купить лакрицу (личную)", callback_data="buy_licorice")])
    if user["clan"]:
        kb.append([InlineKeyboardButton(text="Купить лакрицу (для клана)", callback_data="buy_clan_licorice")])
    await message.reply(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.message(Command("inventory"))
async def inventory(message: types.Message):
    add_chat(message.chat.id)
    uid = str(message.from_user.id)
    user = get_user_data(uid)
    kb = []
    text = "ИНВЕНТАРЬ\n\n"
    if user["owned_costumes"]:
        text += "КОСТЮМЫ:\n"
        for key in user["owned_costumes"]:
            data = costumes_data[key]
            active = " (надет)" if user["costume"] == key else ""
            kb.append([InlineKeyboardButton(text=f"{data['name']}{active}", callback_data=f"use_costume_{key}")])
    else:
        text += "Костюмов нет\n"
    if user["owned_potions"]:
        text += "\nЗЕЛЬЯ:\n"
        count = Counter(user["owned_potions"])
        for key, qty in count.items():
            data = potions_data[key]
            kb.append([InlineKeyboardButton(text=f"{data['name']} ×{qty}", callback_data=f"use_potion_{key}")])
    else:
        text += "\nЗелий нет\n"
    text += f"\nЛакрица: {user['licorice']} шт."
    if user["clan"]:
        text += f"\nЛакрица клана: {clans[user['clan']]['licorice']} шт."
    await message.reply(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb) if kb else None)

@router.message(Command("profile"))
async def profile(message: types.Message):
    add_chat(message.chat.id)
    if message.reply_to_message:
        uid = str(message.reply_to_message.from_user.id)
        name = message.reply_to_message.from_user.first_name
    else:
        uid = str(message.from_user.id)
        name = message.from_user.first_name
    user = get_user_data(uid)
    bonus = get_current_bonus(uid)
    costume = costumes_data.get(user["costume"], {"name": "Нет"})["name"] if user["costume"] else "Нет"
    clan_text = f"\nКлан: {user['clan']}" if user["clan"] else ""
    text = (
        f"ПРОФИЛЬ: {name}\n\n"
        f"Конфет: {user['candies']}\n"
        f"Всего собрано: {user['total_candies']}\n"
        f"Костюм: {costume}\n"
        f"Бонус: +{bonus}\n"
        f"Лакрица: {user['licorice']}\n"
        f"Побед в дуэлях: {user.get('duel_wins', 0)}"
        f"{clan_text}"
    )
    await message.reply(text)

@router.message(Command("challenges"))
async def challenges(message: types.Message):
    add_chat(message.chat.id)
    uid = str(message.from_user.id)
    user = get_user_data(uid)
    c = user["challenges"]
    text = "ЕЖЕДНЕВНЫЕ ЗАДАНИЯ:\n\n"
    text += f"1. Украсть 3 раза — {c['steal']}/3\n"
    text += f"2. Передать 50 конфет — {c['give']}/50\n"
    text += f"3. Купить в магазине — {c['buy']}/1\n\n"
    if c["steal"] >= 3 or c["give"] >= 50 or c["buy"] >= 1:
        text += "Награды доступны: /claim"
    else:
        text += "Наград нет."
    await message.reply(text)

@router.message(Command("claim"))
async def claim_rewards(message: types.Message):
    add_chat(message.chat.id)
    uid = str(message.from_user.id)
    user = get_user_data(uid)
    c = user["challenges"]
    reward = 0
    licorice = 0
    if c["steal"] >= 3:
        reward += 20
        c["steal"] = 0
    if c["give"] >= 50:
        reward += 30
        c["give"] = 0
    if c["buy"] >= 1:
        licorice += 1
        c["buy"] = 0
    if reward > 0:
        add_candies(uid, reward)
    if licorice > 0:
        user["licorice"] += licorice
    await save_all()
    await message.reply(f"Получено: +{reward} конфет, +{licorice} лакрица")

@router.message(Command("duel"))
async def duel(message: types.Message):
    add_chat(message.chat.id)
    attacker = str(message.from_user.id)
    if not message.reply_to_message:
        await message.reply("Реплай на пользователя!")
        return
    target = str(message.reply_to_message.from_user.id)
    if target == attacker:
        await message.reply("Нельзя себе!")
        return
    attacker_user = get_user_data(attacker)
    victim = get_user_data(target)
    if attacker_user["candies"] < 10:
        await message.reply("Нужно 10 конфет")
        return
    remove_candies(attacker, 10)
    if victim["candies"] < 10:
        add_candies(attacker, 10)
        await message.reply("У соперника мало конфет")
        return
    remove_candies(target, 10)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Камень", callback_data=f"duel_rock_{attacker}_{target}")],
        [InlineKeyboardButton(text="Ножницы", callback_data=f"duel_scissors_{attacker}_{target}")],
        [InlineKeyboardButton(text="Бумага", callback_data=f"duel_paper_{attacker}_{target}")]
    ])
    await message.reply("Дуэль! Выбери:", reply_markup=kb)

@router.message(Command("buyclanlicorice"))
async def buy_clan_licorice(message: types.Message):
    add_chat(message.chat.id)
    uid = str(message.from_user.id)
    user = get_user_data(uid)
    if not user["clan"]:
        await message.reply("Ты не в клане!")
        return
    if user["candies"] < CLAN_LICORICE_PRICE:
        await message.reply("Недостаточно конфет!")
        return
    remove_candies(uid, CLAN_LICORICE_PRICE)
    clans[user["clan"]]["licorice"] += 1
    user["challenges"]["buy"] += 1
    await save_all()
    await message.reply("Лакрица для клана куплена!")

# ====================== ВОЙНА КЛАНОВ ======================
@router.message(Command("clanwar"))
async def clan_war(message: types.Message):
    add_chat(message.chat.id)
    uid = str(message.from_user.id)
    user = get_user_data(uid)
    
    if not user["clan"]:
        await message.reply("Ты не в клане!")
        return
    if clans[user["clan"]]["owner"] != uid:
        await message.reply("Только владелец клана может начинать войну!")
        return
    if not message.reply_to_message:
        await message.reply("Реплай на сообщение с названием клана!")
        return
    target_clan = message.reply_to_message.text.strip()
    if target_clan not in clans:
        await message.reply("Клан не найден!")
        return
    attacker_clan = user["clan"]
    if attacker_clan == target_clan:
        await message.reply("Нельзя атаковать свой клан!")
        return
    
    now = datetime.now(timezone.utc)
    last = clan_war_cooldowns.get(attacker_clan)  # Кулдаун по клану
    if last and now - last < timedelta(minutes=10):
        rem = 600 - int((now - last).total_seconds())
        m, s = divmod(rem, 60)
        await message.reply(f"Подожди {m}м {s}с")
        return
    clan_war_cooldowns[attacker_clan] = now
    
    attacker_clan_data = clans[attacker_clan]
    if attacker_clan_data["candies"] < CLAN_WAR_COST:
        await message.reply(f"Нужно {CLAN_WAR_COST} конфет в казне клана!")
        return
    
    attacker_clan_data["candies"] -= CLAN_WAR_COST
    
    multiplier = 1
    if message.chat.id in RAID_ACTIVE and RAID_ACTIVE[message.chat.id] > now:
        multiplier *= 2
    if now >= FINAL_EVENT_TIME:
        multiplier *= 5
    
    bonus = get_current_bonus(attacker_clan_data["owner"])
    target_clan_data = clans[target_clan]
    if target_clan_data["licorice"] > 0:
        target_clan_data["licorice"] -= 1
        await save_all()
        await message.reply(f"Клан {target_clan} защищён лакрицей! Атака провалилась.\nЛакриц у {target_clan}: {target_clan_data['licorice']}")
        return
    
    attacker_members = len(attacker_clan_data["members"]) + 1
    target_members = len(target_clan_data["members"]) + 1
    success_chance = 0.6 * (attacker_members / max(target_members, 1))
    success = random.random() < success_chance
    if success:
        steal_amount = (20 + bonus) * multiplier
        steal_amount = min(steal_amount, target_clan_data["candies"])
        target_clan_data["candies"] = max(0, target_clan_data["candies"] - steal_amount)
        attacker_clan_data["candies"] += steal_amount
        await message.reply(f"Атака успешна! Клан {attacker_clan} украл {steal_amount} конфет у {target_clan}!")
        try:
            await bot.send_message(target_clan_data["owner"], f"Ваш клан {target_clan} был атакован кланом {attacker_clan}! Потеряно {steal_amount} конфет.")
        except Exception as e:
            logging.error(f"Ошибка отправки уведомления владельцу клана {target_clan}: {e}")
    else:
        await message.reply(f"Атака провалилась! Клан {target_clan} отбился.")
    await save_all()

# ====================== TRICK OR TREAT ======================
@router.message(Command("trickortreat", ignore_case=True))
async def trick_or_treat(message: types.Message):
    logging.warning(f"TRICKORTREAT: от {message.from_user.id}")
    add_chat(message.chat.id)
    attacker = str(message.from_user.id)
    user = get_user_data(attacker)
    user["attacks_today"] += 1
    user["challenges"]["steal"] += 1

    if not message.reply_to_message:
        await message.reply("Реплай на пользователя!")
        return
    target = str(message.reply_to_message.from_user.id)
    tname = message.reply_to_message.from_user.first_name or f"#{target}"

    if target == attacker:
        await message.reply("Нельзя себе!")
        return

    now = datetime.now(timezone.utc)
    last = cooldowns.get(attacker)
    if last and now - last < timedelta(minutes=10):
        rem = 600 - int((now - last).total_seconds())
        m, s = divmod(rem, 60)
        await message.reply(f"Подожди {m}м {s}с")
        return
    cooldowns[attacker] = now

    multiplier = 1
    if message.chat.id in RAID_ACTIVE and RAID_ACTIVE[message.chat.id] > now:
        multiplier *= 2
    if now >= FINAL_EVENT_TIME:
        multiplier *= 5

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Сладость", callback_data=f"sweet_{attacker}_{target}_{multiplier}")],
        [InlineKeyboardButton(text="Гадость", callback_data=f"trick_{attacker}_{target}")]
    ])
    msg = await message.reply(f"{tname}, тебе кинули 'Сладость или гадость'!\nВыбор: 2 минуты.", reply_markup=kb)
    asyncio.create_task(remove_markup_later(msg))

# ====================== CALLBACKS ======================
async def remove_markup_later(msg: types.Message):
    await asyncio.sleep(120)
    try:
        await msg.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logging.error(f"Ошибка удаления разметки: {e}")

@router.callback_query(F.data.startswith("sweet_") | F.data.startswith("trick_"))
async def process_choice(callback: types.CallbackQuery):
    try:
        if callback.message.reply_markup is None:
            await callback.answer("Уже обработано!", show_alert=True)
            return
        parts = callback.data.split("_")
        choice = parts[0]
        att, vic = parts[1], parts[2]
        multiplier = int(parts[3]) if len(parts) > 3 and choice == "sweet" else 1
        if str(callback.from_user.id) != vic:
            await callback.answer("Не твой выбор!", show_alert=True)
            return
        attacker = get_user_data(att)
        victim = get_user_data(vic)
        bonus = get_current_bonus(att)
        now = datetime.now(timezone.utc)
        if choice == "sweet":
            if victim["licorice"] > 0:
                victim["licorice"] -= 1
                text = f"Сладость! Но была лакрица.\nЛакриц: {victim['licorice']}"
            else:
                loss = 5
                remove_candies(vic, loss)
                add_candies(att, (5 + bonus) * multiplier)
                text = f"Сладость!\nУкрадено: {loss * multiplier} + {bonus * multiplier} бонус"
            await save_all()
        else:
            try:
                await bot.restrict_chat_member(
                    callback.message.chat.id, int(vic),
                    types.ChatPermissions(can_send_messages=False),
                    until_date=now + timedelta(minutes=2)
                )
                text = "Гадость! Мут 2 минуты."
            except Exception as e:
                logging.error(f"Ошибка мута пользователя {vic}: {e}")
                await callback.answer("Не удалось замутить.", show_alert=True)
                return
        await callback.message.edit_text(text)
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logging.error(f"Ошибка в sweet/trick: {e}")

@router.callback_query(F.data.startswith("buy_"))
async def buy_item(callback: types.CallbackQuery):
    uid = str(callback.from_user.id)
    user = get_user_data(uid)
    item = callback.data.split("_", 1)[1]
    if item.startswith("costume_"):
        key = item.split("_")[1]
        price = costumes_data[key]["price"]
        if user["candies"] < price:
            await callback.answer("Недостаточно конфет!")
            return
        if key in user["owned_costumes"]:
            await callback.answer("Уже куплено!")
            return
        remove_candies(uid, price)
        user["owned_costumes"].append(key)
        if not user["costume"]:
            user["costume"] = key
        user["challenges"]["buy"] += 1
        await save_all()
        await callback.answer(f"Куплено: {costumes_data[key]['name']}!")
        await callback.message.edit_reply_markup(reply_markup=None)
    elif item.startswith("potion_"):
        key = item.split("_")[1]
        price = potions_data[key]["price"]
        if user["candies"] < price:
            await callback.answer("Недостаточно конфет!")
            return
        remove_candies(uid, price)
        user["owned_potions"].append(key)
        await save_all()
        await callback.answer(f"Куплено: {potions_data[key]['name']}!")
        await callback.message.edit_reply_markup(reply_markup=None)
    elif item == "licorice":
        if user["candies"] < LICORICE_PRICE:
            await callback.answer("Недостаточно конфет!")
            return
        remove_candies(uid, LICORICE_PRICE)
        user["licorice"] += 1
        user["challenges"]["buy"] += 1
        await save_all()
        await callback.answer("Лакрица куплена!")
        await callback.message.edit_reply_markup(reply_markup=None)
    elif item == "clan_licorice":
        if not user["clan"]:
            await callback.answer("Ты не в клане!")
            return
        if user["candies"] < CLAN_LICORICE_PRICE:
            await callback.answer("Недостаточно конфет!")
            return
        remove_candies(uid, CLAN_LICORICE_PRICE)
        clans[user["clan"]]["licorice"] += 1
        user["challenges"]["buy"] += 1
        await save_all()
        await callback.answer("Лакрица для клана куплена!")
        await callback.message.edit_reply_markup(reply_markup=None)

@router.callback_query(F.data.startswith("use_"))
async def use_item(callback: types.CallbackQuery):
    uid = str(callback.from_user.id)
    user = get_user_data(uid)
    item = callback.data.split("_", 1)[1]
    if item.startswith("costume_"):
        key = item.split("_")[1]
        if key not in user["owned_costumes"]:
            await callback.answer("Нет в инвентаре!")
            return
        user["costume"] = key
        await save_all()
        await callback.answer(f"Надет: {costumes_data[key]['name']}")
    elif item.startswith("potion_"):
        key = item.split("_")[1]
        if key not in user["owned_potions"]:
            await callback.answer("Нет в инвентаре!")
            return
        user["owned_potions"].remove(key)
        if key == "temp_boost":
            user["active_potions"]["temp_boost"] = (datetime.now(timezone.utc) + timedelta(minutes=potions_data[key]["duration"])).isoformat()
        elif key == "perm_boost":
            user["active_potions"]["perm_boost"] = user["active_potions"].get("perm_boost", 0) + potions_data[key]["bonus"]
        await save_all()
        await callback.answer(f"Использовано: {potions_data[key]['name']}")
    await callback.message.edit_reply_markup(reply_markup=None)

@router.callback_query(F.data.startswith("duel_"))
async def process_duel(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        choice = parts[1]
        att, vic = parts[2], parts[3]
        if str(callback.from_user.id) != vic:
            await callback.answer("Не твоя дуэль!", show_alert=True)
            return
        choices = ["rock", "scissors", "paper"]
        att_choice = random.choice(choices)
        if att_choice == choice:
            add_candies(att, 10)
            add_candies(vic, 10)
            await callback.message.edit_text("Ничья! +10 конфет каждому.")
        elif (att_choice == "rock" and choice == "scissors") or \
             (att_choice == "scissors" and choice == "paper") or \
             (att_choice == "paper" and choice == "rock"):
            add_candies(att, 20)
            get_user_data(att)["duel_wins"] += 1
            await callback.message.edit_text(f"Ты проиграл! Противник +20 конфет")
        else:
            add_candies(vic, 20)
            get_user_data(vic)["duel_wins"] += 1
            await callback.message.edit_text(f"Ты выиграл! +20 конфет")
        await callback.message.edit_reply_markup(reply_markup=None)
        await save_all()
    except Exception as e:
        logging.error(f"Дуэль: {e}")

# ====================== ПРОМО ======================
@router.message(Command("promo"))
async def use_promo(message: types.Message):
    add_chat(message.chat.id)
    uid = str(message.from_user.id)
    args = message.text.split()
    if len(args) != 2:
        await message.reply("Формат: /promo CODE")
        return
    code = args[1].upper()
    if code not in promo_codes:
        await message.reply("Промокод не найден")
        return
    promo = promo_codes[code]
    if uid in promo["used_by"]:
        await message.reply("Ты уже использовал")
        return
    max_uses = promo.get("max_uses")
    if max_uses and len(promo["used_by"]) >= max_uses:
        await message.reply("Лимит исчерпан")
        return
    add_candies(uid, promo["candies"])
    promo["used_by"].append(uid)
    await save_all()
    await message.reply(f"Промокод `{code}`: +{promo['candies']} конфет")

# ====================== КЛАНЫ ======================
@router.message(Command("clan"))
async def clan_menu(message: types.Message):
    add_chat(message.chat.id)
    uid = str(message.from_user.id)
    user = get_user_data(uid)
    kb = []
    text = "КЛАНЫ\n\n"
    if user["clan"]:
        clan = clans[user["clan"]]
        members = len(clan["members"]) + 1
        text += f"Твой клан: {user['clan']}\n"
        text += f"Участников: {members}\n"
        text += f"Конфет: {clan['candies']}\n"
        text += f"Лакриц: {clan['licorice']}\n"
        text += "Участники:\n"
        try:
            owner = await bot.get_chat(int(clan["owner"]))
            text += f"- {owner.first_name} (владелец)\n"
        except Exception as e:
            logging.error(f"Ошибка получения владельца клана {clan['owner']}: {e}")
            text += f"- User #{clan['owner']} (владелец)\n"
        for member in clan["members"]:
            try:
                member_user = await bot.get_chat(int(member))
                text += f"- {member_user.first_name}\n"
            except Exception as e:
                logging.error(f"Ошибка получения участника клана {member}: {e}")
                text += f"- User #{member}\n"
        if clan["owner"] == uid:
            kb.append([InlineKeyboardButton(text="Распустить клан", callback_data="disband_clan")])
        else:
            kb.append([InlineKeyboardButton(text="Выйти", callback_data="leave_clan")])
    else:
        text += "Ты не в клане.\n"
        kb.append([InlineKeyboardButton(text="Создать клан (100 конфет)", callback_data="create_clan")])
        kb.append([InlineKeyboardButton(text="Присоединиться", callback_data="join_clan")])
    await message.reply(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@router.callback_query(F.data == "create_clan")
async def create_clan(callback: types.CallbackQuery):
    uid = str(callback.from_user.id)
    user = get_user_data(uid)
    if user["candies"] < 100:
        await callback.answer("Нужно 100 конфет!")
        return
    if user["clan"]:
        await callback.answer("Ты уже в клане!")
        return
    base_name = callback.from_user.first_name[:20]
    clan_name = f"Клан {base_name}"
    i = 1
    while clan_name in clans:
        clan_name = f"Клан {base_name} {i}"
        i += 1
    remove_candies(uid, 100)
    clans[clan_name] = {"owner": uid, "members": [], "candies": 0, "licorice": 0}
    user["clan"] = clan_name
    await save_all()
    await callback.answer(f"Клан создан: {clan_name}")
    await callback.message.edit_reply_markup(reply_markup=None)

@router.callback_query(F.data == "disband_clan")
async def disband_clan(callback: types.CallbackQuery):
    uid = str(callback.from_user.id)
    user = get_user_data(uid)
    if not user["clan"] or clans[user["clan"]]["owner"] != uid:
        await callback.answer("Ты не владелец!")
        return
    clan_name = user["clan"]
    for member in clans[clan_name]["members"]:
        get_user_data(member)["clan"] = None
    del clans[clan_name]
    user["clan"] = None
    await save_all()
    await callback.answer(f"Клан {clan_name} распущен.")
    await callback.message.edit_reply_markup(reply_markup=None)

@router.callback_query(F.data == "leave_clan")
async def leave_clan(callback: types.CallbackQuery):
    uid = str(callback.from_user.id)
    user = get_user_data(uid)
    if not user["clan"]:
        await callback.answer("Ты не в клане!")
        return
    clan = clans[user["clan"]]
    if clan["owner"] == uid:
        await callback.answer("Владелец не может выйти! Распусти клан.")
        return
    clan["members"].remove(uid)
    user["clan"] = None
    await save_all()
    await callback.answer("Ты вышел из клана.")
    await callback.message.edit_reply_markup(reply_markup=None)

@router.callback_query(F.data == "join_clan")
async def join_clan(callback: types.CallbackQuery, state: FSMContext):
    uid = str(callback.from_user.id)
    user = get_user_data(uid)
    if user["clan"]:
        await callback.answer("Ты уже в клане!")
        return
    await state.set_state(ClanStates.JOIN_CLAN)
    await callback.message.reply("Введи название клана для присоединения:")
    await callback.message.edit_reply_markup(reply_markup=None)

@router.message(ClanStates.JOIN_CLAN)
async def process_join_clan(message: types.Message, state: FSMContext):
    uid = str(message.from_user.id)
    clan_name = message.text.strip()
    if clan_name not in clans:
        await message.reply("Клан не найден!")
        await state.finish()
        return
    clan = clans[clan_name]
    if len(clan["members"]) + 1 >= MAX_CLAN_MEMBERS:
        await message.reply("Клан переполнен!")
        await state.finish()
        return
    user = get_user_data(uid)
    user["clan"] = clan_name
    clan["members"].append(uid)
    await save_all()
    await message.reply(f"Ты вступил в клан {clan_name}!")
    await state.finish()

@router.message(Command("topclans"))
async def top_clans(message: types.Message):
    add_chat(message.chat.id)
    sorted_clans = sorted(clans.items(), key=lambda x: x[1]["candies"], reverse=True)[:5]
    text = "ТОП-5 КЛАНОВ:\n"
    for i, (name, data) in enumerate(sorted_clans, 1):
        members = len(data["members"]) + 1
        text += f"{i}. {name} — {data['candies']} конфет ({members} чел., лакриц: {data['licorice']})\n"
    await message.reply(text or "Кланов нет.")

# ====================== АДМИН-ПАНЕЛЬ ======================
@router.message(Command("admin"))
async def admin_panel(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Ты не админ.")
        return
    text = (
        "АДМИН-ПАНЕЛЬ\n\n"
        f"Игроков: {len(candies)}\n"
        f"Кланов: {len(clans)}\n"
        f"Чатов: {len(active_chats)}\n"
        f"Онлайн: {len(set(cooldowns.keys()))}\n\n"
        "Команды:\n"
        "/announce TEXT — рассылка\n"
        "/addcandies — реплай + N конфет → дать\n"
        "/removecandies — реплай + N конфет → забрать\n"
        "/createpromo CODE N — создать промокод\n"
        "/deletepromo CODE — удалить промокод\n"
        "/listpromos — список промокодов"
    )
    await message.reply(text)

@router.message(Command("addcandies"))
async def add_candies_admin(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Ты не админ.")
        return
    if not message.reply_to_message:
        await message.reply("Реплай на пользователя: /addcandies N")
        return
    p = message.text.split()[1:]
    if len(p) != 1 or not p[0].isdigit():
        await message.reply("Формат: /addcandies N (реплай)")
        return
    amt = int(p[0])
    tid = str(message.reply_to_message.from_user.id)
    tname = message.reply_to_message.from_user.first_name
    try:
        await bot.get_chat(int(tid))
        add_candies(tid, amt)
        await message.reply(f"Добавлено {amt} конфет → {tname}")
    except Exception as e:
        logging.error(f"Ошибка добавления конфет для {tid}: {e}")
        await message.reply("Пользователь не найден")

@router.message(Command("removecandies"))
async def remove_candies_admin(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Ты не админ.")
        return
    if not message.reply_to_message:
        await message.reply("Реплай на пользователя: /removecandies N")
        return
    p = message.text.split()[1:]
    if len(p) != 1 or not p[0].isdigit():
        await message.reply("Формат: /removecandies N (реплай)")
        return
    amt = int(p[0])
    tid = str(message.reply_to_message.from_user.id)
    tname = message.reply_to_message.from_user.first_name
    try:
        await bot.get_chat(int(tid))
        remove_candies(tid, amt)
        await message.reply(f"Забрано {amt} конфет у {tname}")
    except Exception as e:
        logging.error(f"Ошибка удаления конфет для {tid}: {e}")
        await message.reply("Пользователь не найден")

@router.message(Command("createpromo"))
async def create_promo(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Ты не админ.")
        return
    args = message.text.split()
    if len(args) != 3 or not args[2].isdigit():
        await message.reply("Формат: /createpromo CODE N")
        return
    code = args[1].upper()
    candies_amt = int(args[2])
    promo_codes[code] = {"candies": candies_amt, "used_by": []}
    await save_all()
    await message.reply(f"Промокод {code} создан на {candies_amt} конфет")

@router.message(Command("deletepromo"))
async def delete_promo(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Ты не админ.")
        return
    args = message.text.split()
    if len(args) != 2:
        await message.reply("Формат: /deletepromo CODE")
        return
    code = args[1].upper()
    if code in promo_codes:
        del promo_codes[code]
        await save_all()
        await message.reply(f"Промокод {code} удалён")
    else:
        await message.reply("Промокод не найден")

@router.message(Command("listpromos"))
async def list_promos(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Ты не админ.")
        return
    text = "Список промокодов:\n"
    for code, data in promo_codes.items():
        text += f"{code}: {data['candies']} конфет, использовано {len(data['used_by'])} раз\n"
    await message.reply(text or "Промокодов нет")

# ====================== РЕЙДЫ ======================
async def start_raid(chat_id):
    if chat_id not in active_chats:
        return
    try:
        await bot.send_message(chat_id, "РЕЙД! Удвоенные конфеты 30 минут!")
        RAID_ACTIVE[chat_id] = datetime.now(timezone.utc) + timedelta(minutes=30)
        await asyncio.sleep(1800)
        if chat_id in RAID_ACTIVE:
            del RAID_ACTIVE[chat_id]
        await bot.send_message(chat_id, "Рейд завершён!")
    except Exception as e:
        logging.error(f"Ошибка в рейде для чата {chat_id}: {e}")

async def raid_scheduler():
    while True:
        await asyncio.sleep(RAID_INTERVAL)
        for chat_id in active_chats[:]:
            asyncio.create_task(start_raid(chat_id))

# ====================== ЗАПУСК ======================
async def main():
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("Webhook удалён. Используем polling.")
        dp.include_router(router)
        keep_alive()  # Запуск веб-сервера для UptimeRobot
        asyncio.create_task(raid_scheduler())
        logging.warning("Бот запущен — ВСЁ РАБОТАЕТ!")
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"Ошибка запуска: {e}")

if __name__ == "__main__":
    asyncio.run(main())
