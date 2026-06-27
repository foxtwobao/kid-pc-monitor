from flask import Flask, render_template, request, jsonify, redirect, url_for
import json
import os
import socket
import threading
import ipaddress
import time
from datetime import datetime

from src.agent_auth import sign_message
from src.state_store import atomic_write_json

app = Flask(__name__)

# Store discovered PCs
discovered_pcs = {}
last_scan_time = None
PENDING_COMMANDS = {}
PENDING_COMMANDS_FILE = os.environ.get("KID_PC_PENDING_COMMANDS_FILE", "pending_commands.json")
DEVICE_SECRETS_FILE = os.environ.get("KID_PC_DEVICE_SECRETS_FILE", "device_secrets.json")
PAIRING_TOKEN_FILE = os.environ.get("KID_PC_PAIRING_TOKEN_FILE", "pairing.token")

# Custom PC names (optional) - Add your kids' PC names here
CUSTOM_PC_NAMES = {
    # Example: '192.168.1.105': 'Tommy\'s Laptop',
    # Example: '192.168.1.112': 'Sarah\'s Desktop',
}

# Child secrets are normally written automatically by the one-line pairing flow
# into DEVICE_SECRETS_FILE. You can still set KID_PC_DEVICE_SECRETS manually to
# override or add entries with a JSON object mapping IPs to hex secrets.
DEVICE_SECRETS = {
    # Example: '192.168.10.251': '0123abcd...',
}


def configured_device_secrets():
    secrets = dict(DEVICE_SECRETS)
    secrets.update(load_device_secrets())
    env_value = os.environ.get("KID_PC_DEVICE_SECRETS")
    if env_value:
        try:
            secrets.update(json.loads(env_value))
        except json.JSONDecodeError:
            print("Invalid KID_PC_DEVICE_SECRETS JSON; ignoring environment value")
    return secrets


def device_secret_for_host(host):
    return configured_device_secrets().get(host)


def load_device_secrets(secrets_file=None):
    path = os.fspath(secrets_file or os.environ.get("KID_PC_DEVICE_SECRETS_FILE", DEVICE_SECRETS_FILE))
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(ip): str(secret) for ip, secret in data.items()}


def save_device_secret(ip, secret, secrets_file=None):
    ipaddress.ip_address(ip)
    secret_value = str(secret).strip().lower()
    if len(secret_value) != 64:
        raise ValueError("device secret must be 64 hex characters")
    try:
        bytes.fromhex(secret_value)
    except ValueError as exc:
        raise ValueError("device secret must be 64 hex characters") from exc
    path = secrets_file or os.environ.get("KID_PC_DEVICE_SECRETS_FILE", DEVICE_SECRETS_FILE)
    secrets_map = load_device_secrets(path)
    secrets_map[str(ip)] = secret_value
    atomic_write_json(path, secrets_map)
    return secrets_map


def current_pairing_token():
    env_value = os.environ.get("KID_PC_PAIRING_TOKEN")
    if env_value:
        return env_value.strip()
    token_file = os.environ.get("KID_PC_PAIRING_TOKEN_FILE", PAIRING_TOKEN_FILE)
    if os.path.exists(token_file):
        try:
            with open(token_file, "r", encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            return ""
    return ""


def build_signed_command(body, secret_hex, now=None, nonce=None):
    return sign_message(body, bytes.fromhex(secret_hex), now=now, nonce=nonce)


def command_body_from_legacy(command):
    if isinstance(command, dict):
        return command
    if command == "LOCK":
        return {"command": "lock", "reason": "manual"}
    if command == "GET_STATUS":
        return {"command": "status"}
    if command.startswith("MESSAGE:"):
        return {"command": "message", "message": command.split(":", 1)[1]}
    if command.startswith("SET_LIMIT:"):
        return {"command": "set_limit", "minutes": int(command.split(":", 1)[1])}
    if command.startswith("ADD_LOCK_TIME:"):
        return {"command": "add_lock_time", "time": command.split(":", 1)[1]}
    if command == "CLEAR_USAGE_LIMIT":
        return {"command": "clear_usage_limit"}
    if command == "CLEAR_LOCK_TIMES":
        return {"command": "clear_lock_times"}
    if command == "CLEAR_ALL":
        return {"command": "clear_all"}
    return {"command": command.lower()}


def is_policy_command(body):
    return body.get("command") in {
        "apply_policy",
        "set_limit",
        "add_lock_time",
        "clear_usage_limit",
        "clear_lock_times",
        "clear_all",
    }


def load_pending_commands(pending_file=PENDING_COMMANDS_FILE):
    pending_path = os.fspath(pending_file)
    if not os.path.exists(pending_path):
        return {}
    try:
        with open(pending_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    PENDING_COMMANDS.clear()
    PENDING_COMMANDS.update(data)
    return PENDING_COMMANDS


def save_pending_commands(pending_file=PENDING_COMMANDS_FILE):
    atomic_write_json(pending_file, PENDING_COMMANDS)


def record_pending_command(ip, body, last_error, pending_file=PENDING_COMMANDS_FILE):
    PENDING_COMMANDS[ip] = {
        "body": body,
        "last_error": last_error,
        "created_at": datetime.now().isoformat(),
    }
    save_pending_commands(pending_file)


def sync_pending_command(ip, sender=None, pending_file=PENDING_COMMANDS_FILE):
    pending = PENDING_COMMANDS.get(ip)
    if not pending:
        return False
    sender = sender or send_signed_body
    success, response = sender(ip, pending["body"])
    if success:
        PENDING_COMMANDS.pop(ip, None)
        save_pending_commands(pending_file)
        return True
    pending["last_error"] = response
    save_pending_commands(pending_file)
    return False


load_pending_commands()


def send_signed_body(host, body, port=9999):
    secret_hex = device_secret_for_host(host)
    if not secret_hex:
        return False, "No device secret configured"
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(5)
        client.connect((host, port))
        envelope = build_signed_command(body, secret_hex)
        client.send((json.dumps(envelope) + "\n").encode("utf-8"))
        response = client.recv(4096).decode()
        client.close()
        return True, response
    except Exception as e:
        return False, str(e)


def query_status(ip, port=9999):
    success, response = send_signed_body(ip, {"command": "status"}, port=port)
    if not success:
        return None
    try:
        payload = json.loads(response)
    except json.JSONDecodeError:
        return None
    if not payload.get("success"):
        return None
    return payload.get("body", {})


def time_remaining_from_status(status):
    policy = status.get("policy")
    state = status.get("state", {})
    if not policy or not policy.get("daily_limit_minutes"):
        return "No limits set"
    usage = state.get("usage_seconds_by_user", {})
    current_user = status.get("current_user")
    if current_user and current_user in usage:
        used_seconds = usage[current_user]
    else:
        used_seconds = max(usage.values(), default=0)
    remaining_seconds = policy["daily_limit_minutes"] * 60 - used_seconds
    remaining_minutes = max(0, int(remaining_seconds / 60))
    return f"{remaining_minutes} minutes"


def current_user_from_status(status):
    return status.get("current_user")

def get_local_ip():
    """Get the local IP address of this machine"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def check_pc_status(ip, port=9999):
    """Check if a PC is locked"""
    status = query_status(ip, port=port)
    if not status:
        return "UNKNOWN"
    state = status.get("state", {})
    return "LOCKED" if state.get("active_lock_reason") else "UNLOCKED"

def get_current_user(ip, port=9999):
    """Get the current username logged in on the kid PC (as reported by the agent)."""
    status = query_status(ip, port=port)
    return current_user_from_status(status) if status else None

def get_usage_limit(ip, port=9999):
    """Get the current usage limit in minutes"""
    status = query_status(ip, port=port)
    policy = status.get("policy") if status else None
    return policy.get("daily_limit_minutes") if policy else None

def get_lock_times(ip, port=9999):
    """Get scheduled lock times"""
    status = query_status(ip, port=port)
    policy = status.get("policy") if status else None
    if not policy:
        return None
    return [window["start"] for window in policy.get("bedtime_windows", [])]

def get_time_remaining(ip, port=9999):
    """Get time remaining until next lock"""
    status = query_status(ip, port=port)
    return time_remaining_from_status(status) if status else None

def scan_for_servers(port=9999):
    """Scan the local network for PCs running the control server"""
    global discovered_pcs, last_scan_time
    local_ip = get_local_ip()
    network = ipaddress.ip_network(f"{local_ip}/24", strict=False)
    discovered_pcs = {}
    
    def check_host(ip):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            result = s.connect_ex((str(ip), port))
            s.close()
            if result == 0:
                # Try to get hostname from the PC directly
                hostname = CUSTOM_PC_NAMES.get(str(ip), None)
                if not hostname:
                    try:
                        # First try to get name from the control server
                        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        s2.settimeout(1)
                        s2.connect((str(ip), port))
                        s2.send(b"GET_NAME")
                        hostname = s2.recv(1024).decode().strip()
                        s2.close()
                        if not hostname:
                            raise Exception("Empty name")
                    except:
                        try:
                            # Fallback to system hostname resolution
                            hostname = socket.gethostbyaddr(str(ip))[0]
                            hostname = hostname.split('.')[0].upper()
                        except:
                            hostname = f"PC at {ip}"
                
                sync_pending_command(str(ip))
                discovered_pcs[str(ip)] = {
                    'hostname': hostname,
                    'status': 'online',
                    'locked': False,  # Will update in separate check
                    'last_seen': datetime.now(),
                    'pending_sync': str(ip) in PENDING_COMMANDS,
                }
        except:
            pass
    
    threads = []
    for ip in network.hosts():
        t = threading.Thread(target=check_host, args=(ip,))
        t.start()
        threads.append(t)
    
    for t in threads:
        t.join()
    
    last_scan_time = datetime.now()
    return discovered_pcs

def send_command(host, command, port=9999):
    """Send a command to the remote PC"""
    body = command_body_from_legacy(command)
    success, response = send_signed_body(host, body, port=port)
    if not success and is_policy_command(body):
        record_pending_command(host, body, response)
    return success, response

@app.route('/')
def index():
    """Main page showing all discovered PCs"""
    # Update lock status and current user for all PCs
    for ip in discovered_pcs:
        status = check_pc_status(ip)
        discovered_pcs[ip]['locked'] = (status == "LOCKED")

        # Get current user
        username = get_current_user(ip)
        if username:
            discovered_pcs[ip]['current_user'] = username
        discovered_pcs[ip]['pending_sync'] = ip in PENDING_COMMANDS

    return render_template('index.html',
                         pcs=discovered_pcs,
                         last_scan=last_scan_time)

@app.route('/scan')
def scan():
    """Scan for PCs and redirect to main page"""
    scan_for_servers()
    return redirect(url_for('index'))

@app.route('/control/<ip>')
def control(ip):
    """Control page for a specific PC"""
    pc_info = discovered_pcs.get(ip, {'hostname': 'Unknown', 'status': 'unknown'})
    sync_pending_command(ip)
    # Check current lock status
    status = check_pc_status(ip)
    pc_info['locked'] = (status == "LOCKED")

    # Get current user
    username = get_current_user(ip)
    if username:
        pc_info['current_user'] = username

    # Get current limits and time remaining (always update, even if None)
    usage_limit = get_usage_limit(ip)
    pc_info['usage_limit'] = usage_limit  # Update even if None to clear old values

    lock_times = get_lock_times(ip)
    pc_info['lock_times'] = lock_times  # Update even if None to clear old values

    time_remaining = get_time_remaining(ip)
    pc_info['time_remaining'] = time_remaining  # Update even if None
    pc_info['pending_sync'] = ip in PENDING_COMMANDS

    return render_template('control.html', ip=ip, pc_info=pc_info)

@app.route('/action', methods=['POST'])
def action():
    """Execute an action on a PC"""
    data = request.json
    ip = data.get('ip')
    action_type = data.get('action')
    
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Action request: {action_type} for {ip}")
    
    if action_type == 'lock':
        success, response = send_command(ip, "LOCK")
        # Update our local status immediately
        if success and ip in discovered_pcs:
            discovered_pcs[ip]['locked'] = True
    elif action_type == 'shutdown':
        success, response = send_command(ip, "SHUTDOWN")
    elif action_type == 'message':
        message = data.get('message', '')
        success, response = send_command(ip, f"MESSAGE:{message}")
    elif action_type == 'set_limit':
        minutes = data.get('minutes', 120)
        success, response = send_command(ip, f"SET_LIMIT:{minutes}")
    elif action_type == 'add_lock_time':
        lock_time = data.get('time', '21:00')
        success, response = send_command(ip, f"ADD_LOCK_TIME:{lock_time}")
    elif action_type == 'clear_usage_limit':
        success, response = send_command(ip, "CLEAR_USAGE_LIMIT")
    elif action_type == 'clear_lock_times':
        success, response = send_command(ip, "CLEAR_LOCK_TIMES")
    elif action_type == 'clear_all':
        success, response = send_command(ip, "CLEAR_ALL")
    else:
        success, response = False, "Unknown action"

    pending = ip in PENDING_COMMANDS
    if pending and not success:
        response = f"{response}; policy change saved as pending sync"

    return jsonify({'success': success, 'response': response, 'pending': pending})


@app.route('/api/pair', methods=['POST'])
def pair_child():
    data = request.get_json(silent=True) or {}
    expected_token = current_pairing_token()
    if not expected_token or data.get("token") != expected_token:
        return jsonify({"success": False, "error": "invalid pairing token"}), 403

    ip = str(data.get("ip") or request.remote_addr or "").strip()
    secret = str(data.get("secret") or "").strip()
    hostname = str(data.get("hostname") or f"PC at {ip}").strip()
    try:
        save_device_secret(ip, secret)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400

    discovered_pcs[ip] = {
        "hostname": hostname or f"PC at {ip}",
        "status": "online",
        "locked": False,
        "last_seen": datetime.now(),
        "pending_sync": ip in PENDING_COMMANDS,
    }
    return jsonify({"success": True, "ip": ip, "hostname": hostname})

# HTML Templates
INDEX_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Kids PC Control Panel</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f0f0f0;
        }
        .container {
            max-width: 600px;
            margin: 0 auto;
        }
        h1 {
            color: #333;
            text-align: center;
        }
        .scan-btn {
            display: block;
            width: 100%;
            padding: 15px;
            margin: 20px 0;
            background-color: #4CAF50;
            color: white;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            cursor: pointer;
        }
        .scan-btn:hover {
            background-color: #45a049;
        }
        .pc-card {
            background: white;
            padding: 20px;
            margin: 10px 0;
            border-radius: 10px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            cursor: pointer;
            transition: transform 0.2s;
        }
        .pc-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 10px rgba(0,0,0,0.15);
        }
        .pc-name {
            font-size: 18px;
            font-weight: bold;
            color: #333;
        }
        .pc-ip {
            color: #666;
            font-size: 14px;
        }
        .status {
            display: inline-block;
            padding: 5px 10px;
            border-radius: 15px;
            font-size: 12px;
            margin-top: 10px;
        }
        .status.online {
            background-color: #4CAF50;
            color: white;
        }
        .status.locked {
            background-color: #ff9800;
            color: white;
        }
        .last-scan {
            text-align: center;
            color: #666;
            font-size: 14px;
            margin-top: 20px;
        }
    </style>
    <script>
        // Auto-refresh every 30 seconds
        setTimeout(function() {
            location.reload();
        }, 30000);
    </script>
</head>
<body>
    <div class="container">
        <h1>👨‍👩‍👧‍👦 Kids PC Control Panel</h1>
        
        <button onclick="location.href='/scan'" class="scan-btn">
            🔍 Scan for PCs
        </button>
        
        {% if pcs %}
            <h2>Available PCs:</h2>
            {% for ip, info in pcs.items() %}
            <div class="pc-card" onclick="location.href='/control/{{ ip }}'">
                <div class="pc-name">💻 {{ info.hostname }}</div>
                <div class="pc-ip">{{ ip }}</div>
                {% if info.get('current_user') %}
                <div class="pc-ip">👤 User: {{ info.current_user }}</div>
                {% endif %}
                {% if info.get('pending_sync') %}
                <div class="pc-ip" style="color: #ff9800;">⏳ Pending policy sync</div>
                {% endif %}
                {% if info.locked %}
                <span class="status locked">🔒 LOCKED</span>
                {% else %}
                <span class="status online">● ONLINE</span>
                {% endif %}
            </div>
            {% endfor %}
        {% else %}
            <p style="text-align: center; color: #666;">
                No PCs found. Click "Scan for PCs" to search.
            </p>
        {% endif %}
        
        {% if last_scan %}
        <div class="last-scan">
            Last scan: {{ last_scan.strftime('%I:%M %p') }}
        </div>
        {% endif %}
    </div>
</body>
</html>
'''

CONTROL_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Control {{ pc_info.hostname }}</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f0f0f0;
        }
        .container {
            max-width: 500px;
            margin: 0 auto;
        }
        h1 {
            color: #333;
            text-align: center;
            font-size: 24px;
        }
        .back-btn {
            display: inline-block;
            padding: 10px 20px;
            background-color: #666;
            color: white;
            text-decoration: none;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .action-group {
            background: white;
            padding: 20px;
            margin: 15px 0;
            border-radius: 10px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .action-title {
            font-size: 18px;
            font-weight: bold;
            margin-bottom: 15px;
            color: #333;
        }
        .btn {
            display: block;
            width: 100%;
            padding: 15px;
            margin: 10px 0;
            border: none;
            border-radius: 5px;
            font-size: 16px;
            cursor: pointer;
            transition: background-color 0.3s;
        }
        .btn-lock {
            background-color: #ff9800;
            color: white;
        }
        .btn-lock:hover {
            background-color: #e68900;
        }
        .btn-shutdown {
            background-color: #f44336;
            color: white;
        }
        .btn-shutdown:hover {
            background-color: #da190b;
        }
        .btn-message {
            background-color: #2196F3;
            color: white;
        }
        .btn-message:hover {
            background-color: #0b7dda;
        }
        .btn-limit {
            background-color: #9c27b0;
            color: white;
        }
        .btn-limit:hover {
            background-color: #7b1fa2;
        }
        input[type="text"], input[type="number"], input[type="time"] {
            width: 100%;
            padding: 10px;
            margin: 10px 0;
            border: 1px solid #ddd;
            border-radius: 5px;
            box-sizing: border-box;
            font-size: 16px;
        }
        .quick-limit {
            display: inline-block;
            padding: 8px 15px;
            margin: 5px;
            background-color: #e0e0e0;
            border-radius: 20px;
            cursor: pointer;
            font-size: 14px;
        }
        .quick-limit:hover {
            background-color: #d0d0d0;
        }
        .status-message {
            padding: 15px;
            margin: 15px 0;
            border-radius: 5px;
            text-align: center;
            display: none;
        }
        .status-message.success {
            background-color: #d4edda;
            color: #155724;
        }
        .status-message.error {
            background-color: #f8d7da;
            color: #721c24;
        }
    </style>
</head>
<body>
    <div class="container">
        <a href="/" class="back-btn">← Back to PCs</a>

        <h1>💻 {{ pc_info.hostname }}</h1>
        <p style="text-align: center; color: #666;">{{ ip }}</p>
        {% if pc_info.get('current_user') %}
        <p style="text-align: center; color: #666;">👤 User: <strong>{{ pc_info.current_user }}</strong></p>
        {% endif %}
        {% if pc_info.get('pending_sync') %}
        <p style="text-align: center; color: #ff9800;">⏳ Pending policy sync. The child PC has not acknowledged the latest change yet.</p>
        {% endif %}

        <!-- Display Current Settings (Always Visible) -->
        <div class="action-group">
            <div class="action-title">📊 Current Settings</div>

            <!-- Daily Usage Limit -->
            <p>⏱️ <strong>Daily Limit:</strong>
            {% if pc_info.get('usage_limit') %}
                {{ pc_info.usage_limit }} minutes ({{ (pc_info.usage_limit / 60)|round(1) }} hours)
                <button onclick="clearLimit('usage')" style="margin-left: 10px; padding: 5px 10px; background-color: #f44336; color: white; border: none; border-radius: 3px; cursor: pointer; font-size: 12px;">❌ Clear</button>
            {% else %}
                <span style="color: #999;">Not set</span>
            {% endif %}
            </p>

            <!-- Time Remaining -->
            {% if pc_info.get('time_remaining') and pc_info.get('time_remaining') != 'No limits set' %}
            <p>⏳ <strong>Time Remaining:</strong> {{ pc_info.time_remaining }}</p>
            {% endif %}

            <!-- Scheduled Locks -->
            <p>🕐 <strong>Scheduled Locks:</strong>
            {% if pc_info.get('lock_times') %}
                {{ pc_info.lock_times|join(', ') }}
                <button onclick="clearLimit('locks')" style="margin-left: 10px; padding: 5px 10px; background-color: #f44336; color: white; border: none; border-radius: 3px; cursor: pointer; font-size: 12px;">❌ Clear</button>
            {% else %}
                <span style="color: #999;">Not set</span>
            {% endif %}
            </p>

            <!-- Clear All Button -->
            {% if pc_info.get('usage_limit') or pc_info.get('lock_times') %}
            <button onclick="clearLimit('all')" style="width: 100%; margin-top: 10px; padding: 10px; background-color: #ff5722; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px;">🗑️ Clear All Limits</button>
            {% endif %}
        </div>

        {% if pc_info.locked %}
        <div class="status-message" style="display: block; background-color: #fff3cd; color: #856404;">
            🔒 This computer is currently LOCKED
        </div>
        {% endif %}
        
        <div id="status-message" class="status-message"></div>
        
        <div class="action-group">
            <div class="action-title">🔒 Quick Actions</div>
            <button class="btn btn-lock" onclick="performAction('lock')">
                Lock Computer Now
            </button>
            <button class="btn btn-shutdown" onclick="confirmAndPerform('shutdown')">
                Shutdown Computer
            </button>
        </div>
        
        <div class="action-group">
            <div class="action-title">💬 Send Message</div>
            <input type="text" id="message-text" placeholder="Type your message here...">
            <button class="btn btn-message" onclick="sendMessage()">
                Send Message
            </button>
        </div>
        
        <div class="action-group">
            <div class="action-title">⏱️ Set Time Limit</div>
            <div>Quick limits:</div>
            <div style="text-align: center;">
                <span class="quick-limit" onclick="setQuickLimit(30)">30 min</span>
                <span class="quick-limit" onclick="setQuickLimit(60)">1 hour</span>
                <span class="quick-limit" onclick="setQuickLimit(120)">2 hours</span>
                <span class="quick-limit" onclick="setQuickLimit(180)">3 hours</span>
            </div>
            <input type="number" id="limit-minutes" placeholder="Or enter minutes...">
            <button class="btn btn-limit" onclick="setLimit()">
                Set Time Limit
            </button>
        </div>
        
        <div class="action-group">
            <div class="action-title">🕐 Set Lock Time</div>
            <input type="time" id="lock-time" value="21:00">
            <button class="btn btn-limit" onclick="setLockTime()">
                Set Bedtime Lock
            </button>
        </div>
    </div>
    
    <script>
        function showStatus(message, isSuccess) {
            const statusEl = document.getElementById('status-message');
            statusEl.textContent = message;
            statusEl.className = 'status-message ' + (isSuccess ? 'success' : 'error');
            statusEl.style.display = 'block';
            setTimeout(() => {
                statusEl.style.display = 'none';
            }, 3000);
        }
        
        function performAction(action) {
            fetch('/action', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    ip: '{{ ip }}',
                    action: action
                })
            })
            .then(response => response.json())
            .then(data => {
                showStatus(data.response, data.success);
                // Reload page after 2 seconds to update lock status
                if (data.success && (action === 'lock' || action === 'shutdown')) {
                    setTimeout(() => {
                        location.reload();
                    }, 2000);
                }
            });
        }
        
        function confirmAndPerform(action) {
            if (confirm('Are you sure you want to shutdown this computer?')) {
                performAction(action);
            }
        }
        
        function sendMessage() {
            const message = document.getElementById('message-text').value;
            if (!message) {
                showStatus('Please enter a message', false);
                return;
            }
            
            fetch('/action', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    ip: '{{ ip }}',
                    action: 'message',
                    message: message
                })
            })
            .then(response => response.json())
            .then(data => {
                showStatus(data.response, data.success);
                if (data.success) {
                    document.getElementById('message-text').value = '';
                }
            });
        }
        
        function setQuickLimit(minutes) {
            document.getElementById('limit-minutes').value = minutes;
            setLimit();
        }
        
        function setLimit() {
            const minutes = document.getElementById('limit-minutes').value;
            if (!minutes) {
                showStatus('Please enter time in minutes', false);
                return;
            }

            fetch('/action', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    ip: '{{ ip }}',
                    action: 'set_limit',
                    minutes: parseInt(minutes)
                })
            })
            .then(response => response.json())
            .then(data => {
                showStatus(data.response, data.success);
                if (data.success) {
                    // Reload page after 1 second to show updated settings
                    setTimeout(() => {
                        location.reload();
                    }, 1000);
                }
            });
        }
        
        function setLockTime() {
            const time = document.getElementById('lock-time').value;
            if (!time) {
                showStatus('Please select a time', false);
                return;
            }

            fetch('/action', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    ip: '{{ ip }}',
                    action: 'add_lock_time',
                    time: time
                })
            })
            .then(response => response.json())
            .then(data => {
                showStatus(data.response, data.success);
                if (data.success) {
                    // Reload page after 1 second to show updated settings
                    setTimeout(() => {
                        location.reload();
                    }, 1000);
                }
            });
        }

        function clearLimit(type) {
            let confirmMsg, action;

            if (type === 'usage') {
                confirmMsg = 'Clear the daily usage limit?';
                action = 'clear_usage_limit';
            } else if (type === 'locks') {
                confirmMsg = 'Clear all scheduled lock times?';
                action = 'clear_lock_times';
            } else if (type === 'all') {
                confirmMsg = 'Clear ALL limits and scheduled locks?';
                action = 'clear_all';
            }

            if (!confirm(confirmMsg)) {
                return;
            }

            fetch('/action', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    ip: '{{ ip }}',
                    action: action
                })
            })
            .then(response => response.json())
            .then(data => {
                showStatus(data.response, data.success);
                if (data.success) {
                    // Reload page after 1 second to show updated settings
                    setTimeout(() => {
                        location.reload();
                    }, 1000);
                }
            });
        }
    </script>
</body>
</html>
'''

# Create template files
import os
os.makedirs('templates', exist_ok=True)

with open('templates/index.html', 'w', encoding='utf-8') as f:
    f.write(INDEX_TEMPLATE)

with open('templates/control.html', 'w', encoding='utf-8') as f:
    f.write(CONTROL_TEMPLATE)

if __name__ == '__main__':
    # Do initial scan
    print("Performing initial scan...")
    scan_for_servers()
    
    # Start the web server
    print(f"\nWeb Control Panel starting...")
    print(f"Access from your phone at: http://{get_local_ip()}:5000")
    print(f"Or from this PC at: http://localhost:5000")
    
    app.run(host='0.0.0.0', port=5000, debug=False)
