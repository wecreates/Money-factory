#!/usr/bin/env bash
set -euo pipefail
FARM_DIR="${FARM_DIR:-/opt/cyzor/Money-factory/automation/browser-farm}"
cd "$FARM_DIR"
sudo docker compose ps
sudo docker compose logs --tail=120 browser-farm
if ! sudo docker compose ps --status running | grep -q browser-farm; then
  echo "Browser farm container is not running"
  exit 1
fi
echo CYZOR_BROWSER_FARM_HEALTHY
