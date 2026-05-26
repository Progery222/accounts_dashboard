FROM nginx:alpine
COPY deploy/nginx-atomic/default.conf /etc/nginx/conf.d/default.conf
COPY new_frontend /usr/share/nginx/html
# vendor/ иногда попадает в образ с mode 0700 — nginx (не root) тогда не видит файлы
# и try_files отдаёт app.html (text/html) вместо .js → «Скрипт не загрузился».
RUN chmod -R a+rX /usr/share/nginx/html/vendor
