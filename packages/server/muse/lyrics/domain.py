import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, TypedDict

from muse.catalog.domain import SINGLES
from muse.shared.errors import DomainError

LRCLIB = "https://lrclib.net"
USER_AGENT = "Muse (https://github.com/tempoloss/Muse)"
TIMEOUT_S = 8.0
SLACK_S = 3.0
DAY_S = 86400
LYRICS_TTL_S = 14 * DAY_S
SINGLES_PREFIX = "Синглы · "
LYRICS_UNAVAILABLE = "lyrics unavailable"
STAMP = re.compile(r"\[(\d+):(\d{1,2})(?:[.:,](\d{1,3}))?\]")


class LyricLine(TypedDict):
    at: float
    text: str


class LyricsView(TypedDict):
    synced: list[LyricLine] | None
    plain: str | None
    instrumental: bool


class UnreachableError(DomainError):
    def __init__(self) -> None:
        super().__init__(LYRICS_UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class Record:
    duration: float | None
    instrumental: bool
    plain: str | None
    synced: str | None


class LyricsSource(Protocol):
    async def find(
        self, artist: str, title: str, album: str | None, duration: float | None
    ) -> LyricsView: ...


def album_param(album: str | None) -> str | None:
    name = album or ""
    return None if name == SINGLES or name.startswith(SINGLES_PREFIX) else name or None


def stamp_at(match: re.Match[str]) -> float:
    return int(match[1]) * 60 + int(match[2]) + int((match[3] or "0").ljust(3, "0")) / 1000


def stamped_line(line: str) -> list[LyricLine]:
    matches = list(STAMP.finditer(line))
    if not matches:
        return []
    text = line[matches[-1].end() :].strip()
    return [{"at": stamp_at(match), "text": text} for match in matches]


def synced_lines(lrc: str | None) -> list[LyricLine] | None:
    lines = [line for text in (lrc or "").splitlines() for line in stamped_line(text)]
    return sorted(lines, key=lambda line: line["at"]) or None


def lyrics_of(record: Record | None) -> LyricsView:
    if record is None:
        return {"synced": None, "plain": None, "instrumental": False}
    return {
        "synced": synced_lines(record.synced),
        "plain": record.plain,
        "instrumental": record.instrumental,
    }


def prefer_synced(record: Record) -> bool:
    return bool(record.synced)


def pick(records: Sequence[Record], duration: float | None) -> Record | None:
    if duration is None:
        return None
    near = [
        record
        for record in records
        if record.duration is not None and abs(record.duration - duration) <= SLACK_S
    ]
    return max(near, key=prefer_synced, default=None)
