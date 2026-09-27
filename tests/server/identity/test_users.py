import copy
import json
import os
import re
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from muse.identity.domain import InvalidUsersError, parse_users
from muse.identity.infra.users_file import UsersFile

type Change = Callable[[dict[str, Any]], object]

INCOMPLETE = (
    "users.json: every user needs non-empty string id, login, name, animal, theme, emoji, nick"
)


def test_each_user_knows_the_partner_and_how_the_client_sees_them(
    users_document: dict[str, Any],
) -> None:
    users = parse_users(users_document)
    alice = users.get("alice")
    bob = users.by_login("  BOB ")
    assert alice is not None
    assert bob is not None

    assert users.partner(alice) is bob
    assert users.partner_id("bob") == "alice"
    assert users.me(alice) == {
        "id": "alice",
        "name": "Алиса",
        "animal": "fox",
        "theme": "light",
        "gen": "Алиса",
        "dat": "Алиса",
        "author": False,
        "partner": {
            "id": "bob",
            "name": "Боб",
            "animal": "bear",
            "theme": "dark",
            "gen": "Боба",
            "dat": "Бобу",
            "author": True,
        },
    }
    assert (alice.beast, bob.beast) == ("🦊 Лисёнок", "🐻 Мишка")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["users"].pop(), "users.json: need exactly 2 users"),
        (lambda d: d.clear(), "users.json: need exactly 2 users"),
        (lambda d: d["users"][0].update(login="  "), INCOMPLETE),
        (lambda d: d["users"][1].pop("nick"), INCOMPLETE),
        (
            lambda d: d["users"][0].update(password_hash=5),
            "users.json: alice: password_hash must be a string or null",
        ),
        (lambda d: d["users"][1].update(id="alice"), "users.json: duplicate id"),
        (lambda d: d["users"][1].update(login=" ALICE "), "users.json: duplicate login"),
    ],
)
def test_invalid_users_are_refused_with_the_reason(
    users_document: dict[str, Any], change: Change, message: str
) -> None:
    document = copy.deepcopy(users_document)
    change(document)

    with pytest.raises(InvalidUsersError, match=f"^{re.escape(message)}$"):
        parse_users(document)


def test_an_unreadable_file_is_reported_with_its_path(tmp_path: Path) -> None:
    path = tmp_path / "users.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(InvalidUsersError, match=r"users\.json: cannot read"):
        UsersFile(path).load()


def test_saving_a_hash_rewrites_only_that_user(
    tmp_path: Path, users_document: dict[str, Any]
) -> None:
    document = copy.deepcopy(users_document)
    document["users"][0]["note"] = "оставить"
    path = tmp_path / "users.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    UsersFile(path).save_hash("alice", "new-hash")

    saved = json.loads(path.read_text(encoding="utf-8"))
    document["users"][0]["password_hash"] = "new-hash"
    assert saved == document
    assert "оставить" in path.read_text(encoding="utf-8")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["users.json"]
    with pytest.raises(InvalidUsersError, match="no such user: zed"):
        UsersFile(path).save_hash("zed", "x")


@pytest.mark.skipif(sys.platform == "win32", reason="needs POSIX file modes")
def test_saving_a_hash_keeps_the_file_private(
    tmp_path: Path, users_document: dict[str, Any]
) -> None:
    path = tmp_path / "users.json"
    path.write_text(json.dumps(users_document), encoding="utf-8")
    path.chmod(0o600)
    umask = os.umask(0o022)
    try:
        UsersFile(path).save_hash("alice", "new-hash")
    finally:
        os.umask(umask)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_the_example_users_ship_without_passwords() -> None:
    example = Path(__file__).resolve().parents[3] / "deploy" / "users.example.json"

    users = parse_users(json.loads(example.read_text(encoding="utf-8")))

    assert [user.password_hash for user in users.all] == [None, None]
