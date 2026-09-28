from typing import Any

from dishka.integrations.litestar import FromDishka, inject
from litestar import Router, get
from litestar.params import FromPath, FromQuery

from muse.catalog.domain import NO_ALBUM, NO_PLAYLIST, NO_SUCH_ARTIST, NO_SUCH_GENRE, NO_TRACK
from muse.catalog.service import Catalog
from muse.shared.errors import domain_errors

ERRORS = {NO_SUCH_ARTIST: 404, NO_ALBUM: 404, NO_TRACK: 404, NO_SUCH_GENRE: 404, NO_PLAYLIST: 404}


@get("/genres")
@inject
async def genres(catalog: FromDishka[Catalog]) -> list[dict[str, Any]]:
    return await catalog.genres()


@get("/artists")
@inject
async def artists(catalog: FromDishka[Catalog], genre: FromQuery[str] = "") -> list[dict[str, Any]]:
    return await catalog.artists(genre)


@get("/artist/{name:str}")
@inject
async def artist(name: FromPath[str], catalog: FromDishka[Catalog]) -> dict[str, Any]:
    return await catalog.artist(name)


@get("/albums")
@inject
async def albums(catalog: FromDishka[Catalog], genre: FromQuery[str] = "") -> list[dict[str, Any]]:
    return await catalog.albums(genre)


@get("/album/{aid:int}")
@inject
async def album(aid: FromPath[int], catalog: FromDishka[Catalog]) -> dict[str, Any]:
    return await catalog.album(aid)


@get("/search")
@inject
async def search(catalog: FromDishka[Catalog], q: FromQuery[str] = "") -> dict[str, Any]:
    return await catalog.search(q)


@get("/track/{tid:int}")
@inject
async def track(tid: FromPath[int], catalog: FromDishka[Catalog]) -> dict[str, Any]:
    return await catalog.track(tid)


@get("/genre/{genre:str}")
@inject
async def genre(genre: FromPath[str], catalog: FromDishka[Catalog]) -> dict[str, Any]:
    return await catalog.genre(genre)


@get("/playlists")
@inject
async def playlists(catalog: FromDishka[Catalog]) -> list[dict[str, Any]]:
    return await catalog.playlists()


@get("/playlist/{name:str}")
@inject
async def playlist(name: FromPath[str], catalog: FromDishka[Catalog]) -> dict[str, Any]:
    return await catalog.playlist(name)


router = Router(
    "/api",
    route_handlers=[
        genres,
        artists,
        artist,
        albums,
        album,
        search,
        track,
        genre,
        playlists,
        playlist,
    ],
    exception_handlers=domain_errors(ERRORS),
)
