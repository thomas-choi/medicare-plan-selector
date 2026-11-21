# Sourced by the Makefile (bash) after .env is loaded. Works out where the dev MySQL/Redis live:
#   - local (default): this machine's docker compose stack on 127.0.0.1:3307 / :6380;
#   - remote: another machine's dev stack, e.g. a coding host (ml3090) using the stack on ml3060 (192.168.0.216).
# The MySQL host comes from MSP_DB_HOST, else from INGEST_DATABASE_URL / DATABASE_URL in .env. It is local when it
# is a loopback name/address or one of this machine's own addresses (`hostname -I`).
# Redis is app-local (DESIGN-v0.4-ADDENDUM A10): its host comes from REDIS_URL only and defaults to 127.0.0.1, never
# to the MySQL host. A remote Redis is an explicit opt-in (a non-local host in REDIS_URL).
# Sets DEV_DB_HOST, DEV_DB_PORT, DEV_REDIS_HOST, DEV_REDIS_PORT, DEV_DB_REMOTE and DEV_REDIS_REMOTE (1 or empty).
# When MySQL is remote, it also exports COMPOSE_*_URL (unless already set) so the api container uses the same MySQL
# as the host. A local Redis is reached from the container as the compose service `redis:6379` (127.0.0.1 inside it
# is the container itself); with REDIS_URL unset the compose default URL already does that.

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
DEV_REDIS_HOST="${DEV_REDIS_HOST:-127.0.0.1}"
DEV_REDIS_PORT="$(_devdb_port "${REDIS_URL:-}" "${MSP_REDIS_PORT:-6380}")"
DEV_DB_REMOTE=""
_devdb_is_local "$DEV_DB_HOST" || DEV_DB_REMOTE=1
DEV_REDIS_REMOTE=""
_devdb_is_local "$DEV_REDIS_HOST" || DEV_REDIS_REMOTE=1

_devdb_redis_in_compose() { # local Redis URL -> the same URL via the compose service name
  local scheme="${1%%://*}" rest="${1#*://}" auth="" path=""
  case "$rest" in *@*) auth="${rest%%@*}@"; rest="${rest#*@}" ;; esac
  case "$rest" in */*) path="/${rest#*/}" ;; esac
  printf '%s://%sredis:6379%s' "$scheme" "$auth" "$path"
}

if [ -n "$DEV_DB_REMOTE" ]; then
  # The containers reach the remote stack over the LAN with the same URLs as the host.
  export COMPOSE_DATABASE_URL="${COMPOSE_DATABASE_URL:-${DATABASE_URL:-}}"
  export COMPOSE_INGEST_DATABASE_URL="${COMPOSE_INGEST_DATABASE_URL:-${INGEST_DATABASE_URL:-}}"
  export COMPOSE_MIGRATOR_DATABASE_URL="${COMPOSE_MIGRATOR_DATABASE_URL:-${MIGRATOR_DATABASE_URL:-}}"
  if [ -n "$DEV_REDIS_REMOTE" ]; then
    export COMPOSE_REDIS_URL="${COMPOSE_REDIS_URL:-${REDIS_URL:-}}"
  elif [ -n "${REDIS_URL:-}" ]; then
    export COMPOSE_REDIS_URL="${COMPOSE_REDIS_URL:-$(_devdb_redis_in_compose "$REDIS_URL")}"
  fi
fi

# Check that whatever is remote answers: MySQL when DEV_DB_REMOTE, Redis only when DEV_REDIS_REMOTE.
devdb_check_remote() {
  local ok=1 hp targets=()
  [ -n "$DEV_DB_REMOTE" ] && targets+=("$DEV_DB_HOST:$DEV_DB_PORT")
  [ -n "$DEV_REDIS_REMOTE" ] && targets+=("$DEV_REDIS_HOST:$DEV_REDIS_PORT")
  for hp in "${targets[@]}"; do
    if timeout 3 bash -c "</dev/tcp/${hp%:*}/${hp##*:}" 2>/dev/null; then
      echo "remote dev store on $hp: reachable"
    else
      echo "ERROR: $hp is not reachable from $(hostname)." >&2
      ok=0
    fi
  done
  [ "$ok" = 1 ] && return 0
  cat >&2 <<EOF

.env points MySQL (or an explicitly remote REDIS_URL) at another machine, so no local MySQL is started.
Check that the server is up and its port is reachable from $(hostname) (firewall, bind address), and that the
host/port in DATABASE_URL / INGEST_DATABASE_URL / MIGRATOR_DATABASE_URL (or MSP_DB_HOST) are right.
Redis stays on this machine: keep REDIS_URL on 127.0.0.1:6380 or leave it out (docs/OPERATION.md).
Or use this machine's own MySQL: point the three DB URLs in .env at 127.0.0.1:3307.
EOF
  return 1
}
