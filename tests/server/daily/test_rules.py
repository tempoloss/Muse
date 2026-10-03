from collections import Counter
from datetime import date
from typing import Any

import pytest

from muse.catalog.domain import LibraryTrack
from muse.daily.domain import (
    DailyDraft,
    DailyRecord,
    Listening,
    daily_build,
    daily_pool,
    daily_prompt,
    daily_topup,
    reply_playlists,
    shown_order,
)
from muse.discovery.domain import RadioModel, build_radio_model
from muse.identity.domain import User

DAY = date(2026, 1, 15)
GENRES = ("Rap", "Indie", None)
USERS = (
    User(
        id="alice",
        login="alice",
        name="Алиса",
        animal="fox",
        theme="light",
        emoji="🦊",
        nick="Лисёнок",
    ),
    User(
        id="bob",
        login="Bob",
        name="Боб",
        animal="bear",
        theme="dark",
        emoji="🐻",
        nick="Мишка",
        name_gen="Боба",
        name_dat="Бобу",
    ),
)
NOTHING = Listening({"alice": [], "bob": []}, {"alice": {}, "bob": {}}, set())


def track(track_id: int, artist: str, genre: str | None = "Rap") -> LibraryTrack:
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


def library(artists: int, per_artist: int, playlists: list[set[str]] | None = None) -> RadioModel:
    tracks = [
        track(artist * 10 + index, f"Artist {artist}", GENRES[artist % 3])
        for artist in range(1, artists + 1)
        for index in range(per_artist)
    ]
    return build_radio_model(tracks, playlists or [])


def one_per_artist(first: int, count: int) -> list[int]:
    return [artist * 10 for artist in range(first, first + count)]


def playlist(
    title: str, tracks: list[Any], owner: object = "both", blurb: object = ""
) -> dict[str, Any]:
    return {"for": owner, "title": title, "blurb": blurb, "tracks": tracks}


def build(raw: object, model: RadioModel, pool_ids: set[int] | None = None) -> list[DailyDraft]:
    return daily_build(raw, pool_ids or set(model.by_id), model, USERS, DAY)


def artist_of(model: RadioModel, track_id: int) -> str:
    return model.by_id[track_id]["artist"]


def test_a_playlist_keeps_pool_tracks_once_and_three_per_artist() -> None:
    model = library(40, 4)
    pool_ids = set(model.by_id) - {400, 401, 402, 403}
    picks = [10, 11, 12, 13, 999999, "x", 10, "20", " 30 ", 3.0, 400, *one_per_artist(4, 10)]

    (draft,) = build([playlist("Утро", picks)], model, pool_ids)

    assert draft.tracks[:15] == [10, 11, 12, 20, 30, *one_per_artist(4, 10)]
    assert (draft.picked, len(draft.tracks), len(set(draft.tracks))) == (15, 25, 25)
    extra = Counter(artist_of(model, track_id) for track_id in draft.tracks[15:])
    assert set(extra) <= {f"Artist {number}" for number in range(2, 14)}
    assert max(Counter(artist_of(model, track_id) for track_id in draft.tracks).values()) == 3


def test_short_playlists_are_dropped_full_ones_kept_long_ones_cut() -> None:
    model = library(40, 4)
    raw = [
        playlist("Мало", one_per_artist(1, 11)),
        playlist("Ровно", one_per_artist(1, 12)),
        playlist("Полный", one_per_artist(1, 25)),
        playlist("Длинный", one_per_artist(1, 40)),
    ]

    drafts = build(raw, model)

    assert [(d.title, d.picked, len(d.tracks)) for d in drafts] == [
        ("Ровно", 12, 25),
        ("Полный", 25, 25),
        ("Длинный", 30, 30),
    ]
    assert drafts[2].tracks == one_per_artist(1, 30)


def test_titles_must_be_present_and_distinct_and_texts_are_squeezed() -> None:
    model = library(20, 2)
    tracks = one_per_artist(1, 12)
    raw = [
        playlist("   ", tracks),
        playlist("  Ночь \n в  городе ", tracks, blurb="  тихо \t и  тепло "),
        playlist(" ночь в ГОРОДЕ", tracks),
        playlist("Т" * 80, tracks, blurb="б" * 200),
        playlist("Без описания", tracks, blurb=None),
    ]

    drafts = build(raw, model)

    assert [(d.title, d.blurb) for d in drafts] == [
        ("Ночь в городе", "тихо и тепло"),
        ("Т" * 60, "б" * 140),
        ("Без описания", ""),
    ]


@pytest.mark.parametrize(
    ("owner", "expected"),
    [
        ("alice", "alice"),
        (" BOB ", "bob"),
        ("Боб", "bob"),
        ("алиса", "alice"),
        ("both", "both"),
        ("nobody", "both"),
        (None, "both"),
    ],
)
def test_owners_resolve_by_id_or_name_else_both(owner: object, expected: str) -> None:
    model = library(20, 1)

    (draft,) = build([playlist("Вместе", one_per_artist(1, 12), owner=owner)], model)

    assert draft.owner == expected


def test_at_most_eight_playlists_are_kept_and_junk_is_ignored() -> None:
    model = library(20, 1)
    raw = ["junk", None, *(playlist(f"P{n}", one_per_artist(1, 12)) for n in range(10))]

    assert [draft.title for draft in build(raw, model)] == [f"P{n}" for n in range(8)]
    assert build({"playlists": raw}, model) == []
    assert build(None, model) == []


def test_topup_brings_near_artists_without_repeats_or_a_fourth_track() -> None:
    model = library(10, 4, playlists=[{"Artist 1", "Artist 2"}])

    extra = daily_topup([10, 11], 10, model, DAY)

    assert not {10, 11} & set(extra)
    assert Counter(artist_of(model, track_id) for track_id in extra) == {
        "Artist 1": 1,
        "Artist 2": 3,
    }
    assert daily_topup([10, 11], 2, model, DAY) == extra[:2]


def test_the_pool_keeps_favourites_and_adds_unheard_tracks_around_them() -> None:
    model = library(100, 3)
    listening = Listening(
        likes={"alice": [10, 20], "bob": []},
        plays={"alice": {}, "bob": {30: 5, 31: 1}},
        heard={30, 31, 40, 41, 42},
    )

    pool = [item["id"] for item in daily_pool(DAY, model, USERS, listening)]

    assert {10, 20, 30, 31} <= set(pool)
    assert not {40, 41, 42} & set(pool)
    assert {11, 12, 21, 22, 32} <= set(pool)
    assert len(pool) == len(set(pool)) <= 4 + 160 + 40
    assert [item["id"] for item in daily_pool(DAY, model, USERS, listening)] == pool
    tomorrow = daily_pool(date(2026, 1, 16), model, USERS, listening)
    assert [item["id"] for item in tomorrow] != pool


def test_the_prompt_lists_every_pool_track_with_our_marks() -> None:
    model = build_radio_model([track(1, "Kiro", "Rap"), track(2, "Wexa", None)], [])
    listening = Listening({"alice": [1], "bob": []}, {"alice": {}, "bob": {1: 3}}, {1})

    prompt = daily_prompt(DAY, list(model.tracks), model, USERS, listening, ["Утро", "Вечер"])

    assert "\n1|Kiro — Song 1|Rap|♥А ▶Б3\n2|Wexa — Song 2|-|новое\n" in prompt
    assert "Сегодня четверг, 15 января." in prompt
    assert "- Алиса: Kiro; жанры: Rap\n- Боб: Kiro; жанры: Rap\n" in prompt
    assert "не повторяй их: Утро; Вечер." in prompt
    assert '2 для Алиса ("for": "alice"), 2 для Боба ("for": "bob")' in prompt
    assert (
        "Метки: ♥А — нравится Алиса, ♥Б — нравится Бобу, ▶А3 — Алиса слушал 3 раза, "
        "новое — ещё никто из них не слушал." in prompt
    )


def test_a_prompt_without_history_says_so() -> None:
    model = build_radio_model([track(1, "Kiro")], [])

    prompt = daily_prompt(date(2026, 3, 1), list(model.tracks), model, USERS, NOTHING, [])

    assert "Сегодня воскресенье, 1 марта." in prompt
    assert "- Алиса: пока мало данных; жанры: —" in prompt
    assert "не повторяй их: их пока нет." in prompt


def test_replies_are_read_from_their_outermost_json_object() -> None:
    fenced = '```json\n{"playlists": [{"title": "x", "tracks": [1]}]}\n```'

    assert reply_playlists(fenced) == [{"title": "x", "tracks": [1]}]
    assert reply_playlists("не JSON") is None
    with pytest.raises(ValueError):
        reply_playlists('{"playlists": [1,}')


def test_a_day_shows_mine_then_ours_then_my_partners() -> None:
    def record(owner: str, slot: int) -> DailyRecord:
        return {
            "id": slot,
            "day": "2026-01-15",
            "slot": slot,
            "for_user": owner,
            "title": f"T{slot}",
            "blurb": "",
            "tracks": [],
            "model": "m",
            "created_at": 0,
        }

    rows = [
        record(owner, slot) for slot, owner in enumerate(("bob", "both", "alice", "bob", "both"))
    ]

    def order(user_id: str) -> list[tuple[str, int]]:
        return [(row["for_user"], row["slot"]) for row in shown_order(rows, user_id)]

    assert order("alice") == [("alice", 2), ("both", 1), ("both", 4), ("bob", 0), ("bob", 3)]
    assert order("bob") == [("bob", 0), ("bob", 3), ("both", 1), ("both", 4), ("alice", 2)]
