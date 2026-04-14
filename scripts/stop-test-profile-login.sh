#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${APP_CONTAINER_NAME_TEST:-gatewaygrok-api-test}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <profile_id>"
  exit 1
fi

PROFILE_ID="$1"

docker exec "${CONTAINER_NAME}" sh -lc "
set -eu
pkill -f 'profile_login_bootstrap.py --profile-id ${PROFILE_ID}' || true
pkill -f '/app/storage-test/profiles/${PROFILE_ID}/user-data' || true
pkill -f 'Xvfb :10[0-9]' || true
rm -f /tmp/.X10[0-9]-lock /tmp/.X11-unix/X10[0-9] 2>/dev/null || true
"

echo "Stopped login/bootstrap processes for profile ${PROFILE_ID} in ${CONTAINER_NAME}"
