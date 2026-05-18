# CLAUDE.md

This file provides guidance to coding agents working in this repository.

## Stack

- **Backend**: Django 5 + Django REST Framework, PostgreSQL, APScheduler, Playwright (Chromium).
- **Frontend**: React 18 + TypeScript + Vite + TanStack Query + React Router + Tailwind.
- **Locale**: Russian (`ru-ru`, `Europe/Moscow`). User-facing strings in API responses should stay in Russian.

## Source of truth and legacy leftovers

- The live backend is Django, entered through `backend/manage.py` and `backend/config/`.
- `backend/app/`, `backend/migrations/` and `backend/alembic.ini` are legacy FastAPI/Alembic leftovers.
- `docker-compose.yml` and `backend/Dockerfile` still run `uvicorn app.main:app` (legacy path) and are not an accurate source of truth for local Django development.

## Run commands

### Backend — зависимости (Poetry)

Источник правды: `backend/pyproject.toml` + **`backend/poetry.lock`** (зафиксированные версии). В каталоге `backend/` создаётся локальный `.venv` (`poetry.toml`: `virtualenvs.in-project = true`).

**Windows:** если `py` по умолчанию — **Python 3.13 free-threading (`3.13t`)**, перед `poetry install` зафиксируйте **обычный GIL 3.13** (иначе нет колёс `psycopg-binary` / `greenlet`): `py -3.13 -m poetry env use` и путь к `python.exe`, в `sys.version` которого **нет** строки `free-threading` (часто это `…\Python313\python.exe`, а не `python3.13t.exe`).

```bash
cd backend
py -3.13 -m poetry install
```

Дальше (из `backend/`):

```bash
py -3.13 -m poetry run python manage.py migrate
py -3.13 -m poetry run python manage.py runserver   # http://localhost:8000
py -3.13 -m poetry run python manage.py makemigrations <app>
py -3.13 -m poetry run python manage.py createsuperuser
py -3.13 -m poetry run python manage.py test accounts
```

Новая библиотека: `py -3.13 -m poetry add <пакет>` → затем **`py -3.13 -m poetry lock`** при необходимости.

**Docker** по-прежнему ставит зависимости из `requirements.txt`. После смены зависимостей в Poetry обновите файл (нужен плагин `poetry-plugin-export`, один раз: `py -3.13 -m poetry self add poetry-plugin-export`):

```bash
cd backend
py -3.13 -m poetry export -f requirements.txt --output requirements.txt --without-hashes
```

На Linux/macOS достаточно `poetry install` и `poetry run python manage.py …` при выбранном подходящем интерпретаторе (`poetry env use 3.12` и т.д.).

Frontend (run from `frontend/`):
```bash
npm run dev       # http://localhost:5173
npm run build     # tsc -b && vite build
```

Playwright browser install (once per machine):
```bash
python -m playwright install chromium
```

### Долгие процессы в Cursor (агенты)

- `runserver`, `npm run dev`, `cloudflared` и аналоги поднимайте **в фоне во встроенном терминале Cursor** (инструмент Shell: `block_until_ms: 0`), при необходимости — **отдельный фоновый запуск на каждый процесс**, чтобы логи не смешивались.
- На **Windows** оболочка по умолчанию часто PowerShell: в одной строке используйте `Set-Location '…'; команда`, а не `cd … && …` (иначе синтаксическая ошибка).
- **Не** открывайте отдельные окна Windows (`Start-Process cmd /k` и т.п.), пока пользователь явно не попросит вынести процесс из IDE.
- Локально: один **`backend/`** Django на **`http://127.0.0.1:8000`** — и **`/api/accounts/`** (дашборд / Atomic), и **`/api/subscribers/`** (Подписчики; код приложения в `subs/backend/subscribers`). Фронт **«Подписчики»**: `subs/frontend`** (`npm run dev` → **:5180**, прокси `/api` → **:8000**; из `new_frontend/`: `npm run dev:5180`). **Не** поднимайте Atomic на 5180. **`DASHBOARD_API_URL`** в `.env` нужен только если HTTP-синхронизация subs должна бить **не** в `http://127.0.0.1:8000`. Туннель к Subs: `subs/frontend/npm run tunnel` или `new_frontend/npm run tunnel:subs` (алиас `tunnel:8010`).

## Architecture

### Data model (`accounts/models.py`)

- Unified entity per social account: `Account(username, platform)`.
- Platforms currently in enum: `tiktok`, `instagram`, `youtube`, `telegram`, `x`, `threads`, `facebook`.
- `Post` belongs to `Account`, dedup key is `(account, external_id)`.
- `AccountSnapshot` and `PostSnapshot` are daily snapshots, unique by `(account, date)` and `(post, date)`.
- `take_snapshot_if_needed()` is idempotent per day.

### Refresh pipeline (`accounts/views.py`)

`_apply_refresh(account)` is the single refresh entry point:
1. Take daily snapshot before overwrite.
2. Call platform-specific scraper via `_scrape()`.
3. Update account fields.
4. Sync post list via `_sync_posts()` (post snapshots happen there).
5. Recalculate aggregated stats (`view_count`, and for some platforms `like_count`) from posts.
6. Update current-day snapshot and repair historical zero snapshots used for delta baseline.

API triggers:
- `POST /api/accounts/{id}/refresh/`
- `POST /api/accounts/refresh_all/`

### Scrapers and workers

- Dispatcher is in `accounts/views.py` (`_scrape()`), but implementations live under `backend/platforms/`.
- Current platform modules:
  - `platforms/tiktok/`
  - `platforms/instagram/`
  - `platforms/youtube/`
  - `platforms/telegram/`
  - `platforms/x/`
  - `platforms/threads/`
  - `platforms/facebook/`
- `tiktok_app/` still exists and is wired in `config/urls.py` for TikTok-specific API routes, but it is no longer the only place where TikTok scraping logic lives.
- Playwright-based platforms use subprocess worker scripts that emit JSON to stdout and logs to stderr.

### Scheduler (`accounts/apps.py`)

- Scheduler starts in `AccountsConfig.ready()`.
- Autoreload guard is critical: when running `runserver`, startup is skipped unless `RUN_MAIN == "true"`.
- There is always a fixed nightly job at `03:00` Moscow time.
- Additionally, user-configurable schedule is loaded from `RefreshScheduleConfig` (`interval` or specific `times`) and can add/remove `auto_refresh_*` jobs dynamically.

### Frontend

- API client: `frontend/src/api/client.ts` (`VITE_API_URL` with fallback to empty string).
- Query cache stale time is 60 seconds (`frontend/src/main.tsx`).
- Routes in `frontend/src/App.tsx`:
  - `/` is the main accounts page.
  - `/accounts` redirects to `/`.
  - Also present: `/analytics`, `/accounts/:id`, `/profiles`, `/tiktok/:username`, `/settings`.

## Conventions and guardrails

- For new platform support:
  1. Add enum value in `Platform`.
  2. Add scraper module under `backend/platforms/<platform>/`.
  3. Wire platform branch in `_scrape()` (`accounts/views.py`).
  4. Return normalized payload for account fields and `_posts` list with `external_id` as string.
- For "not found / parse failed" cases in scrapers, raise `ValueError` (mapped to 4xx by views).
- Let unexpected scraper errors bubble to be reported as server-side failures (5xx path in views).
- Keep "snapshot before update" behavior intact; serializers compute deltas from latest snapshot with `date < today`.
- **Playwright / Subs:** съём аудитории из «Подписчиков» вызывает тот же API `POST /api/accounts/{id}/audience/refresh/`, что и дашборд — **один пул** демонов и **те же сохранённые сессии**, что у AccountsStats (`ACCOUNTS_BROWSER_PROFILE_DIR` / `ACCOUNTS_BROWSER_HEADLESS` в `worker_accounts.env`, иначе `BROWSER_PROFILE_DIR` / дефолт из `worker_utils`). Файл **`worker_subs.env`** подключается отдельно только для настроек, не связанных с браузером (см. `worker_subs.env.example`).

## Known risks to keep in mind

- Repo currently contains credentials-like defaults in `backend/config/settings.py` for Facebook env vars. Treat as security debt and avoid propagating secrets in commits.
- Docker env wiring does not match Django DB settings (`DATABASE_URL` vs `DB_*`). If touching deployment docs/config, align these explicitly instead of assuming compose works as-is.
