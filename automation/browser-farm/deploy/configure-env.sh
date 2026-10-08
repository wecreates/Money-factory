#!/usr/bin/env bash
set -euo pipefail
FARM_DIR="${FARM_DIR:-/opt/cyzor/Money-factory/automation/browser-farm}"
mkdir -p "$FARM_DIR"
cat > "$FARM_DIR/.env" <<EOF
MAX_PARALLEL=${MAX_PARALLEL:-3}
HEADLESS=${HEADLESS:-true}
GITHUB_TOKEN=${FARM_GITHUB_TOKEN}
GITHUB_REPOSITORY=${GITHUB_REPOSITORY:-wecreates/Money-factory}
GITHUB_BRANCH=${GITHUB_BRANCH:-main}
GITHUB_QUEUE_PATH=${GITHUB_QUEUE_PATH:-automation/browser-farm/cloud-queue}
GITHUB_POLL_MS=${GITHUB_POLL_MS:-15000}
EOF
chmod 600 "$FARM_DIR/.env"
echo CYZOR_BROWSER_FARM_ENV_CONFIGURED
