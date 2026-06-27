#!/usr/bin/env bash
# Install the Kid PC Monitor web panel as a systemd --user service (Linux only).
# Requires: systemd, bash. Uses the repo layout: this file lives in scripts/.

set -euo pipefail

UNIT_NAME="kid-pc-monitor-web-panel.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WEB_PANEL_PY="${REPO_ROOT}/src/web_panel.py"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_PATH="${UNIT_DIR}/${UNIT_NAME}"

usage() {
    cat <<'EOF'
Usage: install_web_panel_linux.sh <command>

Commands:
  install     Write a systemd user unit, enable and start the web panel.
  uninstall   Stop, disable, and remove the user unit.
  status      Show systemctl --user status.
  cat-unit    Print the unit file that would be used (no writes).

Environment (optional):
  PYTHON      Full path to python interpreter (default: .venv, venv, or python3)

The service runs with WorkingDirectory set to the repo root and starts the
panel as a module, matching the src.* imports used by the current codebase.

Optional — start at boot without an interactive login:
  sudo loginctl enable-linger "$USER"
EOF
}

die() {
    echo "Error: $*" >&2
    exit 1
}

require_linux() {
    case "$(uname -s)" in
        Linux) ;;
        *) die "This script is for Linux only (found: $(uname -s))." ;;
    esac
}

pick_python() {
    if [[ -n "${PYTHON:-}" ]]; then
        [[ -x "$PYTHON" ]] || die "PYTHON is not executable: $PYTHON"
        echo "$PYTHON"
        return
    fi
    for candidate in \
        "${REPO_ROOT}/.venv/bin/python3" \
        "${REPO_ROOT}/.venv/bin/python" \
        "${REPO_ROOT}/venv/bin/python3" \
        "${REPO_ROOT}/venv/bin/python"; do
        if [[ -x "$candidate" ]]; then
            echo "$candidate"
            return
        fi
    done
    if command -v python3 >/dev/null 2>&1; then
        command -v python3
        return
    fi
    die "No usable Python found. Create a venv in the repo root or set PYTHON=/path/to/python3"
}

require_systemctl_user() {
    systemctl --user status >/dev/null 2>&1 || die \
        "systemctl --user failed. Is systemd user session available? Try: loginctl enable-linger \"$USER\" (may require sudo) or log in once with a desktop session."
}

# Print a systemd user unit to stdout (paths must not contain shell metacharacters).
render_unit() {
    local py="$1"
    [[ -f "$WEB_PANEL_PY" ]] || die "Missing web panel script: $WEB_PANEL_PY"
    cat <<EOF
[Unit]
Description=Kid PC Monitor web panel (parent UI on port 5000)
After=network.target

[Service]
Type=simple
WorkingDirectory=${REPO_ROOT}
Environment=PYTHONUNBUFFERED=1
ExecStart=${py} -m src.web_panel
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
EOF
}

write_unit() {
    local py="$1"
    mkdir -p "$UNIT_DIR"
    render_unit "$py" >"$UNIT_PATH"
    echo "Wrote: $UNIT_PATH"
}

cmd_install() {
    require_linux
    require_systemctl_user
    local py
    py="$(pick_python)"
    echo "Using Python: $py"
    write_unit "$py"
    systemctl --user daemon-reload
    systemctl --user enable "$UNIT_NAME"
    systemctl --user restart "$UNIT_NAME"
    echo ""
    echo "Service is enabled and running. Check: systemctl --user status $UNIT_NAME"
    echo "Open: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<this-host-ip>'):5000"
    echo ""
    echo "Firewall (example): sudo ufw allow 5000/tcp"
    echo "Boot without login (optional): sudo loginctl enable-linger \"$USER\""
}

cmd_uninstall() {
    require_linux
    systemctl --user disable --now "$UNIT_NAME" 2>/dev/null || true
    rm -f "$UNIT_PATH"
    systemctl --user daemon-reload
    echo "Removed $UNIT_NAME (if it was present)."
}

cmd_status() {
    require_linux
    systemctl --user status "$UNIT_NAME" || true
}

cmd_cat_unit() {
    require_linux
    local py
    py="$(pick_python)"
    echo "# Preview (not written to disk):"
    render_unit "$py"
}

main() {
    local cmd="${1:-}"
    case "$cmd" in
        install) cmd_install ;;
        uninstall) cmd_uninstall ;;
        status) cmd_status ;;
        cat-unit) cmd_cat_unit ;;
        -h|--help|help) usage ;;
        *) usage; exit 1 ;;
    esac
}

main "$@"
