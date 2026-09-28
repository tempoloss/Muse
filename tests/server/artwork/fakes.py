from collections.abc import Sequence
from dataclasses import dataclass, field

from muse.artwork.domain import TransientError

type Asked = tuple[tuple[str | None, ...], str | None, tuple[str | None, ...]]


class Pauses(list[float]):
    async def __call__(self, seconds: float) -> None:
        self.append(seconds)


@dataclass
class FakeStores:
    covers: dict[str, str] = field(default_factory=dict)
    pictures: dict[str, str] = field(default_factory=dict)
    images: dict[str, bytes] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)
    asked: list[Asked] = field(default_factory=list)

    def fail_while_flaky(self, name: str) -> None:
        left = self.failures.get(name, 0)
        if left:
            self.failures[name] = left - 1
            raise TransientError("quota")

    async def album_art(
        self, names: Sequence[str | None], album: str | None, titles: Sequence[str | None]
    ) -> str | None:
        self.asked.append((tuple(names), album, tuple(titles)))
        self.fail_while_flaky(album or "")
        return self.covers.get(album or "")

    async def artist_picture(self, name: str) -> str | None:
        self.fail_while_flaky(name)
        return self.pictures.get(name)

    async def download(self, url: str) -> bytes:
        return self.images[url]
