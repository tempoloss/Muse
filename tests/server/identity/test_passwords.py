import bcrypt
import pytest

from muse.identity.service import PasswordService
from muse.shared.errors import DomainError


class MemoryStore:
    def __init__(self) -> None:
        self.hashes: dict[str, str] = {}

    def save_hash(self, user_id: str, password_hash: str) -> None:
        self.hashes[user_id] = password_hash


@pytest.mark.parametrize("password", ["short", "ё" * 37])
def test_typed_passwords_need_ten_characters_and_at_most_72_bytes(password: str) -> None:
    store = MemoryStore()

    with pytest.raises(DomainError, match="10\\+ characters and at most 72 bytes"):
        PasswordService(store).set("alice", password)
    assert store.hashes == {}


def test_a_saved_password_verifies_against_its_hash() -> None:
    store = MemoryStore()

    PasswordService(store).set("alice", "correct horse")
    generated = PasswordService(store).set_random("bob")

    assert bcrypt.checkpw(b"correct horse", store.hashes["alice"].encode())
    assert bcrypt.checkpw(generated.encode(), store.hashes["bob"].encode())
    assert len(generated) == 16
