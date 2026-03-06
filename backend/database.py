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

CREATE_PROMO_CODES_TABLE_SQL = """CREATE TABLE IF NOT EXISTS promo_codes (
    code TEXT PRIMARY KEY,
    discount_percent INTEGER NOT NULL DEFAULT 0,
    max_uses INTEGER NOT NULL DEFAULT 0,
    used_count INTEGER NOT NULL DEFAULT 0,
    expires_at REAL,
    created_at REAL DEFAULT 0,
    promo_type TEXT NOT NULL DEFAULT 'discount',
    pro_days INTEGER DEFAULT 0
)"""

CREATE_PROMO_CODE_USES_TABLE_SQL = """CREATE TABLE IF NOT EXISTS promo_code_uses (
    telegram_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    PRIMARY KEY (telegram_id, code)
)"""


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
        try:
            _turso_execute("ALTER TABLE users ADD COLUMN applied_promo_code TEXT")
        except Exception:
            pass
        _turso_execute(CREATE_PROMO_CODES_TABLE_SQL)
        try:
            _turso_execute("ALTER TABLE promo_codes ADD COLUMN promo_type TEXT DEFAULT 'discount'")
        except Exception:
            pass
        try:
            _turso_execute("ALTER TABLE promo_codes ADD COLUMN pro_days INTEGER DEFAULT 0")
        except Exception:
            pass
        _turso_execute(CREATE_PROMO_CODE_USES_TABLE_SQL)
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
        try:
            await db.execute("ALTER TABLE users ADD COLUMN applied_promo_code TEXT")
            await db.commit()
        except Exception:
            pass
        await db.execute(CREATE_PROMO_CODES_TABLE_SQL)
        await db.commit()
        try:
            await db.execute("ALTER TABLE promo_codes ADD COLUMN promo_type TEXT DEFAULT 'discount'")
            await db.commit()
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE promo_codes ADD COLUMN pro_days INTEGER DEFAULT 0")
            await db.commit()
        except Exception:
            pass
        await db.execute(CREATE_PROMO_CODE_USES_TABLE_SQL)
        await db.commit()
    finally:
        await db.close()


async def create_promo_code(
    code: str,
    discount_percent: int = 0,
    max_uses: int = 0,
    expires_at: float | None = None,
    promo_type: str = "discount",
    pro_days: int = 0,
) -> None:
    """Создаёт промокод. promo_type: 'discount' | 'free_pro'. Для free_pro — pro_days (1–50000)."""
    code = (code or "").strip().upper()
    if not code:
        raise ValueError("Код не может быть пустым")
    promo_type = "free_pro" if promo_type == "free_pro" else "discount"
    discount_percent = max(0, min(100, discount_percent))
    pro_days = max(0, min(50000, pro_days)) if promo_type == "free_pro" else 0
    now = time.time()
    if _use_turso:
        _turso_execute(
            "INSERT INTO promo_codes (code, discount_percent, max_uses, used_count, expires_at, created_at, promo_type, pro_days) VALUES (?, ?, ?, 0, ?, ?, ?, ?)",
            [code, discount_percent, max_uses, expires_at, now, promo_type, pro_days],
        )
        return
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute(
            "INSERT INTO promo_codes (code, discount_percent, max_uses, used_count, expires_at, created_at, promo_type, pro_days) VALUES (?, ?, ?, 0, ?, ?, ?, ?)",
            (code, discount_percent, max_uses, expires_at, now, promo_type, pro_days),
        )
        await db.commit()
    finally:
        await db.close()


async def get_promo_code(code: str) -> dict | None:
    """Возвращает промокод по коду или None."""
    code = (code or "").strip().upper()
    if not code:
        return None
    if _use_turso:
        rs = _turso_execute("SELECT code, discount_percent, max_uses, used_count, expires_at, created_at, promo_type, pro_days FROM promo_codes WHERE code = ?", [code])
        if not rs["rows"]:
            return None
        r = rs["rows"][0]
        return {"code": r[0], "discount_percent": r[1], "max_uses": r[2], "used_count": r[3], "expires_at": r[4], "created_at": r[5] or 0, "promo_type": r[6] if len(r) > 6 else "discount", "pro_days": r[7] if len(r) > 7 else 0}
    db = await aiosqlite.connect(DB_PATH)
    try:
        cur = await db.execute(
            "SELECT code, discount_percent, max_uses, used_count, expires_at, created_at, promo_type, pro_days FROM promo_codes WHERE code = ?",
            (code,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return {"code": row[0], "discount_percent": row[1], "max_uses": row[2], "used_count": row[3], "expires_at": row[4], "created_at": row[5] or 0, "promo_type": row[6] if len(row) > 6 else "discount", "pro_days": row[7] if len(row) > 7 else 0}
    finally:
        await db.close()


async def check_promo_used_by_user(telegram_id: int, code: str) -> bool:
    """Проверяет, использовал ли пользователь уже этот промокод (1 раз на 1 аккаунт)."""
    code = (code or "").strip().upper()
    if not code:
        return True
    if _use_turso:
        rs = _turso_execute("SELECT 1 FROM promo_code_uses WHERE telegram_id = ? AND code = ?", [telegram_id, code])
        return len(rs.get("rows", [])) > 0
    db = await aiosqlite.connect(DB_PATH)
    try:
        cur = await db.execute("SELECT 1 FROM promo_code_uses WHERE telegram_id = ? AND code = ?", (telegram_id, code))
        row = await cur.fetchone()
        return row is not None
    finally:
        await db.close()


async def record_promo_used_by_user(telegram_id: int, code: str) -> None:
    """Записывает, что пользователь использовал промокод."""
    code = (code or "").strip().upper()
    if not code:
        return
    if _use_turso:
        _turso_execute("INSERT OR IGNORE INTO promo_code_uses (telegram_id, code) VALUES (?, ?)", [telegram_id, code])
        return
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute("INSERT OR IGNORE INTO promo_code_uses (telegram_id, code) VALUES (?, ?)", (telegram_id, code))
        await db.commit()
    finally:
        await db.close()


async def get_user_applied_promo(telegram_id: int) -> str | None:
    """Возвращает применённый (но ещё не использованный при оплате) промокод скидки."""
    if _use_turso:
        rs = _turso_execute("SELECT applied_promo_code FROM users WHERE telegram_id = ?", [telegram_id])
        if rs.get("rows") and rs["rows"][0][0]:
            return rs["rows"][0][0]
        return None
    db = await aiosqlite.connect(DB_PATH)
    try:
        cur = await db.execute("SELECT applied_promo_code FROM users WHERE telegram_id = ?", (telegram_id,))
        row = await cur.fetchone()
        return row[0] if row and row[0] else None
    finally:
        await db.close()


async def set_user_applied_promo(telegram_id: int, code: str | None) -> None:
    """Устанавливает применённый промокод скидки для пользователя."""
    code = (code or "").strip().upper() or None
    if _use_turso:
        _turso_execute("UPDATE users SET applied_promo_code = ? WHERE telegram_id = ?", [code, telegram_id])
        return
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute("UPDATE users SET applied_promo_code = ? WHERE telegram_id = ?", (code, telegram_id))
        await db.commit()
    finally:
        await db.close()


async def apply_promo_for_user(telegram_id: int, code: str) -> tuple[bool, str]:
    """
    Применяет промокод для пользователя.
    Возвращает (ok, message). 1 промокод = 1 раз на 1 аккаунт.
    Для free_pro — сразу выдаёт Pro. Для discount — сохраняет для следующей оплаты.
    """
    promo = await get_promo_code(code)
    if not promo:
        return (False, "Промокод не найден")
    if await check_promo_used_by_user(telegram_id, code):
        return (False, "Вы уже использовали этот промокод")
    now = time.time()
    if promo.get("expires_at") and promo["expires_at"] < now:
        return (False, "Срок действия промокода истёк")
    if promo.get("max_uses", 0) > 0 and promo.get("used_count", 0) >= promo["max_uses"]:
        return (False, "Промокод исчерпан")

    promo_type = promo.get("promo_type") or "discount"
    if promo_type == "free_pro":
        days = max(1, min(50000, promo.get("pro_days") or 30))
        await set_user_pro(telegram_id, True, days=days)
        await record_promo_used_by_user(telegram_id, code)
        await increment_promo_used(code)
        return (True, f"Pro на {days} дней активирован!")
    else:
        await record_promo_used_by_user(telegram_id, code)
        await set_user_applied_promo(telegram_id, code)
        return (True, f"Скидка {promo.get('discount_percent', 0)}% будет применена при оплате")


async def validate_and_apply_promo(code: str, telegram_id: int | None = None) -> tuple[int, str | None]:
    """
    Проверяет промокод и возвращает (discount_percent, error_message).
    Для типа discount. Если telegram_id передан — проверяет, не использовал ли уже пользователь.
    Не увеличивает used_count — это делается при успешной оплате.
    """
    promo = await get_promo_code(code)
    if not promo:
        return (0, "Промокод не найден")
    if promo.get("promo_type") == "free_pro":
        return (0, "Этот промокод — бесплатный Pro. Примените его в профиле.")
    now = time.time()
    if promo.get("expires_at") and promo["expires_at"] < now:
        return (0, "Срок действия промокода истёк")
    if promo.get("max_uses", 0) > 0 and promo.get("used_count", 0) >= promo["max_uses"]:
        return (0, "Промокод исчерпан")
    if telegram_id and await check_promo_used_by_user(telegram_id, code):
        return (0, "Вы уже использовали этот промокод")
    return (promo.get("discount_percent", 0), None)


async def increment_promo_used(code: str) -> None:
    """Увеличивает счётчик использований промокода (после успешной оплаты)."""
    code = (code or "").strip().upper()
    if not code:
        return
    if _use_turso:
        _turso_execute("UPDATE promo_codes SET used_count = used_count + 1 WHERE code = ?", [code])
        return
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute("UPDATE promo_codes SET used_count = used_count + 1 WHERE code = ?", (code,))
        await db.commit()
    finally:
        await db.close()


async def list_promo_codes() -> list[dict]:
    """Список всех промокодов."""
    if _use_turso:
        rs = _turso_execute("SELECT code, discount_percent, max_uses, used_count, expires_at, created_at, promo_type, pro_days FROM promo_codes ORDER BY created_at DESC")
        return [
            {"code": r[0], "discount_percent": r[1], "max_uses": r[2], "used_count": r[3], "expires_at": r[4], "created_at": r[5] or 0, "promo_type": r[6] if len(r) > 6 else "discount", "pro_days": r[7] if len(r) > 7 else 0}
            for r in rs["rows"]
        ]
    db = await aiosqlite.connect(DB_PATH)
    try:
        cur = await db.execute(
            "SELECT code, discount_percent, max_uses, used_count, expires_at, created_at, promo_type, pro_days FROM promo_codes ORDER BY created_at DESC"
        )
        rows = await cur.fetchall()
        return [
            {"code": r[0], "discount_percent": r[1], "max_uses": r[2], "used_count": r[3], "expires_at": r[4], "created_at": r[5] or 0, "promo_type": r[6] if len(r) > 6 else "discount", "pro_days": r[7] if len(r) > 7 else 0}
            for r in rows
        ]
    finally:
        await db.close()


async def delete_promo_code(code: str) -> bool:
    """Удаляет промокод. Возвращает True если удалён."""
    code = (code or "").strip().upper()
    if not code:
        return False
    if _use_turso:
        _turso_execute("DELETE FROM promo_codes WHERE code = ?", [code])
        return True
    db = await aiosqlite.connect(DB_PATH)
    try:
        await db.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
        await db.commit()
        return True
    finally:
        await db.close()


# ─── Turso via libsql-client


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
