#!/usr/bin/env sh
set -e

# Pre-warm Hotel Info cache if missing, then run the given command.

APP_DIR="/app"
cd "$APP_DIR"

LANGUAGE="${PAPI_DEFAULT_LANGUAGE:-en}"
CACHE_PATH="${PAPI_HOTEL_CACHE_PATH:-./.cache/hotel_info.sqlite}"
OUT_PATH="./.cache/partner_feed_${LANGUAGE}.json.zst"

# Detect sandbox from base path
SANDBOX_FLAG=""
case "${PAPI_BASE_PATH:-}" in
  *api-sandbox.worldota.net*) SANDBOX_FLAG="--sandbox" ;;
esac

ensure_cache() {
  if [ -f "$CACHE_PATH" ] && [ -s "$CACHE_PATH" ]; then
    echo "Cache present at $CACHE_PATH"
    return 0
  fi
  echo "Cache missing at $CACHE_PATH — attempting to fetch dump and import..."
  mkdir -p "$(dirname "$CACHE_PATH")" "$(dirname "$OUT_PATH")"
  # Best-effort: if credentials are wrong, do not crash the container
  if python tools/fetch_and_import_dump.py --language "$LANGUAGE" --cache "$CACHE_PATH" --out "$OUT_PATH" $SANDBOX_FLAG; then
    echo "Cache populated successfully."
  else
    echo "Warning: failed to fetch/import dump. Proceeding without pre-warmed cache." >&2
  fi
}

ensure_cache

exec "$@"

