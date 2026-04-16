#!/bin/sh
set -eu

mkdir -p /app/storage

if [ "${GATEWAY_REUSE_LIVE_BROWSER_FOR_JOBS:-false}" = "true" ] && [ -n "${AUTO_LOGIN_PROFILE_ID:-}" ]; then
  echo "[entrypoint] starting login watchdog for profile ${AUTO_LOGIN_PROFILE_ID}"
  python /app/scripts/login_watchdog.py \
    --profile-id "${AUTO_LOGIN_PROFILE_ID}" \
    --interval "${AUTO_LOGIN_WATCHDOG_INTERVAL:-15}" \
    >> /app/storage/login-watchdog.log 2>&1 &
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
