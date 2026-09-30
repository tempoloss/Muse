import json
import random
from pathlib import Path

import httpx
import pytest
from structlog.testing import capture_logs

from muse.settings import Settings
from muse.together.infra.notes import NotesFiles
from tests.server.support import ManualClock

DAY_MS = 86_400_000
NOTES = [{"kind": "fact" if i % 2 else "line", "text": f"n{i}"} for i in range(1, 6)]


def daily_order(user_id: str, day: str) -> list[dict[str, str]]:
    return random.Random(f"{user_id}:notes:{day}").sample(NOTES, len(NOTES))


async def test_notes_keep_one_order_all_day_and_reshuffle_the_next(
    alice: httpx.AsyncClient,
    bob: httpx.AsyncClient,
    client: httpx.AsyncClient,
    settings: Settings,
    clock: ManualClock,
) -> None:
    settings.paths.notes_dir.mkdir()
    document = {"notes": [*NOTES, {"kind": "x", "text": "bad"}]}
    (settings.paths.notes_dir / "bob.json").write_text(json.dumps(document), encoding="utf-8")
    today = clock.today().isoformat()

    first, again = [(await bob.get("/api/notes")).json() for _ in range(2)]
    clock.ms += DAY_MS
    tomorrow = (await bob.get("/api/notes")).json()

    assert first == again == {"notes": daily_order("bob", today)}
    assert tomorrow == {"notes": daily_order("bob", clock.today().isoformat())}
    assert tomorrow != first
    assert (await alice.get("/api/notes")).json() == {"notes": []}
    assert (await client.get("/api/notes")).status_code == 401


async def test_valid_notes_are_trimmed_and_invalid_ones_are_skipped_with_a_log(
    tmp_path: Path,
) -> None:
    document = {
        "notes": [
            {"kind": "fact", "text": "  likes rain  "},
            {"kind": "line", "text": "met in May", "date": "2024-05-01"},
            {"kind": "line", "text": "no date", "date": None},
            {"kind": "line", "text": "x" * 280},
            {"kind": "quote", "text": "unknown kind"},
            {"kind": "fact", "text": "   "},
            {"kind": "fact", "text": "x" * 281},
            {"kind": "fact", "text": 7},
            {"kind": "fact", "text": "short date", "date": "2024-5-1"},
            {"kind": "fact", "text": "empty date", "date": ""},
            "plain string",
        ]
    }
    (tmp_path / "bob.json").write_text(json.dumps(document), encoding="utf-8")

    with capture_logs() as logs:
        loaded = await NotesFiles(tmp_path).notes("bob")

    assert loaded == [
        {"kind": "fact", "text": "likes rain"},
        {"kind": "line", "text": "met in May", "date": "2024-05-01"},
        {"kind": "line", "text": "no date"},
        {"kind": "line", "text": "x" * 280},
    ]
    assert [entry["event"] for entry in logs] == ["notes: bob: skipped 7 invalid entries"]


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ("{broken", "Expecting property name enclosed in double quotes"),
        ("[1, 2]", "'list' object has no attribute 'get'"),
        ('{"notes": {"kind": "fact"}}', '"notes" is not a list'),
    ],
)
async def test_an_unreadable_notes_file_counts_as_no_notes(
    tmp_path: Path, content: str, problem: str
) -> None:
    (tmp_path / "bob.json").write_text(content, encoding="utf-8")

    with capture_logs() as logs:
        loaded = await NotesFiles(tmp_path).notes("bob")

    assert loaded == []
    [entry] = logs
    assert entry["event"].startswith(f"notes: bob: {problem}")
