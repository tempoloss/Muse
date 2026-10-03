import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NotRequired, Protocol, TypedDict

from muse.catalog.domain import Track
from muse.shared.errors import DomainError
from muse.shared.events import Event

LIVE_FRESH_MS = 45000
FOLLOW_WAIT_S = 25
FOLLOW_TTL_MS = 40000
FOLLOW_POLL_S = 0.25
SHARED_STEP_MS = 30000
LETTER_MAX_CHARS = 280
NOTE_KINDS = ("fact", "line")
NOTE_MAX_CHARS = 280
NOTE_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
PARTNER_FOLLOWS = "partner follows you"
BAD_TEXT = "bad text"
NO_LETTER = "no letter"


class PartnerNow(TypedDict):
    track: Track
    position: float
    playing: bool
    following: bool


class Mirrored(TypedDict):
    track: Track
    position: float
    playing: bool
    at: int


class LiveView(TypedDict):
    partner: PartnerNow | None
    together: bool
    unread: int


class FollowView(TypedDict):
    partner: Mirrored | None


LetterView = TypedDict(
    "LetterView",
    {
        "id": int,
        "from": str,
        "to": str,
        "track": Track | None,
        "text": str,
        "created_at": int,
        "read_at": int | None,
    },
)


class LetterList(TypedDict):
    received: list[LetterView]
    sent: list[LetterView]


class OursTrack(Track):
    added_by: str
    added_at: int


class OursView(TypedDict):
    tracks: list[OursTrack]
    albums: list[int]


class Note(TypedDict):
    kind: str
    text: str
    date: NotRequired[str]


class NotesView(TypedDict):
    notes: list[Note]


@dataclass(frozen=True, slots=True)
class TogetherAccrued(Event):
    seconds_before: float
    seconds_after: float


@dataclass(frozen=True, slots=True)
class LetterSent(Event):
    sender: str
    recipient: str
    letter_id: int
    track_id: int
    text: str


@dataclass(frozen=True, slots=True)
class OursChanged(Event):
    user: str
    track_id: int
    added_new: bool


@dataclass(frozen=True, slots=True)
class Beat:
    track_id: int | None
    position: float
    playing: bool
    at: int


def fresh(beat: Beat | None, now: int) -> bool:
    return bool(
        beat and beat.playing and beat.track_id is not None and now - beat.at <= LIVE_FRESH_MS
    )


def follows(started_at: int | None, now: int) -> bool:
    return now - (started_at or 0) <= FOLLOW_TTL_MS


def shared_seconds(previous: Beat | None, current: Beat, partner: Beat | None) -> float | None:
    if not (
        current.playing
        and current.track_id is not None
        and fresh(partner, current.at)
        and previous
        and previous.playing
    ):
        return None
    return min(current.at - previous.at, SHARED_STEP_MS) / 1000 / 2


def clamped(position: float, track: Track) -> float:
    dur = track["dur"]
    return min(position, dur) if dur else position


def live_partner(beat: Beat, track: Track, now: int, following: bool) -> PartnerNow:
    position = beat.position + (now - beat.at) / 1000
    return {
        "track": track,
        "position": clamped(position, track),
        "playing": True,
        "following": following,
    }


def mirrored_track_id(beat: Beat | None, now: int) -> int | None:
    if not beat or beat.track_id is None or (beat.playing and now - beat.at > LIVE_FRESH_MS):
        return None
    return beat.track_id


def mirror(beat: Beat, track: Track, now: int) -> Mirrored:
    position = beat.position + ((now - beat.at) / 1000 if beat.playing else 0)
    return {
        "track": track,
        "position": clamped(position, track),
        "playing": beat.playing,
        "at": beat.at,
    }


@dataclass(frozen=True, slots=True)
class Letter:
    id: int
    sender: str
    recipient: str
    track_id: int
    text: str
    created_at: int
    read_at: int | None

    def view(self, tracks: dict[int, Track]) -> LetterView:
        return {
            "id": self.id,
            "from": self.sender,
            "to": self.recipient,
            "track": tracks.get(self.track_id),
            "text": self.text,
            "created_at": self.created_at,
            "read_at": self.read_at,
        }


@dataclass(frozen=True, slots=True)
class OursMark:
    track_id: int
    added_by: str
    added_at: int


def letter_text(text: str) -> str:
    body = text.strip()
    if not 1 <= len(body) <= LETTER_MAX_CHARS:
        raise DomainError(BAD_TEXT)
    return body


def valid_note(note: object) -> bool:
    if not isinstance(note, dict) or note.get("kind") not in NOTE_KINDS:
        return False
    text, day = note.get("text"), note.get("date")
    return (
        isinstance(text, str)
        and 0 < len(text.strip()) <= NOTE_MAX_CHARS
        and (day is None or NOTE_DATE.fullmatch(str(day)) is not None)
    )


def note_view(note: Mapping[str, Any]) -> Note:
    return {
        "kind": note["kind"],
        "text": note["text"].strip(),
        **({"date": note["date"]} if note.get("date") else {}),
    }


class LiveBoard(Protocol):
    def report(
        self, user_id: str, partner_id: str, beat: Beat
    ) -> tuple[Beat | None, Beat | None]: ...

    def beat_of(self, user_id: str) -> Beat | None: ...

    def partner_state(self, partner_id: str, now: int) -> tuple[Beat | None, bool]: ...

    def start_following(self, user_id: str, partner_id: str, now: int) -> bool: ...

    def stop_following(self, user_id: str) -> None: ...

    def together_now(self, now_ms: int) -> bool: ...


class TogetherLedger(Protocol):
    async def accrue(self, day: str, seconds: float) -> float: ...


class LetterBox(Protocol):
    async def send(
        self, sender: str, recipient: str, track_id: int, text: str, now: int
    ) -> int: ...

    async def received(self, user_id: str) -> list[Letter]: ...

    async def sent(self, user_id: str) -> list[Letter]: ...

    async def addressed_to(self, letter_id: int, user_id: str) -> bool: ...

    async def mark_read(self, letter_id: int, now: int) -> None: ...

    async def unread(self, user_id: str) -> int: ...


class OursList(Protocol):
    async def marks(self) -> list[OursMark]: ...

    async def add(self, track_id: int, user_id: str, now: int) -> bool: ...

    async def remove(self, track_id: int) -> None: ...


class NotesSource(Protocol):
    async def notes(self, user_id: str) -> list[Note]: ...
