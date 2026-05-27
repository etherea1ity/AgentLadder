param(
    [switch]$Stop,
    [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

$RepoWin = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoForWslPath = $RepoWin -replace "\\", "/"
$RepoWsl = (wsl.exe wslpath -a $RepoForWslPath).Trim()
$Mode = if ($Stop) { "stop" } else { "start" }
$OpenFlag = if ($NoOpen) { "0" } else { "1" }

$Bash = @'
set -Eeuo pipefail
ROOT_DIR="__REPO_WSL__"
MODE="__MODE__"
OPEN_BROWSER="__OPEN_BROWSER__"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5123}"
LEGACY_WEB_PORT="${LEGACY_WEB_PORT:-5173}"
HOST="${HOST:-0.0.0.0}"
OPEN_HOST="${OPEN_HOST:-127.0.0.1}"

cd "$ROOT_DIR"

find_pids_on_port() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true
    return
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltnp 2>/dev/null | awk -v port=":${port}" '$4 ~ port {print $0}' | sed -nE 's/.*pid=([0-9]+).*/\1/p' | sort -u || true
    return
  fi
  if command -v fuser >/dev/null 2>&1; then
    fuser -n tcp "${port}" 2>/dev/null | tr ' ' '\n' | sed '/^$/d' || true
  fi
}

kill_port() {
  local port="$1"
  local pids
  pids="$(find_pids_on_port "$port" | sort -u | tr '\n' ' ')"
  if [[ -z "${pids// }" ]]; then
    echo "port ${port} is free"
    return
  fi
  echo "Stopping port ${port}: ${pids}"
  # shellcheck disable=SC2086
  kill ${pids} 2>/dev/null || true
  sleep 0.8
  local survivors=""
  local pid
  for pid in ${pids}; do
    if kill -0 "$pid" 2>/dev/null; then survivors+=" ${pid}"; fi
  done
  if [[ -n "${survivors// }" ]]; then
    echo "Force stopping:${survivors}"
    # shellcheck disable=SC2086
    kill -9 ${survivors} 2>/dev/null || true
  fi
}

ensure_python_env() {
  if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
    echo "Creating Python virtualenv at .venv ..."
    python3 -m venv "$ROOT_DIR/.venv"
  fi
  if [[ ! -x "$ROOT_DIR/.venv/bin/uvicorn" ]]; then
    echo "Installing Python dependencies ..."
    "$ROOT_DIR/.venv/bin/python" -m pip install -e "$ROOT_DIR[dev]"
  fi
}

ensure_web_env() {
  if [[ ! -d "$ROOT_DIR/apps/web/node_modules" ]]; then
    echo "Installing frontend dependencies ..."
    (cd "$ROOT_DIR/apps/web" && npm install)
  fi
}

wait_url() {
  local name="$1"
  local url="$2"
  local tries="${3:-120}"
  local i
  for ((i=1; i<=tries; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "${name} ready: ${url}"
      return 0
    fi
    sleep 0.25
  done
  echo "! ${name} may still be starting: ${url}"
}

start_backend() {
  echo "Starting backend on http://${OPEN_HOST}:${API_PORT} ..."
  (cd "$ROOT_DIR" && setsid -f env PYTHONUNBUFFERED=1 "$ROOT_DIR/.venv/bin/uvicorn" apps.api.main:app --host "$HOST" --port "$API_PORT" >/dev/null 2>&1)
  sleep 0.3
}

start_frontend() {
  echo "Starting frontend on http://${OPEN_HOST}:${WEB_PORT} ..."
  (cd "$ROOT_DIR/apps/web" && setsid -f npm run dev -- --host "$HOST" --port "$WEB_PORT" >/dev/null 2>&1)
  sleep 0.3
}

open_browser() {
  local url="http://${OPEN_HOST}:${WEB_PORT}"
  if [[ "$OPEN_BROWSER" != "1" ]]; then return 0; fi
  if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command "Start-Process '${url}'" >/dev/null 2>&1 || true
  elif command -v cmd.exe >/dev/null 2>&1; then
    cmd.exe /c start "" "$url" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
  fi
}

if [[ "$MODE" == "stop" ]]; then
  kill_port "$API_PORT"
  kill_port "$WEB_PORT"
  if [[ "$LEGACY_WEB_PORT" != "$WEB_PORT" ]]; then kill_port "$LEGACY_WEB_PORT"; fi
  echo "Stopped Agent Ladder dev ports."
  exit 0
fi

echo "Mode: real DashScope LLM"
kill_port "$API_PORT"
kill_port "$WEB_PORT"
if [[ "$LEGACY_WEB_PORT" != "$WEB_PORT" ]]; then kill_port "$LEGACY_WEB_PORT"; fi
ensure_python_env
ensure_web_env
start_backend
start_frontend
wait_url "backend" "http://${OPEN_HOST}:${API_PORT}/api/health" 240 || true
wait_url "frontend" "http://${OPEN_HOST}:${WEB_PORT}" 120 || true
open_browser
printf '\nAgent Ladder is running.\n\nFrontend: http://%s:%s\nBackend:  http://%s:%s/api/health\n\nStop:\n  powershell -ExecutionPolicy Bypass -File .\\start.ps1 -Stop\n' "$OPEN_HOST" "$WEB_PORT" "$OPEN_HOST" "$API_PORT"
'@

$Bash = $Bash.Replace("__REPO_WSL__", $RepoWsl).Replace("__MODE__", $Mode).Replace("__OPEN_BROWSER__", $OpenFlag)
$Bash | wsl.exe bash -lc "tr -d '\015' | bash -s"
