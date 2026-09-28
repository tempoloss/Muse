from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from muse.artwork.domain import TransientError
from muse.artwork.infra.stores import OnlineStores
from muse.catalog.domain import SINGLES
from tests.server.artwork.fakes import Pauses

type Json = dict[str, Any]

CDN = "https://cdn.example.org/images"
DEEZER_HOST = "api.deezer.com"
ITUNES_HOST = "itunes.apple.com"
QUOTA = {"type": "Exception", "message": "Quota limit exceeded", "code": 4}
OURS = ("Ozzle Prime", "Ozzle Prime")
TITLES = ["Copper Harbor", "Static Lake", "Neon Kettle", "Paper Owl"]


def art(name: str) -> str:
    return f"{CDN}/cover/{name}/1000x1000.jpg"


def deezer_album(album_id: int, title: str, artist: str, cover: str) -> Json:
    return {"id": album_id, "title": title, "artist": {"name": artist}, "cover_xl": cover}


def deezer_track(title: str, artist: str, album: str, cover: str) -> Json:
    return {
        "title": title,
        "artist": {"name": artist},
        "album": {"title": album, "cover_xl": cover},
    }


@dataclass
class StoreWeb:
    searches: dict[tuple[str, str], list[Json]] = field(default_factory=dict)
    tracklists: dict[str, list[str]] = field(default_factory=dict)
    discographies: dict[str, list[list[Json]]] = field(default_factory=dict)
    itunes: dict[tuple[str, str, str], list[Json]] = field(default_factory=dict)
    quota: bool = False
    seen: list[httpx.URL] = field(default_factory=list)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        self.seen.append(url)
        if url.host == ITUNES_HOST:
            key = (url.params["country"], url.params["entity"], url.params["term"])
            return httpx.Response(200, json={"results": self.itunes.get(key, [])})
        if self.quota:
            return httpx.Response(200, json={"error": QUOTA})
        section, name, *_ = url.path.strip("/").split("/")
        if section == "search":
            return httpx.Response(
                200, json={"data": self.searches.get((name, url.params["q"]), [])}
            )
        if section == "album":
            titles = self.tracklists.get(name, [])
            return httpx.Response(200, json={"data": [{"title": title} for title in titles]})
        return httpx.Response(
            200, json=self.discography_page(name, int(url.params.get("index", 0)))
        )

    def discography_page(self, artist_id: str, index: int) -> Json:
        pages = self.discographies.get(artist_id, [[]])
        page: Json = {"data": pages[index]}
        if index + 1 < len(pages):
            page["next"] = (
                f"https://{DEEZER_HOST}/artist/{artist_id}/albums?limit=500&index={index + 1}"
            )
        return page

    def asked(self, host: str) -> list[str | None]:
        return [
            url.params.get("q", url.params.get("term")) for url in self.seen if url.host == host
        ]


@pytest.fixture
def web() -> StoreWeb:
    return StoreWeb()


@pytest.fixture
def pauses() -> Pauses:
    return Pauses()


@pytest.fixture
async def stores(web: StoreWeb, pauses: Pauses) -> AsyncIterator[OnlineStores]:
    async with httpx.AsyncClient(transport=httpx.MockTransport(web)) as client:
        yield OnlineStores(client, sleep=pauses)


async def test_an_album_cover_needs_one_of_our_credits(web: StoreWeb, stores: OnlineStores) -> None:
    web.searches[("album", "Ozzle Prime Copper Harbor")] = [
        deezer_album(1, "Copper Harbor", "Somebody Else", art("theirs")),
        deezer_album(2, "Copper Harbor", "Wexa & Ozzle Prime", art("ours")),
    ]

    assert await stores.album_art(OURS, "Copper Harbor", TITLES) == art("ours")


async def test_an_exact_title_beats_an_earlier_extended_one(
    web: StoreWeb, stores: OnlineStores
) -> None:
    extended = deezer_album(1, "Copper Harbor 20th Anniversary Edition", "Ozzle Prime", art("long"))
    exact = deezer_album(2, "Copper Harbor", "Ozzle Prime", art("exact"))
    web.searches[("album", "Ozzle Prime Copper Harbor")] = [extended, exact]
    both = await stores.album_art(OURS, "Copper Harbor", TITLES)
    web.searches[("album", "Ozzle Prime Copper Harbor")] = [extended]
    alone = await stores.album_art(OURS, "Copper Harbor", TITLES)

    assert (both, alone) == (art("exact"), art("long"))


async def test_the_song_search_finds_albums_the_album_search_misses(
    web: StoreWeb, stores: OnlineStores
) -> None:
    placeholder = f"{CDN}/cover//1000x1000.jpg"
    web.searches[("album", "Ozzle Prime Copper Harbor")] = [
        deezer_album(1, "Copper Harbor", "Ozzle Prime", placeholder)
    ]
    web.searches[("track", "Ozzle Prime Copper Harbor")] = [
        deezer_track("Static Lake", "Ozzle Prime", "Copper Harbor", art("song"))
    ]

    assert await stores.album_art(OURS, "Copper Harbor", TITLES) == art("song")


async def test_a_renamed_artist_is_matched_by_title_only_with_tracklist_proof(
    web: StoreWeb, stores: OnlineStores, pauses: Pauses
) -> None:
    web.searches[("album", "Late Registration")] = [
        deezer_album(10, "Late Registration", "Tribute Kids", art("tribute")),
        deezer_album(11, "Late Registration", "Vexley Moon", art("renamed")),
    ]
    web.tracklists["10"] = ["Intro", "Skit", "Copper Harbor"]
    web.tracklists["11"] = ["Copper Harbor", "Static Lake", "Bonus", "Neon Kettle"]

    assert await stores.album_art(("Vex", "Vex"), "Late Registration", TITLES) == art("renamed")
    assert pauses == [0.2, 0.2, 0.2]


async def test_a_same_titled_album_by_someone_else_is_never_taken(
    web: StoreWeb, stores: OnlineStores
) -> None:
    web.searches[("album", "Late Registration")] = [
        deezer_album(10, "Late Registration", "Tribute Kids", art("tribute"))
    ]
    web.tracklists["10"] = ["Intro", "Skit", "Copper Harbor"]

    assert await stores.album_art(("Vex", "Vex"), "Late Registration", TITLES) is None


async def test_without_a_match_every_store_is_asked_at_its_own_pace(
    web: StoreWeb, stores: OnlineStores, pauses: Pauses
) -> None:
    assert await stores.album_art(("Vex", "Vex"), "Late Registration", TITLES) is None

    assert pauses == [0.2] * 5 + [3.0] * 4
    assert web.asked(DEEZER_HOST) == [
        "Vex Late Registration",
        "Vex Late Registration",
        "Late Registration",
        "Vex",
        "Vex",
    ]
    assert web.asked(ITUNES_HOST) == ["Vex Late Registration"] * 4
    assert [(url.params["country"], url.params["entity"]) for url in web.seen[5:]] == [
        ("US", "album"),
        ("US", "song"),
        ("RU", "album"),
        ("RU", "song"),
    ]


async def test_singles_are_matched_by_one_of_their_first_three_songs(
    web: StoreWeb, stores: OnlineStores
) -> None:
    credits = ("Kiro Delta", "Kiro Delta & Wexa")
    web.searches[("track", "Kiro Delta Static Lake")] = [
        deezer_track("Static Lake", "Wexa", "Static Lake - Single", art("single"))
    ]
    found = await stores.album_art(credits, SINGLES, TITLES)
    web.searches = {
        ("track", "Kiro Delta Paper Owl"): [
            deezer_track("Paper Owl", "Kiro Delta", "Paper Owl", art("fourth"))
        ]
    }
    web.seen.clear()
    fourth = await stores.album_art(credits, SINGLES, TITLES)

    assert found == art("single")
    assert fourth is None
    assert web.asked(DEEZER_HOST) == [f"Kiro Delta {title}" for title in TITLES[:3]]


async def test_a_deezer_quota_error_is_transient_while_itunes_still_answers(
    web: StoreWeb, stores: OnlineStores
) -> None:
    web.quota = True
    web.itunes[("US", "album", "Ozzle Prime Copper Harbor")] = [
        {
            "artistName": "Ozzle Prime",
            "collectionName": "Copper Harbor",
            "artworkUrl100": f"{CDN}/itunes/100x100bb.jpg",
        }
    ]

    assert await stores.album_art(OURS, "Copper Harbor", TITLES) == f"{CDN}/itunes/600x600bb.jpg"


async def test_a_store_failure_is_raised_when_no_other_store_matched(
    web: StoreWeb, stores: OnlineStores
) -> None:
    web.quota = True

    with pytest.raises(TransientError, match="Quota limit exceeded"):
        await stores.album_art(OURS, "Copper Harbor", TITLES)
    assert len(web.asked(ITUNES_HOST)) == 4


async def test_the_artist_discography_finds_what_the_searches_miss(
    web: StoreWeb, stores: OnlineStores
) -> None:
    web.searches[("artist", "Ozzle Prime")] = [{"id": 7, "name": "Ozzle Prime", "nb_fan": 120}]
    web.discographies["7"] = [
        [
            deezer_album(1, "Copper Harbor", "Ozzle Prime", f"{CDN}/cover//1000x1000.jpg"),
            deezer_album(2, "Static", "Ozzle Prime", art("static")),
        ],
        [deezer_album(3, "Copper Harbor (Deluxe)", "Ozzle Prime", art("deluxe"))],
    ]

    assert await stores.album_art(OURS, "Copper Harbor", TITLES) == art("deluxe")
    assert [str(url) for url in web.seen if url.path.endswith("/albums")] == [
        f"https://{DEEZER_HOST}/artist/7/albums?limit=500",
        f"https://{DEEZER_HOST}/artist/7/albums?limit=500&index=1",
    ]


async def test_an_artist_picture_prefers_the_exact_name_then_the_most_fans(
    web: StoreWeb, stores: OnlineStores
) -> None:
    web.searches[("artist", "Sable Pylon")] = [
        {"name": "Sable Pylon", "nb_fan": 12, "picture_xl": art("tiny")},
        {"name": "Sable Pylon & Wexa", "nb_fan": 900000, "picture_xl": art("duo")},
        {"name": "Sable Pylon", "nb_fan": 4000, "picture_xl": art("known")},
    ]
    exact = await stores.artist_picture("Sable Pylon")
    web.searches[("artist", "Sable Pylon")] = [
        {"name": "Somebody Else", "nb_fan": 900000, "picture_xl": art("else")},
        {"name": "Sable Pylon & Wexa", "nb_fan": 9, "picture_xl": art("duo")},
    ]
    collaboration = await stores.artist_picture("Sable Pylon")

    assert (exact, collaboration) == (art("known"), art("duo"))


async def test_a_short_name_needs_an_exact_match_and_a_placeholder_is_no_picture(
    web: StoreWeb, stores: OnlineStores
) -> None:
    web.searches[("artist", "Oz")] = [{"name": "Oz & Wexa", "nb_fan": 50, "picture_xl": art("duo")}]
    collaboration = await stores.artist_picture("Oz")
    web.searches[("artist", "Oz")] = [
        {"name": "OZ", "nb_fan": 1, "picture_xl": f"{CDN}/artist//1000x1000.jpg"}
    ]
    placeholder = await stores.artist_picture("Oz")

    assert (collaboration, placeholder) == (None, None)


async def test_unreachable_or_unreadable_answers_are_transient(pauses: Pauses) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/images/moved.jpg":
            return httpx.Response(302, headers={"location": f"{CDN}/ok.jpg"})
        if request.url.path == "/images/ok.jpg":
            return httpx.Response(200, content=b"jpeg")
        if request.url.path == "/images/down.jpg":
            raise httpx.ConnectError("refused", request=request)
        if request.url.host == DEEZER_HOST:
            return httpx.Response(200, text="<html>busy</html>")
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        stores = OnlineStores(client, sleep=pauses)
        assert await stores.download(f"{CDN}/moved.jpg") == b"jpeg"
        for url in (f"{CDN}/gone.jpg", f"{CDN}/down.jpg"):
            with pytest.raises(TransientError):
                await stores.download(url)
        with pytest.raises(TransientError):
            await stores.artist_picture("Sable Pylon")
