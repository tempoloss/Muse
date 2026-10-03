import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from muse.cli import check
from muse.settings import Settings


def edited(path: Path, sql: str) -> Path:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(sql)
        connection.commit()
    return path


def broken(settings: Settings, tmp_path: Path, breakage: str) -> Settings:
    paths = settings.paths
    if breakage == "no database":
        paths.user_db.unlink()
        return settings
    if breakage == "stale schema":
        edited(paths.user_db, "UPDATE alembic_version SET version_num='0000'")
        return settings
    if breakage == "empty catalog":
        catalog = tmp_path / "empty.sqlite"
        shutil.copyfile(paths.catalog_db, catalog)
        moved = {"catalog_db": edited(catalog, "UPDATE tracks SET status='failed'")}
    else:
        unmounted = tmp_path / "unmounted"
        unmounted.mkdir()
        moved = {"library_dir": unmounted}
    return settings.model_copy(update={"paths": paths.model_copy(update=moved)})


def test_a_working_install_passes_the_check(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check(settings) == 0

    assert capsys.readouterr().out.startswith("ok: 2 users, ")


@pytest.mark.parametrize(
    ("breakage", "complaint"),
    [
        ("no database", "no user database"),
        ("stale schema", "user database is at 0000"),
        ("empty catalog", "the catalog has no playable tracks"),
        ("no track files", "has a readable file"),
    ],
)
def test_the_check_fails_when_the_server_could_not_play_music(
    settings: Settings,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    breakage: str,
    complaint: str,
) -> None:
    assert check(broken(settings, tmp_path, breakage)) == 1

    assert complaint in capsys.readouterr().err
