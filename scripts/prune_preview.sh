#!/bin/bash
set -euo pipefail

echo "========== 1) docker image prune (без -a) =========="
echo "Удаляются только <none>:<none> — старые слои после docker build."
echo ""
docker images -f dangling=true --format '  {{.Size}}\t{{.ID}}'
echo "Штук: $(docker images -f dangling=true -q | wc -l)"

echo ""
echo "========== 2) docker image prune -a =========="
echo "Плюс к п.1: теги, на которые нет ни одного контейнера (даже остановленного)."
echo ""
echo "--- УДАЛЯТСЯ ---"
removed=0
while read -r size tag id; do
  cnt=$(docker ps -a --filter "ancestor=${id}" -q 2>/dev/null | wc -l)
  if [ "$cnt" -eq 0 ]; then
    echo "  ${size}\t${tag}\t${id}"
    removed=$((removed + 1))
  fi
done < <(docker images --format '{{.Size}} {{.Repository}}:{{.Tag}} {{.ID}}')
echo "Штук (включая dangling): $removed"

echo ""
echo "--- НЕ ТРОНЕТ (контейнер привязан к этому ID) ---"
while read -r size tag id; do
  cnt=$(docker ps -a --filter "ancestor=${id}" -q 2>/dev/null | wc -l)
  if [ "$cnt" -gt 0 ]; then
    names=$(docker ps -a --filter "ancestor=${id}" --format '{{.Names}}' | tr '\n' ',' | sed 's/,$//')
    echo "  ${size}\t${tag}\t<- ${names}"
  fi
done < <(docker images --format '{{.Size}} {{.Repository}}:{{.Tag}} {{.ID}}')

echo ""
echo "========== docker system df =========="
docker system df
