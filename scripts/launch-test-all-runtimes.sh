#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash "${ROOT_DIR}/scripts/launch-test-profile-runtime.sh" d5a1ef00-a053-4ca4-8ed8-58429b396a1a :101
bash "${ROOT_DIR}/scripts/launch-test-profile-runtime.sh" dda2bb75-52ad-4a30-bda0-2f3082ef49c1 :102
bash "${ROOT_DIR}/scripts/launch-test-profile-runtime.sh" e6980c8f-3d4b-4e0b-b70b-8f23e1872c26 :103

echo "Launched all 3 test profile runtimes."
