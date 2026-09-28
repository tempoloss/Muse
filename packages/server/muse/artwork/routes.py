from pathlib import Path

from dishka.integrations.litestar import FromDishka, inject
from litestar import Router, get
from litestar.params import FromPath, FromQuery
from litestar.response import File

from muse.artwork.domain import NO_ARTIST_IMAGE, NO_COVER
from muse.artwork.service import Artwork
from muse.shared.errors import domain_errors

ERRORS = {NO_ARTIST_IMAGE: 404, NO_COVER: 404}


def jpeg(path: Path) -> File:
    return File(
        path, media_type="image/jpeg", content_disposition_type="inline", filename=path.name
    )


@get("/artist-image")
@inject
async def artist_image(
    name: FromQuery[str], artwork: FromDishka[Artwork], s: FromQuery[int] = 0
) -> File:
    return jpeg(await artwork.artist_image(name, s))


@get("/cover/{aid:int}")
@inject
async def cover(aid: FromPath[int], artwork: FromDishka[Artwork], s: FromQuery[int] = 0) -> File:
    return jpeg(await artwork.cover(aid, s))


router = Router(
    "/api", route_handlers=[artist_image, cover], exception_handlers=domain_errors(ERRORS)
)
