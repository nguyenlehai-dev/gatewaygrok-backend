#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE_TEST:-http://127.0.0.1:18084}"
ADMIN_USERNAME="${GATEWAY_ADMIN_USERNAME_TEST:-admin_test}"
ADMIN_PASSWORD="${GATEWAY_ADMIN_PASSWORD_TEST:-change-me-test}"

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <profile_id> <cookie_file>"
  echo "Example: $0 d5a1ef00-a053-4ca4-8ed8-58429b396a1a /path/to/cookies.json"
  exit 1
fi

PROFILE_ID="$1"
COOKIE_FILE="$2"

if [[ ! -f "${COOKIE_FILE}" ]]; then
  echo "Cookie file not found: ${COOKIE_FILE}"
  exit 1
fi

ADMIN_TOKEN="$(
  curl -s -X POST "${API_BASE}/api/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${ADMIN_USERNAME}\",\"password\":\"${ADMIN_PASSWORD}\"}" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])'
)"

curl -s -X POST "${API_BASE}/api/profiles/${PROFILE_ID}/cookies" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -F "file=@${COOKIE_FILE}"

echo
echo "Imported cookies into profile ${PROFILE_ID}"
