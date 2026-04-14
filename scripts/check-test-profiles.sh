#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE_TEST:-http://127.0.0.1:18084}"
ADMIN_USERNAME="${GATEWAY_ADMIN_USERNAME_TEST:-admin_test}"
ADMIN_PASSWORD="${GATEWAY_ADMIN_PASSWORD_TEST:-change-me-test}"

PROFILE_IDS=("$@")

if [[ ${#PROFILE_IDS[@]} -eq 0 ]]; then
  PROFILE_IDS=(
    "d5a1ef00-a053-4ca4-8ed8-58429b396a1a"
    "dda2bb75-52ad-4a30-bda0-2f3082ef49c1"
    "e6980c8f-3d4b-4e0b-b70b-8f23e1872c26"
  )
fi

ADMIN_TOKEN="$(
  curl -s -X POST "${API_BASE}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USERNAME}\",\"password\":\"${ADMIN_PASSWORD}\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])'
)"

for pid in "${PROFILE_IDS[@]}"; do
  echo "PROFILE:${pid}"
  curl -s -X POST "${API_BASE}/api/profiles/${pid}/session-check" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print({k:d.get(k) for k in ["state","summary","live_browser_connected","requires_live_browser","page_url","title"]})'
done
