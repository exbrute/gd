import math
import os
import time

import aiosqlite

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data.db"))
TURSO_URL = os.getenv("TURSO_URL", "").strip()
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()

def _int_env(name: str, default: int, min_val: int, max_val: int) -> int:
    try:
        v = int(os.getenv(name, str(default)))
        return max(min_val, min(max_val, v))
    except (ValueError, TypeError):
        return default

# Количество бесплатных активаций (запросов) за период — настраивается от 1 до 50000
FREE_LIMIT = _int_env("FREE_LIMIT", 10, 1, 50000)
FREE_COOLDOWN_DAYS = 7
# Длительность Pro-подписки в днях (1–50000) — задаётся при выдаче
PRO_SUBSCRIPTION_DAYS_DEFAULT = _int_env("PRO_SUBSCRIPTION_DAYS", 30, 1, 50000)

_use_turso = bool(TURSO_URL and TURSO_AUTH_TOKEN)

if _use_turso:
    _turso_http_url = TURSO_URL.replace("libsql://", "https://")

CREATE_TABLE_SQL = """CREATE TABLE IF NOT EXISTS users (
    telegram_id   INTEGER PRIMARY KEY,
    username      TEXT DEFAULT '',
    first_name    TEXT DEFAULT '',
    is_banned     INTEGER DEFAULT 0,
    is_pro        INTEGER DEFAULT 0,
    requests_used INTEGER DEFAULT 0,
    period_start  REAL DEFAULT 0,
    created_at    REAL DEFAULT 0,
    pro_until     REAL
)"""

CREATE_SOLUTIONS_TABLE_SQL = """CREATE TABLE IF NOT EXISTS solutions (
    id TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    created_at REAL DEFAULT 0,
    telegram_id INTEGER,
    task_text TEXT
)"""

# Решения хранятся 12 часов, затем удаляются
SOLUTION_RETENTION_SECONDS = 12 * 3600


# ─── Turso via libsql-client ─────────────────────────────────────
# Uses HTTP for https:// (works with regional *.aws-*.turso.io)

def _turso_execute(sql: str, args=None) -> dict:
    """Execute SQL via libsql_client. Returns {columns: [...], rows: [...]}."""
    import libsql_client
    url = _turso_http_url
    with libsql_client.create_client_sync(url=url, auth_token=TURSO_AUTH_TOKEN) as client:
        if args:
            rs = client.execute(sql, args)
        else:
            rs = client.execute(sql)
    cols = list(rs.columns) if rs.columns else []
    rows = [list(r) for r in rs.rows]
    return {"columns": cols, "rows": rows}


def _turso_row_to_dict(result: dict, row: list) -> dict:
    d = {}
    for i, col in enumerate(result["columns"]):
        val = row[i]
        if col in ("telegram_id", "is_banned", "is_pro", "requests_used"):
            val = int(val) if val is not None else 0
        elif col in ("period_start", "created_at", "pro_until"):
            val = float(val) if val is not None else 0.0
        d[col] = val
    return d


# ─── Unified helpers ─────────────────────────────────────────────

async def init_db():
    if _use_turso:
        _turso_execute(CREATE_TABLE_SQL)
        _turso_execute(CREATE_SOLUTIONS_TABLE_SQL)
        try:
            _turso_execute("ALTER TABLE solutions ADD COLUMN telegram_id INTEGER")
        except Exception:
            pass
        try:
            _turso_execute("ALTER TABLE solutions ADD COLUMN task_text TEXT")
        except Exception:
            pass
        try:
            _turso_execute("ALTER TABLE users ADD COLUMN pro_until REAL")
        except Exception:
            pass
        return
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.executescript(CREATE_TABLE_SQL)
        await db.executescript(CREATE_SOLUTIONS_TABLE_SQL)
        await db.commit()
        try:
            await db.execute("ALTER TABLE solutions ADD COLUMN telegram_id INTEGER")
            await db.commit()
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE solutions ADD COLUMN task_text TEXT")
            await db.commit()
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE users ADD COLUMN pro_until REAL")
            await db.commit()
        except Exception:
            pass
    finally:
        await db.close()


async def save_solution(sid: str, content: str, telegram_id: int | None = None, task_text: str | None = None) -> None:
    """Сохраняет решение в БД. Хранится 12 часов, привязано к пользователю для личного кабинета."""
    now = time.time()
    task_text = (task_text or "").strip() or None
    if _use_turso:
        _turso_execute(
            "INSERT OR REPLACE INTO solutions (id, content, created_at, telegram_id, task_text) VALUES (?, ?, ?, ?, ?)",
            [sid, content, now, telegram_id, task_text],
        )
        return
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute(
            "INSERT OR REPLACE INTO solutions (id, content, created_at, telegram_id, task_text) VALUES (?, ?, ?, ?, ?)",
            (sid, content, now, telegram_id, task_text),
        )
        await db.commit()
    finally:
        await db.close()


async def get_and_delete_solution(sid: str) -> str | None:
    """Извлекает решение и удаляет его (одноразовая страница). Решения старше 12 ч считаются просроченными."""
    now = time.time()
    cutoff = now - SOLUTION_RETENTION_SECONDS
    if _use_turso:
        rs = _turso_execute("SELECT content, created_at FROM solutions WHERE id = ?", [sid])
        if not rs["rows"]:
            return None
        content, created_at = rs["rows"][0][0], rs["rows"][0][1] or 0
        if created_at < cutoff:
            _turso_execute("DELETE FROM solutions WHERE id = ?", [sid])
            return None
        _turso_execute("DELETE FROM solutions WHERE id = ?", [sid])
        return content
    db = await aiosqlite.connect(DB_PATH)
    try:
        cur = await db.execute("SELECT content, created_at FROM solutions WHERE id = ?", (sid,))
        row = await cur.fetchone()
        if not row:
            return None
        content, created_at = row[0], row[1] or 0
        if created_at < cutoff:
            await db.execute("DELETE FROM solutions WHERE id = ?", (sid,))
            await db.commit()
            return None
        await db.execute("DELETE FROM solutions WHERE id = ?", (sid,))
        await db.commit()
        return content
    finally:
        await db.close()


async def list_solutions_for_user(telegram_id: int) -> list[dict]:
    """Список решений пользователя за последние 12 часов (id, created_at, task_text)."""
    now = time.time()
    cutoff = now - SOLUTION_RETENTION_SECONDS
    if _use_turso:
        rs = _turso_execute(
            "SELECT id, created_at, task_text FROM solutions WHERE telegram_id = ? AND created_at >= ? ORDER BY created_at DESC",
            [telegram_id, cutoff],
        )
        return [{"id": r[0], "created_at": r[1] or 0, "task_text": r[2] if len(r) > 2 else None} for r in rs["rows"]]
    db = await aiosqlite.connect(DB_PATH)
    try:
        cur = await db.execute(
            "SELECT id, created_at, task_text FROM solutions WHERE telegram_id = ? AND created_at >= ? ORDER BY created_at DESC",
            (telegram_id, cutoff),
        )
        rows = await cur.fetchall()
        return [{"id": r[0], "created_at": r[1] or 0, "task_text": r[2] if len(r) > 2 else None} for r in rows]
    finally:
        await db.close()


async def delete_solutions_older_than(seconds: int) -> None:
    """Удаляет решения старше заданного количества секунд (очистка по TTL 12 ч)."""
    cutoff = time.time() - seconds
    if _use_turso:
        _turso_execute("DELETE FROM solutions WHERE created_at < ?", [cutoff])
        return
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute("DELETE FROM solutions WHERE created_at < ?", (cutoff,))
        await db.commit()
    finally:
        await db.close()


async def get_or_create_user(telegram_id: int, username: str = "", first_name: str = "") -> dict:
    if _use_turso:
        return _turso_get_or_create_user(telegram_id, username, first_name)
    return await _sqlite_get_or_create_user(telegram_id, username, first_name)


def user_has_active_pro(user: dict) -> bool:
    """Pro активна, если pro_until > now или is_pro без pro_until (бессрочно)."""
    pro_until = user.get("pro_until") or 0
    if pro_until > 0 and pro_until > time.time():
        return True
    if user["is_pro"] and (not pro_until or pro_until <= 0):
        return True  # старые бессрочные Pro
    return False


async def check_can_solve(telegram_id: int) -> dict:
    user = await get_or_create_user(telegram_id)
    if user["is_banned"]:
        return {"allowed": False, "remaining": 0, "reason": "banned", "days_until_update": 0}
    if user_has_active_pro(user):
        return {"allowed": True, "remaining": "unlimited", "reason": "pro", "days_until_update": None}

    now = time.time()
    period_start = user["period_start"] or now
    if now - period_start >= FREE_COOLDOWN_DAYS * 86400:
        if _use_turso:
            _turso_execute("UPDATE users SET requests_used = 0, period_start = ? WHERE telegram_id = ?", [now, telegram_id])
        else:
            db = await aiosqlite.connect(DB_PATH)
            try:
                await db.execute("UPDATE users SET requests_used = 0, period_start = ? WHERE telegram_id = ?", (now, telegram_id))
                await db.commit()
            finally:
                await db.close()
        user["requests_used"] = 0
        period_start = now

    period_end = period_start + FREE_COOLDOWN_DAYS * 86400
    days_until_update = max(0, math.ceil((period_end - now) / 86400))
    remaining = max(0, FREE_LIMIT - user["requests_used"])
    if remaining <= 0:
        return {"allowed": False, "remaining": 0, "reason": "limit", "days_until_update": days_until_update, "free_limit": FREE_LIMIT}
    return {"allowed": True, "remaining": remaining, "reason": "free", "days_until_update": days_until_update, "free_limit": FREE_LIMIT}


async def increment_usage(telegram_id: int):
    sql = "UPDATE users SET requests_used = requests_used + 1 WHERE telegram_id = ?"
    if _use_turso:
        _turso_execute(sql, [telegram_id])
        return
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute(sql, (telegram_id,))
        await db.commit()
    finally:
        await db.close()


async def get_all_users() -> list[dict]:
    sql = "SELECT * FROM users ORDER BY created_at DESC"
    if _use_turso:
        rs = _turso_execute(sql)
        return [_turso_row_to_dict(rs, r) for r in rs["rows"]]
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    try:
        cur = await db.execute(sql)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await db.close()


async def set_user_pro(telegram_id: int, is_pro: bool, days: int | None = None):
    """Включить/выключить Pro. days: 1–50000, при включении — на сколько дней (по умол. PRO_SUBSCRIPTION_DAYS)."""
    now = time.time()
    if is_pro:
        d = days if days is not None else PRO_SUBSCRIPTION_DAYS_DEFAULT
        d = max(1, min(50000, d))
        pro_until = now + d * 86400
        if _use_turso:
            _turso_execute("UPDATE users SET is_pro = 1, pro_until = ? WHERE telegram_id = ?", [pro_until, telegram_id])
        else:
            db = await aiosqlite.connect(DB_PATH)
            try:
                await db.execute("UPDATE users SET is_pro = 1, pro_until = ? WHERE telegram_id = ?", (pro_until, telegram_id))
                await db.commit()
            finally:
                await db.close()
    else:
        if _use_turso:
            _turso_execute("UPDATE users SET is_pro = 0, pro_until = NULL WHERE telegram_id = ?", [telegram_id])
        else:
            db = await aiosqlite.connect(DB_PATH)
            try:
                await db.execute("UPDATE users SET is_pro = 0, pro_until = NULL WHERE telegram_id = ?", (telegram_id,))
                await db.commit()
            finally:
                await db.close()


async def set_user_banned(telegram_id: int, is_banned: bool):
    sql = "UPDATE users SET is_banned = ? WHERE telegram_id = ?"
    val = 1 if is_banned else 0
    if _use_turso:
        _turso_execute(sql, [val, telegram_id])
        return
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute(sql, (val, telegram_id))
        await db.commit()
    finally:
        await db.close()


async def reset_user_requests(telegram_id: int):
    sql = "UPDATE users SET requests_used = 0, period_start = ? WHERE telegram_id = ?"
    now = time.time()
    if _use_turso:
        _turso_execute(sql, [now, telegram_id])
        return
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute(sql, (now, telegram_id))
        await db.commit()
    finally:
        await db.close()


# ─── SQLite-only ─────────────────────────────────────────────────

async def _sqlite_get_or_create_user(telegram_id: int, username: str, first_name: str) -> dict:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
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


# ─── Turso-only ──────────────────────────────────────────────────

def _turso_get_or_create_user(telegram_id: int, username: str, first_name: str) -> dict:
    rs = _turso_execute("SELECT * FROM users WHERE telegram_id = ?", [telegram_id])
    if rs["rows"]:
        user = _turso_row_to_dict(rs, rs["rows"][0])
        if username or first_name:
            _turso_execute(
                "UPDATE users SET username = ?, first_name = ? WHERE telegram_id = ?",
                [username or user["username"], first_name or user["first_name"], telegram_id],
            )
            rs = _turso_execute("SELECT * FROM users WHERE telegram_id = ?", [telegram_id])
            user = _turso_row_to_dict(rs, rs["rows"][0])
        return user
    now = time.time()
    _turso_execute(
        "INSERT INTO users (telegram_id, username, first_name, created_at, period_start) VALUES (?, ?, ?, ?, ?)",
        [telegram_id, username, first_name, now, now],
    )
    rs = _turso_execute("SELECT * FROM users WHERE telegram_id = ?", [telegram_id])
    return _turso_row_to_dict(rs, rs["rows"][0])
