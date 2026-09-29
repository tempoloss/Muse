from dataclasses import replace
from datetime import date

import pytest

from muse.pet.domain import (
    PET_SLEEP_MS,
    Pet,
    QuestPick,
    album_progress,
    cared,
    drawn_album,
    mood,
    quest_kind,
    quest_view,
    sampled_likes,
    ticked,
    together_progress,
    turn_share,
    valid_name,
)
from muse.shared.errors import DomainError

HOUR = 3600 * 1000
NOW = 1_800_000_000_000


def pet(**fields: object) -> Pet:
    base = Pet(
        name=None,
        born_at=0,
        food=50,
        joy=50,
        energy=50,
        clean=50,
        sick=False,
        asleep_until=None,
        updated_at=NOW,
    )
    return replace(base, **fields)


def album(album_id: int, ntracks: int) -> dict[str, object]:
    return {"id": album_id, "name": f"A{album_id}", "artist": "X", "ntracks": ntracks, "year": None}


def test_a_neglected_pet_starves_into_sickness() -> None:
    later = ticked(pet(updated_at=NOW - 30 * HOUR), NOW)

    assert (later.food, later.joy, later.energy, later.clean) == (0, 0, 0, 0)
    assert later.sick is True
    assert later.updated_at == NOW
    assert mood(later, together=True) == "sick"


def test_a_sick_pet_loses_joy_twice_as_fast() -> None:
    healthy = ticked(pet(updated_at=NOW - 2 * HOUR), NOW)
    sick = ticked(pet(updated_at=NOW - 2 * HOUR, sick=True), NOW)

    assert (healthy.joy, sick.joy) == (44, 38)
    assert healthy.food == sick.food == 42


def test_sleep_restores_energy_until_the_alarm_then_the_pet_decays_awake() -> None:
    asleep = pet(energy=20, asleep_until=NOW - HOUR, updated_at=NOW - 3 * HOUR)

    later = ticked(asleep, NOW)

    assert later.asleep_until is None
    assert later.energy == 20 + 2 * 15 - 2.5
    assert later.food == 50 - 2 * 2 - 4


def test_a_rested_pet_wakes_before_its_alarm() -> None:
    rested = ticked(pet(energy=95, asleep_until=NOW + HOUR, updated_at=NOW - HOUR), NOW)
    dozing = ticked(pet(energy=50, asleep_until=NOW + HOUR, updated_at=NOW - HOUR), NOW)

    assert (rested.energy, rested.asleep_until) == (100, None)
    assert dozing.asleep_until == NOW + HOUR


def test_time_never_runs_backwards() -> None:
    assert ticked(pet(updated_at=NOW + HOUR), NOW) == pet(updated_at=NOW + HOUR)


@pytest.mark.parametrize(
    ("fields", "together", "expected"),
    [
        ({"asleep_until": NOW + HOUR}, True, "sleeping"),
        ({}, True, "dancing"),
        ({"food": 24.9, "clean": 0}, False, "hungry"),
        ({"clean": 29.9}, False, "dirty"),
        ({"joy": 70, "food": 50}, False, "happy"),
        ({"joy": 69.9}, False, "idle"),
    ],
)
def test_mood(fields: dict[str, object], together: bool, expected: str) -> None:
    assert mood(pet(**fields), together) == expected


def test_feeding_twice_in_a_row_by_the_same_carer_counts_half() -> None:
    assert turn_share("feed", "alice", "alice") == 0.5
    assert turn_share("feed", "bob", "alice") == 1
    assert turn_share("feed", None, "alice") == 1
    assert turn_share("sleep", "alice", "alice") == 1
    assert cared(pet(food=90), "feed", 1, NOW).pet.food == 100
    assert cared(pet(), "feed", 0.5, NOW).pet.food == 62.5


def test_play_costs_energy_and_food_and_needs_energy() -> None:
    played = cared(pet(), "play", 1, NOW)

    assert (played.pet.joy, played.pet.energy, played.pet.food) == (70, 40, 45)
    with pytest.raises(DomainError, match="tired"):
        cared(pet(energy=9.9), "play", 1, NOW)


def test_a_sleeping_pet_only_wakes_or_heals() -> None:
    asleep = pet(asleep_until=NOW + HOUR, sick=True, food=10)

    for action in ("feed", "play", "wash"):
        with pytest.raises(DomainError, match="asleep"):
            cared(asleep, action, 1, NOW)
    woken = cared(asleep, "sleep", 1, NOW)
    healed = cared(asleep, "heal", 1, NOW)

    assert (woken.pet.asleep_until, woken.logged_as) == (None, "wake")
    assert (healed.pet.sick, healed.pet.food, healed.pet.joy) == (False, 30, 50)


def test_sleep_sets_the_alarm_and_wash_cleans() -> None:
    slept = cared(pet(), "sleep", 1, NOW)

    assert (slept.pet.asleep_until, slept.logged_as) == (NOW + PET_SLEEP_MS, "sleep")
    assert cared(pet(clean=10), "wash", 0.5, NOW).pet.clean == 40
    with pytest.raises(DomainError, match="healthy"):
        cared(pet(), "heal", 1, NOW)


@pytest.mark.parametrize(
    ("name", "ok"), [("", False), ("Ёж", True), ("x" * 24, True), ("x" * 25, False)]
)
def test_pet_names_are_1_to_24_characters(name: str, ok: bool) -> None:
    assert valid_name(name) is ok


@pytest.mark.parametrize(
    ("day", "kind"),
    [
        (date(2026, 1, 17), "letters"),
        (date(2026, 1, 18), "shared_like"),
        (date(2026, 1, 21), "together"),
        (date(2026, 1, 29), "same_album"),
    ],
)
def test_the_quest_of_the_day_is_seeded_by_the_date(day: date, kind: str) -> None:
    assert quest_kind(day) == kind


def test_the_drawn_album_is_seeded_by_the_date_among_albums_doable_in_a_day() -> None:
    albums = [album(1, 4), album(2, 5), album(3, 14), album(4, 15), album(5, 9)]

    drawn = [drawn_album(albums, date(2026, 1, day)) for day in range(1, 29)]

    assert {pick["id"] if pick else None for pick in drawn} == {2, 3, 5}
    assert drawn_album(albums, date(2026, 1, 3)) == album(5, 9)
    assert drawn_album([album(1, 4), album(4, 15)], date(2026, 1, 3)) is None


def test_album_progress_needs_80_percent_from_each_listener() -> None:
    progress = album_progress(album(7, 9), {"alice": 9, "bob": 3}, ["alice", "bob"])

    assert progress.album == {"id": 7, "name": "A7", "artist": "X", "ntracks": 9, "need": 8}
    assert progress.parts == [
        {"user": "alice", "progress": 8, "goal": 8},
        {"user": "bob", "progress": 3, "goal": 8},
    ]
    assert (progress.progress, progress.goal, progress.text) == (
        11,
        16,
        "Послушаем альбом «A7» — X",
    )


def test_quest_like_samples_are_seeded_per_listener_and_day() -> None:
    theirs = list(range(100, 160))

    sample = sampled_likes("alice", date(2026, 1, 17), theirs)

    assert (len(sample), sample[:5]) == (20, [129, 137, 149, 104, 154])
    assert sampled_likes("bob", date(2026, 1, 17), theirs) != sample
    assert sampled_likes("alice", date(2026, 1, 17), [5]) == [5]


def test_together_progress_counts_whole_minutes_up_to_ten() -> None:
    assert [together_progress(s) for s in (0, 59.9, 60, 599, 3600)] == [0, 0, 1, 9, 10]


def test_a_quest_is_done_at_its_goal_and_names_who_picked_it() -> None:
    progress = album_progress(album(7, 5), {"alice": 4, "bob": 4}, ["alice", "bob"])

    view = quest_view("same_album", progress, QuestPick("same_album", 7, "bob"))

    assert (view["done"], view["picked_by"], view["goal"]) == (True, "bob", 8)
