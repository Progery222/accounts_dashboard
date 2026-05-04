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

Backend (run from `backend/`; local `.venv` exists in repo):
```bash
python manage.py migrate
python manage.py runserver    # http://localhost:8000
python manage.py makemigrations <app>
python manage.py createsuperuser
python manage.py test accounts
```

Frontend (run from `frontend/`):
```bash
npm run dev       # http://localhost:5173
npm run build     # tsc -b && vite build
```

Playwright browser install (once per machine):
```bash
python -m playwright install chromium
```

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

## Known risks to keep in mind

- Repo currently contains credentials-like defaults in `backend/config/settings.py` for Facebook env vars. Treat as security debt and avoid propagating secrets in commits.
- Docker env wiring does not match Django DB settings (`DATABASE_URL` vs `DB_*`). If touching deployment docs/config, align these explicitly instead of assuming compose works as-is.
