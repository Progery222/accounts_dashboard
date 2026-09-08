    client_max_body_size 32m;

    location /api/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
    }

    location /admin/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
    }

    location /media/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
    }

    location /healthz/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
    }

    location = /index.html {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        try_files $uri =404;
    }

    # Legacy Atomic bookmarks → new SPA
    location = /app.html {
        return 302 /;
    }

    location = /app.bundle.js {
        return 404;
    }

    location / {
        try_files $uri $uri/ @spa;
    }

    location @spa {
        add_header Cache-Control "no-cache, no-store, must-revalidate" always;
        try_files /index.html =404;
    }
