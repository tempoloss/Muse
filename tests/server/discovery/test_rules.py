import math
import random
from collections import Counter
from datetime import date, timedelta
from itertools import pairwise

from muse.discovery.domain import (
    MIX_SIZE,
    RadioTaste,
    Track,
    build_radio_model,
    draw_mix,
    draw_radio,
    excluded_ids,
    spaced,
)

NOBODY = RadioTaste(set(), set())


def track(track_id: int, artist: str, genre: str | None = "Rap") -> Track:
    return {
        "id": track_id,
        "num": 1,
        "title": f"Song {track_id}",
        "dur": 200,
        "album_id": track_id,
        "album": f"Album {track_id}",
        "artist": artist,
        "genre": genre,
    }


def library() -> list[Track]:
    tracks = [track(index, "Seed") for index in range(1, 7)]
    tracks += [track(index, "Near", "Indie") for index in range(11, 15)]
    for number in range(30):
        genre = "Rap" if number % 2 else "Indie"
        tracks += [track(100 + number * 10 + index, f"Other {number}", genre) for index in range(3)]
    return tracks


def test_artists_sharing_a_small_playlist_are_closer_than_in_a_big_one() -> None:
    model = build_radio_model([track(1, "A")], [{"A", "B"}, {"A", "B", "C", "D"}, {"E"}, set()])

    assert model.links["A"]["B"] == model.links["B"]["A"] == 1 / math.sqrt(2) + 1 / 2
    assert model.links["C"] == {"A": 0.5, "B": 0.5, "D": 0.5}
    assert model.links["E"] == {}
    assert "A" not in model.links["A"]
    assert model.by_id[1]["artist"] == "A"


def test_radio_prefers_the_seed_artist_and_its_playlist_neighbours_within_caps() -> None:
    tracks = library()
    model = build_radio_model(tracks, [{"Seed", "Near"}])
    seed = model.by_id[1]

    picked = draw_radio(model, seed, {1, 2}, NOBODY, 25, random.Random(3))

    ids = [item["id"] for item in picked]
    artists = Counter(item["artist"] for item in picked)
    assert len(ids) == len(set(ids)) == 25
    assert not {1, 2} & set(ids)
    assert (artists["Seed"], artists["Near"]) == (3, 2)
    assert max(count for artist, count in artists.items() if artist != "Seed") == 2
    assert all(a["artist"] != b["artist"] for a, b in pairwise(picked))
    assert picked[0]["artist"] != "Seed"
    assert set(picked[0]) == {"id", "num", "title", "dur", "album_id", "album", "artist"}


def test_radio_favours_my_likes_then_my_partners_likes() -> None:
    tracks = [track(index, f"Artist {index}", None) for index in range(1, 201)]
    model = build_radio_model(tracks, [])
    taste = RadioTaste(mine=set(range(150, 155)), partner=set(range(160, 165)))
    drawn: Counter[str] = Counter()
    for seed_value in range(40):
        for item in draw_radio(model, model.by_id[1], {1}, taste, 10, random.Random(seed_value)):
            mine, partner = item["id"] in taste.mine, item["id"] in taste.partner
            drawn["mine" if mine else "partner" if partner else "other"] += 1

    assert drawn["mine"] / 5 > drawn["partner"] / 5 > drawn["other"] / 189


def test_spacing_avoids_the_same_artist_twice_in_a_row_while_it_can() -> None:
    picked = [track(1, "A"), track(2, "A"), track(3, "B"), track(4, "C"), track(5, "A")]

    order = [item["id"] for item in spaced(picked, "A")]

    assert order == [3, 1, 4, 2, 5]


def test_excluded_ids_take_the_first_300_numeric_items() -> None:
    assert excluded_ids("5, 7,x,,-3,8 ,4.5") == {5, 7, 8}
    assert excluded_ids(",".join(str(index) for index in range(1, 400))) == set(range(1, 301))
    assert excluded_ids("") == set()


def test_a_mix_favours_liked_then_played_tracks() -> None:
    tracks = [track(index, f"Artist {index}") for index in range(150)]
    liked, played = set(range(50)), set(range(50, 100))
    shown: Counter[str] = Counter()
    for offset in range(30):
        day = date(2026, 1, 1) + timedelta(days=offset)
        mix = draw_mix(tracks, liked, played, random.Random(f"alice:Rap:{day}"))
        assert len(mix) == MIX_SIZE
        for item in mix:
            kind = "liked" if item["id"] in liked else "played" if item["id"] in played else "new"
            shown[kind] += 1

    assert shown["liked"] > shown["played"] > shown["new"]


def test_a_small_genre_mixes_every_track_once() -> None:
    tracks = [track(index, "A") for index in range(7)]

    mix = draw_mix(tracks, set(), set(), random.Random("bob:Indie:2026-01-17"))

    assert sorted(item["id"] for item in mix) == list(range(7))
