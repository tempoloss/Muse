import math
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Protocol

from muse.shared.errors import DomainError
from muse.shared.events import Event

type Row = dict[str, Any]

PET_STATS = ("food", "joy", "energy", "clean")
PET_AWAKE = {"food": -4, "joy": -3, "energy": -2.5, "clean": -2}
PET_ASLEEP = {"food": -2, "joy": 0, "energy": 15, "clean": -1}
CARE = ("feed", "play", "sleep", "wash", "heal")
CARE_LOG = ("feed", "play", "sleep", "wake", "wash", "heal")
TAKES_TURNS = ("feed", "play", "wash")
NEEDS_AWAKE = ("feed", "play", "wash")
HOUR_MS = 3600 * 1000
PET_SLEEP_MS = 3 * HOUR_MS
TURN_MS = 6 * HOUR_MS
PET_MUSIC_DAY = 30
MUSIC_FOOD = 2
PET_TOGETHER_DAY = 40
TREAT = {"food": 10, "joy": 10}
CARE_BONUS = {"food": 10, "joy": 20, "energy": 10, "clean": 10}
QUEST_REWARD = {"food": 20, "joy": 20, "energy": 20, "clean": 20}
NAME_MAX_CHARS = 24
HUNGRY_BELOW = 25
HUNGER_CHECK_S = 600
HUNGER_PUSH_EVERY_MS = 12 * HOUR_MS
DIRTY_BELOW = 30
NO_SUCH_ACTION = "no such action"
BAD_NAME = "bad name"
ASLEEP = "asleep"
TIRED = "tired"
HEALTHY = "healthy"
DONE = "done"
QUESTS = {
    "same_album": ("Послушаем альбом «{album}» — {artist}", 2),
    "shared_like": ("Найдём песню, которая понравится нам обоим", 1),
    "letters": ("Обменяемся записками", 2),
    "together": ("Послушаем музыку одновременно 10 минут", 10),
}
QUEST_ALBUM_SHARE = 0.8
QUEST_ALBUM_MIN_TRACKS = 5
QUEST_ALBUM_MAX_TRACKS = 14
ANY_ALBUM = "Послушаем один альбом"
QUEST_LIKE_SAMPLE = 20
TOGETHER_QUEST_MINUTES = 10


@dataclass(frozen=True, slots=True)
class Pet:
    name: str | None
    born_at: int
    food: float
    joy: float
    energy: float
    clean: float
    sick: bool
    asleep_until: int | None
    updated_at: int


@dataclass(frozen=True, slots=True)
class Care:
    pet: Pet
    logged_as: str


def clamp(value: float) -> float:
    return min(100.0, max(0.0, value))


def ticked(pet: Pet, now: int) -> Pet:
    until, at = pet.asleep_until, pet.updated_at
    asleep_h = max(0, min(now, until) - at) / HOUR_MS if until else 0
    awake_h = max(0, now - at) / HOUR_MS - asleep_h
    stats = {
        stat: clamp(
            getattr(pet, stat)
            + PET_ASLEEP[stat] * asleep_h
            + PET_AWAKE[stat] * awake_h * (2 if stat == "joy" and pet.sick else 1)
        )
        for stat in PET_STATS
    }
    woke = bool(until) and (until <= now or stats["energy"] >= 100)
    return replace(
        pet,
        **stats,
        sick=pet.sick or stats["food"] <= 0 or stats["clean"] <= 0,
        asleep_until=None if woke else until,
        updated_at=max(at, now),
    )


def added(pet: Pet, **deltas: float) -> Pet:
    return replace(
        pet, **{stat: clamp(getattr(pet, stat) + delta) for stat, delta in deltas.items()}
    )


def together_joy(seconds_before: float, seconds_after: float) -> float:
    return min(PET_TOGETHER_DAY, seconds_after / 60) - min(PET_TOGETHER_DAY, seconds_before / 60)


def hungry(pet: Pet) -> bool:
    return pet.food < HUNGRY_BELOW


def mood(pet: Pet, together: bool) -> str:
    if pet.sick:
        return "sick"
    if pet.asleep_until:
        return "sleeping"
    if together:
        return "dancing"
    if hungry(pet):
        return "hungry"
    if pet.clean < DIRTY_BELOW:
        return "dirty"
    return "happy" if pet.joy >= 70 and pet.food >= 50 else "idle"


def valid_name(name: str) -> bool:
    return 1 <= len(name) <= NAME_MAX_CHARS


def turn_share(action: str, last_carer: str | None, user_id: str) -> float:
    return 0.5 if action in TAKES_TURNS and last_carer == user_id else 1


def _feed(pet: Pet, half: float, _: int) -> Care:
    return Care(replace(pet, food=clamp(pet.food + 25 * half)), "feed")


def _play(pet: Pet, half: float, _: int) -> Care:
    if pet.energy < 10:
        raise DomainError(TIRED)
    joy, energy, food = clamp(pet.joy + 20 * half), clamp(pet.energy - 10), clamp(pet.food - 5)
    return Care(replace(pet, joy=joy, energy=energy, food=food), "play")


def _sleep(pet: Pet, _: float, now: int) -> Care:
    if pet.asleep_until is not None:
        return Care(replace(pet, asleep_until=None), "wake")
    return Care(replace(pet, asleep_until=now + PET_SLEEP_MS), "sleep")


def _wash(pet: Pet, half: float, _: int) -> Care:
    return Care(replace(pet, clean=clamp(pet.clean + 60 * half)), "wash")


def _heal(pet: Pet, _: float, __: int) -> Care:
    if not pet.sick:
        raise DomainError(HEALTHY)
    floors = {stat: max(getattr(pet, stat), 30.0) for stat in PET_STATS}
    return Care(replace(pet, sick=False, **floors), "heal")


CARE_EFFECTS: dict[str, Callable[[Pet, float, int], Care]] = {
    "feed": _feed,
    "play": _play,
    "sleep": _sleep,
    "wash": _wash,
    "heal": _heal,
}


def cared(pet: Pet, action: str, half: float, now: int) -> Care:
    if pet.asleep_until is not None and action in NEEDS_AWAKE:
        raise DomainError(ASLEEP)
    return CARE_EFFECTS[action](pet, half, now)


def pet_view(pet: Pet, together: bool, quest: Row, log: list[Row]) -> Row:
    return {
        "name": pet.name,
        "born_at": pet.born_at,
        **{stat: round(getattr(pet, stat)) for stat in PET_STATS},
        "sick": pet.sick,
        "asleep": bool(pet.asleep_until),
        "mood": mood(pet, together),
        "together_now": together,
        "quest": quest,
        "log": log,
    }


@dataclass(frozen=True, slots=True)
class QuestPick:
    kind: str
    album_id: int | None
    set_by: str


@dataclass(frozen=True, slots=True)
class QuestProgress:
    text: str
    progress: int
    goal: int
    album: Row | None = None
    track: Row | None = None
    parts: list[Row] | None = None


def quest_kind(today: date) -> str:
    return random.Random(f"quest:{today}").choice(sorted(QUESTS))


def drawn_album(albums: Sequence[Row], today: date) -> Row | None:
    pool = [
        album
        for album in albums
        if QUEST_ALBUM_MIN_TRACKS <= album["ntracks"] <= QUEST_ALBUM_MAX_TRACKS
    ]
    return random.Random(f"quest-album:{today}").choice(pool) if pool else None


def album_progress(album: Row, heard: Mapping[str, int], user_ids: Sequence[str]) -> QuestProgress:
    need = max(1, math.ceil(album["ntracks"] * QUEST_ALBUM_SHARE))
    progress = {user_id: min(heard.get(user_id, 0), need) for user_id in user_ids}
    parts: list[Row] = [
        {"user": user_id, "progress": done, "goal": need} for user_id, done in progress.items()
    ]
    return QuestProgress(
        QUESTS["same_album"][0].format(album=album["name"], artist=album["artist"]),
        sum(progress.values()),
        2 * need,
        album={
            "id": album["id"],
            "name": album["name"],
            "artist": album["artist"],
            "ntracks": album["ntracks"],
            "need": need,
        },
        parts=parts,
    )


def any_album() -> QuestProgress:
    return QuestProgress(ANY_ALBUM, 0, QUESTS["same_album"][1])


def sampled_likes(user_id: str, today: date, theirs: Sequence[int]) -> list[int]:
    rng = random.Random(f"{user_id}:quest-like:{today}")
    return rng.sample(list(theirs), min(QUEST_LIKE_SAMPLE, len(theirs)))


def together_progress(seconds: float) -> int:
    return min(TOGETHER_QUEST_MINUTES, int(seconds // 60))


def quest_view(kind: str, progress: QuestProgress, picked: QuestPick | None) -> Row:
    return {
        "kind": kind,
        "text": progress.text,
        "progress": progress.progress,
        "goal": progress.goal,
        "done": progress.progress >= progress.goal,
        "album": progress.album,
        "track": progress.track,
        "parts": progress.parts,
        "picked_by": picked.set_by if picked else None,
    }


@dataclass(frozen=True, slots=True)
class QuestAlbumChosen(Event):
    user: str
    album_id: int
    name: str
    artist: str


class ListeningTogether(Protocol):
    def together_now(self, now_ms: int) -> bool: ...


class PetRepository(Protocol):
    async def lock(self) -> None: ...

    async def load(self) -> Pet: ...

    async def save(self, pet: Pet) -> None: ...

    async def rename(self, name: str) -> None: ...

    async def log(
        self, at: int, user: str | None, action: str, detail: str | None = None
    ) -> None: ...

    async def logged(self, action: str, detail: str) -> bool: ...

    async def music_fed_since(self, since: int) -> float: ...

    async def last_carer(self, action: str, since: int) -> str | None: ...

    async def carers_since(self, since: int, user_ids: Sequence[str]) -> int: ...

    async def recent_log(self) -> list[Row]: ...

    async def hungry_pushed_since(self, since: int) -> bool: ...


class QuestRepository(Protocol):
    async def picked(self, day: str) -> QuestPick | None: ...

    async def pick(self, day: str, chosen: QuestPick, at: int) -> None: ...

    async def album_heard(self, since: int, album_id: int) -> dict[str, int]: ...

    async def shared_like_since(self, since: int) -> bool: ...

    async def liked_only_by(self, liker: str, other: str) -> list[int]: ...

    async def letter_senders_since(self, since: int) -> int: ...

    async def together_seconds(self, day: str) -> float: ...
