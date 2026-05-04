# Django + Playwright (Chromium) + gunicorn для headless деплоя (Railway/VPS).
# База Microsoft Playwright уже содержит Chromium и системные зависимости.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# APScheduler и Django USE_TZ используют zoneinfo; без tzdata в образе:
# «No time zone found with key Europe/Moscow».
USER root
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    BROWSER_HEADLESS=true \
    RUN_SCHEDULER=true \
    PORT=8000 \
    TZ=Europe/Moscow

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

# В образе ms-playwright Chromium уже установлен; страховка на случай минорных
# обновлений библиотеки Playwright из requirements.txt.
RUN python -m playwright install chromium

COPY . .

# Каталог под persistent profile / cookies storage_state. На Railway нужен
# Volume mount именно сюда, чтобы экспортированные с dev-машины state-файлы
# и telegram.session/instagram.session переживали редеплои.
ENV BROWSER_PROFILE_DIR=/app/.browser-profile
RUN mkdir -p "$BROWSER_PROFILE_DIR" /app/staticfiles

# Собираем статику под тем же DEBUG=false, что и на Railway: иначе при
# DEBUG=True в слое сборки не подключается CompressedManifestStaticFilesStorage,
# manifest не совпадает с рантаймом и WhiteNoise может валить процесс.
RUN DEBUG=false python manage.py collectstatic --noinput

EXPOSE 8000

# На Railway PORT инжектируется при старте; поддерживаем оба варианта.
# --workers 1 — обязательное условие, если scheduler крутится в этом же
# процессе (RUN_SCHEDULER=true), иначе APScheduler задублирует задачи.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 1 --threads 4 --timeout 600"]
