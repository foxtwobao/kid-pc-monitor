#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${KID_PC_REPO_URL:-https://github.com/foxtwobao/kid-pc-monitor.git}"
RAW_BASE="${KID_PC_RAW_BASE:-https://raw.githubusercontent.com/foxtwobao/kid-pc-monitor/main}"
INSTALL_DIR="${KID_PC_PARENT_DIR:-$HOME/.kid-pc-monitor/app}"
PANEL_PORT="${KID_PC_PANEL_PORT:-5000}"
CURRENT_USER="${USER:-$(id -un)}"
SERVICE_NAME="kid-pc-monitor.service"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
RUNNER="$INSTALL_DIR/run_parent_panel.sh"
LOG_FILE="$INSTALL_DIR/web_panel.log"
BACKGROUND_SERVICE=""
AUTOSTART_STATUS=""

need() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Missing required command: $1" >&2
        exit 1
    }
}

need git
need python3

systemd_user_available() {
    command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1
}

stop_existing_systemd_user_service() {
    if systemd_user_available; then
        systemctl --user stop "$SERVICE_NAME" >/dev/null 2>&1 || true
    fi
}

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

write_parent_runner() {
    cat >"$RUNNER" <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "$INSTALL_DIR"
export KID_PC_PAIRING_TOKEN_FILE="$PAIRING_TOKEN_FILE"
export KID_PC_DEVICE_SECRETS_FILE="$INSTALL_DIR/device_secrets.json"
export KID_PC_PANEL_PORT="$PANEL_PORT"
exec >>"$LOG_FILE" 2>&1
exec "$PYTHON" -m src.web_panel
EOF
    chmod 700 "$RUNNER"
}

install_systemd_user_service() {
    systemd_user_available || return 1
    mkdir -p "$SYSTEMD_USER_DIR"
    cat >"$SYSTEMD_USER_DIR/$SERVICE_NAME" <<EOF
[Unit]
Description=Kid PC Monitor parent web panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$RUNNER
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now "$SERVICE_NAME"
    BACKGROUND_SERVICE="systemd user service: $SERVICE_NAME"
    AUTOSTART_STATUS="enabled with systemctl --user enable --now"
    if command -v loginctl >/dev/null 2>&1; then
        if loginctl enable-linger "$CURRENT_USER" >/dev/null 2>&1; then
            AUTOSTART_STATUS="$AUTOSTART_STATUS; boot autostart enabled via loginctl linger"
        else
            AUTOSTART_STATUS="$AUTOSTART_STATUS; starts after user login. For boot before login, run: loginctl enable-linger $CURRENT_USER"
        fi
    fi
}

start_nohup_parent_panel() {
    nohup "$RUNNER" >/dev/null 2>&1 &
    BACKGROUND_SERVICE="nohup background process (pid $!)"
    AUTOSTART_STATUS="not configured automatically because systemd user services are unavailable"
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

write_parent_runner
stop_existing_systemd_user_service
stop_existing_parent_panel
if ! install_systemd_user_service; then
    start_nohup_parent_panel
fi

cat <<EOF

Kid PC Monitor parent panel is ready.

Open:
  http://${PARENT_IP}:${PANEL_PORT}

Run this ONE command on each child Windows PC from an Administrator PowerShell:
  ${CHILD_COMMAND}

Background service:
  ${BACKGROUND_SERVICE}

Autostart:
  ${AUTOSTART_STATUS}

Log:
  ${LOG_FILE}

EOF
