#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE_TEST:-http://127.0.0.1:18084}"
CLIENT_API_KEY="${CLIENT_API_KEY_TEST:-}"

if [[ -z "${CLIENT_API_KEY}" ]]; then
  echo "Set CLIENT_API_KEY_TEST before running this script."
  exit 1
fi

curl -s "${API_BASE}/api/client/verify" \
  -H "x-api-key: ${CLIENT_API_KEY}"
echo
