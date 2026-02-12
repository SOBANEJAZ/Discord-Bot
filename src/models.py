from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class OpenSession:
    user_id: str
    started_at_utc: datetime


@dataclass(frozen=True, slots=True)
class DailyTotal:
    day_local: str
    user_id: str
    seconds: int


@dataclass(frozen=True, slots=True)
class ReportRow:
    user_id: str
    display_name: str
    seconds: int
