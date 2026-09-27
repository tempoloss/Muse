from datetime import datetime
from zoneinfo import ZoneInfo

from muse.shared.clock import ZonedClock

ORIGIN = "https://testserver.local"
WRITE = {"Origin": ORIGIN}
PASSWORDS = {"alice": "test-pass-alice", "bob": "test-pass-bob"}


class ManualClock(ZonedClock):
    def __init__(self, ms: int, zone: str = "UTC") -> None:
        super().__init__(ZoneInfo(zone))
        self.ms = ms

    def now_ms(self) -> int:
        return self.ms

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.ms / 1000, self.zone)
