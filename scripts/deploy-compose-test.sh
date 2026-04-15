#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env.test"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Create it from .env.test.example first."
  exit 1
fi

while IFS='=' read -r key value; do
  case "${key}" in
    APP_PORT|APP_CONTAINER_NAME|COMPOSE_PROJECT_NAME)
      export "${key}=${value}"
      ;;
  esac
done < <(grep -E '^(APP_PORT|APP_CONTAINER_NAME|COMPOSE_PROJECT_NAME)=' "${ENV_FILE}" || true)

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-gatewaygrok-test-be}"

cd "${ROOT_DIR}"
if [[ -n "${APP_CONTAINER_NAME:-}" ]] && docker ps -a --format '{{.Names}}' | grep -Fxq "${APP_CONTAINER_NAME}"; then
  docker rm -f "${APP_CONTAINER_NAME}"
fi

mkdir -p "${ROOT_DIR}/storage-test"

docker compose --env-file "${ENV_FILE}" -f docker-compose.test.yml -p "${PROJECT_NAME}" up -d --build
docker compose --env-file "${ENV_FILE}" -f docker-compose.test.yml -p "${PROJECT_NAME}" ps

CONTAINER_NAME="${APP_CONTAINER_NAME:-gatewaygrok-api-test}"
if docker ps --format '{{.Names}}' | grep -Fxq "${CONTAINER_NAME}"; then
  echo "Waiting for ${CONTAINER_NAME} to become healthy..."
  for _ in {1..45}; do
    health_status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}healthy{{end}}' "${CONTAINER_NAME}" 2>/dev/null || true)"
    if [[ "${health_status}" == "healthy" ]]; then
      break
    fi
    sleep 2
  done

  echo "Relaunching Grok no-VNC/CDP runtimes for active test profiles..."
  docker exec "${CONTAINER_NAME}" bash -lc '
    set -euo pipefail
    export PYTHONPATH=/app
    python3 - <<'"'"'PY'"'"'
from app.db.session import SessionLocal
from app.models.profile import Profile

with SessionLocal() as db:
    profiles = (
        db.query(Profile)
        .filter(Profile.is_active.is_(True), Profile.category == "grok")
        .order_by(Profile.name.asc())
        .all()
    )
    for index, profile in enumerate(profiles, start=101):
        print(f"{profile.id} :{index}")
PY
  ' | while read -r profile_id display; do
    [[ -n "${profile_id}" && -n "${display}" ]] || continue
    docker exec "${CONTAINER_NAME}" bash -lc "
      set -euo pipefail
      rm -f /tmp/.X${display#:}-lock /tmp/.X11-unix/X${display#:}
      find /app/storage-test/profiles/${profile_id}/user-data -maxdepth 1 \\( -name SingletonLock -o -name SingletonSocket -o -name SingletonCookie \\) -delete 2>/dev/null || true
      GATEWAY_XVFB_DISPLAY=${display} nohup python3 /app/scripts/profile_runtime_bootstrap.py --profile-id ${profile_id} --url https://grok.com/imagine >/tmp/${profile_id}-runtime.log 2>&1 &
    "
  done
fi
