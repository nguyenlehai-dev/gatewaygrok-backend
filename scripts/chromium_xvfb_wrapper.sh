#!/bin/sh
set -eu

if [ -n "${GATEWAY_CHROMIUM_BINARY:-}" ] && [ -x "${GATEWAY_CHROMIUM_BINARY}" ]; then
  CHROMIUM_BIN="${GATEWAY_CHROMIUM_BINARY}"
else
  CHROMIUM_BIN="$(find /ms-playwright -path '*/chrome-linux/chrome' -type f | head -n 1)"
fi

if [ -z "${CHROMIUM_BIN:-}" ] || [ ! -x "${CHROMIUM_BIN}" ]; then
  echo "chromium_xvfb_wrapper: chromium binary not found" >&2
  exit 1
fi

exec xvfb-run -a --server-args="-screen 0 1920x1080x24" "${CHROMIUM_BIN}" "$@"
