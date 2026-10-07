#!/usr/bin/env bash
set -euo pipefail
cd /opt/cyzor/Money-factory/automation/browser-farm
if ! sudo docker compose ps | grep -q "Up"; then
  echo "Browser farm is not running. Restarting."
  sudo docker compose up -d
  sleep 5
fi
sudo docker compose ps
