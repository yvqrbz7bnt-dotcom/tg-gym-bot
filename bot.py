# tg-gym-bot — версия для aiogram 2.25.1 (совместима с iSH)
import os
import aiosqlite
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton

TOKEN = os.getenv("TG_TOKEN")
DB = "gymbot.db"

PLAN = {
    "A": [
        {"exercise":"Back Squat (Hack)","sets":4,"reps":8,"default":30.0,"min_step":5.0},
        {"exercise":"Leg Press (Wide)","sets":4,"reps":12,"default":120.0,"min_step":5.0},
        {"exercise":"Leg Extension","sets":4,"reps":12,"default":36.0,"min_step":4.5},
    ],
    "B": [
        {"exercise":"Bench Press","sets":3,"reps":10,"default":50.0,"min_step":2.5},
        {"exercise":"Incline DB Press 45°","sets":4,"reps":8,"default":25.0,"min_step":2.5},
        {"exercise":"Seated Press (Smith)","sets":4,"reps":12,"default":40.0,"min_step":2.5},
    ],
    "C": [
        {"exercise":"Lat Pulldown to Chest","sets":4,"reps":10,"default":55.0,"min_step":4.5},
        {"exercise":"One-Arm DB Row","sets":4,"reps":10,"default":30.0,"min_step":2.5},
        {"exercise":"Seated Row (Close-Grip)","sets":4,"reps":12,"default":49.0,"min_step":4.5},
    ],
    "D": [
        {"exercise":"EZ Bar Curl (Standing)","sets":4,"reps":10,"default":30.0,"min_step":2.5},
        {"exercise":"DB Hammer Curl (Both)","sets":3,"reps":12,"default":12.0,"min_step":2.5},
        {"exercise":"Triceps Pushdown (Straight)","sets":4,"reps":15,"default":32.0,"min_step":4.5},
    ]
}

bot = Bot(TOKEN)
dp = Dispatcher(bot)

async def init_db():
    async with aiosqlite.connect(DB) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY, tg_id INTEGER UNIQUE, n REAL DEFAULT 2.5, plan_state TEXT DEFAULT 'A'
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS progress(
            user_id INTEGER, exercise TEXT, weight REAL, fails INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, exercise)
        )""")
        await db.commit()

async def get_user(db, tg_id):
    c = await db.execute("SELECT id,n,plan_state FROM users WHERE tg_id=?", (tg_id,))
    row = await c.fetchone()
    if row: return row
    await db.execute("INSERT INTO users(tg_id) VALUES(?)", (tg_id,))
    await db.commit()
    c = await db.execute("SELECT id,n,plan_state FROM users WHERE tg_id=?", (tg_id,))
    return await c.fetchone()

async def get_weight(db, user_id, ex_name, default):
    c = await db.execute("SELECT weight,fails FROM progress WHERE user_id=? AND exercise=?", (user_id,ex_name))
    row = await c.fetchone()
    if row: return row[0], row[1]
    await db.execute("INSERT INTO progress(user_id,exercise,weight,fails) VALUES(?,?,?,0)", (user_id,ex_name,default))
    await db.commit()
    return default, 0

async def set_weight(db, user_id, ex_name, weight=None, fails=None):
    c = await db.execute("SELECT weight,fails FROM progress WHERE user_id=? AND exercise=?", (user_id,ex_name))
    row = await c.fetchone()
    if row:
        w = weight if weight is not None else row[0]
        f = fails if fails is not None else row[1]
        await db.execute("UPDATE progress SET weight=?, fails=? WHERE user_id=? AND exercise=?", (w,f,user_id,ex_name))
    else:
        await db.execute("INSERT INTO progress(user_id,exercise,weight,fails) VALUES(?,?,?,?)", (user_id,ex_name, weight or 0.0, fails or 0))
    await db.commit()

def kb_for_set(ex, w):
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"✅ {ex} {w:.1f} — легко"),
             KeyboardButton(text=f"🟡 {ex} {w:.1f} — норм")],
            [KeyboardButton(text=f"❌ {ex} {w:.1f} — не сделал")]
        ],
        resize_keyboard=True
    )

@dp.message_handler(commands=['start'])
async def start(m: Message):
    await init_db()
    async with aiosqlite.connect(DB) as db:
        await get_user(db, m.from_user.id)
    await m.answer("Готов! Команды: /today — план, /n 2.5 — шаг прибавки, /swap — смена дня.")

@dp.message_handler(lambda msg: msg.text and msg.text.startswith("/n"))
async def set_n_cmd(m: Message):
    parts = m.text.split()
    if len(parts) < 2:
        return await m.answer("Формат: /n 2.5")
    try:
        val = float(parts[1])
    except:
        return await m.answer("Формат: /n 2.5")
    async with aiosqlite.connect(DB) as db:
        uid, n, state = await get_user(db, m.from_user.id)
        await db.execute("UPDATE users SET n=? WHERE id=?", (val, uid))
        await db.commit()
    await m.answer(f"Шаг прибавки установлен: {val} кг")

@dp.message_handler(commands=['swap'])
async def swap(m: Message):
    async with aiosqlite.connect(DB) as db:
        uid, n, state = await get_user(db, m.from_user.id)
        next_state = {"A":"B","B":"C","C":"D","D":"A"}[state]
        await db.execute("UPDATE users SET plan_state=? WHERE id=?", (next_state, uid))
        await db.commit()
    await m.answer(f"Следующий день: {next_state}")

@dp.message_handler(commands=['today'])
async def today(m: Message):
    async with aiosqlite.connect(DB) as db:
        uid, n, state = await get_user(db, m.from_user.id)
        plan = PLAN[state]
        lines = [f"День {state}:"]
        for it in plan:
            w, _ = await get_weight(db, uid, it["exercise"], it["default"])
            lines.append(f"• {it['exercise']}: {it['sets']}×{it['reps']} @ {w:.1f} кг")
        await m.answer("\n".join(lines))

@dp.message_handler(regexp=r"^(✅|🟡|❌)")
async def log_set(m: Message):
    parts = m.text.split()
    mark = parts[0]
    # Вес — первое число с точкой/без
    nums = [p for p in parts if p.replace('.', '', 1).isdigit()]
    if not nums:
        return
    w = float(nums[0])
    # Имя упражнения — всё между маркером и числом
    ex_tokens = []
    for p in parts[1:]:
        if p == nums[0]: break
        ex_tokens.append(p)
    ex = " ".join(ex_tokens)
    async with aiosqlite.connect(DB) as db:
        uid, n, _ = await get_user(db, m.from_user.id)
        cur_w, fails = await get_weight(db, uid, ex, w)
        if mark == "✅":
            await set_weight(db, uid, ex, cur_w + n, 0)
            await m.answer(f"{ex}: отлично! Следующий раз {cur_w+n:.1f} кг")
        elif mark == "🟡":
            await set_weight(db, uid, ex, cur_w, 0)
            await m.answer(f"{ex}: оставим {cur_w:.1f} кг")
        else:
            fails += 1
            if fails >= 2:
                new_w = round(cur_w * 0.9, 1)
                await set_weight(db, uid, ex, new_w, 0)
                await m.answer(f"{ex}: делоуд −10% → {new_w:.1f} кг")
            else:
                await set_weight(db, uid, ex, cur_w, fails)
                await m.answer(f"{ex}: зафиксировал неудачу ({fails}/2). Вес пока {cur_w:.1f} кг")

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Set TG_TOKEN env var")
    executor.start_polling(dp, skip_updates=True)
