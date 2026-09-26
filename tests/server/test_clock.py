from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from muse.shared.clock import ZonedClock

TOKYO = ZonedClock(ZoneInfo("Asia/Tokyo"))


def utc_ms(*parts: int) -> int:
    return int(datetime(*parts, tzinfo=UTC).timestamp() * 1000)


def test_a_day_starts_at_local_midnight() -> None:
    assert TOKYO.day_start_ms(date(2026, 1, 17)) == utc_ms(2026, 1, 16, 15, 0)
    assert ZonedClock(ZoneInfo("UTC")).day_start_ms(date(2026, 1, 17)) == utc_ms(2026, 1, 17)


def test_hours_are_read_on_the_local_clock() -> None:
    instant = utc_ms(2026, 1, 16, 15, 30)

    assert TOKYO.local_hour(instant) == 0
    assert ZonedClock(ZoneInfo("UTC")).local_hour(instant) == 15


def test_today_follows_the_configured_zone() -> None:
    east = ZonedClock(ZoneInfo("Pacific/Kiritimati"))
    west = ZonedClock(ZoneInfo("Etc/GMT+12"))

    assert east.today() > west.today()
    assert east.now().utcoffset() == ZoneInfo("Pacific/Kiritimati").utcoffset(east.now())
