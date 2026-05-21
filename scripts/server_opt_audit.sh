#!/bin/bash
# Аудит /opt на VPS — запускать на сервере: bash /tmp/server_opt_audit.sh
set -u

section() { echo ""; echo "========== $1 =========="; }

section "HOST"
hostname -f 2>/dev/null || hostname
uname -a
df -h / /opt 2>/dev/null || df -h /

section "/opt listing"
ls -la /opt

section "DOCKER all containers"
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || echo "docker ps failed"

section "/opt root docker-compose.yml (head)"
head -80 /opt/docker-compose.yml 2>/dev/null || echo "no /opt/docker-compose.yml"

section "NGINX proxy (head)"
head -60 /opt/nginx-proxy.conf 2>/dev/null || echo "no nginx-proxy.conf"

section "ATOME-STUDIO: tree apps packages"
find /opt/atome-studio/apps -maxdepth 3 \( -name package.json -o -name Dockerfile -o -name README.md \) 2>/dev/null | head -40
ls -la /opt/atome-studio/apps 2>/dev/null
ls -la /opt/atome-studio/packages 2>/dev/null

section "ATOME-STUDIO: package.json"
cat /opt/atome-studio/package.json 2>/dev/null

section "ATOME-STUDIO: docker-compose.yml"
cat /opt/atome-studio/docker-compose.yml 2>/dev/null

section "ATOME-STUDIO: deploy.sh"
cat /opt/atome-studio/deploy.sh 2>/dev/null

section "ATOME-STUDIO: .env.example (no secrets)"
cat /opt/atome-studio/.env.example 2>/dev/null

section "ATOME-STUDIO: git"
cd /opt/atome-studio && git remote -v 2>/dev/null; git log -1 --oneline 2>/dev/null; git branch -a 2>/dev/null | head -10

section "ATOME-STUDIO: docker compose"
cd /opt/atome-studio && docker compose ps -a 2>/dev/null
cd /opt/atome-studio && docker compose config --services 2>/dev/null

section "ATOME-STUDIO: CLAUDE.md (head 80)"
head -80 /opt/atome-studio/CLAUDE.md 2>/dev/null

section "ATOME-STUDIO: tz (head 40)"
head -40 /opt/atome-studio/tz_atom_studio.md 2>/dev/null

section "OTHER /opt projects (compose + size)"
for d in /opt/*/; do
  name=$(basename "$d")
  [ "$name" = "atome-studio" ] && continue
  [ -d "$d" ] || continue
  echo "--- $name ($(du -sh "$d" 2>/dev/null | cut -f1)) ---"
  ls "$d" 2>/dev/null | head -15
  [ -f "${d}docker-compose.yml" ] && head -25 "${d}docker-compose.yml" 2>/dev/null
done

section "PORTS listening"
ss -tlnp 2>/dev/null | head -35 || netstat -tlnp 2>/dev/null | head -35

section "DONE"
