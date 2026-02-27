## GDZ Bot (Telegram WebApp) + OpenRouter / OnlySq / OpenAI

Мини‑приложение Telegram (React) + бэкенд (FastAPI), который генерирует решения через OpenAI‑совместимый API (OpenRouter, OnlySq или OpenAI).

### Быстрый старт (Windows / PowerShell)

1) Установить зависимости Python:

```powershell
cd C:\Users\exbru\Desktop\gdz_bot
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

2) Создать файл `.env` вручную (рядом с `requirements.txt`) и заполнить по примеру `env.example`.

3) Запустить вебапп + API:

```powershell
npm run dev
```

4) Запустить бота:

```powershell
npm run bot
```

### OpenRouter (рекомендуется)

[OpenRouter](https://openrouter.ai/docs/quickstart) — единый API к сотням моделей (GPT, Claude, Gemini и др.). Приоритет выше, чем у OpenAI/OnlySq: если задан `OPENROUTER_API_KEY`, используется именно он.

Пример для `.env`:

```env
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=openai/gpt-4o-mini
# Опционально — для отображения в лидерборде OpenRouter:
OPENROUTER_SITE_URL=https://your-app.example.com
OPENROUTER_APP_TITLE=GDZ Bot
```

Модели задаются в формате `провайдер/модель`, например: `openai/gpt-4o`, `anthropic/claude-3-haiku`, `google/gemini-2.0-flash`.

### OnlySq (много моделей)

OnlySq заявляет OpenAI SDK совместимость, поэтому достаточно указать `OPENAI_BASE_URL` и ключ.

- Документация: [OnlySq API](https://docs.onlysq.ru/)

Пример для `.env`:

```env
ONLYSQ_API_KEY=onlysq_...
OPENAI_BASE_URL=https://api.onlysq.ru/v1
OPENAI_MODEL=gemini-2.0-flash
```

Важно: ключ **не вставляйте в код** и не коммитьте в git — храните только в `.env` на сервере/локально.

#### Если видишь 404 HTML от OnlySq

Значит ты попал не в тот OpenAI‑совместимый endpoint. В этом проекте есть fallback режим OnlySq **API v2**:

```env
ONLYSQ_API_STYLE=v2
ONLYSQ_API_KEY=onlysq_...
ONLYSQ_V2_URL=https://api.onlysq.ru/ai/v2
OPENAI_MODEL=gemini-2.0-flash
```


