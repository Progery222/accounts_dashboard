#!/bin/bash
# Устарело: Funnel на ноде streamcut заменён отдельной нодой accountsstats.
# См. scripts/enable-accountsstats-tailscale-funnel.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec "$ROOT/scripts/enable-accountsstats-tailscale-funnel.sh"
