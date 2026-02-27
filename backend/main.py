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
)

load_dotenv()

ADMIN_SECRET = os.getenv("ADMIN_SECRET", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
INIT_DATA_EXPIRY = 86400  # initData valid for 24h


def validate_init_data(init_data: str) -> dict | None:
    """Validate Telegram WebApp initData. Returns parsed user dict or None."""
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
        check_string = "\n".join(check_pairs)

        secret_key = hmac.new(b"WebAppData", TELEGRAM_BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            return None

        user_json = parsed.get("user", [""])[0]
        if user_json:
            return json.loads(unquote(user_json))
        return {}
    except Exception:
        return None


def require_telegram(init_data: str | None) -> dict:
    """Validate initData header, raise 403 if invalid. Returns user dict."""
    if not TELEGRAM_BOT_TOKEN:
        return {}
    if not init_data:
        raise HTTPException(status_code=403, detail="Missing Telegram authorization")
    user = validate_init_data(init_data)
    if user is None:
        raise HTTPException(status_code=403, detail="Invalid Telegram authorization")
    return user

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

# Одноразовые страницы решений (id → ответ)
_solution_store: dict[str, str] = {}


class SolveRequest(BaseModel):
    text: Optional[str] = None
    detail: Literal["short", "detailed"] = "short"
    image_base64: Optional[str] = None
    telegram_id: Optional[int] = None


class SolveResponse(BaseModel):
    answer: str


class SolutionCreateRequest(BaseModel):
    answer: str


class SolutionCreateResponse(BaseModel):
    url: str


@app.get("/", response_class=FileResponse)
async def index() -> FileResponse:
    """
    Telegram WebApp entry point – serves the dark-themed frontend.
    """
    index_path = os.path.join(static_dir, "index.html")
    if not os.path.exists(index_path):
        raise HTTPException(status_code=500, detail="Frontend is not built or missing.")
    return FileResponse(index_path)


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
        "is_pro": bool(user["is_pro"]),
        "is_banned": bool(user["is_banned"]),
        "requests_used": user["requests_used"],
        "remaining": limits["remaining"],
        "allowed": limits["allowed"],
        "reason": limits["reason"],
    }


@app.post("/api/solve", response_model=SolveResponse)
async def solve(req: SolveRequest, x_telegram_init_data: str | None = Header(None)) -> SolveResponse:
    tg_user = require_telegram(x_telegram_init_data)
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
        return SolveResponse(answer=prepare_math_for_render(str(answer).strip()))

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
    return SolveResponse(answer=prepare_math_for_render(answer.strip()))


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
async def create_solution(req: SolutionCreateRequest, x_telegram_init_data: str | None = Header(None)) -> SolutionCreateResponse:
    require_telegram(x_telegram_init_data)
    sid = str(uuid.uuid4())
    _solution_store[sid] = (req.answer or "").strip()
    return SolutionCreateResponse(url=f"/solution/{sid}")


@app.get("/solution/{solution_id}", response_class=HTMLResponse)
async def get_solution_page(solution_id: str) -> HTMLResponse:
    """Отдаёт одноразовую HTML-страницу с решением (KaTeX рендерит формулы на клиенте)."""
    content = _solution_store.pop(solution_id, "")
    if not content:
        raise HTTPException(status_code=404, detail="Страница просмотрена или не существует")
    return HTMLResponse(content=_build_solution_html(content, solution_id))


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
    return users


@app.post("/api/admin/pro")
async def admin_set_pro(telegram_id: int = Query(...), value: bool = Query(True), secret: str = Query(...)):
    _require_admin(secret)
    await set_user_pro(telegram_id, value)
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


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(secret: str = Query("")):
    if not ADMIN_SECRET or secret != ADMIN_SECRET:
        return HTMLResponse("<h1>403 Forbidden</h1>", status_code=403)
    return HTMLResponse(_build_admin_html(secret))


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
</style>
</head>
<body>
<h1>Admin Panel</h1>
<div class="stats" id="stats"></div>
<input class="search" id="search" placeholder="Поиск по ID, username, имени..." oninput="filterTable()">
<table><thead><tr>
<th>ID</th><th>Username</th><th>Имя</th><th>Статус</th><th>Запросов</th><th>Действия</th>
</tr></thead><tbody id="tbody"></tbody></table>

<script>
const S = "{secret}";
const API = "/api/admin";
let allUsers = [];

async function load() {{
  const r = await fetch(API + "/users?secret=" + S);
  allUsers = await r.json();
  renderStats();
  renderTable(allUsers);
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


