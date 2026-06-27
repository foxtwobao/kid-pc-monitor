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
