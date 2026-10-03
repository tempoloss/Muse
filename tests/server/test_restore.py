import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import httpx
import pytest
from litestar.testing import AsyncTestClient

from muse.app import create_app
from muse.settings import Settings
from muse.userdb import upgrade_database
from tests.server.support import ORIGIN, WRITE, signed_in

SNAPSHOT = Path(__file__).resolve().parents[2] / "deploy" / "bin" / "muse-backup-snapshot"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("sqlite3") is None,
    reason="needs a POSIX shell and the sqlite3 CLI",
)


def nightly_backup(data: Path, backups: Path) -> Path:
    backups.mkdir()
    script = SNAPSHOT.read_text(encoding="utf-8")
    script = script.replace("/srv/muse/data", str(data)).replace("/var/backups/muse", str(backups))
    owner = data.stat()
    script = script.replace("chown muse:muse", f"chown {owner.st_uid}:{owner.st_gid}")
    subprocess.run(["sh", "-c", script], check=True)
    [archive] = backups.glob("muse-*.tar.gz")
    return archive


def restore(archive: Path, data: Path) -> None:
    command = ["tar", "-xzf", str(archive), "-C", str(data), "--no-overwrite-dir"]
    subprocess.run(command, check=True)


async def test_a_nightly_backup_brings_a_fresh_server_back_with_the_same_likes(
    settings: Settings, alice: httpx.AsyncClient, track_id: int, tmp_path: Path
) -> None:
    assert (await alice.put(f"/api/likes/{track_id}", headers=WRITE)).status_code == 204
    (settings.paths.data_dir / "vapid.pem").write_text("key", encoding="utf-8")
    archive = nightly_backup(settings.paths.data_dir, tmp_path / "backups")

    restored = tmp_path / "restored"
    restored.mkdir()
    restored.chmod(0o750)
    restore(archive, restored)
    with tarfile.open(archive, "r:gz") as tar:
        assert sorted(tar.getnames()) == ["muse.sqlite", "users.json", "vapid.pem"]
    assert stat.S_IMODE(restored.stat().st_mode) == 0o750
    assert stat.S_IMODE((restored / "muse.sqlite").stat().st_mode) == 0o600
    upgrade_database(restored / "muse.sqlite")
    paths = settings.paths.model_copy(update={"data_dir": restored})
    app = create_app(settings.model_copy(update={"paths": paths}))
    async with AsyncTestClient(app=app, base_url=ORIGIN):
        client = await signed_in(app, "alice")
        likes = (await client.get("/api/likes")).json()
        await client.aclose()

    assert likes["me"] == [track_id]
