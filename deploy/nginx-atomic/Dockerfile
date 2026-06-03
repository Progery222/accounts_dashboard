FROM node:20-alpine AS build
WORKDIR /src
COPY new_frontend ./new_frontend
COPY deploy/nginx-atomic/precompile.mjs ./deploy/nginx-atomic/precompile.mjs
RUN npm install @babel/standalone@7.26.9 --no-save \
    && node deploy/nginx-atomic/precompile.mjs /src/new_frontend/app.html \
    && (test -s /src/new_frontend/vendor/react.production.min.js \
        || wget -q -O /src/new_frontend/vendor/react.production.min.js \
            https://unpkg.com/react@18.3.1/umd/react.production.min.js) \
    && (test -s /src/new_frontend/vendor/react-dom.production.min.js \
        || wget -q -O /src/new_frontend/vendor/react-dom.production.min.js \
            https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js)

FROM nginx:alpine
COPY deploy/nginx-atomic/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/new_frontend /usr/share/nginx/html
# vendor/ иногда попадает в образ с mode 0700 — nginx (не root) тогда не видит файлы
# и try_files отдаёт app.html (text/html) вместо .js → «Скрипт не загрузился».
RUN chmod -R a+rX /usr/share/nginx/html/vendor /usr/share/nginx/html/app.bundle.js
