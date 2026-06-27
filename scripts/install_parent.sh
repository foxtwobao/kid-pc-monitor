#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${KID_PC_REPO_URL:-https://github.com/foxtwobao/kid-pc-monitor.git}"
RAW_BASE="${KID_PC_RAW_BASE:-https://raw.githubusercontent.com/foxtwobao/kid-pc-monitor/main}"
INSTALL_DIR="${KID_PC_PARENT_DIR:-$HOME/.kid-pc-monitor/app}"
PANEL_PORT="${KID_PC_PANEL_PORT:-5000}"

need() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Missing required command: $1" >&2
        exit 1
    }
}

need git
need python3

list_parent_panel_pids() {
    if command -v lsof >/dev/null 2>&1; then
        lsof -tiTCP:"$PANEL_PORT" -sTCP:LISTEN 2>/dev/null || true
        return
    fi
    if command -v ss >/dev/null 2>&1; then
        ss -ltnp "sport = :$PANEL_PORT" 2>/dev/null |
            sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' || true
        return
    fi
    if command -v fuser >/dev/null 2>&1; then
        fuser -n tcp "$PANEL_PORT" 2>/dev/null | tr ' ' '\n' || true
        return
    fi
}

stop_existing_parent_panel() {
    local pids pid cmd blocked=0 stopped=0
    pids="$(list_parent_panel_pids | sed '/^$/d' | sort -u)"
    [[ -z "$pids" ]] && return

    for pid in $pids; do
        [[ "$pid" == "$$" ]] && continue
        cmd="$(ps -p "$pid" -o args= 2>/dev/null || true)"
        if [[ "$cmd" == *"src.web_panel"* ]]; then
            echo "Stopping existing Kid PC Monitor parent panel on port ${PANEL_PORT} (pid ${pid})..."
            kill "$pid" 2>/dev/null || true
            stopped=1
        else
            echo "Port ${PANEL_PORT} is already in use by pid ${pid}: ${cmd}" >&2
            blocked=1
        fi
    done

    if [[ "$blocked" -eq 1 ]]; then
        echo "Stop the process above, or rerun with KID_PC_PANEL_PORT=<another-port>." >&2
        exit 1
    fi

    if [[ "$stopped" -eq 1 ]]; then
        for _ in {1..30}; do
            pids="$(list_parent_panel_pids | sed '/^$/d' | sort -u)"
            [[ -z "$pids" ]] && return
            sleep 0.2
        done
        echo "Port ${PANEL_PORT} is still busy after stopping the old parent panel." >&2
        exit 1
    fi
}

mkdir -p "$(dirname "$INSTALL_DIR")"
if [[ -d "$INSTALL_DIR/.git" ]]; then
    git -C "$INSTALL_DIR" pull --ff-only
else
    rm -rf "$INSTALL_DIR"
    git clone "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
python3 -m venv .venv
PYTHON="$INSTALL_DIR/.venv/bin/python"
"$PYTHON" -m pip install --upgrade pip >/dev/null
"$PYTHON" -m pip install -r requirements.txt

PAIRING_TOKEN_FILE="$INSTALL_DIR/pairing.token"
if [[ ! -s "$PAIRING_TOKEN_FILE" ]]; then
    "$PYTHON" - <<'PY' >"$PAIRING_TOKEN_FILE"
import secrets
print(secrets.token_urlsafe(24))
PY
    chmod 600 "$PAIRING_TOKEN_FILE"
fi
PAIRING_TOKEN="$(tr -d '\r\n' < "$PAIRING_TOKEN_FILE")"

PARENT_IP="$("$PYTHON" - <<'PY'
import socket

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.connect(("8.8.8.8", 80))
    print(sock.getsockname()[0])
except OSError:
    print("127.0.0.1")
finally:
    sock.close()
PY
)"

CHILD_COMMAND="powershell -NoProfile -ExecutionPolicy Bypass -Command \"iex (irm '${RAW_BASE}/scripts/install_child.ps1'); Install-KidPCMonitorChild -ParentUrl 'http://${PARENT_IP}:${PANEL_PORT}' -PairingToken '${PAIRING_TOKEN}'\""

stop_existing_parent_panel

cat <<EOF

Kid PC Monitor parent panel is ready.

Open:
  http://${PARENT_IP}:${PANEL_PORT}

Run this ONE command on each child Windows PC from an Administrator PowerShell:
  ${CHILD_COMMAND}

Keep this terminal open while pairing child PCs.

EOF

export KID_PC_PAIRING_TOKEN_FILE="$PAIRING_TOKEN_FILE"
export KID_PC_DEVICE_SECRETS_FILE="$INSTALL_DIR/device_secrets.json"
export KID_PC_PANEL_PORT="$PANEL_PORT"
exec "$PYTHON" -m src.web_panel
