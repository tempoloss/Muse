import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "deploy" / "bin" / "muse-install-release"
MUSE = """#!/bin/sh
release=$(dirname "$0")/../..
case "$*" in
  "db snapshot") [ -f "$FAIL/snapshot" ] && exit 1; cp "$DB" "$DB.snapshot" ;;
  "db upgrade") cat "$release/src/marker" > "$DB"; [ ! -f "$FAIL/upgrade" ] ;;
  "db restore") cp "$DB.snapshot" "$DB" ;;
  check) [ ! -f "$FAIL/check" ] ;;
  *) exit 2 ;;
esac
"""
SYSTEMCTL = """case "$1" in
  stop) echo stopped > "$SERVICE" ;;
  restart) [ -f "$FAIL/restart" ] && exit 1; cat "$CURRENT/src/marker" > "$SERVICE" ;;
  start) cat "$CURRENT/src/marker" > "$SERVICE" ;;
esac"""
STUBS = {
    "uv": 'mkdir -p "$UV_PROJECT_ENVIRONMENT/bin" && cp "$FAKE_MUSE" "$UV_PROJECT_ENVIRONMENT/bin/"',
    "runuser": 'shift 3; exec "$@"',
    "systemctl": SYSTEMCTL,
    "curl": '[ -f "$FAIL/health" ] && echo 500 || echo 200',
    "sleep": "exit 0",
}

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX shell")


@pytest.fixture
def host(tmp_path: Path) -> Path:
    root = tmp_path / "opt"
    (root / "releases").mkdir(parents=True)
    (root / "python").mkdir()
    (tmp_path / "fail").mkdir()
    (tmp_path / "bin").mkdir()
    for path, body in [
        *((tmp_path / "bin" / name, f"#!/bin/sh\n{body}\n") for name, body in STUBS.items()),
        (tmp_path / "muse", MUSE),
    ]:
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
    script = INSTALLER.read_text(encoding="utf-8").replace("/opt/muse", str(root))
    (tmp_path / "install").write_text(script, encoding="utf-8")
    return tmp_path


def install(host: Path, sha: str, marker: str, fail: str | None = None) -> int:
    for flag in (host / "fail").iterdir():
        flag.unlink()
    if fail:
        (host / "fail" / fail).touch()
    (host / "marker").write_text(marker, encoding="utf-8")
    with tarfile.open(host / "release.tar", "w") as tar:
        tar.add(host / "marker", arcname="src/marker")
    env = {
        **os.environ,
        "PATH": f"{host / 'bin'}:{os.environ['PATH']}",
        "FAIL": str(host / "fail"),
        "DB": str(host / "muse.sqlite"),
        "SERVICE": str(host / "service"),
        "CURRENT": str(host / "opt" / "current"),
        "FAKE_MUSE": str(host / "muse"),
    }
    with (host / "release.tar").open("rb") as release:
        done = subprocess.run(
            ["sh", str(host / "install"), sha], stdin=release, env=env, check=False
        )
    return done.returncode


def state(host: Path) -> tuple[str, str, str]:
    live = host / "opt" / "current" / "src" / "marker"
    return (
        live.read_text(encoding="utf-8"),
        (host / "muse.sqlite").read_text(encoding="utf-8"),
        (host / "service").read_text(encoding="utf-8").strip(),
    )


def releases(host: Path) -> int:
    return len(list((host / "opt" / "releases").iterdir()))


def test_a_good_release_serves_its_migrated_database(host: Path) -> None:
    assert install(host, "abc1234", "first") == 0

    assert install(host, "def5678", "second") == 0

    assert state(host) == ("second", "second", "second")
    assert releases(host) == 2


@pytest.mark.parametrize("failure", ["snapshot", "upgrade", "restart", "health", "check"])
def test_a_release_that_does_not_come_up_leaves_the_previous_one_on_its_database(
    host: Path, failure: str
) -> None:
    assert install(host, "abc1234", "first") == 0

    assert install(host, "def5678", "second", fail=failure) == 1

    assert state(host) == ("first", "first", "first")
    assert releases(host) == 1


def test_a_failed_reinstall_of_the_live_commit_keeps_the_running_release(host: Path) -> None:
    assert install(host, "abc1234", "first") == 0

    assert install(host, "abc1234", "second", fail="health") == 1

    assert state(host) == ("first", "first", "first")
    assert releases(host) == 1


def test_a_reinstall_of_the_same_commit_ships_the_new_files(host: Path) -> None:
    assert install(host, "abc1234", "first") == 0

    assert install(host, "abc1234", "second") == 0

    assert state(host) == ("second", "second", "second")
