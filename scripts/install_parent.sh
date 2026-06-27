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
exec "$PYTHON" -m src.web_panel
