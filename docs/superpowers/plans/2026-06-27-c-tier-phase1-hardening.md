# C-Tier Phase 1 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the hard foundation for offline-capable Windows parental control: local policy enforcement, service/helper split, authenticated commands, service recovery, ACL/firewall hardening, and remote Windows validation.

**Architecture:** The child PC runs a trusted Windows service that owns policy, state, authentication, enforcement, and logs. A per-user helper handles desktop interaction and lock requests. The parent web panel sends authenticated JSON commands and treats offline devices as unsynced rather than inactive.

**Tech Stack:** Python 3.10+, Flask, pytest, stdlib `hmac`/`hashlib`/`json`/`socket`, Windows Service integration through pywin32 on Windows, PowerShell for ACL/firewall/service installation checks.

---

## Scope

This plan implements Phase 1 from `docs/superpowers/specs/2026-06-27-c-tier-parental-control-hardening-design.md`.

In scope:

- Local policy and state files.
- Atomic persistence.
- Offline enforcement calculations.
- HMAC-authenticated JSON command envelope.
- TCP service command server.
- Helper heartbeat and lock request protocol.
- Windows service install script.
- ACL and firewall setup.
- Parent web-panel command client changes.
- Remote test checklist for `192.168.10.251`.

Out of scope for Phase 1:

- Full event-log UI.
- Polished multi-device management.
- Windows policy restrictions such as disabling Task Manager or PowerShell.
- Cloud sync.
- Browser history, screenshots, keylogging, or stealth behavior.

## File Structure

- Create `tests/test_policy.py`: unit tests for policy validation and version handling.
- Create `tests/test_state_store.py`: unit tests for atomic JSON persistence and daily usage reset.
- Create `tests/test_auth.py`: unit tests for HMAC signing, timestamp validation, and nonce replay rejection.
- Create `tests/test_enforcement.py`: unit tests for remaining-time and lock-decision calculations.
- Create `tests/test_command_server.py`: unit tests for authenticated command dispatch without binding public ports.
- Create `src/policy.py`: policy dataclass, validation, serialization, and default policy.
- Create `src/state_store.py`: atomic JSON read/write and state defaults.
- Create `src/agent_auth.py`: signed command envelope and verification helpers.
- Create `src/enforcement.py`: pure policy/state enforcement engine.
- Create `src/command_server.py`: authenticated TCP JSON server.
- Create `src/helper_ipc.py`: localhost IPC message schema for service-to-helper messages.
- Create `src/helper.py`: interactive session helper process.
- Create `src/kid_service.py`: service orchestration entry point.
- Create `src/windows_service.py`: pywin32 Windows service wrapper.
- Create `src/windows_hardening.py`: ACL, firewall, and service-recovery helper commands.
- Create `scripts/install_service.py`: admin installer for child PCs.
- Create `scripts/uninstall_service.py`: token-gated uninstaller.
- Modify `src/web_panel.py`: replace raw string commands with authenticated JSON client calls.
- Modify `requirements.txt`: include Windows-only pywin32 and pytest for development.
- Create `docs/remote-windows-test.md`: exact remote validation checklist.

## Remote Test Prerequisites

The test Windows host is `192.168.10.251`. Current network probe shows RDP `3389` is open, while WinRM `5985/5986`, SSH `22`, SMB `445`, RPC `135`, and current agent port `9999` are closed.

Before automated remote install/testing, enable one automation channel:

- Preferred: WinRM over HTTP on the private LAN.
- Alternative: OpenSSH Server on Windows.
- Manual fallback: RDP session and run commands by hand.

Preferred WinRM setup on the Windows test machine from an elevated PowerShell:

```powershell
Set-ExecutionPolicy RemoteSigned -Scope LocalMachine -Force
Enable-PSRemoting -Force
Set-Item WSMan:\localhost\Service\AllowUnencrypted $true
Set-Item WSMan:\localhost\Service\Auth\Basic $true
New-NetFirewallRule -DisplayName "WinRM 5985" -Direction Inbound -Protocol TCP -LocalPort 5985 -Action Allow
```

On this Linux development machine, install or provide one of these clients before remote automation:

```bash
pwsh -NoLogo -Command '$PSVersionTable.PSVersion'
# or
evil-winrm -h
```

Credential handling rule: never write the password to repository files, docs, shell history, screenshots, or commits. Use an interactive prompt or transient environment variable for one command session only.

## Task 1: Policy Model

**Files:**
- Create: `src/policy.py`
- Test: `tests/test_policy.py`

- [ ] **Step 1: Write the failing policy tests**

```python
# tests/test_policy.py
import pytest

from src.policy import BedtimeWindow, Policy, PolicyValidationError


def test_policy_accepts_valid_daily_limit_and_bedtime():
    policy = Policy(
        device_id="kid-pc-1",
        policy_version=3,
        daily_limit_minutes=90,
        bedtime_windows=[BedtimeWindow(start="21:00", end="07:00")],
        monitored_users=["kid"],
        exempt_users=[],
        warning_minutes=[15, 5, 1],
        temporary_extensions={},
        parent_panel_allowed_ips=["192.168.10.10"],
        updated_at="2026-06-27T13:00:00+08:00",
    )

    policy.validate()
    assert policy.to_dict()["policy_version"] == 3


def test_policy_rejects_overlap_between_monitored_and_exempt_users():
    policy = Policy(
        device_id="kid-pc-1",
        policy_version=1,
        daily_limit_minutes=60,
        bedtime_windows=[],
        monitored_users=["kid"],
        exempt_users=["kid"],
        warning_minutes=[15, 5, 1],
        temporary_extensions={},
        parent_panel_allowed_ips=[],
        updated_at="2026-06-27T13:00:00+08:00",
    )

    with pytest.raises(PolicyValidationError, match="same user"):
        policy.validate()


def test_policy_rejects_invalid_bedtime_clock_value():
    with pytest.raises(PolicyValidationError, match="HH:MM"):
        BedtimeWindow(start="25:00", end="07:00").validate()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python -m pytest tests/test_policy.py -v
```

Expected: fail because `src.policy` does not exist.

- [ ] **Step 3: Implement the policy model**

```python
# src/policy.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import ipaddress
import re
from typing import Any


TIME_RE = re.compile(r"^\d{2}:\d{2}$")


class PolicyValidationError(ValueError):
    """Raised when a policy cannot be safely enforced."""


@dataclass(frozen=True)
class BedtimeWindow:
    start: str
    end: str

    def validate(self) -> None:
        for value in (self.start, self.end):
            if not TIME_RE.match(value):
                raise PolicyValidationError("Bedtime values must use HH:MM format")
            hour, minute = map(int, value.split(":"))
            if hour > 23 or minute > 59:
                raise PolicyValidationError("Bedtime values must use valid HH:MM times")

    def to_dict(self) -> dict[str, str]:
        return {"start": self.start, "end": self.end}


@dataclass(frozen=True)
class Policy:
    device_id: str
    policy_version: int
    daily_limit_minutes: int | None
    bedtime_windows: list[BedtimeWindow] = field(default_factory=list)
    monitored_users: list[str] = field(default_factory=list)
    exempt_users: list[str] = field(default_factory=list)
    warning_minutes: list[int] = field(default_factory=lambda: [15, 5, 1])
    temporary_extensions: dict[str, int] = field(default_factory=dict)
    parent_panel_allowed_ips: list[str] = field(default_factory=list)
    updated_at: str = ""

    def validate(self) -> None:
        if not self.device_id:
            raise PolicyValidationError("device_id is required")
        if self.policy_version < 1:
            raise PolicyValidationError("policy_version must be positive")
        if self.daily_limit_minutes is not None and self.daily_limit_minutes < 1:
            raise PolicyValidationError("daily_limit_minutes must be positive")
        overlap = set(self.monitored_users) & set(self.exempt_users)
        if overlap:
            raise PolicyValidationError("The same user cannot be monitored and exempt")
        for warning in self.warning_minutes:
            if warning < 1:
                raise PolicyValidationError("warning_minutes must be positive")
        for window in self.bedtime_windows:
            window.validate()
        for ip in self.parent_panel_allowed_ips:
            ipaddress.ip_address(ip)
        if self.updated_at:
            datetime.fromisoformat(self.updated_at)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["bedtime_windows"] = [window.to_dict() for window in self.bedtime_windows]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Policy":
        policy = cls(
            device_id=data["device_id"],
            policy_version=int(data["policy_version"]),
            daily_limit_minutes=data.get("daily_limit_minutes"),
            bedtime_windows=[BedtimeWindow(**item) for item in data.get("bedtime_windows", [])],
            monitored_users=list(data.get("monitored_users", [])),
            exempt_users=list(data.get("exempt_users", [])),
            warning_minutes=list(data.get("warning_minutes", [15, 5, 1])),
            temporary_extensions=dict(data.get("temporary_extensions", {})),
            parent_panel_allowed_ips=list(data.get("parent_panel_allowed_ips", [])),
            updated_at=data.get("updated_at", ""),
        )
        policy.validate()
        return policy
```

- [ ] **Step 4: Run policy tests and verify they pass**

Run:

```bash
python -m pytest tests/test_policy.py -v
```

Expected: all `tests/test_policy.py` tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/policy.py tests/test_policy.py
git commit -m "feat: add enforceable policy model"
```

## Task 2: Atomic State Store

**Files:**
- Create: `src/state_store.py`
- Test: `tests/test_state_store.py`

- [ ] **Step 1: Write failing state persistence tests**

```python
# tests/test_state_store.py
from datetime import date

from src.state_store import AgentState, StateStore


def test_state_store_round_trips_json(tmp_path):
    store = StateStore(tmp_path / "state.json")
    state = AgentState(
        current_date="2026-06-27",
        usage_seconds_by_user={"kid": 120},
        active_lock_reason=None,
        last_policy_version=7,
        unsent_event_cursor=4,
        helper_last_seen_at=None,
    )

    store.save(state)

    assert store.load() == state


def test_state_store_returns_default_when_missing(tmp_path):
    state = StateStore(tmp_path / "missing.json").load()

    assert state.current_date == date.today().isoformat()
    assert state.usage_seconds_by_user == {}
    assert state.last_policy_version == 0


def test_state_rolls_usage_on_new_day():
    state = AgentState(
        current_date="2026-06-26",
        usage_seconds_by_user={"kid": 3600},
        active_lock_reason="limit",
        last_policy_version=2,
        unsent_event_cursor=1,
        helper_last_seen_at="2026-06-26T20:00:00+08:00",
    )

    rolled = state.for_today(today="2026-06-27")

    assert rolled.current_date == "2026-06-27"
    assert rolled.usage_seconds_by_user == {}
    assert rolled.active_lock_reason is None
    assert rolled.last_policy_version == 2
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
python -m pytest tests/test_state_store.py -v
```

Expected: fail because `src.state_store` does not exist.

- [ ] **Step 3: Implement atomic state persistence**

```python
# src/state_store.py
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import json
from pathlib import Path
import tempfile


@dataclass(frozen=True)
class AgentState:
    current_date: str
    usage_seconds_by_user: dict[str, int]
    active_lock_reason: str | None
    last_policy_version: int
    unsent_event_cursor: int
    helper_last_seen_at: str | None

    @classmethod
    def default(cls) -> "AgentState":
        return cls(
            current_date=date.today().isoformat(),
            usage_seconds_by_user={},
            active_lock_reason=None,
            last_policy_version=0,
            unsent_event_cursor=0,
            helper_last_seen_at=None,
        )

    @classmethod
    def from_dict(cls, data: dict) -> "AgentState":
        return cls(
            current_date=data["current_date"],
            usage_seconds_by_user={k: int(v) for k, v in data.get("usage_seconds_by_user", {}).items()},
            active_lock_reason=data.get("active_lock_reason"),
            last_policy_version=int(data.get("last_policy_version", 0)),
            unsent_event_cursor=int(data.get("unsent_event_cursor", 0)),
            helper_last_seen_at=data.get("helper_last_seen_at"),
        )

    def to_dict(self) -> dict:
        return asdict(self)

    def for_today(self, today: str | None = None) -> "AgentState":
        today_value = today or date.today().isoformat()
        if self.current_date == today_value:
            return self
        return AgentState(
            current_date=today_value,
            usage_seconds_by_user={},
            active_lock_reason=None,
            last_policy_version=self.last_policy_version,
            unsent_event_cursor=self.unsent_event_cursor,
            helper_last_seen_at=None,
        )


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> AgentState:
        if not self.path.exists():
            return AgentState.default()
        with self.path.open("r", encoding="utf-8") as handle:
            return AgentState.from_dict(json.load(handle)).for_today()

    def save(self, state: AgentState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(self.path.parent),
            delete=False,
        ) as handle:
            json.dump(state.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_name = handle.name
        Path(temp_name).replace(self.path)
```

- [ ] **Step 4: Run state tests and verify they pass**

Run:

```bash
python -m pytest tests/test_state_store.py -v
```

Expected: all `tests/test_state_store.py` tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/state_store.py tests/test_state_store.py
git commit -m "feat: add atomic agent state store"
```

## Task 3: Authenticated Command Envelope

**Files:**
- Create: `src/agent_auth.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Write failing auth tests**

```python
# tests/test_auth.py
import time

import pytest

from src.agent_auth import AuthError, NonceStore, sign_message, verify_message


def test_signed_message_verifies_with_shared_secret():
    secret = b"dev-secret"
    envelope = sign_message({"command": "status"}, secret, now=1000, nonce="abc")

    body = verify_message(envelope, secret, now=1001, nonce_store=NonceStore())

    assert body == {"command": "status"}


def test_rejects_replayed_nonce():
    secret = b"dev-secret"
    store = NonceStore()
    envelope = sign_message({"command": "status"}, secret, now=1000, nonce="abc")

    verify_message(envelope, secret, now=1001, nonce_store=store)

    with pytest.raises(AuthError, match="replay"):
        verify_message(envelope, secret, now=1001, nonce_store=store)


def test_rejects_stale_timestamp():
    secret = b"dev-secret"
    envelope = sign_message({"command": "status"}, secret, now=1000, nonce="abc")

    with pytest.raises(AuthError, match="stale"):
        verify_message(envelope, secret, now=2000, nonce_store=NonceStore(), max_skew_seconds=60)


def test_rejects_tampered_body():
    secret = b"dev-secret"
    envelope = sign_message({"command": "status"}, secret, now=int(time.time()), nonce="abc")
    envelope["body"]["command"] = "clear_all"

    with pytest.raises(AuthError, match="signature"):
        verify_message(envelope, secret, now=int(time.time()), nonce_store=NonceStore())
```

- [ ] **Step 2: Run auth tests and verify they fail**

Run:

```bash
python -m pytest tests/test_auth.py -v
```

Expected: fail because `src.agent_auth` does not exist.

- [ ] **Step 3: Implement HMAC signing and verification**

```python
# src/agent_auth.py
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class AuthError(ValueError):
    """Raised when a command envelope fails authentication."""


@dataclass
class NonceStore:
    seen: set[str] = field(default_factory=set)

    def accept(self, nonce: str) -> None:
        if nonce in self.seen:
            raise AuthError("replay detected")
        self.seen.add(nonce)


def _canonical_payload(body: dict[str, Any], timestamp: int, nonce: str) -> bytes:
    return json.dumps(
        {"body": body, "timestamp": timestamp, "nonce": nonce},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _signature(body: dict[str, Any], secret: bytes, timestamp: int, nonce: str) -> str:
    return hmac.new(secret, _canonical_payload(body, timestamp, nonce), hashlib.sha256).hexdigest()


def sign_message(
    body: dict[str, Any],
    secret: bytes,
    now: int | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    timestamp = int(now if now is not None else time.time())
    nonce_value = nonce or uuid.uuid4().hex
    return {
        "body": body,
        "timestamp": timestamp,
        "nonce": nonce_value,
        "signature": _signature(body, secret, timestamp, nonce_value),
    }


def verify_message(
    envelope: dict[str, Any],
    secret: bytes,
    now: int | None,
    nonce_store: NonceStore,
    max_skew_seconds: int = 300,
) -> dict[str, Any]:
    timestamp = int(envelope["timestamp"])
    current_time = int(now if now is not None else time.time())
    if abs(current_time - timestamp) > max_skew_seconds:
        raise AuthError("stale timestamp")
    body = envelope["body"]
    nonce = envelope["nonce"]
    expected = _signature(body, secret, timestamp, nonce)
    if not hmac.compare_digest(expected, envelope.get("signature", "")):
        raise AuthError("invalid signature")
    nonce_store.accept(nonce)
    return body
```

- [ ] **Step 4: Run auth tests and verify they pass**

Run:

```bash
python -m pytest tests/test_auth.py -v
```

Expected: all `tests/test_auth.py` tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent_auth.py tests/test_auth.py
git commit -m "feat: authenticate agent commands"
```

## Task 4: Offline Enforcement Engine

**Files:**
- Create: `src/enforcement.py`
- Test: `tests/test_enforcement.py`

- [ ] **Step 1: Write failing enforcement tests**

```python
# tests/test_enforcement.py
from datetime import datetime, timezone

from src.enforcement import EnforcementDecision, evaluate_policy
from src.policy import BedtimeWindow, Policy
from src.state_store import AgentState


def make_policy(limit=60):
    return Policy(
        device_id="kid-pc-1",
        policy_version=1,
        daily_limit_minutes=limit,
        bedtime_windows=[BedtimeWindow(start="21:00", end="07:00")],
        monitored_users=["kid"],
        exempt_users=[],
        warning_minutes=[15, 5, 1],
        temporary_extensions={},
        parent_panel_allowed_ips=[],
        updated_at="2026-06-27T00:00:00+00:00",
    )


def make_state(seconds):
    return AgentState(
        current_date="2026-06-27",
        usage_seconds_by_user={"kid": seconds},
        active_lock_reason=None,
        last_policy_version=1,
        unsent_event_cursor=0,
        helper_last_seen_at=None,
    )


def test_locks_when_daily_limit_reached_offline():
    decision = evaluate_policy(
        policy=make_policy(limit=60),
        state=make_state(seconds=3600),
        username="kid",
        now=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
    )

    assert decision == EnforcementDecision(should_lock=True, reason="daily_limit", warning_minutes=None)


def test_warns_when_limit_is_near():
    decision = evaluate_policy(
        policy=make_policy(limit=60),
        state=make_state(seconds=55 * 60),
        username="kid",
        now=datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
    )

    assert decision.should_lock is False
    assert decision.warning_minutes == 5


def test_locks_during_bedtime_window_that_crosses_midnight():
    decision = evaluate_policy(
        policy=make_policy(limit=999),
        state=make_state(seconds=0),
        username="kid",
        now=datetime(2026, 6, 27, 22, 0, tzinfo=timezone.utc),
    )

    assert decision.should_lock is True
    assert decision.reason == "bedtime"


def test_exempt_user_is_not_locked():
    policy = Policy(
        device_id="kid-pc-1",
        policy_version=1,
        daily_limit_minutes=1,
        bedtime_windows=[BedtimeWindow(start="21:00", end="07:00")],
        monitored_users=[],
        exempt_users=["parent"],
        warning_minutes=[15, 5, 1],
        temporary_extensions={},
        parent_panel_allowed_ips=[],
        updated_at="2026-06-27T00:00:00+00:00",
    )

    decision = evaluate_policy(
        policy=policy,
        state=make_state(seconds=9999),
        username="parent",
        now=datetime(2026, 6, 27, 22, 0, tzinfo=timezone.utc),
    )

    assert decision.should_lock is False
    assert decision.reason is None
```

- [ ] **Step 2: Run enforcement tests and verify they fail**

Run:

```bash
python -m pytest tests/test_enforcement.py -v
```

Expected: fail because `src.enforcement` does not exist.

- [ ] **Step 3: Implement pure enforcement decisions**

```python
# src/enforcement.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from src.policy import Policy
from src.state_store import AgentState


@dataclass(frozen=True)
class EnforcementDecision:
    should_lock: bool
    reason: str | None
    warning_minutes: int | None


def _parse_clock(value: str) -> time:
    hour, minute = map(int, value.split(":"))
    return time(hour=hour, minute=minute)


def _inside_window(now_time: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= now_time < end
    return now_time >= start or now_time < end


def _user_is_monitored(policy: Policy, username: str) -> bool:
    if policy.monitored_users:
        return username in policy.monitored_users
    if policy.exempt_users:
        return username not in policy.exempt_users
    return True


def evaluate_policy(
    policy: Policy,
    state: AgentState,
    username: str,
    now: datetime,
) -> EnforcementDecision:
    if not _user_is_monitored(policy, username):
        return EnforcementDecision(False, None, None)

    now_time = now.time().replace(tzinfo=None)
    for window in policy.bedtime_windows:
        if _inside_window(now_time, _parse_clock(window.start), _parse_clock(window.end)):
            return EnforcementDecision(True, "bedtime", None)

    if policy.daily_limit_minutes is not None:
        used_seconds = state.usage_seconds_by_user.get(username, 0)
        limit_seconds = policy.daily_limit_minutes * 60
        remaining_seconds = limit_seconds - used_seconds
        if remaining_seconds <= 0:
            return EnforcementDecision(True, "daily_limit", None)
        remaining_minutes = max(1, int(remaining_seconds / 60))
        matching_warnings = [
            warning for warning in sorted(policy.warning_minutes, reverse=True)
            if remaining_minutes <= warning
        ]
        if matching_warnings:
            return EnforcementDecision(False, None, min(matching_warnings))

    return EnforcementDecision(False, None, None)
```

- [ ] **Step 4: Run enforcement tests and verify they pass**

Run:

```bash
python -m pytest tests/test_enforcement.py -v
```

Expected: all `tests/test_enforcement.py` tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/enforcement.py tests/test_enforcement.py
git commit -m "feat: evaluate offline enforcement decisions"
```

## Task 5: Authenticated Command Server

**Files:**
- Create: `src/command_server.py`
- Test: `tests/test_command_server.py`

- [ ] **Step 1: Write failing command dispatch tests**

```python
# tests/test_command_server.py
import pytest

from src.agent_auth import NonceStore, sign_message
from src.command_server import CommandDispatcher


def test_dispatcher_accepts_authenticated_status_command():
    calls = []
    dispatcher = CommandDispatcher(
        secret=b"dev-secret",
        nonce_store=NonceStore(),
        handlers={"status": lambda body: calls.append(body) or {"ok": True}},
        now=lambda: 1000,
    )
    envelope = sign_message({"command": "status"}, b"dev-secret", now=1000, nonce="abc")

    response = dispatcher.dispatch(envelope)

    assert response == {"ok": True}
    assert calls == [{"command": "status"}]


def test_dispatcher_rejects_unknown_command():
    dispatcher = CommandDispatcher(
        secret=b"dev-secret",
        nonce_store=NonceStore(),
        handlers={},
        now=lambda: 1000,
    )
    envelope = sign_message({"command": "clear_all"}, b"dev-secret", now=1000, nonce="abc")

    with pytest.raises(ValueError, match="unknown command"):
        dispatcher.dispatch(envelope)
```

- [ ] **Step 2: Run command server tests and verify they fail**

Run:

```bash
python -m pytest tests/test_command_server.py -v
```

Expected: fail because `src.command_server` does not exist.

- [ ] **Step 3: Implement dispatch without binding sockets**

```python
# src/command_server.py
from __future__ import annotations

import json
import socketserver
import time
from typing import Any, Callable

from src.agent_auth import NonceStore, verify_message


Handler = Callable[[dict[str, Any]], dict[str, Any]]


class CommandDispatcher:
    def __init__(
        self,
        secret: bytes,
        nonce_store: NonceStore,
        handlers: dict[str, Handler],
        now: Callable[[], int] | None = None,
    ):
        self.secret = secret
        self.nonce_store = nonce_store
        self.handlers = handlers
        self.now = now or (lambda: int(time.time()))

    def dispatch(self, envelope: dict[str, Any]) -> dict[str, Any]:
        body = verify_message(envelope, self.secret, self.now(), self.nonce_store)
        command = body.get("command")
        if command not in self.handlers:
            raise ValueError(f"unknown command: {command}")
        return self.handlers[command](body)


class JsonCommandHandler(socketserver.StreamRequestHandler):
    dispatcher: CommandDispatcher

    def handle(self) -> None:
        raw = self.rfile.readline(1024 * 1024)
        envelope = json.loads(raw.decode("utf-8"))
        try:
            response = {"success": True, "body": self.dispatcher.dispatch(envelope)}
        except Exception as exc:
            response = {"success": False, "error": str(exc)}
        self.wfile.write((json.dumps(response) + "\n").encode("utf-8"))


def build_server(host: str, port: int, dispatcher: CommandDispatcher) -> socketserver.ThreadingTCPServer:
    class BoundHandler(JsonCommandHandler):
        pass

    BoundHandler.dispatcher = dispatcher
    return socketserver.ThreadingTCPServer((host, port), BoundHandler)
```

- [ ] **Step 4: Run command server tests and verify they pass**

Run:

```bash
python -m pytest tests/test_command_server.py -v
```

Expected: all `tests/test_command_server.py` tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/command_server.py tests/test_command_server.py
git commit -m "feat: add authenticated command dispatcher"
```

## Task 6: Service Orchestrator And Helper IPC

**Files:**
- Create: `src/helper_ipc.py`
- Create: `src/kid_service.py`
- Create: `src/helper.py`
- Test: extend `tests/test_enforcement.py`

- [ ] **Step 1: Add service orchestration test**

Append to `tests/test_enforcement.py`:

```python
from src.kid_service import KidServiceCore


def test_service_core_requests_lock_when_policy_says_lock(tmp_path):
    sent_messages = []
    policy_path = tmp_path / "policy.json"
    state_path = tmp_path / "state.json"
    policy = make_policy(limit=1)
    policy_path.write_text(__import__("json").dumps(policy.to_dict()), encoding="utf-8")

    core = KidServiceCore(
        policy_path=policy_path,
        state_path=state_path,
        username_provider=lambda: "kid",
        now_provider=lambda: datetime(2026, 6, 27, 12, 0, tzinfo=timezone.utc),
        helper_sender=sent_messages.append,
    )
    core.state = make_state(seconds=60)

    core.tick()

    assert sent_messages[-1] == {"type": "lock", "reason": "daily_limit"}
```

- [ ] **Step 2: Run the service orchestration test and verify it fails**

Run:

```bash
python -m pytest tests/test_enforcement.py::test_service_core_requests_lock_when_policy_says_lock -v
```

Expected: fail because `src.kid_service` does not exist.

- [ ] **Step 3: Implement helper IPC schema and service core**

```python
# src/helper_ipc.py
from __future__ import annotations

import json
from typing import Any


def encode_message(message_type: str, **payload: Any) -> str:
    return json.dumps({"type": message_type, **payload}, sort_keys=True)


def decode_message(raw: str) -> dict[str, Any]:
    message = json.loads(raw)
    if "type" not in message:
        raise ValueError("IPC message missing type")
    return message
```

```python
# src/kid_service.py
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import time
from typing import Callable

from src.enforcement import evaluate_policy
from src.policy import Policy
from src.state_store import AgentState, StateStore


class KidServiceCore:
    def __init__(
        self,
        policy_path: str | Path,
        state_path: str | Path,
        username_provider: Callable[[], str],
        now_provider: Callable[[], datetime],
        helper_sender: Callable[[dict], None],
    ):
        self.policy_path = Path(policy_path)
        self.state_store = StateStore(state_path)
        self.username_provider = username_provider
        self.now_provider = now_provider
        self.helper_sender = helper_sender
        self.state = self.state_store.load()

    def load_policy(self) -> Policy | None:
        if not self.policy_path.exists():
            return None
        return Policy.from_dict(json.loads(self.policy_path.read_text(encoding="utf-8")))

    def tick(self) -> None:
        policy = self.load_policy()
        if policy is None:
            return
        username = self.username_provider()
        self.state = self.state.for_today()
        decision = evaluate_policy(policy, self.state, username, self.now_provider())
        if decision.should_lock:
            self.helper_sender({"type": "lock", "reason": decision.reason})
            self.state = AgentState(
                current_date=self.state.current_date,
                usage_seconds_by_user=self.state.usage_seconds_by_user,
                active_lock_reason=decision.reason,
                last_policy_version=policy.policy_version,
                unsent_event_cursor=self.state.unsent_event_cursor,
                helper_last_seen_at=self.state.helper_last_seen_at,
            )
        elif decision.warning_minutes is not None:
            self.helper_sender({"type": "warning", "minutes": decision.warning_minutes})
        self.state_store.save(self.state)

    def run_forever(self, interval_seconds: int = 1) -> None:
        while True:
            self.tick()
            time.sleep(interval_seconds)
```

```python
# src/helper.py
from __future__ import annotations

import ctypes
import sys
import tkinter as tk
from tkinter import messagebox

from src.helper_ipc import decode_message


def lock_workstation() -> None:
    ctypes.windll.user32.LockWorkStation()


def show_warning(minutes: int) -> None:
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.after(60000, root.destroy)
    messagebox.showwarning("Kid PC Monitor", f"Computer will lock in {minutes} minute(s).")
    root.destroy()


def handle_message(message: dict) -> None:
    if message["type"] == "lock":
        lock_workstation()
    elif message["type"] == "warning":
        show_warning(int(message["minutes"]))
    else:
        raise ValueError(f"unknown helper message: {message['type']}")


def main() -> int:
    for line in sys.stdin:
        handle_message(decode_message(line))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run service orchestration tests**

Run:

```bash
python -m pytest tests/test_enforcement.py -v
```

Expected: all enforcement and service-core tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/helper_ipc.py src/kid_service.py src/helper.py tests/test_enforcement.py
git commit -m "feat: split service core from session helper"
```

## Task 7: Windows Service Installer And Hardening

**Files:**
- Create: `src/windows_service.py`
- Create: `src/windows_hardening.py`
- Create: `scripts/install_service.py`
- Create: `scripts/uninstall_service.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Add Windows dependencies**

Modify `requirements.txt` to include:

```text
Flask>=2.0.0
pywin32>=306; platform_system == "Windows"
pytest>=8.0.0
```

- [ ] **Step 2: Create Windows hardening helpers**

```python
# src/windows_hardening.py
from __future__ import annotations

import subprocess
from pathlib import Path


SERVICE_NAME = "KidPCMonitorService"
PROGRAM_DIR = Path(r"C:\Program Files\KidPCMonitor")
DATA_DIR = Path(r"C:\ProgramData\KidPCMonitor")


def run_powershell(script: str) -> None:
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
    )


def apply_acls() -> None:
    script = rf"""
    New-Item -ItemType Directory -Force -Path "{PROGRAM_DIR}" | Out-Null
    New-Item -ItemType Directory -Force -Path "{DATA_DIR}" | Out-Null
    icacls "{PROGRAM_DIR}" /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" "Users:(OI)(CI)RX" | Out-Null
    icacls "{DATA_DIR}" /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" "Users:(OI)(CI)RX" | Out-Null
    """
    run_powershell(script)


def configure_firewall(parent_ip: str | None) -> None:
    remote_filter = f'-RemoteAddress "{parent_ip}"' if parent_ip else ""
    script = rf"""
    Remove-NetFirewallRule -DisplayName "Kid PC Monitor Agent" -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName "Kid PC Monitor Agent" -Direction Inbound -Protocol TCP -LocalPort 9999 {remote_filter} -Action Allow | Out-Null
    """
    run_powershell(script)


def configure_service_recovery() -> None:
    subprocess.run(
        ["sc.exe", "failure", SERVICE_NAME, "reset=", "86400", "actions=", "restart/60000/restart/60000/restart/60000"],
        check=True,
    )
```

- [ ] **Step 3: Create pywin32 service wrapper**

```python
# src/windows_service.py
from __future__ import annotations

import servicemanager
import win32event
import win32service
import win32serviceutil


class KidPCMonitorWindowsService(win32serviceutil.ServiceFramework):
    _svc_name_ = "KidPCMonitorService"
    _svc_display_name_ = "Kid PC Monitor Service"
    _svc_description_ = "Enforces local kid PC time limits and authenticated parent commands."

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.running = True

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.running = False
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg("Kid PC Monitor Service starting")
        while self.running:
            win32event.WaitForSingleObject(self.stop_event, 1000)
        servicemanager.LogInfoMsg("Kid PC Monitor Service stopped")


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(KidPCMonitorWindowsService)
```

- [ ] **Step 4: Create installer script**

```python
# scripts/install_service.py
from __future__ import annotations

import argparse
import secrets
import shutil
import subprocess
from pathlib import Path

from src.windows_hardening import DATA_DIR, PROGRAM_DIR, apply_acls, configure_firewall, configure_service_recovery


ROOT = Path(__file__).resolve().parents[1]


def copy_agent_files() -> None:
    PROGRAM_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for item in ["src", "requirements.txt"]:
        source = ROOT / item
        target = PROGRAM_DIR / item
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)


def write_secret() -> None:
    secret_path = DATA_DIR / "agent.secret"
    if not secret_path.exists():
        secret_path.write_text(secrets.token_hex(32), encoding="utf-8")


def install_service() -> None:
    service_script = PROGRAM_DIR / "src" / "windows_service.py"
    subprocess.run(["python", str(service_script), "install", "--startup", "auto"], check=True)
    configure_service_recovery()
    subprocess.run(["python", str(service_script), "start"], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-ip", default=None)
    args = parser.parse_args()
    copy_agent_files()
    write_secret()
    apply_acls()
    configure_firewall(args.parent_ip)
    install_service()
    print("Kid PC Monitor service installed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Create token-gated uninstaller script**

```python
# scripts/uninstall_service.py
from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path


PROGRAM_DIR = Path(r"C:\Program Files\KidPCMonitor")
DATA_DIR = Path(r"C:\ProgramData\KidPCMonitor")
TOKEN_HASH_FILE = DATA_DIR / "uninstall.sha256"


def token_matches(token: str) -> bool:
    if not TOKEN_HASH_FILE.exists():
        return False
    expected = TOKEN_HASH_FILE.read_text(encoding="utf-8").strip()
    actual = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return expected == actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", required=True)
    parser.add_argument("--preserve-logs", action="store_true")
    args = parser.parse_args()
    if not token_matches(args.token):
        raise SystemExit("Invalid uninstall token")
    subprocess.run(["python", str(PROGRAM_DIR / "src" / "windows_service.py"), "stop"], check=False)
    subprocess.run(["python", str(PROGRAM_DIR / "src" / "windows_service.py"), "remove"], check=True)
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", 'Remove-NetFirewallRule -DisplayName "Kid PC Monitor Agent" -ErrorAction SilentlyContinue'], check=True)
    print("Kid PC Monitor service removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Commit**

```bash
git add requirements.txt src/windows_service.py src/windows_hardening.py scripts/install_service.py scripts/uninstall_service.py
git commit -m "feat: add windows service installer and hardening"
```

## Task 8: Parent Web Panel Authenticated Client

**Files:**
- Modify: `src/web_panel.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: Add web client signing test**

Append to `tests/test_auth.py`:

```python
from src.web_panel import build_signed_command


def test_web_panel_builds_signed_command():
    envelope = build_signed_command(
        {"command": "lock"},
        secret_hex="6465762d736563726574",
        now=1000,
        nonce="abc",
    )

    body = verify_message(envelope, b"dev-secret", now=1000, nonce_store=NonceStore())

    assert body == {"command": "lock"}
```

- [ ] **Step 2: Run the new web-panel auth test and verify it fails**

Run:

```bash
python -m pytest tests/test_auth.py::test_web_panel_builds_signed_command -v
```

Expected: fail because `build_signed_command` does not exist.

- [ ] **Step 3: Add signed command helper to `src/web_panel.py`**

Add near the top of `src/web_panel.py`:

```python
from src.agent_auth import sign_message


DEVICE_SECRETS = {
    # "192.168.10.251": "hex encoded secret from C:\\ProgramData\\KidPCMonitor\\agent.secret",
}


def build_signed_command(body, secret_hex, now=None, nonce=None):
    return sign_message(body, bytes.fromhex(secret_hex), now=now, nonce=nonce)
```

Update `send_command` to send JSON envelopes:

```python
def send_command(host, command, port=9999):
    try:
        secret_hex = DEVICE_SECRETS.get(host)
        if not secret_hex:
            return False, "No device secret configured"
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(5)
        client.connect((host, port))
        envelope = build_signed_command({"command": command}, secret_hex)
        client.send((json.dumps(envelope) + "\n").encode("utf-8"))
        response = client.recv(4096)
        client.close()
        return True, response.decode()
    except Exception as e:
        return False, str(e)
```

Also add `import json` near the existing imports.

- [ ] **Step 4: Run auth tests and verify they pass**

Run:

```bash
python -m pytest tests/test_auth.py -v
```

Expected: all auth tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/web_panel.py tests/test_auth.py
git commit -m "feat: sign parent web panel commands"
```

## Task 9: Remote Windows Validation Document

**Files:**
- Create: `docs/remote-windows-test.md`

- [ ] **Step 1: Write remote validation checklist**

````markdown
# Remote Windows Test Checklist

Target: `192.168.10.251`

Do not store passwords in this file.

## Prerequisites

- Windows 10/11 test machine is reachable.
- Test user is a standard child account.
- Parent/admin account is available for installation.
- Python 3.10+ is installed and on PATH.
- WinRM 5985 or OpenSSH is enabled for automation.
- RDP remains available as fallback.

## Commands To Run On Windows As Administrator

```powershell
python --version
whoami
net user
sc.exe query KidPCMonitorService
netsh advfirewall firewall show rule name="Kid PC Monitor Agent"
```

## Install

```powershell
cd C:\Users\hulei\kid-pc-monitor
python scripts\install_service.py --parent-ip 192.168.10.10
sc.exe query KidPCMonitorService
```

## Offline Enforcement Test

1. Apply a policy with a one-minute daily limit.
2. Confirm the child service acknowledges the policy.
3. Disable network on the child PC.
4. Wait for the warning and lock behavior.
5. Re-enable network.
6. Confirm logs sync back to the parent panel.

## Anti-Tamper Test

From the standard child account:

```powershell
sc.exe stop KidPCMonitorService
Remove-Item "C:\Program Files\KidPCMonitor" -Recurse
Remove-Item "C:\ProgramData\KidPCMonitor\policy.json"
```

Expected: commands fail with access denied or do not disable service enforcement.
````

- [ ] **Step 2: Commit**

```bash
git add docs/remote-windows-test.md
git commit -m "docs: add remote windows validation checklist"
```

## Task 10: Verification Gate

**Files:**
- All files changed by previous tasks.

- [ ] **Step 1: Run local unit tests**

Run:

```bash
python -m pytest -v
```

Expected: all unit tests pass on Linux. Windows service integration tests are skipped locally unless running on Windows.

- [ ] **Step 2: Run syntax check**

Run:

```bash
python -m compileall src scripts
```

Expected: compile succeeds for cross-platform files. Windows-only imports must be guarded or isolated so Linux compile does not fail.

- [ ] **Step 3: Run remote preflight**

Run:

```bash
for p in 3389 5985 5986 22 445 135 9999; do timeout 2 bash -c "</dev/tcp/192.168.10.251/$p" >/dev/null 2>&1 && echo "$p open" || echo "$p closed"; done
```

Expected before enabling automation: `3389 open`, WinRM or SSH may be closed. Expected before automated install: either `5985 open`, `5986 open`, or `22 open`.

- [ ] **Step 4: Run Windows integration validation**

Run the checklist in `docs/remote-windows-test.md`.

Expected:

- Service installs and starts.
- Firewall rule exists.
- Standard child user cannot stop service.
- Offline one-minute policy still triggers warning and lock.
- Logs remain local while offline and are available after reconnect.

- [ ] **Step 5: Final commit if verification changes docs or scripts**

```bash
git status --short
git add <changed-files>
git commit -m "test: verify c-tier phase1 hardening"
```
