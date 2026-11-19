# Sourced by the Makefile (bash) after .env is loaded. Works out where the dev MySQL/Redis live:
#   - local (default): this machine's docker compose stack on 127.0.0.1:3307 / :6380;
#   - remote: another machine's dev stack, e.g. a coding host (ml3090) using the stack on ml3060 (192.168.0.216).
# The MySQL host comes from MSP_DB_HOST, else from INGEST_DATABASE_URL / DATABASE_URL in .env. It is local when it
# is a loopback name/address or one of this machine's own addresses (`hostname -I`).
# Sets DEV_DB_HOST, DEV_DB_PORT, DEV_REDIS_HOST, DEV_REDIS_PORT and DEV_DB_REMOTE (1 or empty). When remote, it also
# exports COMPOSE_*_URL (unless already set) so the api container uses the same remote MySQL/Redis as the host.

_devdb_host() { # URL -> host
  local u="${1#*://}"
  u="${u##*@}"
  u="${u%%/*}"
  printf '%s' "${u%%:*}"
}

_devdb_port() { # URL default -> port
  local u="${1#*://}"
  u="${u##*@}"
  u="${u%%/*}"
  case "$u" in *:*) printf '%s' "${u##*:}" ;; *) printf '%s' "$2" ;; esac
}

_devdb_is_local() { # host -> 0 if it is this machine
  case "$1" in "" | localhost | 127.* | ::1) return 0 ;; esac
  [ "$1" = "$(hostname)" ] && return 0
  hostname -I 2>/dev/null | tr ' ' '\n' | grep -qxF "$1"
}

_devdb_url="${INGEST_DATABASE_URL:-${DATABASE_URL:-}}"
DEV_DB_HOST="${MSP_DB_HOST:-$(_devdb_host "$_devdb_url")}"
DEV_DB_HOST="${DEV_DB_HOST:-127.0.0.1}"
DEV_DB_PORT="$(_devdb_port "$_devdb_url" "${MSP_MYSQL_PORT:-3307}")"
DEV_REDIS_HOST="$(_devdb_host "${REDIS_URL:-}")"
DEV_REDIS_HOST="${DEV_REDIS_HOST:-$DEV_DB_HOST}"
DEV_REDIS_PORT="$(_devdb_port "${REDIS_URL:-}" "${MSP_REDIS_PORT:-6380}")"
DEV_DB_REMOTE=""
_devdb_is_local "$DEV_DB_HOST" || DEV_DB_REMOTE=1

if [ -n "$DEV_DB_REMOTE" ]; then
  # The containers reach the remote stack over the LAN with the same URLs as the host.
  export COMPOSE_DATABASE_URL="${COMPOSE_DATABASE_URL:-${DATABASE_URL:-}}"
  export COMPOSE_INGEST_DATABASE_URL="${COMPOSE_INGEST_DATABASE_URL:-${INGEST_DATABASE_URL:-}}"
  export COMPOSE_MIGRATOR_DATABASE_URL="${COMPOSE_MIGRATOR_DATABASE_URL:-${MIGRATOR_DATABASE_URL:-}}"
  export COMPOSE_REDIS_URL="${COMPOSE_REDIS_URL:-${REDIS_URL:-}}"
fi

# Remote stack: check that MySQL and Redis answer; explain how to publish them on the DB host if not.
devdb_check_remote() {
  local ok=1 hp
  for hp in "$DEV_DB_HOST:$DEV_DB_PORT" "$DEV_REDIS_HOST:$DEV_REDIS_PORT"; do
    if timeout 3 bash -c "</dev/tcp/${hp%:*}/${hp##*:}" 2>/dev/null; then
      echo "dev stack on $hp: reachable"
    else
      echo "ERROR: $hp is not reachable from $(hostname)." >&2
      ok=0
    fi
  done
  [ "$ok" = 1 ] && return 0
  cat >&2 <<EOF

.env points the dev MySQL/Redis at $DEV_DB_HOST, which is not this machine, so no local MySQL/Redis is started.
On $DEV_DB_HOST (in its repo clone):
  1. set MSP_DB_BIND=$DEV_DB_HOST in its .env (publishes MySQL :3307 and Redis :6380 on that LAN address),
  2. run: make stack-down && make stack-up && make ingest-dev   (ports bind when the containers are created).
Or use this machine's own stack: point the four URLs in .env at 127.0.0.1:3307 / 127.0.0.1:6380.
EOF
  return 1
}
