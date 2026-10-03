import os
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "deploy" / "bin" / "muse-install-release"
STUBS = {
    "uv": "exit 0",
    "runuser": "exit 0",
    "systemctl": '[ -f "$RESTART_FAILS" ] && exit 1; exit 0',
    "sleep": "exit 0",
}

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="needs a POSIX shell")


@pytest.fixture
def host(tmp_path: Path) -> Path:
    root = tmp_path / "opt"
    (root / "releases").mkdir(parents=True)
    (root / "python").mkdir()
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name, body in {**STUBS, "curl": 'cat "$HEALTH"'}.items():
        (stubs / name).write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        (stubs / name).chmod(0o755)
    script = INSTALLER.read_text(encoding="utf-8").replace("/opt/muse", str(root))
    (tmp_path / "install").write_text(script, encoding="utf-8")
    return tmp_path


def install(host: Path, sha: str, marker: str, health: str, *, restart_fails: bool = False) -> int:
    (host / "health").write_text(health, encoding="utf-8")
    (host / "marker").write_text(marker, encoding="utf-8")
    (host / "restart-fails").unlink(missing_ok=True)
    if restart_fails:
        (host / "restart-fails").touch()
    with tarfile.open(host / "release.tar", "w") as tar:
        tar.add(host / "marker", arcname="src/marker")
    env = {
        **os.environ,
        "PATH": f"{host / 'bin'}:{os.environ['PATH']}",
        "HEALTH": str(host / "health"),
        "RESTART_FAILS": str(host / "restart-fails"),
    }
    with (host / "release.tar").open("rb") as release:
        done = subprocess.run(
            ["sh", str(host / "install"), sha], stdin=release, env=env, check=False
        )
    return done.returncode


def live(host: Path) -> str:
    return (host / "opt" / "current" / "src" / "marker").read_text(encoding="utf-8")


def test_a_failed_reinstall_of_the_live_commit_keeps_the_running_release(host: Path) -> None:
    assert install(host, "abc1234", "first", "200") == 0

    assert install(host, "abc1234", "second", "500") == 1

    assert live(host) == "first"
    assert len(list((host / "opt" / "releases").iterdir())) == 1


def test_a_failed_restart_rolls_back_to_the_running_release(host: Path) -> None:
    assert install(host, "abc1234", "first", "200") == 0

    assert install(host, "def5678", "second", "200", restart_fails=True) == 1

    assert live(host) == "first"
    assert len(list((host / "opt" / "releases").iterdir())) == 1


def test_a_reinstall_of_the_same_commit_ships_the_new_files(host: Path) -> None:
    assert install(host, "abc1234", "first", "200") == 0

    assert install(host, "abc1234", "second", "200") == 0

    assert live(host) == "second"
