import pytest

from muse.artwork.domain import artist_key, credit, norm, same_title, same_tracks


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Meteora (Deluxe Edition)", "meteora"),
        ("[Remastered] Hybrid Theory", "hybridtheory"),
        ("Copper Harbor - Single", "copperharbor"),
        ("Copper Harbor - ep", "copperharbor"),
        ("Ёлка и Лёд", "елкаилед"),
        ("a_b-c d", "abcd"),
        ("?!", "?!"),
        (None, ""),
    ],
)
def test_titles_compare_without_editions_punctuation_or_case(
    title: str | None, expected: str
) -> None:
    assert norm(title) == expected


@pytest.mark.parametrize(
    ("credited", "expected"),
    [
        ("42 Dugg & EST Gee", {"42dugg", "estgee", "42duggestgee"}),
        ("Kiro Delta, Wexa", {"kirodelta", "wexa", "kirodeltawexa"}),
        ("Kiro Delta x Wexa", {"kirodelta", "wexa", "kirodeltaxwexa"}),
        ("Kiro Delta feat. Wexa", {"kirodelta", "wexa", "kirodeltafeatwexa"}),
        ("Kiro Delta ft Wexa", {"kirodelta", "wexa", "kirodeltaftwexa"}),
        ("Maxx", {"maxx"}),
        (None, set()),
    ],
)
def test_a_credit_names_every_artist_and_the_whole_line(
    credited: str | None, expected: set[str]
) -> None:
    assert credit(credited) == expected


@pytest.mark.parametrize(
    ("ours", "theirs", "expected"),
    [
        ("meteora", "meteora", True),
        ("meteora", "meteora20thanniversaryedition", True),
        ("abcd", "abcdlive", True),
        ("abc", "abclive", False),
        ("meteora", "hybridtheory", False),
        ("", "", False),
    ],
)
def test_a_title_matches_itself_or_an_extension_of_four_plus_chars(
    ours: str, theirs: str, expected: bool
) -> None:
    assert same_title(ours, theirs) is expected
    assert same_title(theirs, ours) is expected


@pytest.mark.parametrize(
    ("ours", "theirs", "expected"),
    [
        (["One", "Two", "Three", "Four"], ["one", "TWO", "Three (Live)", "Other"], True),
        (["One", "Two", "Three", "Four", "Five", "Six"], ["One", "Two", "Three"], False),
        (["One", "Two"], ["One", "Two"], False),
        (["One", "Two", "Three", "", None], ["One", "Two", "Three"], True),
    ],
)
def test_a_tracklist_proves_an_album_with_three_shared_titles_and_sixty_percent(
    ours: list[str | None], theirs: list[str | None], expected: bool
) -> None:
    assert same_tracks(ours, theirs) is expected


def test_artist_images_keep_the_sha1_file_names_of_the_existing_cache() -> None:
    assert artist_key("Sable Pylon") == "6b70d9edac896b8cf3d7a2bff88f4be8dbbce45d"
