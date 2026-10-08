#!/usr/bin/env bash
set -euo pipefail
REPO_URL="${REPO_URL:-https://github.com/wecreates/Money-factory.git}"
INSTALL_ROOT="${INSTALL_ROOT:-/opt/cyzor}"
APP_DIR="$INSTALL_ROOT/Money-factory"
FARM_DIR="$APP_DIR/automation/browser-farm"
sudo mkdir -p "$INSTALL_ROOT"
sudo chown "$USER":"$USER" "$INSTALL_ROOT"
if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl git docker.io docker-compose-v2
  sudo systemctl enable --now docker
fi
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  git -C "$APP_DIR" fetch --all --prune
  git -C "$APP_DIR" reset --hard origin/main
fi
cd "$FARM_DIR"
if [ ! -f .env ]; then cp .env.example .env; fi
sudo docker compose down || true
sudo docker compose build --pull
sudo docker compose up -d
sudo docker compose ps
echo CYZOR_BROWSER_FARM_DEPLOYED
