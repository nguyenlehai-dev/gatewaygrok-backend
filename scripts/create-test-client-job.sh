#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE_TEST:-http://127.0.0.1:18084}"
CLIENT_API_KEY="${CLIENT_API_KEY_TEST:-}"

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <profile_id> <image|video> <prompt>"
  echo "Example: $0 d5a1ef00-a053-4ca4-8ed8-58429b396a1a image 'simple red apple'"
  exit 1
fi

if [[ -z "${CLIENT_API_KEY}" ]]; then
  echo "Set CLIENT_API_KEY_TEST before running this script."
  exit 1
fi

PROFILE_ID="$1"
TARGET="$2"
PROMPT="$3"

curl -s -X POST "${API_BASE}/api/client/jobs" \
  -H 'Content-Type: application/json' \
  -H "x-api-key: ${CLIENT_API_KEY}" \
  -d "{\"profile_id\":\"${PROFILE_ID}\",\"target\":\"${TARGET}\",\"prompt\":\"${PROMPT}\",\"count\":1}"
echo
