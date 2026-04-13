#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "${ROOT_DIR}/.env" ]]; then
  while IFS='=' read -r key value; do
    case "${key}" in
      APP_PORT|APP_CONTAINER_NAME|COMPOSE_PROJECT_NAME)
        export "${key}=${value}"
        ;;
    esac
  done < <(grep -E '^(APP_PORT|APP_CONTAINER_NAME|COMPOSE_PROJECT_NAME)=' "${ROOT_DIR}/.env" || true)
fi

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-gatewaygrok-be}"

cd "${ROOT_DIR}"
if [[ -n "${APP_CONTAINER_NAME:-}" ]] && docker ps -a --format '{{.Names}}' | grep -Fxq "${APP_CONTAINER_NAME}"; then
  docker rm -f "${APP_CONTAINER_NAME}"
fi
docker compose -p "${PROJECT_NAME}" up -d --build
docker compose -p "${PROJECT_NAME}" ps
