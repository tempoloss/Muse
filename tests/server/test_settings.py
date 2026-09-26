from pathlib import Path

import pytest
from pydantic import ValidationError

from muse.settings import load_settings

EXAMPLE = Path(__file__).resolve().parents[2] / "deploy" / "muse.example.toml"
BASE = """
[paths]
data_dir = "/data"
library_dir = "/lib"
catalog_db = "/data/state.sqlite"
web_dir = "/web"

[http]
public_host = "music.example.org"
origins = ["https://music.example.org"]
"""
NO_PUSH = "\n[push]\nenabled = false\n"


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "muse.toml"
    monkeypatch.setenv("MUSE_CONFIG", str(path))
    return path


def test_the_example_file_is_a_complete_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MUSE_CONFIG", str(EXAMPLE))

    settings = load_settings()

    assert settings.http.origins == ("https://music.example.org",)
    assert settings.push.enabled
    assert settings.clock.timezone == "UTC"
    assert settings.cache.redis_url == "redis://127.0.0.1:6379/0"


def test_state_files_live_in_the_data_directory(config: Path) -> None:
    config.write_text(BASE + NO_PUSH, encoding="utf-8")

    paths = load_settings().paths

    data = Path("/data")
    assert (paths.users_file, paths.user_db, paths.vapid_file) == (
        data / "users.json",
        data / "muse.sqlite",
        data / "vapid.pem",
    )
    assert (paths.notes_dir, paths.covers_dir, paths.artists_dir, paths.thumbs_dir) == (
        data / "notes",
        data / "covers",
        data / "artists",
        data / "thumbs",
    )
    assert paths.player_log == data / "player.log"
    assert paths.playlists_dir == Path("/lib/_Playlists")


def test_environment_overrides_the_file(config: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config.write_text(BASE + NO_PUSH, encoding="utf-8")
    monkeypatch.setenv("MUSE_HTTP__PORT", "4545")
    monkeypatch.setenv("MUSE_CLOCK__TIMEZONE", "Asia/Tokyo")

    settings = load_settings()

    assert (settings.http.host, settings.http.port) == ("127.0.0.1", 4545)
    assert settings.clock.timezone == "Asia/Tokyo"


def test_push_needs_a_subject_while_enabled(config: Path) -> None:
    config.write_text(BASE, encoding="utf-8")

    with pytest.raises(ValidationError, match=r"push\.subject is required"):
        load_settings()


@pytest.mark.parametrize(
    "extra",
    [
        "\n[clock]\ntimezone = 'Mars/Olympus'\n",
        "\n[cache]\nredis = 'redis://127.0.0.1'\n",
        "\n[database]\nurl = 'sqlite://'\n",
    ],
)
def test_invalid_or_unknown_settings_are_refused(config: Path, extra: str) -> None:
    config.write_text(BASE + NO_PUSH + extra, encoding="utf-8")

    with pytest.raises(ValidationError):
        load_settings()
