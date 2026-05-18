# subs — приложение «Подписчики»

В монорепозитории **dashboard** основной путь такой:

- **Один Django** из каталога **`../backend/`** на **`http://127.0.0.1:8000`** — и дашборд аккаунтов (`/api/accounts/`, …), и API «Подписчиков» (`/api/subscribers/…`; код приложения `subscribers` лежит в **`subs/backend/subscribers`** и подключается к тому же проекту).
- **Фронт Subs** — **`subs/frontend`**, Vite на **5180**, прокси **`/api` → 8000** (см. `vite.config.ts`).
- Съём аудитории из Subs вызывает тот же **`POST /api/accounts/…/audience/refresh/`**, что и дашборд: **один пул Playwright** и те же cookies, что у AccountsStats (`worker_accounts.env`). Отдельный **`worker_subs.env`** — только для настроек приложения «Подписчики», не для профиля браузера (см. `*.env.example` в `backend/config/` и `CLAUDE.md`).

Отдельный **`subs/backend/manage.py` на отдельном порту** нужен только для **изолированного** деплоя или старых инструкций; локально обычно достаточно общего `backend/manage.py runserver`.

## Порты (локально, монорепо)

| Сервис | Порт |
|--------|------|
| Dashboard + subs API (Django) | **8000** |
| UI дашборда (subs → «Дашборд», iframe) | **5174** (Atomic `new_frontend`) |
| **subs UI** (Vite) | **5180** |

## Запуск (монорепо)

1. Из **`backend/`**: `py -3.13 -m poetry run python manage.py runserver` → **8000**.
2. Из **`subs/frontend/`**: `npm install` (один раз), затем `npm run dev` → **5180**.

Переменные фронта (`subs/frontend/.env` по образцу `.env.example`):

- **`VITE_API_URL`** — для туннеля и `npm run dev` оставьте **пустым** (иначе mixed content с HTTPS trycloudflare).
- **`VITE_DASHBOARD_API_URL=http://127.0.0.1:8000`**
- **`VITE_DASHBOARD_APP_URL=http://localhost:5174`**

## Доступ из интернета (Cloudflare Quick Tunnel)

1. Django на **8000**, Vite subs на **5180**.
2. Из **`subs/frontend`**: `npm run tunnel` — откройте выданный `https://….trycloudflare.com`.

Кнопка «Дашборд» и iframe «Авторизация» по умолчанию ведут на `localhost` — с другого устройства задайте `VITE_DASHBOARD_APP_URL` / `VITE_DASHBOARD_ATOMIC_URL` на публичные URL (отдельные туннели к **5174** и **8000**).

## База данных (только автономный subs/backend)

**Вариант A — Postgres:** из каталога `subs` — `docker compose up -d db`, в `subs/backend/.env` — `DATABASE_URL=postgresql://subs:subs@127.0.0.1:5435/subs`, драйвер из `requirements-postgres.txt`.

**Вариант B — SQLite:** пустой `DATABASE_URL` → `subs/backend/subs.sqlite3`.

В **монорепо** таблицы `subscribers_*` живут в **той же БД**, что и основной дашборд (`backend/.env`).

## Авторизация TikTok / Instagram

Вкладка **«Авторизация»** в subs встраивает **`app.html?route=settings`** (`VITE_DASHBOARD_APP_URL`, по умолчанию **5174**).

## CORS

В `backend/config/settings.py` уже учтены origins **5180** и **5174**.
