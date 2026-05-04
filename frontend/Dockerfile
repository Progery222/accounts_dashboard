# Production frontend image (Vite build → nginx static).
# Railway передаёт публичный URL backend через VITE_API_URL build-arg.

# ── Build stage ──────────────────────────────────────────────────────────────
FROM node:20-alpine AS build
WORKDIR /app

ARG VITE_API_URL=""
ENV VITE_API_URL=${VITE_API_URL}

COPY package*.json ./
RUN npm ci || npm install
COPY . .
RUN npm run build

# ── Runtime stage ────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template

# PORT          — на каком порту nginx слушает внутри контейнера.
#                 Railway инжектит свой PORT; для VPS обычно ставим 80, а
#                 наружу маппим хост-порт (например 8080:80).
# BACKEND_UPSTREAM — host:port Django backend в той же docker-сети
#                 (для VPS: "backend:8000"). На Railway фронт обращается к
#                 backend напрямую через VITE_API_URL, location /api/ не
#                 используется, но переменная всё равно должна быть задана.
ENV PORT=8080 \
    BACKEND_UPSTREAM=backend:8000
EXPOSE 8080

CMD ["sh", "-c", "envsubst '$$PORT $$BACKEND_UPSTREAM' < /etc/nginx/templates/default.conf.template > /etc/nginx/conf.d/default.conf && exec nginx -g 'daemon off;'"]
