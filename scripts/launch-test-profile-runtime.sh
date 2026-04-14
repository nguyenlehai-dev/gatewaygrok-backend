#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${APP_CONTAINER_NAME_TEST:-gatewaygrok-api-test}"

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <profile_id> <display> [screen] [start_url]"
  echo "Example: $0 d5a1ef00-a053-4ca4-8ed8-58429b396a1a :101 1280x720x24 https://grok.com/imagine"
  exit 1
fi

PROFILE_ID="$1"
DISPLAY_ID="$2"
SCREEN_GEOMETRY="${3:-1280x720x24}"
START_URL="${4:-}"

docker exec "${CONTAINER_NAME}" sh -lc "
set -eu
mkdir -p /app/storage-test
if ! pgrep -f 'Xvfb ${DISPLAY_ID}\b' >/dev/null 2>&1; then
  rm -f /tmp/.X${DISPLAY_ID#:}-lock /tmp/.X11-unix/X${DISPLAY_ID#:} 2>/dev/null || true
  nohup Xvfb ${DISPLAY_ID} -screen 0 ${SCREEN_GEOMETRY} >/app/storage-test/runtime-xvfb-${PROFILE_ID}.log 2>&1 &
  sleep 1
fi
if [ -n \"${START_URL}\" ]; then
  nohup env DISPLAY=${DISPLAY_ID} python /app/scripts/profile_runtime_bootstrap.py --profile-id ${PROFILE_ID} --url ${START_URL} >/app/storage-test/runtime-${PROFILE_ID}.log 2>&1 &
else
  nohup env DISPLAY=${DISPLAY_ID} python /app/scripts/profile_runtime_bootstrap.py --profile-id ${PROFILE_ID} >/app/storage-test/runtime-${PROFILE_ID}.log 2>&1 &
fi
"

echo "Launched runtime browser for profile ${PROFILE_ID} on DISPLAY ${DISPLAY_ID} in container ${CONTAINER_NAME}"
