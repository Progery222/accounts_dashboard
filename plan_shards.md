# План: шардинг съёма и авторизации

Документ для поэтапного внедрения.

> **Статус (2026-05-19):** код шардирования из проекта **снят** (поле `scrape_shard` удалено миграцией `0035`, UI/API шардов убраны). Этот файл — **сохранённый план** на будущее; раздел «Уже сделано» описывает то, что было реализовано ранее и затем откатано.

---

## Решения (согласовано)

| # | Тема | Решение |
|---|------|---------|
| 1 | IP | **Пока один IP**, без доп. прокси/VPN. Сначала оценить эффект от трёх профилей Chrome на одной машине. Фаза 5 (три IP) — отложена. |
| 2 | Платформы на шардах 1–2 | Только **TikTok, Instagram, Facebook, Threads**. На вкладках **Шард 1** и **Шард 2** в настройках авторизации остальные платформы **не показывать**. Шард 0 — все платформы как сейчас. |
| 3 | `AUTO_REFRESH_CONCURRENCY_*` | **Не повышать** при первом включении съёма по шардам. Оставить дефолты (TikTok/FB/IG/Threads = 1). Параллелизм 2–3 — отдельное решение после стабильных прогонов. |
| 4 | Выбор alt-шарда (failover) | Приоритет: **C** (есть сессия в `auth_status`) → **A** `(home+1)%3` → **B** (min нагрузка платформы). |
| 5 | Одиночный refresh | Failover **да**: ручное «Обновить» + автообновление + «Обновить всё». |
| 6 | Ручная смена `scrape_shard` | Через **Django admin** (поле пока **не** в админке — добавить в фазе 0, см. ниже). Отдельный UI в дашборде не планируется. |
| 7 | CSV | **Отдельные колонки:** `scrape_shard`, `failover`, `failover_shard`, `failover_detail`. |
| 8 | Порядок работ | См. раздел **«Рекомендуемый порядок»** ниже. |
| 9 | Audience (Подписчики) | **Не в фокусе.** Съём аудитории **всегда шард 0** (текущий профиль), независимо от `account.scrape_shard`. Подключение к шардам — позже, отдельно. |
| 10 | Пересчёт шардов | **Да:** management-команда перераспределения `scrape_shard` по платформам (как в миграции 0034). |

---

## Цели

1. **Три независимые браузерные сессии** (шарды 0–2) для снижения антибота и (при одном IP) более равномерной нагрузки.
2. **Равномерное распределение аккаунтов** по шардам в БД (`scrape_shard`).
3. **Failover:** одна повторная попытка на другом шарде **≤ 1 раз / 24 ч / аккаунт**, отражение в CSV.
4. **Без поломки текущего режима:** до фазы 1 съём = только шард 0 (как сейчас).

---

## Термины

| Термин | Значение |
|--------|----------|
| **Шард** | Линия: каталог Chrome + daemon Playwright на платформу + авторизация |
| **`scrape_shard`** | 0–2, домашний шард аккаунта в БД |
| **Failover** | Retry на alt-шарде в том же прогоне; **`scrape_shard` не меняется** |
| **Шардные платформы (v1)** | `tiktok`, `instagram`, `facebook`, `threads` — съём и failover по `scrape_shard` |
| **Вне шардов (v1)** | `telegram`, `youtube`, `x`, `rumble`, `reddit` — съём всегда через **профиль шарда 0** |

---

## Уже сделано

### База данных

- `Account.scrape_shard` (0–2), `SCRAPE_SHARD_COUNT = 3`.
- Миграция `0034`: равномерно **по платформе**.
- Новые аккаунты → шард с min count на платформе (`scrape_shard.py`, `signals.py`, импорт CSV).

### Авторизация (не съём)

- Три каталога: шард 0 = базовый профиль; 1–2 = `{база}-shard-N` или env `ACCOUNTS_BROWSER_PROFILE_DIR_SHARD_N`.
- API/UI: параметр `shard`, `GET /api/settings/status/` → `shards[]`.
- **Съём по-прежнему только шард 0.**

### Django admin

- Поле `scrape_shard` в модели есть, в **admin пока не выведено** (нет в `list_display` / форме). Запланировать: `list_display`, `list_filter`, редактируемое поле.

---

## Рекомендуемый порядок работ (решение по п.8)

Логика: сначала **безопасно включить три профиля в съёме** без ускорения за счёт concurrency, потом **устойчивость (failover + CSV)**. Один IP — не ждать ×3 по скорости; ждать разнесения сессий и меньше «все яйца в одной корзине».

```text
Фаза 0b  →  UI авторизации (4 платформы на шардах 1–2) + admin scrape_shard + redistribute_scrape_shards + логин на 1–2
     ↓
Фаза 1   →  Съём по scrape_shard (4 платформы); остальные платформы → всегда worker шарда 0; CONCURRENCY не трогать
     ↓
Фаза 2+3 →  Failover + отдельные колонки CSV (одним релизом)
     ↓
Фаза 4   →  Тюнинг (per-shard delay, карантин шарда, CONCURRENCY=2–3 — только по метрикам)
     ↓
Фаза 5   →  Доп. IP (когда понадобится)
```

**Почему не failover раньше съёма:** failover бессмысленен, пока refresh не ходит в `profile_dir_for_shard(home)` и alt.

**Почему не CONCURRENCY=3 сразу:** один IP + антибот; сначала три последовательные линии с разными cookies, потом ускорение.

---

## Архитектура (целевая)

```text
Account.scrape_shard
  │
  ├─ platform ∈ {tiktok, instagram, facebook, threads}
  │     → worker(platform) @ profile_dir_for_shard(scrape_shard)
  │
  └─ platform ∈ {telegram, youtube, x, rumble, reddit}  [v1]
        → worker @ profile_dir_for_shard(0)   # игнор scrape_shard для съёма

Failover (только для 4 шардных платформ):
  fail @ home → pick alt (C→A→B) → one retry → CSV; ≤1/24h
```

### Модули

| Модуль | Статус |
|--------|--------|
| `accounts/browser_shards.py` | ✅ |
| `accounts/scrape_shard.py` | ✅ |
| `platforms/scrape_sharding.py` | план |
| `platforms/scrape_errors.py` | план |
| `accounts/scrape_failover.py` | план |
| `_refresh_with_failover()` | план |

### Пул воркеров (фаза 1)

- Ключ: `{worker_path}#shard={n}`.
- Env дочернего процесса: `BROWSER_PROFILE_DIR=profile_dir_for_shard(n)`.
- Единый `call_platform_worker(account, payload)`.
- Shutdown / kill Chrome: все каталоги шардов.

### Параллелизм (фаза 1)

- **`AUTO_REFRESH_CONCURRENCY_*` не менять** (п.3).
- Три шарда дадут **очередь по платформе** с разными профилями, но не 3 одновременных TikTok на одном IP — пока concurrency=1.
- Позже (фаза 4): поднять до 2–3 при стабильных ночных прогонах.

---

## Авторизация: шарды 1–2 (фаза 0b, план)

### UI (`new_frontend` — Settings)

- **Шард 0:** все платформы (как сейчас).
- **Шард 1, 2:** показывать только карточки:
  - TikTok, Instagram, Facebook, Threads.
- Скрыть: Telegram, YouTube, X, Threads уже included, Rumble, Reddit.
- Подсказка на вкладке: «На этом шарде настраиваются только TT / IG / FB / Threads».

### API

- `start-auth` / `logout` / `import-cookies` для скрытых платформ на shard≠0: опционально **400** с текстом «на шардах 1–2 только …» (защита от прямых запросов).
- `auth_status.shards[1]` / `[2]`: в ответе можно оставить все ключи, UI фильтрует; или отдавать только 4 — на усмотрение реализации.

### Подготовка пользователя

- Войти в TT/IG/FB/Threads на **шарде 1** и **шарде 2** до включения фазы 1.
- Шард 0 — без изменений.

---

## Failover (политика)

| Правило | Значение |
|---------|----------|
| Лимит | 1 попытка / `account_id` / 24 ч |
| `scrape_shard` в БД | не менять |
| Когда | сразу после ошибки на home, **тот же прогон** |
| Где | автообновление, refresh_all, **одиночный** `POST …/refresh/` |
| Платформы | только `tiktok`, `instagram`, `facebook`, `threads` |

### Выбор alt-шарда (C → A → B)

1. **C:** среди `{0,1,2}\{home}` взять шарды, где `has_session` для платформы (как в `auth_status` / `{platform}_state.json` / probe cookies).
2. **A:** если несколько с сессией — `(home+1)%3`, затем следующий с сессией по кругу.
3. **B:** если всё ещё неоднозначно — min числа аккаунтов этой платформы на шарде.
4. Нет сессии ни на одном alt → `failover: нет сессии`, без попытки.

### Ошибки

- **Eligible:** антибот, timeout, 403, пустой SSR, worker closed, временные 5xx съёма.
- **Не eligible:** `profile_unavailable`, 404, валидация username.

### Учёт 24 ч

- Таблица `AccountScrapeFailoverLog` (рекомендуется): `account_id`, `at`, `from_shard`, `to_shard`, `platform`, `outcome`, `primary_error` (кратко).
- Лимит на **попытку**, не только на успех.

### CSV — отдельные колонки

**Автообновление** (`auto_refresh_csv.py`) и **Обновить всё** (`views._refresh_all_save_report_csv`):

| Колонка | Пример |
|---------|--------|
| `scrape_shard` | `1` |
| `failover` | `нет` / `1→2 OK` / `1→2 fail` / `лимит 24ч` / `нет сессии` |
| `failover_shard` | `2` |
| `failover_detail` | первичная ошибка (обрезка) |

**Шапка отчёта:** счётчики попыток / OK / fail / лимит / нет сессии.

### Аудитория (Подписчики)

- **Вне scope v1:** съём аудитории **только шард 0** (без изменений в `audience.py` при фазах 1–3).
- Failover для audience — не планируется в ближайших фазах.

### Env (позже)

```env
SCRAPE_FAILOVER_ENABLED=true
SCRAPE_FAILOVER_MAX_PER_ACCOUNT_HOURS=24
SCRAPE_FAILOVER_PLATFORMS=tiktok,instagram,facebook,threads
```

---

## Этапы (чеклист)

### Фаза 0 — база ✅

- [x] `scrape_shard` + миграция + автоназначение
- [x] Авторизация 3 шардов (API + вкладки UI)

### Фаза 0b — подготовка к съёму

- [ ] **UI:** на шардах 1–2 только TT / IG / FB / Threads
- [ ] **API:** отклонять auth для прочих платформ при `shard in (1,2)` (опционально)
- [ ] **Django admin:** `scrape_shard` в `list_display`, `list_filter`, редактирование
- [ ] **Management-команда** `redistribute_scrape_shards` (или аналог): равномерно по платформам, как `0034`; опции `--platform`, `--dry-run`
- [ ] Локально: вход в 4 платформы на шардах **1** и **2**
- [ ] Зафиксировать пути в `worker_accounts.env` (при необходимости)

### Фаза 1 — съём по шардам (без ускорения concurrency)

- [ ] `worker_pool` + `#shard=n`
- [ ] `call_platform_worker(account, …)` для TT/IG/FB/Threads
- [ ] Остальные платформы → всегда `profile_dir_for_shard(0)`
- [ ] **`audience.py` не трогать** — audience остаётся на шарде 0 (см. п.9)
- [ ] **`AUTO_REFRESH_CONCURRENCY_*` не менять**
- [ ] Тесты + один ночной прогон «наблюдение»
- [ ] **Критерий:** аккаунт `scrape_shard=2` + TikTok → каталог `…-shard-2`; Telegram на `scrape_shard=2` → всё ещё шард 0

### Фаза 2 — failover

- [ ] `is_failover_eligible`, `pick_failover_shard` (C→A→B)
- [ ] Лимит 24 ч + log
- [ ] `_refresh_with_failover` → `apps.py`, `views.py` (вкл. одиночный refresh)

### Фаза 3 — CSV

- [ ] Колонки + сводка в шапке (оба отчёта)
- [ ] При необходимости: `extract_error_account_ids_from_saved_auto_refresh_csv`

### Фаза 4 — тюнинг (после метрик)

- [ ] Per-shard cooldown
- [ ] Опционально: `AUTO_REFRESH_CONCURRENCY_TIKTOK=2` и т.д.
- [ ] Карантин «больного» шарда
- [ ] Расширить шардные платформы (X, Telegram, …) в auth + съём

### Фаза 5 — IP (отложено)

- [ ] Три стабильных исходящих IP, привязка к шарду
- [ ] Playwright `proxy` per shard или отдельные VM

---

## Риски (актуальные)

| Риск | Митигация |
|------|-----------|
| Один IP | Ожидать умеренный выигрыш; не поднимать concurrency рано |
| Telegram на `scrape_shard=1` в БД | В v1 съём Telegram всё равно с шарда 0 |
| Нет сессии на alt | Failover C→…; CSV `нет сессии` |
| Admin без `scrape_shard` | Фаза 0b |
| Auth на 1–2 не сделан до фазы 1 | Чеклист 0b |

---

## Вне scope (пока)

- Автосмена `scrape_shard` при бане.
- Failover для audience.
- Per-platform разное число шардов.
- Доп. IP.

---

## Критерии приёмки

1. Шарды 1–2 в UI: только 4 платформы авторизации.
2. TikTok `scrape_shard=1` → профиль `…-shard-1`; concurrency TikTok по-прежнему 1.
3. Failover TT: ошибка на 1 → retry на 2 с сессией → CSV `1→2 OK`; повтор в сутки → `лимит 24ч`.
4. Одиночный refresh с failover — как batch.
5. `scrape_shard` в admin редактируется вручную.
6. Отдельные колонки failover в обоих CSV.

---

## Management-команда `redistribute_scrape_shards` (план)

- **Когда:** фаза 0b (вместе с admin).
- **Логика:** та же, что `distribute_scrape_shards` в миграции `0034` — внутри каждой платформы поровну на шарды 0–2, порядок по `id`.
- **Опции:**
  - `--dry-run` — только вывести, сколько уйдёт на каждый шард;
  - `--platform tiktok` — только одна платформа;
  - без флагов — обновить все платформы.
- **Не трогает:** failover, воркеры, audience.

---

*Обновлено: 2026-05-18 — audience = шард 0; команда пересчёта шардов включена в план. Файл восстановлен: 2026-05-19.*
