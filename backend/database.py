import os
import time

import aiosqlite
import httpx

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data.db"))
TURSO_URL = os.getenv("TURSO_URL", "").strip()
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "").strip()

FREE_LIMIT = 10
FREE_COOLDOWN_DAYS = 7

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
    created_at    REAL DEFAULT 0
)"""


# ─── Turso HTTP API ──────────────────────────────────────────────

def _turso_execute(sql: str, args=None) -> dict:
    """Execute SQL via Turso HTTP API. Returns {columns: [...], rows: [...]}."""
    stmts = []
    stmt = {"sql": sql}
    if args:
        stmt["args"] = [{"type": "integer", "value": str(a)} if isinstance(a, int)
                        else {"type": "float", "value": str(a)} if isinstance(a, float)
                        else {"type": "text", "value": str(a)} if a is not None
                        else {"type": "null"}
                        for a in args]
    stmts.append({"type": "execute", "stmt": stmt})
    stmts.append({"type": "close"})

    resp = httpx.post(
        f"{_turso_http_url}/v2/pipeline",
        json={"requests": stmts},
        headers={"Authorization": f"Bearer {TURSO_AUTH_TOKEN}"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    result = data.get("results", [{}])[0]
    if result.get("type") == "error":
        raise RuntimeError(result["error"]["message"])
    response = result.get("response", {}).get("result", {})
    cols = [c["name"] for c in response.get("cols", [])]
    rows_raw = response.get("rows", [])
    rows = []
    for row in rows_raw:
        rows.append([cell.get("value") for cell in row])
    return {"columns": cols, "rows": rows}


def _turso_row_to_dict(result: dict, row: list) -> dict:
    d = {}
    for i, col in enumerate(result["columns"]):
        val = row[i]
        if col in ("telegram_id", "is_banned", "is_pro", "requests_used"):
            val = int(val) if val is not None else 0
        elif col in ("period_start", "created_at"):
            val = float(val) if val is not None else 0.0
        d[col] = val
    return d


# ─── Unified helpers ─────────────────────────────────────────────

async def init_db():
    if _use_turso:
        _turso_execute(CREATE_TABLE_SQL)
        return
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.executescript(CREATE_TABLE_SQL)
        await db.commit()
    finally:
        await db.close()


async def get_or_create_user(telegram_id: int, username: str = "", first_name: str = "") -> dict:
    if _use_turso:
        return _turso_get_or_create_user(telegram_id, username, first_name)
    return await _sqlite_get_or_create_user(telegram_id, username, first_name)


async def check_can_solve(telegram_id: int) -> dict:
    user = await get_or_create_user(telegram_id)
    if user["is_banned"]:
        return {"allowed": False, "remaining": 0, "reason": "banned"}
    if user["is_pro"]:
        return {"allowed": True, "remaining": "unlimited", "reason": "pro"}

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

    remaining = max(0, FREE_LIMIT - user["requests_used"])
    if remaining <= 0:
        return {"allowed": False, "remaining": 0, "reason": "limit"}
    return {"allowed": True, "remaining": remaining, "reason": "free"}


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


async def set_user_pro(telegram_id: int, is_pro: bool):
    sql = "UPDATE users SET is_pro = ? WHERE telegram_id = ?"
    val = 1 if is_pro else 0
    if _use_turso:
        _turso_execute(sql, [val, telegram_id])
        return
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute(sql, (val, telegram_id))
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
