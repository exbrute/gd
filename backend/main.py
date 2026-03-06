import hashlib
import hmac
import html as html_module
import json
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal, Optional
from urllib.parse import parse_qs, unquote

import jwt
from fastapi import FastAPI, HTTPException, Query, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
import httpx
from openai import OpenAI
from pydantic import BaseModel

from .database import (
    init_db, get_or_create_user, check_can_solve, increment_usage,
    get_all_users, set_user_pro, set_user_banned, reset_user_requests,
    save_solution, get_and_delete_solution, list_solutions_for_user,
    delete_solutions_older_than, SOLUTION_RETENTION_SECONDS,
    user_has_active_pro, FREE_LIMIT,
    create_promo_code, get_promo_code, validate_and_apply_promo, increment_promo_used, list_promo_codes, delete_promo_code,
    apply_promo_for_user, get_user_applied_promo, set_user_applied_promo,
)

load_dotenv()

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "").strip()
AUTH_SECRET = os.getenv("AUTH_SECRET", "").strip() or ADMIN_SECRET
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
INIT_DATA_EXPIRY = 86400  # initData valid for 24h

# Crypto Pay (CryptoBot) — https://help.send.tg/en/articles/10279948-crypto-pay-api
CRYPTO_PAY_API_TOKEN = os.getenv("CRYPTO_PAY_API_TOKEN", "").strip()
CRYPTO_PAY_BASE = "https://testnet-pay.crypt.bot" if os.getenv("CRYPTO_PAY_TESTNET", "").lower() in ("1", "true", "yes") else "https://pay.crypt.bot"
PRO_PRICE_AMOUNT = os.getenv("PRO_PRICE_AMOUNT", "299").strip()
PRO_PRICE_CURRENCY = os.getenv("PRO_PRICE_CURRENCY", "RUB").strip()  # RUB, USD, EUR, etc.
# Скидка на Pro в % (0–100), любое значение
PRO_DISCOUNT_PERCENT = max(0, min(100, float(os.getenv("PRO_DISCOUNT_PERCENT", "0").strip() or 0)))


def validate_init_data(init_data: str) -> dict | None:
    """
    Validate Telegram WebApp initData.
    https://core.telegram.org/bots/webapps#validating-data-received-from-the-web-app
    secret_key = HMAC_SHA256(bot_token, "WebAppData")
    hash = HMAC_SHA256(secret_key, data_check_string)
    """
    if not TELEGRAM_BOT_TOKEN or not init_data:
        return None
    try:
        parsed = parse_qs(init_data, keep_blank_values=True)
        received_hash = parsed.get("hash", [""])[0]
        if not received_hash:
            return None

        auth_date = int(parsed.get("auth_date", ["0"])[0])
        if time.time() - auth_date > INIT_DATA_EXPIRY:
            return None

        check_pairs = []
        for key in sorted(parsed.keys()):
            if key == "hash":
                continue
            check_pairs.append(f"{key}={parsed[key][0]}")
        data_check_string = "\n".join(check_pairs)

        secret_key = hmac.new(
            TELEGRAM_BOT_TOKEN.encode(), b"WebAppData", hashlib.sha256
        ).digest()
        computed_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            return None

        user_json = parsed.get("user", [""])[0]
        if user_json:
            return json.loads(unquote(user_json))
        return {}
    except Exception:
        return None


def require_telegram(init_data: str | None) -> dict:
    """Validate initData header. Returns user dict or empty dict if can't validate."""
    if not TELEGRAM_BOT_TOKEN or not init_data:
        return {}
    user = validate_init_data(init_data)
    return user if user is not None else {}


def _jwt_secret() -> str:
    """JWT требует ключ >= 32 байт для HS256. Короткие секреты дополняем через SHA256."""
    s = AUTH_SECRET
    if not s:
        return ""
    return hashlib.sha256(s.encode()).hexdigest() if len(s.encode()) < 32 else s


def _verify_auth_token(token: str) -> dict | None:
    """Verify JWT from bot /auth. Returns user dict {id, first_name, username} or None."""
    secret = _jwt_secret()
    if not secret or not token:
        return None
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        uid = payload.get("telegram_id") or payload.get("sub")
        if not uid:
            return None
        return {
            "id": int(uid),
            "first_name": payload.get("first_name", ""),
            "username": payload.get("username", ""),
        }
    except Exception:
        return None

OPENAI_MODEL_DEFAULT = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip() or None
ONLYSQ_API_STYLE = os.getenv("ONLYSQ_API_STYLE", "openai").strip().lower()
ONLYSQ_V2_URL = (os.getenv("ONLYSQ_V2_URL", "https://api.onlysq.ru/ai/v2").strip()) or "https://api.onlysq.ru/ai/v2"

# OpenRouter: https://openrouter.ai/docs/quickstart
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "").strip() or "openai/gpt-4o-mini"
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "").strip()
OPENROUTER_APP_TITLE = os.getenv("OPENROUTER_APP_TITLE", "").strip()


def build_openai_client() -> Optional[OpenAI]:
    """
    Supports (priority):
    - OpenRouter: OPENROUTER_API_KEY (base_url=https://openrouter.ai/api/v1)
    - OpenAI напрямую: OPENAI_API_KEY (+ optional OPENAI_BASE_URL)
    - OnlySq (OpenAI SDK compatible): ONLYSQ_API_KEY + OPENAI_BASE_URL=https://api.onlysq.ru/v1
    """
    if OPENROUTER_API_KEY:
        kwargs = {
            "api_key": OPENROUTER_API_KEY,
            "base_url": "https://openrouter.ai/api/v1",
        }
        if OPENROUTER_SITE_URL or OPENROUTER_APP_TITLE:
            kwargs["default_headers"] = {}
            if OPENROUTER_SITE_URL:
                kwargs["default_headers"]["HTTP-Referer"] = OPENROUTER_SITE_URL
            if OPENROUTER_APP_TITLE:
                kwargs["default_headers"]["X-OpenRouter-Title"] = OPENROUTER_APP_TITLE
        return OpenAI(**kwargs)

    api_key = os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("ONLYSQ_API_KEY", "").strip()
    if not api_key:
        return None

    base_url = OPENAI_BASE_URL
    if not base_url and os.getenv("ONLYSQ_API_KEY", "").strip():
        base_url = "https://api.onlysq.ru/v1"

    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)


client = build_openai_client()

# Модель для запросов: при OpenRouter — OPENROUTER_MODEL, иначе OPENAI_MODEL
MODEL_FOR_REQUESTS = OPENROUTER_MODEL if OPENROUTER_API_KEY else OPENAI_MODEL_DEFAULT


@asynccontextmanager
async def lifespan(application: FastAPI):
    try:
        await init_db()
    except Exception as e:
        print(f"[WARN] DB init failed: {e}")
    yield

app = FastAPI(title="GDZ Bot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


static_dir = os.path.join(os.path.dirname(__file__), "..", "webapp")
static_dir = os.path.abspath(static_dir)
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Решения хранятся в БД (Turso/SQLite) — на Vercel память не общая между инстансами


class SolveRequest(BaseModel):
    text: Optional[str] = None
    detail: Literal["short", "detailed"] = "short"
    image_base64: Optional[str] = None
    telegram_id: Optional[int] = None
    init_data: Optional[str] = None
    auth_token: Optional[str] = None


class SolveResponse(BaseModel):
    answer: str
    solution_url: Optional[str] = None  # страница решения (сохраняется сразу с telegram_id)


class SolutionCreateRequest(BaseModel):
    answer: str
    task_text: Optional[str] = None  # текст задачи для отображения в истории
    telegram_id: Optional[int] = None  # fallback, если init_data/auth не определили пользователя
    init_data: Optional[str] = None
    auth_token: Optional[str] = None


class SolutionCreateResponse(BaseModel):
    url: str


class PayCreateRequest(BaseModel):
    method: Literal["sbp", "cryptobot"]
    promo_code: Optional[str] = None  # опционально — можно использовать применённый в профиле
    init_data: Optional[str] = None
    auth_token: Optional[str] = None


class ApplyPromoRequest(BaseModel):
    code: str
    init_data: Optional[str] = None
    auth_token: Optional[str] = None


def _serve_index() -> FileResponse:
    index_path = os.path.join(static_dir, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=500, detail="Frontend is not built or missing.")
    return FileResponse(index_path)


@app.get("/", response_class=FileResponse)
async def index() -> FileResponse:
    """Telegram WebApp entry point."""
    return _serve_index()


@app.get("/pay", response_class=FileResponse)
async def pay_page() -> FileResponse:
    """Страница оплаты Pro — тот же SPA."""
    return _serve_index()


def _find_brace_end(s: str, start: int) -> int:
    """Индекс парной } для { в start. -1 если нет."""
    if start >= len(s) or s[start] != "{":
        return -1
    depth = 0
    for j in range(start, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    return -1


def _fix_bare_latex_commands(text: str) -> str:
    """Модель иногда пишет frac, eq, mathbb без backslash — восстанавливаем."""
    if not text:
        return text
    t = text
    t = re.sub(r"(?<!\\)frac\{", r"\\frac{", t)
    t = re.sub(r"(?<!\\)sqrt\{", r"\\sqrt{", t)
    t = re.sub(r"(?<!\\)mathbb\{", r"\\mathbb{", t)
    t = re.sub(r"(?<!\\)in mathbb", r"\\in \\mathbb", t)
    t = re.sub(r"(?<!\\)mid ", r"\\mid ", t)
    t = re.sub(r"(?<!\\)setminus", r"\\setminus", t)
    t = re.sub(r" eq (?=[0-9\-xX])", r" \\neq ", t)
    t = re.sub(r" in (?=mathbb|\\\\mathbb|R[^a-z])", r" \\in ", t)
    # R в множествах → \mathbb{R}
    t = re.sub(r"\\in R\b", r"\\in \\mathbb{R}", t)
    t = re.sub(r"\\in R\s*\|", r"\\in \\mathbb{R} \\mid", t)
    t = re.sub(r"\\in R\s*\}", r"\\in \\mathbb{R} \\}", t)
    # | в множествах \mathbb{R} | x → \mathbb{R} \mid x
    t = re.sub(r"(\\mathbb\{R\})\s*\|\s*", r"\1 \\mid ", t)
    # Убираем дубли "D = { x D = {x"
    t = re.sub(r"D = \\\\\{\s*x\s*D = \\\\\{x", r"D = \\\\{x", t)
    # Опечатка модели: x - 4x - 4 → x - 4, x + 4x + 4 → x + 4
    t = re.sub(r"x - 4x - 4", r"x - 4", t)
    t = re.sub(r"x \+ 4x \+ 4", r"x + 4", t)
    return t


def prepare_math_for_render(text: str) -> str:
    """Минимальная подготовка: фиксим голые LaTeX-команды и нормализуем слеши.
    Модель сама ставит \\( \\) — не нужно оборачивать повторно."""
    if not text:
        return text
    t = _fix_bare_latex_commands(text)
    t = re.sub(r"\\\\+([a-zA-Z])", r"\\\1", t)  # \\frac → \frac
    t = re.sub(r"[\\]+\(", r"\\(", t)
    t = re.sub(r"[\\]+\)", r"\\)", t)
    t = re.sub(r"[\\]+\[", r"\\[", t)
    t = re.sub(r"[\\]+\]", r"\\]", t)
    return t


@app.get("/api/me")
async def api_me(request: Request, debug: bool = Query(False)):
    """Extract user from initData or X-Auth-Token (JWT from bot /auth)."""
    init_data = _get_init_data(request)
    auth_token = _get_auth_token(request)
    tg_user = _resolve_user(request, init_data, auth_token)
    uid = tg_user.get("id")

    if not uid and init_data:
        try:
            params = parse_qs(init_data, keep_blank_values=True)
            user_json = params.get("user", [""])[0]
            if user_json:
                import json as _json
                parsed = _json.loads(unquote(user_json))
                uid = parsed.get("id")
                tg_user = parsed
        except Exception:
            pass

    if not uid:
        resp = {"telegram_id": None, "first_name": "", "username": "", "is_pro": False,
                "remaining": FREE_LIMIT, "requests_used": 0, "allowed": True, "reason": "anonymous",
                "days_until_update": 7, "free_limit": FREE_LIMIT}
        if debug:
            resp["debug"] = {
                "init_data_received": bool(init_data and len(init_data) > 0),
                "init_data_len": len(init_data) if init_data else 0,
                "auth_token_used": bool(auth_token),
                "bot_token_set": bool(TELEGRAM_BOT_TOKEN),
            }
        return resp

    username = tg_user.get("username", "")
    first_name = tg_user.get("first_name", "")
    user = await get_or_create_user(int(uid), username, first_name)
    limits = await check_can_solve(int(uid))
    applied = await get_user_applied_promo(int(uid))
    return {
        "telegram_id": user["telegram_id"],
        "username": user["username"],
        "first_name": user["first_name"],
        "is_pro": user_has_active_pro(user),
        "is_banned": bool(user["is_banned"]),
        "requests_used": user["requests_used"],
        "remaining": limits["remaining"],
        "allowed": limits["allowed"],
        "reason": limits["reason"],
        "days_until_update": limits.get("days_until_update"),
        "free_limit": limits.get("free_limit"),
        "applied_promo_code": applied,
    }


@app.get("/api/user")
async def api_user(
    telegram_id: int = Query(...),
    username: str = Query(""),
    first_name: str = Query(""),
    x_telegram_init_data: str | None = Header(None),
):
    tg_user = require_telegram(x_telegram_init_data)
    if tg_user.get("id") and tg_user["id"] != telegram_id:
        raise HTTPException(status_code=403, detail="User ID mismatch")
    user = await get_or_create_user(telegram_id, username, first_name)
    limits = await check_can_solve(telegram_id)
    return {
        "telegram_id": user["telegram_id"],
        "username": user["username"],
        "first_name": user["first_name"],
        "is_pro": user_has_active_pro(user),
        "is_banned": bool(user["is_banned"]),
        "requests_used": user["requests_used"],
        "remaining": limits["remaining"],
        "allowed": limits["allowed"],
        "reason": limits["reason"],
        "free_limit": limits.get("free_limit"),
    }


@app.post("/api/solve", response_model=SolveResponse)
async def solve(req: SolveRequest, request: Request) -> SolveResponse:
    init_data = _get_init_data(request, req.init_data)
    auth_token = _get_auth_token(request, req.auth_token)
    tg_user = _resolve_user(request, init_data, auth_token)
    if tg_user.get("id") and req.telegram_id and tg_user["id"] != req.telegram_id:
        raise HTTPException(status_code=403, detail="User ID mismatch")
    if not req.telegram_id and tg_user.get("id"):
        req.telegram_id = tg_user["id"]

    if not client:
        raise HTTPException(
            status_code=500,
            detail="AI provider is not configured.",
        )

    if not (req.text or req.image_base64):
        raise HTTPException(
            status_code=400, detail="Either text or image must be provided."
        )

    if req.telegram_id:
        limits = await check_can_solve(req.telegram_id)
        if not limits["allowed"]:
            if limits["reason"] == "banned":
                raise HTTPException(status_code=403, detail="Ваш аккаунт заблокирован.")
            raise HTTPException(status_code=429, detail="Лимит запросов исчерпан. Подождите 7 дней или оформите Pro-подписку.")

    system_prompt = (
        "Ты опытный школьный учитель математики. Решай задачи так, как объяснял бы ученику у доски: "
        "простым языком, пошагово, с пояснением каждого действия — почему именно так, а не иначе. "
        "Если есть подводные камни или типичные ошибки, предупреди о них. "
        "Отвечай на русском языке. "
        "Все математические формулы обязательно оформляй в LaTeX: "
        "для формул внутри текста используй \\( ... \\), для формул на отдельной строке — \\[ ... \\]. "
        "Примеры: \\( y = \\frac{7}{x-4} \\), \\( x \\in \\mathbb{R} \\), \\( D = \\{ x \\mid x \\neq 4 \\} \\). "
    )

    if req.detail == "short":
        system_prompt += (
            "Отвечай по делу, но каждый шаг объясняй понятно. Не пропускай логику — ученик должен понять, а не просто списать."
        )
    else:
        system_prompt += (
            "Расписывай максимально подробно: каждый шаг, каждый переход, каждое правило. "
            "Объясняй так, чтобы даже тот, кто видит тему впервые, всё понял."
        )

    user_content: list = []
    if req.text:
        user_content.append(
            {"type": "text", "text": f"Вот условие задачи:\n\n{req.text.strip()}"}
        )

    if req.image_base64:
        # Frontend отправляет base64 без префикса или с data: URI – поддерживаем оба варианта.
        image_url = req.image_base64
        if not image_url.startswith("data:"):
            image_url = f"data:image/jpeg;base64,{image_url}"

        user_content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": image_url,
                },
            }
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    # OnlySq API v2 mode (NOT OpenAI-compatible; skip when using OpenRouter)
    if ONLYSQ_API_STYLE == "v2" and not OPENROUTER_API_KEY:
        onlysq_key = os.getenv("ONLYSQ_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()
        if not onlysq_key:
            raise HTTPException(status_code=500, detail="ONLYSQ_API_KEY is not configured.")

        model_to_use = OPENAI_MODEL_DEFAULT
        print(f"[DEBUG] OnlySq v2: using model '{model_to_use}' (from OPENAI_MODEL={os.getenv('OPENAI_MODEL', 'NOT SET')})")
        payload = {"model": model_to_use, "request": {"messages": messages}}
        headers = {"Authorization": f"Bearer {onlysq_key}", "Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=60) as h:
                r = await h.post(ONLYSQ_V2_URL, json=payload, headers=headers)
        except Exception as exc:  # pragma: no cover - defensive
            raise HTTPException(status_code=500, detail=f"OnlySq v2 error: {exc}") from exc

        if r.status_code != 200:
            raise HTTPException(
                status_code=500,
                detail=f"OnlySq v2 returned {r.status_code}: {r.text[:500]}",
            )

        data = r.json()
        answer = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if req.telegram_id:
            await increment_usage(req.telegram_id)
        answer_rendered = prepare_math_for_render(str(answer).strip())
        task_label = (req.text or "").strip() or "Задача по изображению"
        sid = str(uuid.uuid4())
        tid = req.telegram_id or (tg_user.get("id") if tg_user else None)
        await save_solution(sid, answer_rendered, telegram_id=tid, task_text=task_label)
        return SolveResponse(answer=answer_rendered, solution_url=f"/solution/{sid}")

    try:
        completion = client.chat.completions.create(
            model=MODEL_FOR_REQUESTS,
            messages=messages,
        )
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"AI API error: {exc}") from exc

    answer = completion.choices[0].message.content or ""
    if req.telegram_id:
        await increment_usage(req.telegram_id)
    answer_rendered = prepare_math_for_render(answer.strip())
    task_label = (req.text or "").strip() or "Задача по изображению"
    sid = str(uuid.uuid4())
    tid = req.telegram_id or (tg_user.get("id") if tg_user else None)
    await save_solution(sid, answer_rendered, telegram_id=tid, task_text=task_label)
    return SolveResponse(answer=answer_rendered, solution_url=f"/solution/{sid}")


def _normalize_math_delimiters(content: str) -> str:
    r"""Убирает лишние слеши перед ( ) [ ] — любой \\+ перед delimiter → один \."""
    t = content
    t = re.sub(r"[\\]+\(", r"\\(", t)
    t = re.sub(r"[\\]+\)", r"\\)", t)
    t = re.sub(r"[\\]+\[", r"\\[", t)
    t = re.sub(r"[\\]+\]", r"\\]", t)
    return t


def _clean_solution_content(content: str) -> str:
    """Убирает ### перед номерами и заменяет \\[ \\] на \\( \\) — иначе отображается как текст."""
    t = content
    # ### a), ### 1. и т.д. → просто a), 1.
    t = re.sub(r"^###\s*", "", t, flags=re.MULTILINE)
    # \[ ... \] → \( ... \) — используем только inline, чтобы \] не светилось как текст
    t = re.sub(r"\\\[", r"\\(", t)
    t = re.sub(r"\\\]", r"\\)", t)
    return t


def _build_solution_html(content: str, solution_id: str = "") -> str:
    """Собирает полную HTML-страницу решения в стиле «Вот, что у нас получилось»."""
    content = _clean_solution_content(content)
    content = _normalize_math_delimiters(content)
    # \( и \) на отдельных строках → склеиваем, иначе <br> разобьёт на разные DOM-узлы и KaTeX не найдёт
    content = re.sub(r'\\\(\s+', r'\\( ', content)
    content = re.sub(r'\s+\\\)', r' \\)', content)
    safe = html_module.escape(content).replace("\n", "<br>")
    short_id = solution_id[:8] if solution_id else ""
    date_str = datetime.now().strftime("%d.%m.%Y")
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Решение</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    *{{ box-sizing:border-box; margin:0; padding:0; }}
    html{{ min-height:100%%; }}
    body{{ min-height:100vh; font-family:Inter,system-ui,sans-serif; background:#050a18; color:#c8d6e5; line-height:1.7; -webkit-font-smoothing:antialiased; overflow-x:hidden; }}

    .bg{{ position:fixed; inset:0; z-index:0; pointer-events:none; }}
    .bg .orb{{ position:absolute; border-radius:50%%; filter:blur(100px); opacity:.35; animation:float 12s ease-in-out infinite alternate; }}
    .bg .orb-1{{ width:420px; height:420px; top:-10%%; left:-8%%; background:radial-gradient(circle,#6366f1,transparent 70%%); }}
    .bg .orb-2{{ width:350px; height:350px; bottom:-5%%; right:-10%%; background:radial-gradient(circle,#f97316,transparent 70%%); animation-delay:-4s; animation-duration:14s; }}
    .bg .orb-3{{ width:280px; height:280px; top:40%%; left:50%%; transform:translateX(-50%%); background:radial-gradient(circle,#06b6d4,transparent 70%%); animation-delay:-8s; animation-duration:16s; }}
    .bg .grid{{ position:absolute; inset:0; background-image: linear-gradient(rgba(148,163,184,.04) 1px,transparent 1px), linear-gradient(90deg,rgba(148,163,184,.04) 1px,transparent 1px); background-size:48px 48px; mask-image:radial-gradient(ellipse 60%% 50%% at 50%% 0%%,#000 30%%,transparent 100%%); }}
    @keyframes float{{ 0%{{ transform:translate(0,0) scale(1); }} 100%{{ transform:translate(30px,-40px) scale(1.12); }} }}

    .wrap{{ position:relative; z-index:1; max-width:460px; margin:0 auto; padding:28px 18px 40px; }}

    .top-bar{{ display:flex; align-items:center; justify-content:space-between; margin-bottom:28px; animation:fadeDown .5s ease-out both; }}
    .back{{ display:inline-flex; align-items:center; gap:6px; color:#64748b; font-size:13px; font-weight:500; text-decoration:none; transition:color .25s; }}
    .back:hover{{ color:#e2e8f0; }}
    .back svg{{ width:16px; height:16px; stroke:currentColor; stroke-width:2; fill:none; }}
    .badge{{ padding:5px 12px; border-radius:999px; font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:.12em; background:linear-gradient(135deg,rgba(34,197,94,.15),rgba(34,197,94,.05)); border:1px solid rgba(34,197,94,.3); color:#4ade80; }}

    .hero{{ text-align:center; margin-bottom:32px; animation:fadeDown .6s ease-out .1s both; }}
    .hero h1{{ font-size:26px; font-weight:800; letter-spacing:-.03em; background:linear-gradient(135deg,#f1f5f9 0%%,#94a3b8 100%%); -webkit-background-clip:text; -webkit-text-fill-color:transparent; background-clip:text; }}
    .hero p{{ margin-top:8px; font-size:13px; color:#64748b; }}

    .solution-card{{ position:relative; border-radius:20px; padding:2px; margin-bottom:24px; background:linear-gradient(135deg,rgba(99,102,241,.4),rgba(249,115,22,.3),rgba(6,182,212,.3)); animation:fadeUp .6s ease-out .2s both; }}
    .solution-card-inner{{ border-radius:18px; padding:24px 20px; background:linear-gradient(160deg,rgba(15,23,42,.97),rgba(15,23,42,.92)); backdrop-filter:blur(40px); }}
    .solution-card::before{{ content:''; position:absolute; inset:-1px; border-radius:21px; background:linear-gradient(135deg,rgba(99,102,241,.2),rgba(249,115,22,.15),rgba(6,182,212,.15)); filter:blur(20px); opacity:.6; z-index:-1; }}

    #content{{ font-size:14px; color:#cbd5e1; }}
    #content p{{ margin:0 0 10px; }}
    #content .katex{{ font-size:1.08em; color:#e2e8f0; }}
    #content .katex-display{{ margin:14px 0; overflow-x:auto; padding:12px 0; border-top:1px solid rgba(148,163,184,.08); border-bottom:1px solid rgba(148,163,184,.08); }}

    .actions{{ display:flex; gap:10px; flex-wrap:wrap; justify-content:center; margin-bottom:24px; animation:fadeUp .6s ease-out .35s both; }}
    .btn{{ position:relative; padding:12px 22px; border-radius:14px; border:1px solid rgba(148,163,184,.15); background:rgba(15,23,42,.8); color:#e2e8f0; font:600 13px/1.4 Inter,sans-serif; cursor:pointer; text-decoration:none; transition:all .3s cubic-bezier(.4,0,.2,1); overflow:hidden; backdrop-filter:blur(12px); }}
    .btn::before{{ content:''; position:absolute; inset:0; border-radius:inherit; background:radial-gradient(circle at 20%% -20%%,rgba(255,255,255,.06),transparent 60%%); pointer-events:none; }}
    .btn:hover{{ border-color:rgba(148,163,184,.35); transform:translateY(-2px); box-shadow:0 8px 32px rgba(0,0,0,.4); }}
    .btn-primary{{ background:linear-gradient(135deg,#f97316,#fb923c); border:none; color:#0f172a; font-weight:700; box-shadow:0 0 0 1px rgba(249,115,22,.2), 0 12px 40px rgba(249,115,22,.3); }}
    .btn-primary:hover{{ box-shadow:0 0 0 1px rgba(249,115,22,.3), 0 20px 50px rgba(249,115,22,.4); filter:brightness(1.08); }}
    .btn-icon{{ width:16px; height:16px; stroke:currentColor; stroke-width:2; fill:none; vertical-align:-2px; margin-right:6px; }}

    .footer{{ display:flex; justify-content:space-between; align-items:center; font-size:11px; color:#475569; padding-top:16px; border-top:1px solid rgba(148,163,184,.06); animation:fadeUp .6s ease-out .55s both; }}
    .footer span{{ display:flex; align-items:center; gap:4px; }}

    .pro-card{{ position:relative; border-radius:16px; padding:20px 18px; margin-bottom:24px; background:linear-gradient(135deg,rgba(249,115,22,.12),rgba(249,115,22,.04)); border:1px solid rgba(249,115,22,.25); animation:fadeUp .6s ease-out .15s both; }}
    .pro-card h3{{ font-size:16px; font-weight:700; color:#f97316; margin:0 0 14px; }}
    .pro-card-list{{ list-style:none; margin:0 0 16px; padding:0; }}
    .pro-card-list li{{ display:flex; align-items:center; gap:8px; font-size:13px; color:#e2e8f0; margin-bottom:8px; }}
    .pro-card-list li:last-child{{ margin-bottom:0; }}
    .pro-card-btn{{ display:inline-flex; align-items:center; gap:6px; padding:10px 18px; border-radius:12px; border:none; background:linear-gradient(135deg,#f97316,#fb923c); color:#0f172a; font:600 14px Inter,sans-serif; cursor:pointer; text-decoration:none; transition:transform .2s, box-shadow .2s; box-shadow:0 8px 24px rgba(249,115,22,.35); }}
    .pro-card-btn:hover{{ transform:translateY(-1px); box-shadow:0 12px 32px rgba(249,115,22,.45); }}

    @keyframes fadeDown{{ from{{ opacity:0; transform:translateY(-12px); }} to{{ opacity:1; transform:translateY(0); }} }}
    @keyframes fadeUp{{ from{{ opacity:0; transform:translateY(16px); }} to{{ opacity:1; transform:translateY(0); }} }}
  </style>
</head>
<body>
  <div class="bg">
    <div class="orb orb-1"></div>
    <div class="orb orb-2"></div>
    <div class="orb orb-3"></div>
    <div class="grid"></div>
  </div>

  <div class="wrap">
    <div class="top-bar">
      <a href="/" class="back">
        <svg viewBox="0 0 24 24"><path d="M19 12H5M12 5l-7 7 7 7"/></svg>
        Назад
      </a>
      <span class="badge">Готово</span>
    </div>

    <div class="hero">
      <h1>Решение готово</h1>
      <p>Формулы отрендерены автоматически</p>
    </div>

    <div class="pro-card">
      <h3>Хочешь безлимит? Оформи Pro.</h3>
      <ul class="pro-card-list">
        <li>✨ Безлимит задач</li>
        <li>✨ Приоритетная скорость</li>
        <li>✨ Решение «как в тетради»</li>
        <li>✨ Разные способы решения</li>
      </ul>
      <a href="/#pay" class="pro-card-btn">🔥 Перейти на PRO</a>
    </div>

    <div class="solution-card">
      <div class="solution-card-inner">
        <div id="content">{safe}</div>
      </div>
    </div>

    <div class="actions">
      <a href="/" class="btn btn-primary">
        <svg class="btn-icon" viewBox="0 0 24 24"><path d="M12 5v14M5 12l7-7 7 7"/></svg>
        Новая задача
      </a>
      <button type="button" class="btn" id="copy-btn">
        <svg class="btn-icon" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
        Копировать
      </button>
      <button type="button" class="btn" id="share-btn">
        <svg class="btn-icon" viewBox="0 0 24 24"><circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.59 13.51l6.83 3.98M15.41 6.51l-6.82 3.98"/></svg>
        Поделиться
      </button>
    </div>

    <div class="footer">
      <span>{date_str}</span>
      <span>#{short_id}</span>
    </div>
  </div>

  <script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
  <script>
    document.addEventListener("DOMContentLoaded", function() {{
      var el = document.getElementById("content");
      if (el && window.renderMathInElement) {{
        renderMathInElement(el, {{
          delimiters: [
            {{ left: "$$", right: "$$", display: true }},
            {{ left: "\\\\(", right: "\\\\)", display: false }},
            {{ left: "$", right: "$", display: false }}
          ],
          throwOnError: false
        }});
      }}

      var copyBtn = document.getElementById("copy-btn");
      if (copyBtn) copyBtn.addEventListener("click", function() {{
        navigator.clipboard.writeText(el.innerText).then(function() {{
          copyBtn.textContent = "Скопировано!";
          setTimeout(function() {{ copyBtn.innerHTML = '<svg class="btn-icon" viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>Копировать'; }}, 1500);
        }});
      }});

      var shareBtn = document.getElementById("share-btn");
      if (shareBtn) shareBtn.addEventListener("click", function() {{
        if (navigator.share) {{
          navigator.share({{ title: "Решение", text: el.innerText }}).catch(function(){{}});
        }} else {{
          navigator.clipboard.writeText(el.innerText).then(function() {{ alert("Текст скопирован — отправь в чат!"); }});
        }}
      }});
    }});
  </script>
</body>
</html>"""


@app.post("/api/solution", response_model=SolutionCreateResponse)
async def create_solution(req: SolutionCreateRequest, request: Request) -> SolutionCreateResponse:
    init_data = _get_init_data(request, req.init_data)
    auth_token = _get_auth_token(request, req.auth_token)
    if not init_data and not auth_token and not req.telegram_id:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    tg_user = _resolve_user(request, init_data, auth_token)
    telegram_id = (tg_user.get("id") if tg_user else None) or req.telegram_id
    sid = str(uuid.uuid4())
    await save_solution(sid, (req.answer or "").strip(), telegram_id=telegram_id, task_text=req.task_text)
    return SolutionCreateResponse(url=f"/solution/{sid}")


@app.get("/api/solutions")
async def api_list_solutions(request: Request):
    """Список сохранённых решений пользователя за последние 12 часов (для личного кабинета)."""
    init_data = _get_init_data(request)
    auth_token = _get_auth_token(request)
    if not init_data and not auth_token:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    tg_user = _resolve_user(request, init_data, auth_token)
    telegram_id = tg_user.get("id")
    if not telegram_id:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    await delete_solutions_older_than(SOLUTION_RETENTION_SECONDS)
    items = await list_solutions_for_user(int(telegram_id))
    return {"solutions": [{"id": x["id"], "created_at": x["created_at"], "task_text": x.get("task_text")} for x in items]}


@app.get("/solution/{solution_id}", response_class=HTMLResponse)
async def get_solution_page(solution_id: str) -> HTMLResponse:
    """Отдаёт одноразовую HTML-страницу с решением. Решения хранятся 12 часов."""
    content = await get_and_delete_solution(solution_id)
    if not content:
        raise HTTPException(status_code=404, detail="Страница просмотрена, не существует или срок хранения истёк (12 ч)")
    return HTMLResponse(content=_build_solution_html(content, solution_id))


def _pro_price_with_discount(extra_discount_percent: float = 0) -> str:
    """Сумма Pro с учётом скидки (PRO_DISCOUNT_PERCENT + дополнительная % от промокода)."""
    try:
        base = float(PRO_PRICE_AMOUNT.replace(",", "."))
    except (ValueError, TypeError):
        base = 299.0
    total_discount = min(100, PRO_DISCOUNT_PERCENT + extra_discount_percent)
    amount = base * (1 - total_discount / 100.0)
    amount = max(0.01, round(amount, 2))
    return str(int(amount) if amount == int(amount) else amount)


async def _crypto_pay_create_invoice(telegram_id: int, promo_discount_percent: int = 0, promo_code: str | None = None) -> dict:
    """Crypto Pay API createInvoice. Сумма с учётом PRO_DISCOUNT_PERCENT и промокода."""
    if not CRYPTO_PAY_API_TOKEN:
        raise HTTPException(status_code=503, detail="Crypto Pay не настроен. Добавьте CRYPTO_PAY_API_TOKEN.")
    payload = {"telegram_id": telegram_id, "product": "pro"}
    if promo_code:
        payload["promo_code"] = promo_code
    payload_data = json.dumps(payload)
    amount = _pro_price_with_discount(extra_discount_percent=promo_discount_percent)
    body = {
        "currency_type": "fiat",
        "fiat": PRO_PRICE_CURRENCY,
        "amount": amount,
        "description": "Pro подписка — безлимит задач",
        "payload": payload_data,
        "expires_in": 3600,  # 1 час
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{CRYPTO_PAY_BASE}/api/createInvoice",
            headers={"Crypto-Pay-API-Token": CRYPTO_PAY_API_TOKEN},
            json=body,
        )
    data = r.json()
    if not data.get("ok"):
        err = data.get("error", {})
        code = err.get("code", "UNKNOWN")
        msg = err.get("name", str(err))
        raise HTTPException(status_code=502, detail=f"Crypto Pay: {code} — {msg}")
    inv = data.get("result", {})
    url = inv.get("mini_app_invoice_url") or inv.get("web_app_invoice_url") or inv.get("bot_invoice_url")
    if not url:
        raise HTTPException(status_code=502, detail="Crypto Pay не вернул URL оплаты")
    return {"url": url, "invoice_id": inv.get("invoice_id")}


def _get_init_data(request: Request, body_init_data: str | None = None) -> str:
    """Извлекает initData из заголовка, query, или тела запроса."""
    h = request.headers.get("X-Telegram-Init-Data") or request.headers.get("x-telegram-init-data")
    q = request.query_params.get("init_data")
    return (h or "").strip() or (q or "").strip() or (body_init_data or "").strip() or ""


def _get_auth_token(request: Request, body_token: str | None = None) -> str:
    """Извлекает JWT auth token из заголовка, query или тела."""
    h = request.headers.get("X-Auth-Token") or request.headers.get("x-auth-token")
    q = request.query_params.get("auth_token") or request.query_params.get("tg_auth")
    return (h or "").strip() or (q or "").strip() or (body_token or "").strip() or ""


def _resolve_user(request: Request, init_data: str = "", auth_token: str = "") -> dict:
    """Определяет пользователя: initData (Telegram WebApp) или JWT (от бота /auth)."""
    if init_data:
        u = require_telegram(init_data)
        if u.get("id"):
            return u
    if auth_token:
        u = _verify_auth_token(auth_token)
        if u:
            return u
    return {}


class AuthTelegramRequest(BaseModel):
    token: str


@app.post("/api/auth/telegram")
async def api_auth_telegram(req: AuthTelegramRequest) -> dict:
    """Обменивает JWT от бота (команда /auth) на данные пользователя."""
    user = _verify_auth_token(req.token or "")
    if not user:
        raise HTTPException(status_code=401, detail="Недействительная ссылка. Отправьте /auth боту заново.")
    uid = user["id"]
    u = await get_or_create_user(uid, user.get("username", ""), user.get("first_name", ""))
    limits = await check_can_solve(uid)
    applied = await get_user_applied_promo(uid)
    return {
        "telegram_id": uid,
        "username": u["username"],
        "first_name": u["first_name"],
        "is_pro": user_has_active_pro(u),
        "requests_used": u["requests_used"],
        "remaining": limits["remaining"],
        "days_until_update": limits.get("days_until_update"),
        "free_limit": limits.get("free_limit"),
        "applied_promo_code": applied,
        "auth_token": req.token,
    }


@app.post("/api/apply-promo")
async def apply_promo(req: ApplyPromoRequest, request: Request):
    """Применяет промокод из профиля. 1 промокод = 1 раз на аккаунт."""
    init_data = _get_init_data(request, req.init_data)
    auth_token = _get_auth_token(request, req.auth_token)
    tg_user = _resolve_user(request, init_data, auth_token)
    telegram_id = tg_user.get("id")
    if not telegram_id:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    code = (req.code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Введите промокод")
    ok, msg = await apply_promo_for_user(int(telegram_id), code)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "message": msg}


@app.post("/api/pay/create")
async def pay_create(req: PayCreateRequest, request: Request):
    """
    Создаёт платёж на подписку Pro.
    Методы: cryptobot (Crypto Pay API), sbp — в разработке.
    """
    init_data = _get_init_data(request, req.init_data)
    auth_token = _get_auth_token(request, req.auth_token)
    tg_user = _resolve_user(request, init_data, auth_token)
    telegram_id = tg_user.get("id")
    if not telegram_id:
        raise HTTPException(status_code=401, detail="Требуется авторизация. Отправьте /auth боту.")

    if req.method not in ("sbp", "cryptobot"):
        raise HTTPException(status_code=400, detail="Неизвестный способ оплаты")

    promo_discount = 0
    applied_promo = (req.promo_code or "").strip() or await get_user_applied_promo(telegram_id)
    if applied_promo:
        promo_discount, err = await validate_and_apply_promo(applied_promo, telegram_id=int(telegram_id))
        if err:
            raise HTTPException(status_code=400, detail=err)
        applied_promo = applied_promo.strip().upper()

    if req.method == "cryptobot":
        result = await _crypto_pay_create_invoice(telegram_id, promo_discount_percent=promo_discount, promo_code=applied_promo)
        return {"ok": True, "url": result["url"]}

    # СБП — в разработке
    raise HTTPException(status_code=501, detail="СБП в разработке. Используйте CryptoBot.")


def _verify_crypto_pay_signature(body: bytes, signature: str) -> bool:
    """Проверка подписи webhook Crypto Pay API (HMAC-SHA-256)."""
    if not CRYPTO_PAY_API_TOKEN or not signature:
        return False
    secret = hashlib.sha256(CRYPTO_PAY_API_TOKEN.encode()).digest()
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/api/pay/cryptobot/webhook")
async def crypto_pay_webhook(request: Request):
    """
    Webhook Crypto Pay API — вызывается при оплате счёта.
    Включите в @CryptoBot: Crypto Pay → My Apps → Webhooks.
    URL: https://ваш-домен/api/pay/cryptobot/webhook
    """
    if not CRYPTO_PAY_API_TOKEN:
        raise HTTPException(status_code=503, detail="Crypto Pay не настроен")
    body = await request.body()
    sig = request.headers.get("crypto-pay-api-signature", "")
    if not _verify_crypto_pay_signature(body, sig):
        raise HTTPException(status_code=403, detail="Invalid signature")
    data = json.loads(body)
    update_type = data.get("update_type")
    if update_type == "invoice_paid":
        invoice = data.get("payload", {})  # Invoice object
        custom_payload = invoice.get("payload", "")  # our JSON string
        try:
            pl = json.loads(custom_payload) if isinstance(custom_payload, str) else (custom_payload or {})
        except json.JSONDecodeError:
            pl = {}
        telegram_id = pl.get("telegram_id")
        if telegram_id and pl.get("product") == "pro":
            await set_user_pro(int(telegram_id), True)
        if pl.get("promo_code"):
            await increment_promo_used(pl["promo_code"])
            await set_user_applied_promo(int(telegram_id), None)  # сбросить применённый промокод
    return {"ok": True}


# ═══════════════════ ADMIN ═══════════════════

def _require_admin(secret: str):
    if not ADMIN_SECRET:
        raise HTTPException(status_code=500, detail="ADMIN_SECRET not configured")
    if secret != ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")


@app.get("/api/admin/users")
async def admin_list_users(secret: str = Query(...)):
    _require_admin(secret)
    users = await get_all_users()
    for u in users:
        u["is_pro"] = user_has_active_pro(u)
    return users


@app.post("/api/admin/pro")
async def admin_set_pro(
    telegram_id: int = Query(...),
    value: bool = Query(True),
    days: int | None = Query(None, ge=1, le=50000),  # длительность Pro в днях (1–50000)
    secret: str = Query(...),
):
    _require_admin(secret)
    await set_user_pro(telegram_id, value, days=days if value else None)
    return {"ok": True}


@app.post("/api/admin/ban")
async def admin_set_ban(telegram_id: int = Query(...), value: bool = Query(True), secret: str = Query(...)):
    _require_admin(secret)
    await set_user_banned(telegram_id, value)
    return {"ok": True}


@app.post("/api/admin/reset")
async def admin_reset_requests(telegram_id: int = Query(...), secret: str = Query(...)):
    _require_admin(secret)
    await reset_user_requests(telegram_id)
    return {"ok": True}


@app.get("/api/admin/promos")
async def admin_list_promos(secret: str = Query(...)):
    _require_admin(secret)
    promos = await list_promo_codes()
    return {"promos": promos}


@app.post("/api/admin/promo")
async def admin_create_promo(
    secret: str = Query(...),
    code: str = Query(...),
    promo_type: str = Query("discount", description="discount | free_pro"),
    discount_percent: int = Query(0, ge=0, le=100),
    pro_days: int = Query(0, ge=0, le=50000),
    max_uses: int = Query(0, ge=0),
    expires_days: int | None = Query(None, ge=1),
):
    _require_admin(secret)
    try:
        expires_at = None
        if expires_days is not None:
            expires_at = time.time() + expires_days * 86400
        pt = "free_pro" if promo_type == "free_pro" else "discount"
        await create_promo_code(code, discount_percent, max_uses=max_uses, expires_at=expires_at, promo_type=pt, pro_days=pro_days)
        return {"ok": True, "code": code.strip().upper()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/admin/promo")
async def admin_delete_promo(code: str = Query(...), secret: str = Query(...)):
    _require_admin(secret)
    await delete_promo_code(code)
    return {"ok": True}


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(secret: str = Query("")):
    if not ADMIN_SECRET or secret.strip() != ADMIN_SECRET.strip():
        return HTMLResponse("<h1>403 Forbidden</h1>", status_code=403)
    return HTMLResponse(_build_admin_html(secret))


_PROMO_TYPE_SCRIPT = r"""
document.getElementById('promoType').onchange = function() {
  const t = this.value;
  document.getElementById('fieldDiscount').style.display = t === 'discount' ? 'flex' : 'none';
  document.getElementById('fieldProDays').style.display = t === 'free_pro' ? 'flex' : 'none';
};
document.getElementById('promoType').dispatchEvent(new Event('change'));
"""


def _build_admin_html(secret: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Admin Panel</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:Inter,sans-serif;background:#0a0f1e;color:#e2e8f0;padding:24px;min-height:100vh}}
h1{{font-size:22px;margin-bottom:20px;background:linear-gradient(135deg,#f97316,#fb923c);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.stats{{display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap}}
.stat{{background:rgba(15,23,42,.8);border:1px solid rgba(148,163,184,.15);border-radius:12px;padding:14px 18px;min-width:120px}}
.stat-val{{font-size:20px;font-weight:700;color:#f97316}}
.stat-lbl{{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.08em;margin-top:2px}}
.search{{width:100%;padding:10px 14px;border-radius:10px;border:1px solid rgba(148,163,184,.2);background:rgba(15,23,42,.9);color:#e2e8f0;font-size:14px;margin-bottom:16px;outline:none}}
.search:focus{{border-color:#f97316}}
table{{width:100%;border-collapse:collapse}}
th{{text-align:left;font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.08em;padding:8px 10px;border-bottom:1px solid rgba(148,163,184,.1)}}
td{{padding:10px;font-size:13px;border-bottom:1px solid rgba(148,163,184,.06)}}
tr:hover td{{background:rgba(249,115,22,.04)}}
.badge{{display:inline-block;padding:2px 8px;border-radius:999px;font-size:10px;font-weight:600;letter-spacing:.05em}}
.badge-pro{{background:rgba(249,115,22,.15);color:#fb923c;border:1px solid rgba(249,115,22,.3)}}
.badge-free{{background:rgba(148,163,184,.1);color:#94a3b8;border:1px solid rgba(148,163,184,.2)}}
.badge-ban{{background:rgba(239,68,68,.15);color:#f87171;border:1px solid rgba(239,68,68,.3)}}
.act{{padding:4px 10px;border-radius:8px;border:1px solid rgba(148,163,184,.2);background:rgba(15,23,42,.9);color:#e2e8f0;font-size:11px;cursor:pointer;transition:all .2s;margin:2px}}
.act:hover{{border-color:#f97316;color:#f97316}}
.act-danger{{color:#f87171}}
.act-danger:hover{{border-color:#ef4444;color:#ef4444}}
.section{{margin-top:32px}}
.section h2{{font-size:16px;margin-bottom:12px;color:#94a3b8}}
.promo-form{{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;margin-bottom:16px}}
.promo-form input{{padding:8px 12px;border-radius:8px;border:1px solid rgba(148,163,184,.2);background:rgba(15,23,42,.9);color:#e2e8f0;font-size:13px;width:120px}}
.promo-form input[type="number"]{{width:70px}}
.promo-form label{{font-size:11px;color:#64748b;display:block;margin-bottom:4px}}
.promo-form .field{{display:flex;flex-direction:column}}
.btn{{padding:8px 16px;border-radius:8px;border:none;background:linear-gradient(135deg,#f97316,#fb923c);color:#0f172a;font-weight:600;font-size:12px;cursor:pointer}}
.btn:hover{{opacity:.95}}
</style>
</head>
<body>
<h1>Admin Panel</h1>
<div class="stats" id="stats"></div>
<input class="search" id="search" placeholder="Поиск по ID, username, имени..." oninput="filterTable()">
<table><thead><tr>
<th>ID</th><th>Username</th><th>Имя</th><th>Статус</th><th>Запросов</th><th>Действия</th>
</tr></thead><tbody id="tbody"></tbody></table>

<div class="section">
<h2>Промокоды</h2>
<div class="promo-form">
<div class="field">
<label>Код</label>
<input type="text" id="promoCode" placeholder="SALE20" maxlength="32">
</div>
<div class="field">
<label>Тип</label>
<select id="promoType" style="padding:8px 12px;border-radius:8px;border:1px solid rgba(148,163,184,.2);background:rgba(15,23,42,.9);color:#e2e8f0;font-size:13px;width:110px">
<option value="discount">Скидка %</option>
<option value="free_pro">Бесплатный Pro</option>
</select>
</div>
<div class="field" id="fieldDiscount">
<label>Скидка %</label>
<input type="number" id="promoDiscount" value="20" min="0" max="100">
</div>
<div class="field" id="fieldProDays" style="display:none">
<label>Дней Pro</label>
<input type="number" id="promoProDays" value="7" min="1" max="50000">
</div>
<div class="field">
<label>Макс. использ. (0=∞)</label>
<input type="number" id="promoMaxUses" value="0" min="0">
</div>
<div class="field">
<label>Срок (дней, пусто=∞)</label>
<input type="number" id="promoExpires" placeholder="30" min="1">
</div>
<button class="btn" onclick="createPromo()">Создать</button>
</div>
<script>{_PROMO_TYPE_SCRIPT}</script>
<table><thead><tr>
<th>Код</th><th>Тип</th><th>Скидка/Дней</th><th>Использовано</th><th>Срок</th><th>Действия</th>
</tr></thead><tbody id="promoTbody"></tbody></table>
</div>

<script>
const S = "{secret}";
const API = "/api/admin";
let allUsers = [];

async function load() {{
  const r = await fetch(API + "/users?secret=" + S);
  allUsers = await r.json();
  renderStats();
  renderTable(allUsers);
  loadPromos();
}}

async function loadPromos() {{
  const r = await fetch(API + "/promos?secret=" + S);
  const data = await r.json();
  const promos = data.promos || [];
  document.getElementById("promoTbody").innerHTML = promos.map(p => {{
    const used = p.used_count + (p.max_uses ? ' / ' + p.max_uses : '');
    const exp = p.expires_at ? new Date(p.expires_at * 1000).toLocaleDateString('ru') : '∞';
    const type = (p.promo_type || 'discount') === 'free_pro' ? 'Pro' : 'Скидка';
    const val = (p.promo_type || 'discount') === 'free_pro' ? (p.pro_days || 0) + ' дн.' : (p.discount_percent || 0) + '%';
    return '<tr><td><strong>' + p.code + '</strong></td><td>' + type + '</td><td>' + val + '</td><td>' + used + '</td><td>' + exp + '</td><td><button class="act act-danger" onclick="deletePromo(\\'' + p.code + '\\')">Удалить</button></td></tr>';
  }}).join('') || '<tr><td colspan="6">Нет промокодов</td></tr>';
}}

async function createPromo() {{
  const code = document.getElementById("promoCode").value.trim();
  const promoType = document.getElementById("promoType").value;
  const discount = parseInt(document.getElementById("promoDiscount").value, 10) || 0;
  const proDays = parseInt(document.getElementById("promoProDays").value, 10) || 7;
  const maxUses = parseInt(document.getElementById("promoMaxUses").value, 10) || 0;
  const expires = document.getElementById("promoExpires").value.trim();
  if (!code) {{ alert('Введите код'); return; }}
  let url = API + "/promo?secret=" + S + "&code=" + encodeURIComponent(code) + "&promo_type=" + promoType + "&discount_percent=" + discount + "&pro_days=" + proDays + "&max_uses=" + maxUses;
  if (expires) url += "&expires_days=" + parseInt(expires, 10);
  const r = await fetch(url, {{ method: "POST" }});
  if (!r.ok) {{ const e = await r.json(); alert(e.detail || 'Ошибка'); return; }}
  document.getElementById("promoCode").value = '';
  loadPromos();
}}

async function deletePromo(code) {{
  if (!confirm('Удалить промокод ' + code + '?')) return;
  await fetch(API + "/promo?secret=" + S + "&code=" + encodeURIComponent(code), {{ method: "DELETE" }});
  loadPromos();
}}

function renderStats() {{
  const total = allUsers.length;
  const pro = allUsers.filter(u => u.is_pro).length;
  const banned = allUsers.filter(u => u.is_banned).length;
  document.getElementById("stats").innerHTML =
    stat(total, "Всего") + stat(pro, "Pro") + stat(banned, "Забанено");
}}

function stat(v, l) {{
  return '<div class="stat"><div class="stat-val">' + v + '</div><div class="stat-lbl">' + l + '</div></div>';
}}

function renderTable(users) {{
  document.getElementById("tbody").innerHTML = users.map(u => {{
    const status = u.is_banned
      ? '<span class="badge badge-ban">BAN</span>'
      : u.is_pro
        ? '<span class="badge badge-pro">PRO</span>'
        : '<span class="badge badge-free">FREE</span>';
    return '<tr>' +
      '<td>' + u.telegram_id + '</td>' +
      '<td>' + (u.username || '—') + '</td>' +
      '<td>' + (u.first_name || '—') + '</td>' +
      '<td>' + status + '</td>' +
      '<td>' + u.requests_used + '</td>' +
      '<td>' +
        (u.is_pro
          ? '<button class="act" onclick="setPro(' + u.telegram_id + ',false)">Убрать Pro</button>'
          : '<button class="act" onclick="setPro(' + u.telegram_id + ',true)">Дать Pro</button>') +
        (u.is_banned
          ? '<button class="act" onclick="setBan(' + u.telegram_id + ',false)">Разбанить</button>'
          : '<button class="act act-danger" onclick="setBan(' + u.telegram_id + ',true)">Бан</button>') +
        '<button class="act" onclick="resetReqs(' + u.telegram_id + ')">Сброс</button>' +
      '</td></tr>';
  }}).join('');
}}

function filterTable() {{
  const q = document.getElementById("search").value.toLowerCase();
  const filtered = allUsers.filter(u =>
    String(u.telegram_id).includes(q) ||
    (u.username || '').toLowerCase().includes(q) ||
    (u.first_name || '').toLowerCase().includes(q)
  );
  renderTable(filtered);
}}

async function setPro(id, val) {{
  await fetch(API + "/pro?telegram_id=" + id + "&value=" + val + "&secret=" + S, {{method:"POST"}});
  load();
}}
async function setBan(id, val) {{
  await fetch(API + "/ban?telegram_id=" + id + "&value=" + val + "&secret=" + S, {{method:"POST"}});
  load();
}}
async function resetReqs(id) {{
  await fetch(API + "/reset?telegram_id=" + id + "&secret=" + S, {{method:"POST"}});
  load();
}}

load();
</script>
</body>
</html>"""


