# subs — приложение «Подписчики»

Отдельный сервис: **своя PostgreSQL** и свои таблицы. API дашборда — **8000**; ссылки и iframe в subs по умолчанию ведут на **новый фронт дашборда** `http://localhost:5174/` (см. `VITE_DASHBOARD_APP_URL`). Subs — **8010** (API) и **5180** (фронт).

## Порты (локально)

| Сервис        | Порт |
|---------------|------|
| Dashboard API | 8000 |
| UI дашборда (subs → кнопка «Дашборд», iframe) | **5174** |
| **subs API**  | **8010** |
| **subs UI**   | **5180** |
| **subs Postgres (хост)** | **5435** |

> Django на **8000** — это только дашборд. Subs API запускайте так:  
> `python manage.py runserver 0.0.0.0:8010`

## База данных

**Вариант A — Postgres (как в проде):** из каталога `subs` выполните `docker compose up -d db`, в `subs/backend/.env` укажите `DATABASE_URL=postgresql://subs:subs@127.0.0.1:5435/subs`, затем установите драйвер: `pip install -r requirements-postgres.txt` (из каталога `subs/backend`).

**Вариант B — без Docker:** в `.env` оставьте `DATABASE_URL` пустым — поднимется **SQLite** (`subs/backend/subs.sqlite3`).

Дальше: `python manage.py migrate`.

Данные аккаунтов и аудитории в subs появляются после **«Синхронизация с дашборда»** на фронте (или `POST /api/subscribers/sync/dashboard/`), затем **«Собрать»** по аккаунту вызывает съём на дашборде и импорт списка в subs.

## Запуск

### Бэкенд subs

```bash
cd subs/backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python manage.py migrate
python manage.py runserver 0.0.0.0:8010
```

### Фронт subs

```bash
cd subs/frontend
npm install
copy .env.example .env
npm run dev
```

Переменные фронта (`.env`):

- `VITE_API_URL` — для туннеля и `npm run dev` оставьте **пустым** (HTTPS-страница не может вызывать `http://127.0.0.1:8010` — mixed content, в UI «Failed to fetch»).
- Явный URL — только если API на **другом публичном HTTPS**-хосте (не loopback по http).
- `VITE_DASHBOARD_API_URL=http://127.0.0.1:8000`
- `VITE_DASHBOARD_APP_URL=http://localhost:5174`

## Доступ из интернета (Cloudflare Quick Tunnel)

1. Поднимите **subs API**: `python manage.py runserver 0.0.0.0:8010` (`subs/backend`).
2. Поднимите **Vite**: `npm run dev` (`subs/frontend`) — слушает `0.0.0.0:5180`, разрешён `Host: *.trycloudflare.com`, `/api` уходит на 8010.
3. В другом терминале: `npm run tunnel` — откройте выданный `https://….trycloudflare.com`.

Если в `.env` указан `VITE_API_URL=http://127.0.0.1:8010`, при открытии SPA по **https://…trycloudflare.com** браузер заблокирует запросы (mixed content) — уберите переменную или оставьте пустой; код сам подставит относительный `/api` на том же хосте.

Кнопка «Дашборд» и iframe «Авторизация» по-прежнему ведут на `localhost` — для доступа с другого устройства задайте `VITE_DASHBOARD_APP_URL` / `VITE_DASHBOARD_ATOMIC_URL` на публичные URL (отдельные туннели к **5174** и **8000**).

Если API на отдельном публичном origin, в subs `config/settings.py` уже есть `CORS_ALLOWED_ORIGIN_REGEXES` для `*.trycloudflare.com`. Главный дашборд Django (`backend/config/settings.py`) тоже учитывает trycloudflare для CORS/CSRF.

## Авторизация TikTok / Instagram

Вкладка **«Авторизация»** в subs встраивает **`app.html?route=settings`** нового фронта (`VITE_DASHBOARD_APP_URL`, по умолчанию **5174**). Путь `/settings` у SPA нет — при необходимости используйте редирект `new_frontend/settings.html` → `app.html?route=settings`.

## CORS дашборда

В `dashboard` в `config/settings.py` уже учтены origins **5180** (subs) и **5174** (новый фронт дашборда); при смене портов добавьте свои в те же списки.
