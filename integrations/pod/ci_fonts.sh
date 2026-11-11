#!/usr/bin/env bash
set -euo pipefail

# A package-update network call is unnecessary when all required installed
# faces can actually be opened and rendered. Never replace missing fonts with
# a fallback or skip a failed font check. Keep runner repositories unchanged.
if python integrations/pod/ci_fonts.py; then
  echo 'POD_CI_FONTS_VERIFIED_EXISTING'
else
  timeout --signal=TERM --kill-after=5s 120s bash -euo pipefail -c '
    sudo apt-get update
    sudo apt-get install -y fonts-dejavu-core
  '
  python integrations/pod/ci_fonts.py
  echo 'POD_CI_FONTS_VERIFIED_INSTALLED'
fi
