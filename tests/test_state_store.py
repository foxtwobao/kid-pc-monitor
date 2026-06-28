from datetime import date
import json
from pathlib import Path

import pytest

from src.state_store import AgentState, StateStore, atomic_write_json


def test_state_store_round_trips_json(tmp_path):
    store = StateStore(tmp_path / "state.json")
    state = AgentState(
        current_date=date.today().isoformat(),
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


def test_state_store_loads_utf8_bom_json(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "current_date": date.today().isoformat(),
                "usage_seconds_by_user": {"kid": 12},
                "active_lock_reason": None,
                "last_policy_version": 3,
                "unsent_event_cursor": 0,
                "helper_last_seen_at": None,
            }
        ),
        encoding="utf-8-sig",
    )

    state = StateStore(path).load()

    assert state.usage_seconds_by_user == {"kid": 12}
    assert state.last_policy_version == 3


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


def test_atomic_write_json_preserves_existing_file_when_replace_fails(tmp_path, monkeypatch):
    path = tmp_path / "policy.json"
    path.write_text('{"version": 1}\n', encoding="utf-8")
    original_replace = Path.replace

    def failing_replace(self, target):
        if target == path:
            raise RuntimeError("replace failed")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(RuntimeError, match="replace failed"):
        atomic_write_json(path, {"version": 2})

    assert json.loads(path.read_text(encoding="utf-8")) == {"version": 1}
