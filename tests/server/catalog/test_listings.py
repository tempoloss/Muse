from collections import Counter, defaultdict
from urllib.parse import quote

import httpx

from muse.settings import Settings
from tests.fixtures.catalog import (
    GENRES,
    RENAMED_CANONICAL,
    RENAMED_TAG,
    SINGLES_ALBUM,
    SINGLES_CREDIT,
    SINGLES_DISPLAY,
    FixtureCatalog,
)
from tests.server.catalog.support import fixture_rows, identity

OK_TRACKS = (
    "SELECT t.id, t.artist, t.album_id, a.genre FROM tracks t "
    "JOIN albums a ON a.id=t.album_id WHERE t.status='ok'"
)


async def test_listings_need_a_session(client: httpx.AsyncClient) -> None:
    for path in ("/api/genres", "/api/albums", "/api/artists", "/api/search?q=ab"):
        assert (await client.get(path)).status_code == 401


async def test_genres_count_playable_tracks_and_artist_identities(
    alice: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    names = identity(library)
    tracks: Counter[str] = Counter()
    artists: defaultdict[str, set[str]] = defaultdict(set)
    for row in fixture_rows(library, OK_TRACKS):
        tracks[row["genre"]] += 1
        artists[row["genre"]].add(names[row["artist"]])

    genres = (await alice.get("/api/genres")).json()

    assert {g["genre"] for g in genres} == set(GENRES)
    assert [g["tracks"] for g in genres] == sorted((g["tracks"] for g in genres), reverse=True)
    assert {g["genre"]: (g["tracks"], g["artists"]) for g in genres} == {
        genre: (tracks[genre], len(artists[genre])) for genre in GENRES
    }


async def test_artists_are_listed_and_found_by_their_canonical_name(
    alice: httpx.AsyncClient,
) -> None:
    everyone = {a["name"] for a in (await alice.get("/api/artists")).json()}
    russian = (await alice.get("/api/artists", params={"genre": "RU Rap"})).json()
    page = await alice.get(f"/api/artist/{quote(RENAMED_CANONICAL)}")
    raw = await alice.get(f"/api/artist/{quote(RENAMED_TAG)}")

    assert RENAMED_CANONICAL in everyone
    assert RENAMED_TAG not in everyone
    assert RENAMED_CANONICAL in {a["name"] for a in russian}
    assert len(russian) < len(everyone)
    assert page.status_code == 200
    assert (page.json()["name"], page.json()["genre"]) == (RENAMED_CANONICAL, "RU Rap")
    assert (raw.status_code, raw.json()) == (404, {"detail": "no such artist"})


async def test_singles_are_named_by_their_credit_and_searchable(alice: httpx.AsyncClient) -> None:
    albums = (await alice.get("/api/albums")).json()
    singles = next(a for a in albums if a["name"] == SINGLES_DISPLAY)

    found = (await alice.get("/api/search", params={"q": SINGLES_CREDIT.upper()})).json()

    assert singles["id"] in [a["id"] for a in found["albums"]]
    assert {"id", "name", "year", "genre", "artist", "ntracks"} == set(singles)
    rap = (await alice.get("/api/albums", params={"genre": "Rap"})).json()
    assert singles["id"] in [a["id"] for a in rap]
    assert {a["genre"] for a in rap} == {"Rap"}


async def test_an_album_page_lists_playable_tracks_in_order(
    alice: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    broken = fixture_rows(
        library,
        "SELECT album_id FROM tracks WHERE status<>'ok' AND album_id IN "
        "(SELECT album_id FROM tracks WHERE status='ok') LIMIT 1",
    )[0]["album_id"]
    playable = [
        row["id"]
        for row in fixture_rows(
            library,
            "SELECT id FROM tracks WHERE album_id=? AND status='ok' ORDER BY num",
            (broken,),
        )
    ]

    album = (await alice.get(f"/api/album/{broken}")).json()
    missing = await alice.get("/api/album/999999")

    assert [t["id"] for t in album["tracks"]] == playable
    assert set(album["tracks"][0]) == {"id", "num", "title", "dur"}
    assert album["cover"] == f"/api/cover/{broken}"
    assert (missing.status_code, missing.json()) == (404, {"detail": "no album"})


async def test_album_pages_show_the_canonical_artist_and_keep_the_singles_name(
    alice: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    renamed = fixture_rows(library, "SELECT id FROM albums WHERE artist=?", (RENAMED_TAG,))[0]
    singles = fixture_rows(library, "SELECT id FROM albums WHERE name=?", (SINGLES_ALBUM,))[0]

    renamed_page = (await alice.get(f"/api/album/{renamed['id']}")).json()
    singles_page = (await alice.get(f"/api/album/{singles['id']}")).json()

    assert renamed_page["artist"] == RENAMED_CANONICAL
    assert (singles_page["name"], singles_page["artist"]) == (SINGLES_ALBUM, SINGLES_CREDIT)


async def test_search_needs_two_characters_and_folds_case(alice: httpx.AsyncClient) -> None:
    short = (await alice.get("/api/search", params={"q": "П"})).json()
    found = (await alice.get("/api/search", params={"q": "пирОМ"})).json()
    single = (await alice.get("/api/search", params={"q": "a"})).json()
    many = (await alice.get("/api/search", params={"q": "ER"})).json()

    assert short == single == {"artists": [], "albums": [], "tracks": []}
    assert RENAMED_CANONICAL in [a["name"] for a in found["artists"]]
    assert all(len(many[kind]) <= 20 for kind in ("artists", "albums", "tracks"))
    assert len(many["tracks"]) == 20


async def test_only_playable_tracks_are_shown(
    alice: httpx.AsyncClient, library: FixtureCatalog
) -> None:
    ok = fixture_rows(library, "SELECT id FROM tracks WHERE status='ok' LIMIT 1")[0]["id"]
    pending = fixture_rows(library, "SELECT id FROM tracks WHERE status='pending' LIMIT 1")[0]["id"]

    track = await alice.get(f"/api/track/{ok}")
    gone = await alice.get(f"/api/track/{pending}")

    assert set(track.json()) == {"id", "title", "album", "artist", "dur", "num", "album_id"}
    assert (gone.status_code, gone.json()) == (404, {"detail": "no track"})


async def test_a_genre_lists_every_playable_track_with_covered_albums(
    alice: httpx.AsyncClient, library: FixtureCatalog, settings: Settings
) -> None:
    genres = (await alice.get("/api/genres")).json()
    biggest = max(genres, key=lambda g: g["tracks"])["genre"]
    expected = {row["id"] for row in fixture_rows(library, OK_TRACKS) if row["genre"] == biggest}
    first = await alice.get(f"/api/genre/{quote(biggest)}")
    order = list(dict.fromkeys(t["album_id"] for t in first.json()["tracks"]))
    settings.paths.covers_dir.mkdir()
    for album_id in (order[3], order[1]):
        (settings.paths.covers_dir / f"{album_id}.jpg").write_bytes(b"jpg")

    page = (await alice.get(f"/api/genre/{quote(biggest)}")).json()
    unknown = await alice.get("/api/genre/no-such-genre")

    assert {t["id"] for t in page["tracks"]} == expected
    assert len(page["tracks"]) > 50
    assert (page["genre"], page["title"]) == (biggest, biggest)
    assert page["albums"] == [order[1], order[3]]
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "no such genre"})
