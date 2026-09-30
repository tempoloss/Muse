from datetime import UTC, datetime

import httpx
import pytest
from dishka import Provider, Scope, provide
from litestar.testing import AsyncTestClient

from muse.app import create_app
from muse.diagnostics.domain import device
from muse.settings import Settings
from muse.shared.clock import Clock
from tests.server.support import ORIGIN, WRITE, ManualClock, signed_in

IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) Safari/605.1.15"
CHROME = "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
TOKYO_EVENING = datetime(2026, 1, 16, 23, 30, 5, tzinfo=UTC)


class TokyoClock(Provider):
    @provide(scope=Scope.APP)
    def clock(self) -> Clock:
        return ManualClock(int(TOKYO_EVENING.timestamp() * 1000), "Asia/Tokyo")


def log_lines(settings: Settings, name: str = "player.log") -> list[str]:
    return (settings.paths.data_dir / name).read_text(encoding="utf-8").splitlines()


async def report(client: httpx.AsyncClient, body: dict[str, object]) -> httpx.Response:
    return await client.post("/api/player-log", json=body, headers={**WRITE, "User-Agent": IPHONE})


async def test_ping_answers_signed_in_users_only(
    client: httpx.AsyncClient, alice: httpx.AsyncClient
) -> None:
    anonymous = await client.get("/api/ping")
    response = await alice.get("/api/ping")

    assert anonymous.status_code == 401
    assert (response.status_code, response.json()) == (200, {"ok": True})


async def test_player_log_keeps_one_line_per_event(
    bob: httpx.AsyncClient, settings: Settings
) -> None:
    response = await report(bob, {"event": "stall\nfake line", "track_id": 7})

    assert response.status_code == 204
    assert log_lines(settings)[-1].endswith("bob iPhone stall fake line track=7")


async def test_an_event_is_squeezed_to_sixty_chars_and_the_track_is_optional(
    alice: httpx.AsyncClient, settings: Settings
) -> None:
    await report(alice, {"event": "  reload \t " + "x" * 80})

    assert log_lines(settings)[-1].endswith(f"alice iPhone reload {'x' * 53} track=None")


async def test_lines_are_stamped_in_the_configured_timezone(settings: Settings) -> None:
    app = create_app(settings, providers=[TokyoClock()])
    async with AsyncTestClient(app=app, base_url=ORIGIN):
        alice = await signed_in(app, "alice")
        await report(alice, {"event": "stall", "track_id": 3})
        await alice.aclose()

    assert log_lines(settings) == ["2026-01-17 08:30:05 alice iPhone stall track=3"]


async def test_a_log_over_a_megabyte_is_rotated_before_the_next_line(
    alice: httpx.AsyncClient, settings: Settings
) -> None:
    settings.paths.player_log.write_bytes(b"x" * 999_999 + b"\n")
    (settings.paths.data_dir / "player.log.1").write_text("older\n", encoding="utf-8")

    await report(alice, {"event": "first"})
    at_the_limit = log_lines(settings)
    await report(alice, {"event": "second"})

    assert len(at_the_limit) == 2
    assert at_the_limit[1].endswith("alice iPhone first track=None")
    assert log_lines(settings, "player.log.1") == at_the_limit
    [line] = log_lines(settings)
    assert line.endswith("alice iPhone second track=None")


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [
        (IPHONE, "iPhone"),
        ("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) Safari/605.1.15", "iPad"),
        (f"Mozilla/5.0 (Linux; Android 14; SM-S911B) {CHROME}", "Android"),
        ("Mozilla/5.0 (Windows NT 10.0; rv:131.0) Gecko/20100101 Firefox/131.0", "Firefox"),
        (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) {CHROME} Edg/129.0.0.0", "Edg"),
        (f"Mozilla/5.0 (X11; Linux x86_64) {CHROME}", "Chrome"),
        ("Mozilla/5.0 (Macintosh) Version/17.6 Safari/605.1.15", "Safari"),
        ("curl/8.9.1", "other"),
    ],
)
def test_the_device_is_the_first_known_marker_of_the_user_agent(
    user_agent: str, expected: str
) -> None:
    assert device(user_agent) == expected
