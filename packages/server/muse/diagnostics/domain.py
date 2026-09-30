from datetime import datetime
from typing import Protocol

DEVICES = ("iPhone", "iPad", "Android", "Firefox", "Edg", "Chrome", "Safari")
UNKNOWN_DEVICE = "other"
EVENT_CHARS = 60
ROTATE_BYTES = 1_000_000


def device(user_agent: str) -> str:
    return next((name for name in DEVICES if name in user_agent), UNKNOWN_DEVICE)


def player_log_line(
    at: datetime, user_id: str, user_agent: str, event: str, track_id: int | None
) -> str:
    text = " ".join(event.split())[:EVENT_CHARS]
    return f"{at:%Y-%m-%d %H:%M:%S} {user_id} {device(user_agent)} {text} track={track_id}\n"


class PlayerLog(Protocol):
    async def append(self, line: str) -> None: ...
