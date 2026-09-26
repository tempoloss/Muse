import time
from datetime import date, datetime
from datetime import time as clock_time
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    def now_ms(self) -> int: ...

    def now(self) -> datetime: ...

    def today(self) -> date: ...

    def day_start_ms(self, day: date) -> int: ...

    def local_hour(self, ms: int) -> int: ...


class ZonedClock:
    def __init__(self, zone: ZoneInfo) -> None:
        self.zone = zone

    def now_ms(self) -> int:
        return int(time.time() * 1000)

    def now(self) -> datetime:
        return datetime.now(self.zone)

    def today(self) -> date:
        return self.now().date()

    def day_start_ms(self, day: date) -> int:
        return int(datetime.combine(day, clock_time.min, tzinfo=self.zone).timestamp() * 1000)

    def local_hour(self, ms: int) -> int:
        return datetime.fromtimestamp(ms / 1000, self.zone).hour
