import aiosqlite
import os
import time

_is_vercel = bool(os.getenv("VERCEL"))
_local_db = os.path.join(os.path.dirname(__file__), "..", "data.db")
DB_PATH = "/tmp/data.db" if _is_vercel else os.path.abspath(_local_db)

FREE_LIMIT = 10
FREE_COOLDOWN_DAYS = 7


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    return db


async def init_db():
    db = await get_db()
    try:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id   INTEGER PRIMARY KEY,
                username      TEXT DEFAULT '',
                first_name    TEXT DEFAULT '',
                is_banned     INTEGER DEFAULT 0,
                is_pro        INTEGER DEFAULT 0,
                requests_used INTEGER DEFAULT 0,
                period_start  REAL DEFAULT 0,
                created_at    REAL DEFAULT 0
            );
        """)
        await db.commit()
    finally:
        await db.close()


async def get_or_create_user(telegram_id: int, username: str = "", first_name: str = "") -> dict:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = await cur.fetchone()
        if row:
            if username or first_name:
                await db.execute(
                    "UPDATE users SET username = ?, first_name = ? WHERE telegram_id = ?",
                    (username or row["username"], first_name or row["first_name"], telegram_id),
                )
                await db.commit()
                cur = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
                row = await cur.fetchone()
            return dict(row)
        now = time.time()
        await db.execute(
            "INSERT INTO users (telegram_id, username, first_name, created_at, period_start) VALUES (?, ?, ?, ?, ?)",
            (telegram_id, username, first_name, now, now),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        row = await cur.fetchone()
        return dict(row)
    finally:
        await db.close()


async def check_can_solve(telegram_id: int) -> dict:
    """Returns {allowed: bool, remaining: int|'unlimited', reason: str}."""
    user = await get_or_create_user(telegram_id)

    if user["is_banned"]:
        return {"allowed": False, "remaining": 0, "reason": "banned"}

    if user["is_pro"]:
        return {"allowed": True, "remaining": "unlimited", "reason": "pro"}

    now = time.time()
    period_start = user["period_start"] or now
    seconds_in_period = FREE_COOLDOWN_DAYS * 86400

    if now - period_start >= seconds_in_period:
        db = await get_db()
        try:
            await db.execute(
                "UPDATE users SET requests_used = 0, period_start = ? WHERE telegram_id = ?",
                (now, telegram_id),
            )
            await db.commit()
        finally:
            await db.close()
        user["requests_used"] = 0

    remaining = max(0, FREE_LIMIT - user["requests_used"])
    if remaining <= 0:
        return {"allowed": False, "remaining": 0, "reason": "limit"}

    return {"allowed": True, "remaining": remaining, "reason": "free"}


async def increment_usage(telegram_id: int):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET requests_used = requests_used + 1 WHERE telegram_id = ?",
            (telegram_id,),
        )
        await db.commit()
    finally:
        await db.close()


async def get_all_users() -> list[dict]:
    db = await get_db()
    try:
        cur = await db.execute("SELECT * FROM users ORDER BY created_at DESC")
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def set_user_pro(telegram_id: int, is_pro: bool):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET is_pro = ? WHERE telegram_id = ?",
            (1 if is_pro else 0, telegram_id),
        )
        await db.commit()
    finally:
        await db.close()


async def set_user_banned(telegram_id: int, is_banned: bool):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET is_banned = ? WHERE telegram_id = ?",
            (1 if is_banned else 0, telegram_id),
        )
        await db.commit()
    finally:
        await db.close()


async def reset_user_requests(telegram_id: int):
    db = await get_db()
    try:
        await db.execute(
            "UPDATE users SET requests_used = 0, period_start = ? WHERE telegram_id = ?",
            (time.time(), telegram_id),
        )
        await db.commit()
    finally:
        await db.close()
