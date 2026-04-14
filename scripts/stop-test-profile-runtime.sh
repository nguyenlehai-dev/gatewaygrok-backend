#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${APP_CONTAINER_NAME_TEST:-gatewaygrok-api-test}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <profile_id> [display]"
  exit 1
fi

PROFILE_ID="$1"
DISPLAY_ID="${2:-}"

docker exec "${CONTAINER_NAME}" sh -lc "
set -eu
pkill -f 'profile_runtime_bootstrap.py --profile-id ${PROFILE_ID}' || true
pkill -f '/app/storage-test/profiles/${PROFILE_ID}/user-data' || true
if [ -n \"${DISPLAY_ID}\" ]; then
  pkill -f 'Xvfb ${DISPLAY_ID}\b' || true
  rm -f /tmp/.X${DISPLAY_ID#:}-lock /tmp/.X11-unix/X${DISPLAY_ID#:} 2>/dev/null || true
fi
"

echo "Stopped runtime browser for profile ${PROFILE_ID} in ${CONTAINER_NAME}"
