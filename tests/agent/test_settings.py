import re
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from muse_agent import settings
from muse_agent.settings import ConfigError
from tests.agent.support import EXAMPLE


def config_file(tmp_path: Path, old: str, new: str) -> Path:
    text = EXAMPLE.read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / "agent.toml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return path


def test_the_shipped_example_loads_with_typed_values() -> None:
    cfg = settings.load(EXAMPLE)

    assert cfg.paths.work_dir == Path("D:/music/agent")
    assert cfg.rclone.transfers == 16
    assert cfg.rclone.max_delete == 200
    assert cfg.daily.timezone == ZoneInfo("UTC")
    assert cfg.daily.command == ("llm-cli", "--model", "{model}", "--prompt-file", "{prompt_file}")
    assert cfg.daily.models == ("model-a",)
    assert cfg.deploy.web_dist == Path("D:/music/web/dist")


@pytest.mark.parametrize(
    ("old", "new", "complaint"),
    [
        ("hour = 5", "hour = 5\nhours = 6", "daily.hours: unknown key"),
        ("[deploy]", "[extra]\nkey = 1\n[deploy]", "extra: unknown key"),
        ('agent_host = "vps-agent"', "", "vps.agent_host: missing"),
        ('timezone = "UTC"', 'timezone = "Mars/Olympus"', "daily.timezone: unknown time zone"),
        ("hour = 5", 'hour = "5"', "daily.hour: must be an integer"),
        ("hour = 5", "hour = true", "daily.hour: must be an integer"),
        ("hour = 5", "hour = 24", "daily.hour: must be within 0..23"),
        (
            'models = ["model-a"]',
            "models = []",
            "daily.models: must be a non-empty list of strings",
        ),
        ('exe = "rclone"', 'exe = ""', "rclone.exe: must be a non-empty string"),
        (
            'web_dist = "D:/music/web/dist"',
            "web_dist = 1",
            "deploy.web_dist: must be a non-empty string",
        ),
    ],
)
def test_a_bad_setting_is_reported_with_its_key(
    tmp_path: Path, old: str, new: str, complaint: str
) -> None:
    path = config_file(tmp_path, old, new)

    with pytest.raises(ConfigError, match=re.escape(complaint)):
        settings.load(path)


def test_a_missing_file_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        settings.load(tmp_path / "agent.toml")


def test_the_environment_chooses_the_config_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MUSE_AGENT_CONFIG", str(EXAMPLE))
    assert settings.load().vps.agent_host == "vps-agent"

    monkeypatch.delenv("MUSE_AGENT_CONFIG")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert settings.default_path() == tmp_path / "Roaming" / "muse" / "agent.toml"

    monkeypatch.delenv("APPDATA")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    expected = tmp_path / "home" / "AppData" / "Roaming" / "muse" / "agent.toml"
    assert settings.default_path() == expected
