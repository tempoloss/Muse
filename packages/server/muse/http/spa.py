from pathlib import Path

import anyio
from dishka.integrations.litestar import FromDishka, inject
from litestar import Response, route
from litestar.enums import HttpMethod
from litestar.params import FromPath
from litestar.response import File

from muse.settings import Settings
from muse.shared.errors import detail_response

MIME = {
    ".html": "text/html",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".txt": "text/plain",
}
NO_CACHE = ("sw.js", "manifest.webmanifest")


def cache_headers(relative: str) -> dict[str, str]:
    if relative.startswith("assets/"):
        return {"Cache-Control": "public, max-age=31536000, immutable"}
    if relative in NO_CACHE:
        return {"Cache-Control": "no-cache"}
    return {}


def served(path: Path, headers: dict[str, str]) -> File:
    return File(
        path,
        media_type=MIME.get(path.suffix.lower()),
        headers=headers,
        content_disposition_type="inline",
        filename=path.name,
    )


async def web_file(web_dir: Path, relative: str) -> Path | None:
    if not relative:
        return None
    root = await anyio.Path(web_dir).resolve()
    target = await anyio.Path(web_dir / relative).resolve()
    if target.is_relative_to(root) and await target.is_file():
        return Path(target)
    return None


@route(
    ["/api", "/api/{path:path}"],
    http_method=[HttpMethod.GET, HttpMethod.HEAD],
    opt={"skip_auth": True},
    include_in_schema=False,
)
async def api_not_found(path: FromPath[str] = "") -> Response[dict[str, object]]:
    return detail_response(404, "not found")


@route(
    ["/", "/{path:path}"],
    http_method=[HttpMethod.GET, HttpMethod.HEAD],
    opt={"skip_auth": True},
    include_in_schema=False,
)
@inject
async def spa(settings: FromDishka[Settings], path: FromPath[str] = "") -> Response | File:
    relative = path.lstrip("/")
    web_dir = settings.paths.web_dir
    if found := await web_file(web_dir, relative):
        return served(found, cache_headers(relative))
    index = web_dir / "index.html"
    if not await anyio.Path(index).is_file():
        return Response("web client not built", status_code=503, media_type="text/plain")
    return served(index, {"Cache-Control": "no-cache"})
