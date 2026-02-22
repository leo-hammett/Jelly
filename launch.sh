#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$ROOT_DIR/.jelly_tmp/mcp-sidecars"
ENV_FILE="$STATE_DIR/env.sh"
FS_PID_FILE="$STATE_DIR/filesystem.pid"
BR_PID_FILE="$STATE_DIR/browser.pid"
FS_LOG="$STATE_DIR/filesystem.log"
BR_LOG="$STATE_DIR/browser.log"

HOST="${JELLY_MCP_HOST:-127.0.0.1}"
FS_PORT="${JELLY_MCP_FILESYSTEM_PORT:-7611}"
BR_PORT="${JELLY_MCP_BROWSER_PORT:-7612}"
FS_URL="http://${HOST}:${FS_PORT}/mcp"
BR_URL="http://${HOST}:${BR_PORT}/mcp"

mkdir -p "$STATE_DIR"

print_usage() {
  cat <<'EOF'
Usage:
  ./launch.sh start           Start filesystem + browser MCP sidecars
  ./launch.sh stop            Stop both sidecars
  ./launch.sh status          Show sidecar status and URLs
  ./launch.sh env             Print export lines for MCP endpoint env vars
  ./launch.sh run [command]   Start sidecars, run command with env vars, then stop

Examples:
  ./launch.sh start
  source ./.jelly_tmp/mcp-sidecars/env.sh
  uv run python -m jelly

  ./launch.sh run uv run python -m jelly
EOF
}

is_running_pid() {
  local pid="$1"
  if [[ -z "$pid" ]]; then
    return 1
  fi
  kill -0 "$pid" 2>/dev/null
}

wait_for_health() {
  local name="$1"
  local base_url="$2"
  python3 - "$name" "$base_url" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

name = sys.argv[1]
url = sys.argv[2].rstrip("/") + "/health"
deadline = time.time() + 20
while time.time() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:
            if resp.status == 200:
                payload = json.loads(resp.read().decode("utf-8"))
                if payload.get("ok"):
                    sys.exit(0)
    except (urllib.error.URLError, TimeoutError, ValueError):
        pass
    time.sleep(0.25)
print(f"Timed out waiting for {name} sidecar health at {url}", file=sys.stderr)
sys.exit(1)
PY
}

write_env_file() {
  cat >"$ENV_FILE" <<EOF
export JELLY_MCP_FILESYSTEM_URL="$FS_URL"
export JELLY_MCP_BROWSER_URL="$BR_URL"
EOF
}

start_sidecars() {
  local fs_workspace="$ROOT_DIR/output/.mcp/filesystem"
  mkdir -p "$fs_workspace"

  stop_sidecars >/dev/null 2>&1 || true
  write_env_file

  nohup python3 "$ROOT_DIR/jelly/mcp_sidecar.py" \
    --name filesystem \
    --host "$HOST" \
    --port "$FS_PORT" \
    --cwd "$ROOT_DIR" \
    -- npx -y @modelcontextprotocol/server-filesystem "$fs_workspace" \
    >"$FS_LOG" 2>&1 &
  echo "$!" >"$FS_PID_FILE"

  nohup python3 "$ROOT_DIR/jelly/mcp_sidecar.py" \
    --name browser \
    --host "$HOST" \
    --port "$BR_PORT" \
    --cwd "$ROOT_DIR" \
    -- npx -y @playwright/mcp --headless \
    >"$BR_LOG" 2>&1 &
  echo "$!" >"$BR_PID_FILE"

  wait_for_health "filesystem" "http://${HOST}:${FS_PORT}"
  wait_for_health "browser" "http://${HOST}:${BR_PORT}"

  echo "MCP sidecars started."
  echo "Filesystem: $FS_URL"
  echo "Browser:    $BR_URL"
  echo
  echo "To use in current shell:"
  echo "  source \"$ENV_FILE\""
}

stop_one() {
  local name="$1"
  local pid_file="$2"
  if [[ ! -f "$pid_file" ]]; then
    return 0
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if is_running_pid "$pid"; then
    kill "$pid" 2>/dev/null || true
    for _ in {1..20}; do
      if ! is_running_pid "$pid"; then
        break
      fi
      sleep 0.1
    done
    if is_running_pid "$pid"; then
      kill -9 "$pid" 2>/dev/null || true
    fi
    echo "Stopped $name sidecar (pid $pid)."
  fi
  rm -f "$pid_file"
}

stop_sidecars() {
  stop_one "filesystem" "$FS_PID_FILE"
  stop_one "browser" "$BR_PID_FILE"
}

status_sidecars() {
  local fs_pid=""
  local br_pid=""
  [[ -f "$FS_PID_FILE" ]] && fs_pid="$(cat "$FS_PID_FILE" 2>/dev/null || true)"
  [[ -f "$BR_PID_FILE" ]] && br_pid="$(cat "$BR_PID_FILE" 2>/dev/null || true)"

  if is_running_pid "$fs_pid"; then
    echo "filesystem: running (pid $fs_pid) -> $FS_URL"
  else
    echo "filesystem: stopped"
  fi

  if is_running_pid "$br_pid"; then
    echo "browser:    running (pid $br_pid) -> $BR_URL"
  else
    echo "browser:    stopped"
  fi

  echo "env file:   $ENV_FILE"
}

print_env() {
  write_env_file
  cat "$ENV_FILE"
}

run_with_sidecars() {
  start_sidecars
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  trap stop_sidecars EXIT

  if [[ "$#" -eq 0 ]]; then
    uv run python -m jelly
  else
    "$@"
  fi
}

command="${1:-run}"
if [[ "$#" -gt 0 ]]; then
  shift
fi

case "$command" in
  start)
    start_sidecars
    ;;
  stop)
    stop_sidecars
    ;;
  status)
    status_sidecars
    ;;
  env)
    print_env
    ;;
  run)
    run_with_sidecars "$@"
    ;;
  -h|--help|help)
    print_usage
    ;;
  *)
    echo "Unknown command: $command" >&2
    print_usage >&2
    exit 1
    ;;
esac
