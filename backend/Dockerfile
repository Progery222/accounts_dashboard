# Django + Playwright (Chromium) + gunicorn для headless-сервера.
# Базовый образ Microsoft Playwright уже содержит Chromium и системные зависимости.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    BROWSER_HEADLESS=true

WORKDIR /app

COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install gunicorn

# В образе ms-playwright Chromium уже установлен; страховка на случай минорных
# обновлений библиотеки Playwright из requirements.txt.
RUN python -m playwright install chromium

COPY . .

# Каталог под persistent profile / cookies storage_state. Монтируйте volume сюда,
# чтобы экспортированные с dev-машины {platform}_state.json сохранялись.
ENV BROWSER_PROFILE_DIR=/app/.browser-profile
RUN mkdir -p "$BROWSER_PROFILE_DIR"

EXPOSE 8000

# Веб-процесс. Для отдельного scheduler-контейнера переопределите CMD на
#   python manage.py run_scheduler   (или эквивалент).
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 600"]
