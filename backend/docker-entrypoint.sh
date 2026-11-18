#!/bin/sh
# No core dumps: a dump could contain decrypted session data (DESIGN §8.5).
ulimit -c 0
set -eu
case "${1:-api}" in
  api)
    # Wipe all No-save keys once per container start, before any worker accepts requests (N5).
    selector ephemeral-flush
    exec uvicorn --factory selector.api.main:app_factory --host 0.0.0.0 --port 8000 \
      --workers "${API_WORKERS:-2}" --no-access-log --proxy-headers --forwarded-allow-ips '*'
    ;;
  purge-loop)
    # Nightly retention purge (DESIGN §8.1): once at start, then every PURGE_INTERVAL_S (default 24 h).
    while true; do
      selector purge || echo "purge failed" >&2
      sleep "${PURGE_INTERVAL_S:-86400}"
    done
    ;;
  *)
    exec selector "$@"
    ;;
esac
