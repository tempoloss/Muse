import json
from pathlib import Path

import bcrypt
import pytest

from muse.cli import main
from muse.settings import Settings

CONFIG = """
[paths]
data_dir = "{data}"
library_dir = "{data}/lib"
catalog_db = "{data}/state.sqlite"
web_dir = "{data}/web"

[http]
public_host = "music.example.org"
origins = ["https://music.example.org"]

[push]
enabled = false
"""


@pytest.fixture
def configured(settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "muse.toml"
    config.write_text(CONFIG.format(data=settings.paths.data_dir.as_posix()), encoding="utf-8")
    monkeypatch.setenv("MUSE_CONFIG", str(config))
    return settings.paths.users_file


def stored_hash(users_file: Path, user_id: str) -> str:
    users = json.loads(users_file.read_text(encoding="utf-8"))["users"]
    return next(user["password_hash"] for user in users if user["id"] == user_id)


def test_a_random_password_is_printed_once_and_stored_hashed(
    configured: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["passwd", "bob", "--random"]) == 0

    printed = capsys.readouterr().out.strip()
    assert printed.startswith("password for bob: ")
    password = printed.removeprefix("password for bob: ")
    assert bcrypt.checkpw(password.encode(), stored_hash(configured, "bob").encode())


def test_typed_passwords_are_confirmed(
    configured: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    answers = iter(["correct horse battery", "correct horse battery"])
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(answers))

    assert main(["passwd", "alice"]) == 0

    assert capsys.readouterr().out.strip() == "password for alice saved"
    assert bcrypt.checkpw(b"correct horse battery", stored_hash(configured, "alice").encode())


@pytest.mark.parametrize(
    ("argv", "answers", "message"),
    [
        (["passwd", "zed", "--random"], [], "no such user: zed"),
        (["passwd", "alice"], ["correct horse", "correct horses"], "passwords differ"),
        (["passwd", "alice"], ["short", "short"], "10+ characters and at most 72 bytes"),
    ],
)
def test_refused_passwords_leave_the_file_untouched(
    configured: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    answers: list[str],
    message: str,
) -> None:
    before = configured.read_text(encoding="utf-8")
    replies = iter(answers)
    monkeypatch.setattr("getpass.getpass", lambda _prompt: next(replies))

    assert main(argv) == 1

    assert message in capsys.readouterr().err
    assert configured.read_text(encoding="utf-8") == before
