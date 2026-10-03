from dishka.integrations.litestar import FromDishka, inject
from litestar import Request, Response, Router, get
from litestar.params import FromPath, FromQuery
from litestar.response import Stream

from muse.catalog.domain import (
    FILE_GONE,
    NO_ALBUM,
    NO_PLAYLIST,
    NO_SUCH_ARTIST,
    NO_SUCH_GENRE,
    NO_TRACK,
    AlbumCard,
    AlbumPage,
    ArtistCount,
    ArtistPage,
    GenreCount,
    GenrePage,
    PlaylistCard,
    PlaylistPage,
    SearchResult,
    Track,
)
from muse.catalog.service import Catalog
from muse.shared.errors import domain_errors
from muse.shared.ranges import file_response

ERRORS = {
    NO_SUCH_ARTIST: 404,
    NO_ALBUM: 404,
    NO_TRACK: 404,
    NO_SUCH_GENRE: 404,
    NO_PLAYLIST: 404,
    FILE_GONE: 404,
}
MP3 = "audio/mpeg"


@get("/genres")
@inject
async def genres(catalog: FromDishka[Catalog]) -> list[GenreCount]:
    return await catalog.genres()


@get("/artists")
@inject
async def artists(catalog: FromDishka[Catalog], genre: FromQuery[str] = "") -> list[ArtistCount]:
    return await catalog.artists(genre)


@get("/artist/{name:str}")
@inject
async def artist(name: FromPath[str], catalog: FromDishka[Catalog]) -> ArtistPage:
    return await catalog.artist(name)


@get("/albums")
@inject
async def albums(catalog: FromDishka[Catalog], genre: FromQuery[str] = "") -> list[AlbumCard]:
    return await catalog.albums(genre)


@get("/album/{aid:int}")
@inject
async def album(aid: FromPath[int], catalog: FromDishka[Catalog]) -> AlbumPage:
    return await catalog.album(aid)


@get("/search")
@inject
async def search(catalog: FromDishka[Catalog], q: FromQuery[str] = "") -> SearchResult:
    return await catalog.search(q)


@get("/track/{tid:int}")
@inject
async def track(tid: FromPath[int], catalog: FromDishka[Catalog]) -> Track:
    return await catalog.track(tid)


@get("/genre/{genre:str}")
@inject
async def genre(genre: FromPath[str], catalog: FromDishka[Catalog]) -> GenrePage:
    return await catalog.genre(genre)


@get("/playlists")
@inject
async def playlists(catalog: FromDishka[Catalog]) -> list[PlaylistCard]:
    return await catalog.playlists()


@get("/playlist/{name:str}")
@inject
async def playlist(name: FromPath[str], catalog: FromDishka[Catalog]) -> PlaylistPage:
    return await catalog.playlist(name)


@get("/stream/{tid:int}")
@inject
async def stream(
    tid: FromPath[int], request: Request, catalog: FromDishka[Catalog]
) -> Response[bytes] | Stream:
    return await file_response(await catalog.stream_file(tid), MP3, request)


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
        stream,
        genre,
        playlists,
        playlist,
    ],
    exception_handlers=domain_errors(ERRORS),
)
