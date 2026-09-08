# AccountsStats frontend — single-file UI (frontend/index.html), no build step.
FROM nginx:alpine
RUN apk add --no-cache openssl
COPY deploy/nginx-atomic/default.conf /etc/nginx/conf.d/default.conf
COPY deploy/nginx-atomic/dashboard-locations.inc /etc/nginx/conf.d/dashboard-locations.inc
COPY deploy/nginx-atomic/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
COPY frontend/index.html /usr/share/nginx/html/index.html
# Keep a tiny favicon-less tree; SPA fallback is index.html.
RUN chmod a+r /usr/share/nginx/html/index.html \
    && printf '%s\n' '<!doctype html><meta http-equiv="refresh" content="0;url=/">' \
         > /usr/share/nginx/html/app.html \
    && chmod a+r /usr/share/nginx/html/app.html
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
