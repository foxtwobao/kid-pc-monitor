import json

from src.event_log import append_event, read_events


def test_append_event_writes_jsonl(tmp_path):
    path = tmp_path / "events.jsonl"

    append_event(path, "policy.accepted", {"version": 2}, now=lambda: "2026-06-27T12:00:00+08:00")

    assert read_events(path) == [
        {
            "at": "2026-06-27T12:00:00+08:00",
            "type": "policy.accepted",
            "data": {"version": 2},
        }
    ]


def test_read_events_skips_invalid_lines(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"type":"ok"}\nnot-json\n', encoding="utf-8")

    assert read_events(path) == [{"type": "ok"}]
