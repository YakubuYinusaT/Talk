"""What one turn of a call produces, the state a call carries from turn to turn, and the part of the day."""

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass
class Outcome:
    text: str
    key: str
    end_call: bool = False
    action: str = ""
    extra: dict = field(default_factory=dict)  # what the wording step needs: the real facts and the reference sentence


def new_state() -> dict:
    return {
        "pending": None, "turn": 0, "unknown_streak": 0, "low_conf": 0, "silence": 0, "ack_i": 0,
        "t0": time.time(),  # when the call began (no call runs past max_call_seconds)
    }


def daypart(now: datetime | None = None) -> str:
    lagos = (now or datetime.now(timezone.utc)) + timedelta(hours=1)
    return "morning" if lagos.hour < 12 else "afternoon" if lagos.hour < 17 else "evening"
