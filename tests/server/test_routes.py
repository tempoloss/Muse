import re

from litestar import Litestar

from muse.app import create_app
from muse.settings import Settings

PARAMETER = re.compile(r"\{\w+:(\w+)\}")
API = {
    ("POST", "/api/login"),
    ("POST", "/api/logout"),
    ("GET", "/api/me"),
    ("GET", "/api/genres"),
    ("GET", "/api/artists"),
    ("GET", "/api/artist/{str}"),
    ("GET", "/api/albums"),
    ("GET", "/api/album/{int}"),
    ("GET", "/api/playlists"),
    ("GET", "/api/playlist/{str}"),
    ("GET", "/api/search"),
    ("GET", "/api/track/{int}"),
    ("GET", "/api/stream/{int}"),
    ("GET", "/api/genre/{str}"),
    ("GET", "/api/artist-image"),
    ("GET", "/api/cover/{int}"),
    ("GET", "/api/ping"),
    ("POST", "/api/player-log"),
    ("POST", "/api/plays"),
    ("PUT", "/api/likes/{int}"),
    ("DELETE", "/api/likes/{int}"),
    ("GET", "/api/likes"),
    ("GET", "/api/stats"),
    ("GET", "/api/stats/us"),
    ("GET", "/api/push/key"),
    ("POST", "/api/push/subscribe"),
    ("POST", "/api/push/unsubscribe"),
    ("GET", "/api/pet"),
    ("PUT", "/api/quest/album"),
    ("PUT", "/api/pet/name"),
    ("POST", "/api/pet/{str}"),
    ("POST", "/api/live"),
    ("GET", "/api/live"),
    ("GET", "/api/live/follow"),
    ("DELETE", "/api/live/follow"),
    ("POST", "/api/letters"),
    ("GET", "/api/letters"),
    ("POST", "/api/letters/{int}/read"),
    ("GET", "/api/ours"),
    ("PUT", "/api/ours/{int}"),
    ("DELETE", "/api/ours/{int}"),
    ("GET", "/api/notes"),
    ("GET", "/api/lyrics/{int}"),
    ("GET", "/api/radio/{int}"),
    ("GET", "/api/mix/{str}"),
    ("GET", "/api/daily"),
    ("GET", "/api/daily/{int}"),
    ("GET", "/api/home"),
}
WEB = {
    (method, path) for method in ("GET", "HEAD") for path in ("/", "/{path}", "/api", "/api/{path}")
}
OPEN = {("POST", "/api/login"), ("POST", "/api/logout"), *WEB}


def table(app: Litestar) -> set[tuple[str, str, bool]]:
    rows = set()
    for route in app.routes:
        for handler in getattr(route, "route_handlers", ()):
            for method in handler.http_methods - {"OPTIONS"}:
                opened = bool(handler.opt.get("skip_auth"))
                rows.add((method, PARAMETER.sub(r"{\1}", route.path), opened))
    return rows


def test_the_http_surface_is_exactly_the_documented_one(settings: Settings) -> None:
    rows = table(create_app(settings))

    assert {(method, path) for method, path, _ in rows} == API | WEB
    assert {(method, path) for method, path, opened in rows if opened} == OPEN
