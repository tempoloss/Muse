import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
from contextlib import closing
from pathlib import Path
from typing import IO, Any

import pytest

from muse.cli import main
from muse.settings import Settings

DAY = "2026-01-17"
PREFIX = "MUSE:"
WATCHDOG_S = 120
CONFIG = """
[paths]
data_dir = "{data}"
library_dir = "{library}"
catalog_db = "{catalog}"
web_dir = "{web}"

[http]
public_host = "music.example.org"
origins = ["https://music.example.org"]

[push]
enabled = false
"""
POOL_ROW = re.compile(r"^(\d+)\|(.+?) — ", re.M)
OWNED_TITLES = (("alice", "Утро"), ("bob", "День"), ("both", "Ночь"))


@pytest.fixture
def environment(settings: Settings, tmp_path: Path) -> dict[str, str]:
    paths = settings.paths
    config = tmp_path / "muse.toml"
    config.write_text(
        CONFIG.format(
            data=paths.data_dir.as_posix(),
            library=paths.library_dir.as_posix(),
            catalog=paths.catalog_db.as_posix(),
            web=paths.web_dir.as_posix(),
        ),
        encoding="utf-8",
    )
    return {**os.environ, "MUSE_CONFIG": str(config)}


def muse_command() -> str:
    found = shutil.which("muse", path=str(Path(sys.executable).parent))
    assert found, "the muse console script is not installed"
    return found


class Remote:
    def __init__(self, environment: dict[str, str], errors: IO[str], day: str = DAY) -> None:
        self.process = subprocess.Popen(
            [muse_command(), "daily-remote", day],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=errors,
            text=True,
            encoding="utf-8",
            env=environment,
        )
        self.watchdog = threading.Timer(WATCHDOG_S, self.process.kill)
        self.watchdog.start()

    @property
    def stdout(self) -> IO[str]:
        assert self.process.stdout is not None
        return self.process.stdout

    def receive(self) -> dict[str, Any]:
        for line in self.stdout:
            if line.startswith(PREFIX):
                return json.loads(line.removeprefix(PREFIX))
        raise AssertionError("the remote ended without a message")

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def close_input(self) -> None:
        assert self.process.stdin is not None
        self.process.stdin.close()

    def finish(self) -> tuple[int, str]:
        rest = self.stdout.read()
        code = self.process.wait()
        self.watchdog.cancel()
        self.stdout.close()
        self.close_input()
        return code, rest


def one_per_artist(prompt: str) -> list[int]:
    picks: dict[str, int] = {}
    for track_id, artist in POOL_ROW.findall(prompt):
        picks.setdefault(artist, int(track_id))
    return list(picks.values())


def saved_sets(settings: Settings) -> list[tuple[Any, ...]]:
    query = "SELECT day, slot, for_user, title, model FROM daily ORDER BY slot"
    with closing(sqlite3.connect(settings.paths.user_db)) as db:
        return db.execute(query).fetchall()


def test_the_agent_makes_a_day_through_the_remote_protocol(
    environment: dict[str, str], settings: Settings, tmp_path: Path
) -> None:
    with (tmp_path / "remote.err").open("w+", encoding="utf-8") as errors:
        remote = Remote(environment, errors)
        opening = remote.receive()
        assert opening["state"] == "prompt"
        picks = one_per_artist(opening["prompt"])
        assert len(picks) >= 36
        remote.send({"model": "wrong", "reply": "no idea"})
        assert remote.receive() == {"state": "next"}
        playlists = [
            {"for": owner, "title": title, "blurb": "", "tracks": picks[12 * n : 12 * n + 12]}
            for n, (owner, title) in enumerate(OWNED_TITLES)
        ]
        remote.send({"model": "right", "reply": json.dumps({"playlists": playlists})})
        assert remote.receive() == {"state": "saved"}
        code, rest = remote.finish()
        errors.seek(0)
        logged = errors.read()

    assert (code, rest) == (0, "")
    assert "daily: wrong: only 0 usable playlists" in logged
    assert saved_sets(settings) == [
        (DAY, slot, owner, title, "right") for slot, (owner, title) in enumerate(OWNED_TITLES)
    ]
    with (tmp_path / "rerun.err").open("w+", encoding="utf-8") as errors:
        rerun = Remote(environment, errors)
        assert rerun.receive() == {"state": "exists"}
        assert rerun.finish() == (0, "")


@pytest.mark.parametrize("ending", ["done", "eof"])
def test_a_remote_left_without_a_usable_reply_fails(
    environment: dict[str, str], settings: Settings, tmp_path: Path, ending: str
) -> None:
    with (tmp_path / "remote.err").open("w+", encoding="utf-8") as errors:
        remote = Remote(environment, errors)
        assert remote.receive()["state"] == "prompt"
        remote.send({"model": "short", "reply": '{"playlists": [{"title": "x", "tracks": [1]}]}'})
        assert remote.receive() == {"state": "next"}
        if ending == "done":
            remote.send({"done": True})
        else:
            remote.close_input()
        assert remote.receive() == {"state": "failed"}
        assert remote.finish() == (1, "")

    assert saved_sets(settings) == []


def test_a_bad_day_exits_with_2(environment: dict[str, str]) -> None:
    done = subprocess.run(
        [muse_command(), "daily-remote", "2026-02-30"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        timeout=WATCHDOG_S,
        check=False,
    )

    assert (done.returncode, done.stdout) == (2, "")


@pytest.mark.parametrize("day", ["20260117", "2026-W03-6", "2026-1-17", " 2026-01-17"])
def test_only_plain_iso_days_are_accepted(day: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as refused:
        main(["daily-remote", day])

    assert refused.value.code == 2
    assert "not a YYYY-MM-DD day" in capsys.readouterr().err
