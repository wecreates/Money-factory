#!/bin/bash
set -euo pipefail

apt-get update
apt-get install -y ca-certificates curl git docker.io docker-compose-v2
systemctl enable --now docker

mkdir -p /opt/cyzor
cd /opt/cyzor

if [ ! -d Money-factory ]; then
  git clone https://github.com/wecreates/Money-factory.git
fi
cd Money-factory
git pull --ff-only

cd automation/browser-farm
if [ ! -f .env ]; then
  cp .env.example .env
  echo "EDIT /opt/cyzor/Money-factory/automation/browser-farm/.env BEFORE STARTING"
  exit 0
fi

docker compose up -d --build
