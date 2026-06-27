# C-Tier Parental Control Hardening Design

## Goal

Upgrade Kid PC Monitor from a lightweight LAN-controlled script into a Windows parental-control agent that remains effective when the child is offline, raises the bypass cost for standard Windows users, and gives parents auditable control over time limits, lock schedules, and emergency actions.

The design assumes the child uses a standard Windows account and the parent keeps the only administrator account. It does not attempt to defeat a child with administrator credentials, firmware access, external boot media, or physical disk access.

## Non-Goals

- No stealth monitoring.
- No screenshots, keylogging, browser-history collection, or content inspection.
- No guarantee against local administrators.
- No kernel drivers or unsupported Windows security hooks.
- No cloud dependency for enforcement.

## Required Offline Behavior

The child PC must enforce restrictions without network access. The parent web panel is a configuration and visibility surface, not a runtime dependency.

The child-side service stores the last valid policy locally under `C:\ProgramData\KidPCMonitor\policy.json`. When the network is unavailable, the service continues using that policy to track usage, send warnings through the helper, and lock the child session when limits are reached.

Policy changes from the parent panel are applied only after successful authenticated delivery to the child PC. Once accepted, the child PC persists the policy atomically and acknowledges the new policy version. If delivery fails because the child PC is offline, the parent panel shows the pending change as unsynced instead of pretending it is active.

When the child PC reconnects, the parent panel can reconcile policy versions and event logs. Enforcement never waits for that reconciliation.

## Architecture

The Windows child agent is split into two processes:

- `KidPCMonitorService`: a Windows service running as `LocalSystem`.
- `KidPCMonitorHelper`: a per-user desktop helper running inside the child's interactive session.

The parent machine continues to run a Flask web panel, but the panel must authenticate to each child agent and must tolerate offline devices.

```text
Parent Web Panel
  |
  | authenticated LAN command, policy sync, status query
  v
KidPCMonitorService
  - local policy enforcement
  - usage accounting
  - event logging
  - helper supervision
  - firewall-scoped listener
  |
  | localhost IPC
  v
KidPCMonitorHelper
  - warnings
  - lock current session
  - child-visible status
  - heartbeat to service
```

## Child Service Responsibilities

The service owns all trusted state and policy decisions.

- Starts automatically at boot.
- Runs as `LocalSystem`.
- Loads policy and state from `C:\ProgramData\KidPCMonitor\`.
- Listens on TCP `9999` for authenticated parent commands.
- Enforces daily usage limits and scheduled lock windows using local time.
- Continues enforcement when LAN, Wi-Fi, or the parent web panel is unavailable.
- Tracks helper heartbeats and restarts the helper if it exits.
- Records policy changes, lock actions, service lifecycle events, failed auth, and helper restarts.
- Writes logs to both local rotating files and Windows Event Log.
- Uses service recovery so Windows restarts it after crashes.

## Session Helper Responsibilities

The helper handles user-session interactions that a service should not do directly.

- Starts in the child user's interactive session.
- Shows 15, 5, and 1 minute warnings.
- Shows parent messages.
- Displays local status such as remaining time.
- Locks the active child session when instructed by the service.
- Sends periodic heartbeats to the service.
- Does not store trusted policy or secrets.

If the helper is killed, enforcement still belongs to the service. The service restarts the helper and records the event.

## Policy Model

A policy contains:

- `device_id`
- `policy_version`
- `daily_limit_minutes`
- `bedtime_windows`
- `monitored_users`
- `exempt_users`
- `warning_minutes`
- `temporary_extensions`
- `parent_panel_allowed_ips`
- `updated_at`
- `signature` or authenticated message metadata

State contains:

- current day usage counters
- last reset date
- active lock state
- last accepted policy version
- unsent event-log cursor
- helper heartbeat status

Usage accounting is local. The first implementation may count logged-in session time rather than precise keyboard/mouse activity. More precise idle-aware accounting can be added later without changing the service/helper split.

## Parent Web Panel Responsibilities

The web panel becomes a policy manager and status viewer.

- Maintains known child devices and their shared secrets.
- Sends policy updates to reachable child services.
- Shows whether each child has acknowledged the latest policy version.
- Marks offline devices clearly.
- Shows last known status and last sync time.
- Pulls event logs when a device is reachable.
- Allows manual lock, shutdown, message, extra time, and policy changes.
- Requires a parent login before use.

The panel must not report a policy as active on a child PC until the child service acknowledges it.

## Security Model

The system uses defense in depth for standard-user children.

- Child account is standard user.
- Parent account is the only administrator.
- Agent files live under `C:\Program Files\KidPCMonitor\`.
- Mutable policy, state, and logs live under `C:\ProgramData\KidPCMonitor\`.
- Ordinary users cannot modify agent binaries, service config, policy files, or state files.
- TCP commands require authentication.
- Firewall rules limit `9999` to configured parent machine IPs when possible.
- The web panel requires parent authentication.
- Uninstall requires administrator rights and an uninstall token.

Network commands use a shared secret in the first version. Each command includes a timestamp, nonce, body, and HMAC. The service rejects missing auth, invalid HMAC, stale timestamps, and repeated nonces.

## Installation And Uninstall

The Windows installer performs these actions as administrator:

- Copies service and helper files to `C:\Program Files\KidPCMonitor\`.
- Creates `C:\ProgramData\KidPCMonitor\`.
- Generates or imports a device secret.
- Registers `KidPCMonitorService`.
- Configures automatic start.
- Configures service recovery restart actions.
- Creates a helper launch mechanism for monitored child users.
- Applies ACLs to program and data directories.
- Adds Windows Firewall rules for the service port.
- Stores uninstall metadata and uninstall token hash.

Uninstall requires administrator elevation and the uninstall token. It stops the service, removes service registration, removes firewall rules, removes helper launch entries, and optionally preserves logs.

## Enforcement Flow

At boot, the service starts and loads the last accepted policy. If no policy exists, it starts in observation mode and refuses to claim active enforcement.

When the child logs in, the helper starts in that session. The service validates the logged-in user against the policy. If the user is monitored, the service begins or resumes local usage accounting.

During normal use, the service calculates remaining time locally. At warning thresholds it asks the helper to show warnings. When a limit or bedtime window is reached, it asks the helper to lock the session. If the helper is unavailable, the service restarts it and retries.

When offline, this same flow continues with the local policy and local state.

## Event Logging

Events include:

- service installed, started, stopped, crashed, recovered
- helper started, stopped, missing heartbeat, restarted
- policy accepted or rejected
- auth failure and source address
- manual parent command
- warning displayed
- lock triggered and reason
- usage counter reset
- offline/online transition when detected
- uninstall attempted and result

The parent panel displays events after the next successful sync. Events remain local while offline.

## Current Code Impact

The current `src/pc_control.py` mixes policy, network server, Windows locking, message display, and process lifetime in one script. The upgrade should introduce clearer modules rather than continuing to grow that file.

Planned components:

- `src/kid_service.py`: service entry point and lifecycle.
- `src/policy.py`: policy schema, validation, versioning, persistence.
- `src/state_store.py`: atomic state persistence.
- `src/auth.py`: HMAC command authentication.
- `src/ipc.py`: service/helper local communication.
- `src/helper.py`: user-session helper.
- `src/windows_service.py`: Windows service integration.
- `src/windows_acl.py`: ACL and install hardening helpers.
- `src/event_log.py`: local file and Windows Event Log writers.
- `scripts/install_service.py`: admin installer.
- `scripts/uninstall_service.py`: token-gated uninstaller.

Existing web-panel commands should move from raw strings to authenticated JSON messages.

## Error Handling

- Invalid policy: reject and keep current policy.
- Failed policy write: reject command and keep current policy.
- Service restart: reload policy and state, then continue enforcement.
- Helper missing: log event, restart helper, retry user-facing action.
- Parent panel offline: no effect on child enforcement.
- Child PC offline: parent panel marks pending changes unsynced.
- Clock changes: log event and continue using local time; later versions may add stronger clock-tamper detection.

## Testing Strategy

Automated tests should cover policy validation, state persistence, HMAC authentication, nonce replay rejection, usage-limit calculations, bedtime-window calculations, offline policy behavior, and pending-policy status in the web panel.

Windows integration tests should verify service installation, service restart recovery, ACLs, firewall rule creation, helper launch, helper restart after termination, lock command dispatch, and uninstall token handling.

Manual tests should include disconnecting Wi-Fi after policy sync and confirming warnings and lock still occur.

## Rollout Plan

Phase 1 builds the hard foundation:

- local policy store
- service/helper split
- automatic enforcement loop
- authenticated commands
- offline enforcement
- service recovery
- basic ACLs and firewall rules

Phase 2 adds the commercial-control polish:

- parent login
- event-log UI
- pending policy sync state
- uninstall token
- improved installer and uninstaller
- multi-device management
- optional Windows policy restrictions

## Acceptance Criteria

- A child PC enforces the last accepted time policy while disconnected from the network.
- A standard child user cannot stop the service through normal Windows service controls.
- Killing the helper does not remove enforcement; the service restarts it.
- Parent commands without valid authentication are rejected.
- The parent panel distinguishes active policy from pending unsynced changes.
- Agent files and policy files cannot be modified by the child standard user.
- Service crash recovery restarts the service automatically.
- Uninstall requires administrator elevation and the uninstall token.
