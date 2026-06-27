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
