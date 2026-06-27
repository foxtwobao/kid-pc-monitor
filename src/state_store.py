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
        atomic_write_json(self.path, state.to_dict())


def atomic_write_json(path: str | Path, data: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(target.parent),
            delete=False,
        ) as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_name = handle.name
        Path(temp_name).replace(target)
    except Exception:
        if temp_name is not None:
            Path(temp_name).unlink(missing_ok=True)
        raise
