import hashlib
import logging
from pathlib import Path

from muse_agent.proc import Runner, run_logged
from muse_agent.settings import AgentConfig
from muse_agent.snapshot import make_snapshot

SNAPSHOT_NAME = "catalog-publish.sqlite"
PUBLISHED_MD5_NAME = "catalog.md5"
EXCLUDED = ("**/desktop.ini", "**/Thumbs.db")

log = logging.getLogger(__name__)


def publish(cfg: AgentConfig, allow_deletes: bool = False, run: Runner = run_logged) -> bool:
    snapshot = cfg.paths.work_dir / SNAPSHOT_NAME
    stats = make_snapshot(cfg.paths.catalog_db, cfg.paths.library_dir, snapshot)
    code = run(sync_command(cfg, allow_deletes))
    if code != 0:
        log.warning("publish: library sync failed rc=%d", code)
        return False
    summary = f"rows={stats.rows} rewritten={stats.rewritten} missing={stats.missing}"
    digest = md5_of(snapshot)
    record = cfg.paths.work_dir / PUBLISHED_MD5_NAME
    if record.is_file() and record.read_text(encoding="ascii").strip() == digest:
        log.info("publish: catalog unchanged %s", summary)
        return True
    code = run([cfg.rclone.exe, "copyto", str(snapshot), cfg.rclone.catalog_remote])
    if code != 0:
        log.warning("publish: catalog upload failed rc=%d", code)
        return False
    record.write_text(f"{digest}\n", encoding="ascii")
    log.info("publish: catalog uploaded %s", summary)
    return True


def sync_command(cfg: AgentConfig, allow_deletes: bool) -> list[str]:
    rclone = cfg.rclone
    workers = str(rclone.transfers)
    max_delete = -1 if allow_deletes else rclone.max_delete
    excludes = [part for pattern in EXCLUDED for part in ("--exclude", pattern)]
    return [
        rclone.exe,
        "sync",
        str(cfg.paths.library_dir),
        rclone.library_remote,
        "--transfers",
        workers,
        "--checkers",
        workers,
        "--fast-list",
        "--update",
        "--use-server-modtime",
        "--max-delete",
        str(max_delete),
        *excludes,
        "--stats",
        "0",
    ]


def md5_of(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, lambda: hashlib.md5(usedforsecurity=False)).hexdigest()
