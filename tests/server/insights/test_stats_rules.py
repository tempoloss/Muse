from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from muse.insights.domain import common_artists, hours_histogram
from muse.shared.clock import ZonedClock


def utc_ms(text: str) -> int:
    return int(datetime.fromisoformat(text).replace(tzinfo=UTC).timestamp() * 1000)


STARTS = [
    utc_ms("2026-01-17T23:30:00"),
    utc_ms("2026-01-18T00:10:00"),
    utc_ms("2026-01-18T00:59:59"),
]


@pytest.mark.parametrize(("zone", "late", "early"), [("UTC", 23, 0), ("Asia/Tokyo", 8, 9)])
def test_plays_fall_into_the_hour_of_the_configured_timezone(
    zone: str, late: int, early: int
) -> None:
    hours = hours_histogram(STARTS, ZonedClock(ZoneInfo(zone)).local_hour)

    assert len(hours) == 24
    assert (hours[late], hours[early], sum(hours)) == (1, 2, 3)


def test_common_artists_rank_by_the_smaller_count_then_the_total_then_the_name() -> None:
    mine = {"Alpha": 9, "Beta": 3, "Gamma": 3, "Delta": 2, "Echo": 7, "Hotel": 2, "Solo": 50}
    theirs = {"Alpha": 1, "Beta": 3, "Gamma": 4, "Delta": 2, "Echo": 2, "Hotel": 2, "Golf": 4}

    assert common_artists(mine, theirs) == [
        {"name": "Gamma", "me": 3, "partner": 4},
        {"name": "Beta", "me": 3, "partner": 3},
        {"name": "Echo", "me": 7, "partner": 2},
        {"name": "Delta", "me": 2, "partner": 2},
        {"name": "Hotel", "me": 2, "partner": 2},
    ]
