import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from scripts import deploy


def git(repo: Path, *args: str) -> None:
    identity = ["-c", "user.name=Muse Test", "-c", "user.email=test@example.org"]
    command = ["git", "-C", str(repo), *identity, "-c", "commit.gpgsign=false", *args]
    subprocess.run(command, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "packages").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (root / "packages" / "app.py").write_text("x = 1\n", encoding="utf-8")
    git(root, "init", "-q")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "init")
    return root


@pytest.fixture
def web_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("run()", encoding="utf-8")
    return dist


def test_the_release_holds_the_commit_under_src_and_the_client_under_web(
    repo: Path, web_dist: Path
) -> None:
    release = deploy.build_release(repo, web_dist)

    with tarfile.open(fileobj=io.BytesIO(release)) as tar:
        files = {member.name: member for member in tar.getmembers() if member.isfile()}
        app = tar.extractfile("src/packages/app.py")
        script = tar.extractfile("web/assets/app.js")
        assert app is not None
        assert script is not None
        assert app.read() == b"x = 1\n"
        assert script.read() == b"run()"

    assert sorted(files) == [
        "src/packages/app.py",
        "src/pyproject.toml",
        "web/assets/app.js",
        "web/index.html",
    ]
    for member in files.values():
        assert (member.uid, member.gid, member.mode) == (0, 0, 0o644)


@pytest.mark.parametrize("change", ["untracked", "modified"])
def test_a_dirty_working_tree_is_refused(repo: Path, web_dist: Path, change: str) -> None:
    if change == "untracked":
        (repo / "notes.txt").write_text("draft", encoding="utf-8")
    else:
        (repo / "packages" / "app.py").write_text("x = 2\n", encoding="utf-8")

    with pytest.raises(deploy.DeployError, match="uncommitted"):
        deploy.build_release(repo, web_dist)


def test_a_web_client_without_index_is_refused(repo: Path, tmp_path: Path) -> None:
    (tmp_path / "dist").mkdir()

    with pytest.raises(deploy.DeployError, match=r"index\.html"):
        deploy.build_release(repo, tmp_path / "dist")
