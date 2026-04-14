#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${APP_CONTAINER_NAME_TEST:-gatewaygrok-api-test}"

PROFILE_IDS=("$@")

if [[ ${#PROFILE_IDS[@]} -eq 0 ]]; then
  PROFILE_IDS=(
    "d5a1ef00-a053-4ca4-8ed8-58429b396a1a"
    "dda2bb75-52ad-4a30-bda0-2f3082ef49c1"
    "e6980c8f-3d4b-4e0b-b70b-8f23e1872c26"
  )
fi

docker exec "${CONTAINER_NAME}" python - <<'PY' "${PROFILE_IDS[@]}"
import socket
import sys
from app.services.browser_runtime import debug_port_for_profile

for profile_id in sys.argv[1:]:
    port = debug_port_for_profile(profile_id)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    opened = sock.connect_ex(("127.0.0.1", port)) == 0
    sock.close()
    print(f"{profile_id}:{port}:{'open' if opened else 'closed'}")
PY
