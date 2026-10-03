from muse.catalog.domain import SINGLES
from muse.lyrics.domain import (
    Record,
    album_param,
    lyrics_of,
    pick,
    synced_lines,
)


def record(duration: float | None, synced: str | None = None, plain: str | None = None) -> Record:
    return Record(duration=duration, instrumental=False, plain=plain, synced=synced)


def test_a_line_keeps_every_stamp_it_carries() -> None:
    lrc = "[00:12.00][01:30.50]дважды"

    assert synced_lines(lrc) == [{"at": 12.0, "text": "дважды"}, {"at": 90.5, "text": "дважды"}]


def test_stamps_take_seconds_as_hundredths_or_thousandths() -> None:
    lrc = "[00:07]раз\n[01:02.5]два\n[03:04.125]три"

    assert synced_lines(lrc) == [
        {"at": 7.0, "text": "раз"},
        {"at": 62.5, "text": "два"},
        {"at": 184.125, "text": "три"},
    ]


def test_metadata_tags_are_not_lines() -> None:
    lrc = "[ar:Кино]\n[ti:Звезда]\n[length:03:12]\n[00:01.00]текст"

    assert synced_lines(lrc) == [{"at": 1.0, "text": "текст"}]


def test_a_break_is_a_line_with_empty_text() -> None:
    lrc = "[00:10.00]первая\n[00:20.00]\n[00:30.00]вторая"

    assert synced_lines(lrc) == [
        {"at": 10.0, "text": "первая"},
        {"at": 20.0, "text": ""},
        {"at": 30.0, "text": "вторая"},
    ]


def test_lines_come_out_in_time_order() -> None:
    lrc = "[00:30.00]позже\n[00:10.00]раньше"

    assert [line["text"] for line in synced_lines(lrc) or []] == ["раньше", "позже"]


def test_no_stamps_no_synced_lines() -> None:
    assert synced_lines(None) is None
    assert synced_lines("просто текст песни") is None
    assert synced_lines("") is None


def test_singles_are_not_asked_for_by_album() -> None:
    assert album_param(SINGLES) is None
    assert album_param("Синглы · Кино") is None
    assert album_param("Группа крови") == "Группа крови"
    assert album_param(None) is None


def test_a_candidate_is_the_nearest_by_duration_preferring_synced() -> None:
    records = [record(100.0, synced=None, plain="plain"), record(101.5, synced="[00:01.00]a")]

    assert pick(records, 100.0) == records[1]


def test_a_candidate_out_of_slack_is_no_candidate() -> None:
    assert pick([record(96.0, synced="[00:01.00]a")], 100.0) is None
    assert pick([record(None, synced="[00:01.00]a")], 100.0) is None


def test_a_track_without_a_duration_never_matches_a_candidate() -> None:
    assert pick([record(100.0, synced="[00:01.00]a")], None) is None


def test_a_found_record_becomes_the_view_shape() -> None:
    found = lyrics_of(record(100.0, synced="[00:01.00]a", plain="a"))

    assert found == {"synced": [{"at": 1.0, "text": "a"}], "plain": "a", "instrumental": False}


def test_an_instrumental_or_missing_record_has_no_text() -> None:
    instrumental = Record(duration=100.0, instrumental=True, plain=None, synced=None)

    assert lyrics_of(instrumental) == {"synced": None, "plain": None, "instrumental": True}
    assert lyrics_of(None) == {"synced": None, "plain": None, "instrumental": False}
