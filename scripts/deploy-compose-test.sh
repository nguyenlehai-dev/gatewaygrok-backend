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
