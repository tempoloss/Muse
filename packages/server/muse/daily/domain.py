import json
import random
import re
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from muse.discovery.domain import Links, RadioModel, Track
from muse.identity.domain import User

type Ask = Callable[[str], AsyncIterator[tuple[str, str]]]
type Row = dict[str, Any]

NO_PLAYLIST = "no playlist"
BOTH = "both"
TASTE_DAYS = 60
POOL_LIKES = 80
POOL_PLAYS = 40
POOL_FRESH = 160
POOL_EXTRA = 40
POOL_SIZE = 480
PROMPT_LIKES = 200
PROMPT_ARTISTS = 12
PROMPT_GENRES = 4
PAST_TITLES = 30
ARTIST_CAP = 3
DAILY_KEEP = 12
DAILY_FILL = 25
DAILY_MAX = 30
DAILY_MIN_PLAYLISTS = 3
DAILY_MAX_PLAYLISTS = 8
TITLE_CHARS = 60
BLURB_CHARS = 140
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
MONTHS_GEN = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
JSON_OBJECT = re.compile(r"\{.*\}", re.S)


@dataclass(frozen=True, slots=True)
class Listening:
    likes: dict[str, list[int]]
    plays: dict[str, dict[int, int]]
    heard: set[int]


@dataclass(frozen=True, slots=True)
class DailyDraft:
    owner: str
    title: str
    blurb: str
    tracks: list[int]
    picked: int


def most_played(plays: dict[int, int]) -> list[int]:
    return sorted(plays, key=lambda track_id: -plays[track_id])


def favourites(model: RadioModel, users: Sequence[User], listening: Listening) -> dict[int, Track]:
    pool: dict[int, Track] = {}
    for user in users:
        mine = most_played(listening.plays[user.id])[:POOL_PLAYS]
        for track_id in listening.likes[user.id][:POOL_LIKES] + mine:
            if track_id in model.by_id:
                pool[track_id] = model.by_id[track_id]
    return pool


def nearness(pool: Iterable[Track], links: Links) -> defaultdict[str, float]:
    near: defaultdict[str, float] = defaultdict(float)
    for track in pool:
        near[track["artist"]] += 1
        for other, weight in links.get(track["artist"], {}).items():
            near[other] += weight
    return near


def fresh_picks(
    fresh: list[Track], near: defaultdict[str, float], rnd: random.Random
) -> list[Track]:
    per: Counter[str] = Counter()
    picked: list[Track] = []
    drawn = sorted(fresh, key=lambda track: -(rnd.random() ** (1 / (0.05 + near[track["artist"]]))))
    for track in drawn:
        if per[track["artist"]] < ARTIST_CAP:
            per[track["artist"]] += 1
            picked.append(track)
            if len(picked) == POOL_FRESH:
                break
    return picked


def daily_pool(
    day: date, model: RadioModel, users: Sequence[User], listening: Listening
) -> list[Track]:
    rnd = random.Random(f"daily:{day}")
    pool = favourites(model, users, listening)
    near = nearness(pool.values(), model.links)
    fresh = [
        track
        for track in model.tracks
        if track["id"] not in listening.heard and track["id"] not in pool
    ]
    for track in fresh_picks(fresh, near, rnd):
        pool[track["id"]] = track
    for track in rnd.sample(fresh, min(POOL_EXTRA, len(fresh))):
        pool.setdefault(track["id"], track)
    out = list(pool.values())
    rnd.shuffle(out)
    return out[:POOL_SIZE]


def taste_line(user: User, model: RadioModel, listening: Listening) -> str:
    artists: Counter[str] = Counter()
    genres: Counter[str | None] = Counter()
    weighted = list(listening.plays[user.id].items())
    weighted += [(track_id, 1) for track_id in listening.likes[user.id][:PROMPT_LIKES]]
    for track_id, times in weighted:
        if track := model.by_id.get(track_id):
            artists[track["artist"]] += times
            genres[track["genre"]] += times
    names = ", ".join(name for name, _ in artists.most_common(PROMPT_ARTISTS))
    kinds = ", ".join(genre for genre, _ in genres.most_common(PROMPT_GENRES) if genre)
    return f"- {user.name}: {names or 'пока мало данных'}; жанры: {kinds or '—'}"


def pool_row(
    track: Track, marks: dict[str, str], liked: dict[str, set[int]], listening: Listening
) -> str:
    plays = listening.plays
    flags = [f"♥{mark}" for user_id, mark in marks.items() if track["id"] in liked[user_id]]
    flags += [
        f"▶{mark}{plays[user_id][track['id']]}"
        for user_id, mark in marks.items()
        if plays[user_id].get(track["id"])
    ]
    flags += ["новое"] if track["id"] not in listening.heard else []
    return f"{track['id']}|{track['artist']} — {track['title']}|{track['genre'] or '-'}|{' '.join(flags)}"


def legend(users: Sequence[User], marks: dict[str, str]) -> str:
    first = users[0]
    parts = [f"♥{marks[user.id]} — нравится {user.name_dat or user.name}" for user in users]
    parts += [
        f"▶{marks[first.id]}3 — {first.name} слушал 3 раза",
        "новое — ещё никто из них не слушал",
    ]
    return ", ".join(parts)


def daily_prompt(
    day: date,
    pool: Sequence[Track],
    model: RadioModel,
    users: Sequence[User],
    listening: Listening,
    past: Sequence[str],
) -> str:
    first, second = users
    marks = {user.id: user.name[0] for user in users}
    liked = {user_id: set(ids) for user_id, ids in listening.likes.items()}
    taste = "\n".join(taste_line(user, model, listening) for user in users)
    rows = "\n".join(pool_row(track, marks, liked, listening) for track in pool)
    return f"""Ты музыкальный редактор домашнего плеера Muse. Им пользуются двое: {first.name} и {second.name}.
Каждое утро ты собираешь им новые плейлисты из их фонотеки, чтобы всегда было что послушать и не было скучно.

Сегодня {WEEKDAYS[day.weekday()]}, {day.day} {MONTHS_GEN[day.month - 1]}.

Вкусы за последние два месяца:
{taste}

Названия прошлых дней, не повторяй их: {"; ".join(past) or "их пока нет"}.

Собери ровно 6 плейлистов: 2 для {first.name_gen or first.name} ("for": "{first.id}"), 2 для {second.name_gen or second.name} ("for": "{second.id}") и 2 на двоих ("for": "both").
- В каждом 20–30 треков. Бери только id из списка ниже, без повторов внутри плейлиста.
- У каждого своя идея: настроение, время дня, повод, открытия. Не «весь жанр подряд».
- Смешивай любимое (♥, ▶) и новое примерно поровну. На двоих бери то, что подойдёт обоим.
- Не больше 3 треков одного артиста в плейлисте. Расставь треки так, чтобы переходы были плавными.
- title: живое название по-русски до 40 символов. blurb: одна фраза до 90 символов, о чём плейлист.

Ответь только JSON, без пояснений и без markdown:
{{"playlists": [{{"for": "{first.id}", "title": "…", "blurb": "…", "tracks": [123, 456]}}]}}

Метки: {legend(users, marks)}.
Треки (id|артист — название|жанр|метки):
{rows}
"""


def topup_nearness(per: Counter[str], links: Links) -> defaultdict[str, float]:
    near: defaultdict[str, float] = defaultdict(float)
    for artist, count in per.items():
        near[artist] += 3 * count
        for other, weight in links.get(artist, {}).items():
            near[other] += weight * count
    return near


def daily_topup(ids: list[int], count: int, model: RadioModel, day: date) -> list[int]:
    per = Counter(model.by_id[track_id]["artist"] for track_id in ids)
    near = topup_nearness(per, model.links)
    rnd, have, out = random.Random(f"daily:{day}:{ids[0]}"), set(ids), []
    candidates = (
        track for track in model.tracks if track["id"] not in have and near[track["artist"]] > 0
    )
    for track in sorted(
        candidates, key=lambda track: -(rnd.random() ** (1 / near[track["artist"]]))
    ):
        if per[track["artist"]] < ARTIST_CAP:
            per[track["artist"]] += 1
            out.append(track["id"])
            if len(out) == count:
                break
    return out


def track_id_of(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def pool_tracks(values: object, pool_ids: set[int], model: RadioModel) -> list[int]:
    ids: list[int] = []
    per: Counter[str] = Counter()
    for value in values if isinstance(values, list) else []:
        track_id = track_id_of(value)
        if track_id is None or track_id not in pool_ids or track_id in ids:
            continue
        artist = model.by_id[track_id]["artist"]
        if per[artist] < ARTIST_CAP:
            ids.append(track_id)
            per[artist] += 1
    return ids


def squeezed(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def daily_build(
    raw: object, pool_ids: set[int], model: RadioModel, users: Sequence[User], day: date
) -> list[DailyDraft]:
    whose = {user.id: user.id for user in users} | {user.name.casefold(): user.id for user in users}
    out: list[DailyDraft] = []
    titles: set[str] = set()
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        title = squeezed(entry.get("title"), TITLE_CHARS)
        if not title or title.casefold() in titles:
            continue
        ids = pool_tracks(entry.get("tracks"), pool_ids, model)
        if len(ids) < DAILY_KEEP:
            continue
        ids, picked = ids[:DAILY_MAX], min(len(ids), DAILY_MAX)
        if len(ids) < DAILY_FILL:
            ids += daily_topup(ids, DAILY_FILL - len(ids), model, day)
        titles.add(title.casefold())
        owner = whose.get(str(entry.get("for") or "").strip().casefold(), BOTH)
        out.append(DailyDraft(owner, title, squeezed(entry.get("blurb"), BLURB_CHARS), ids, picked))
    return out[:DAILY_MAX_PLAYLISTS]


def reply_playlists(reply: str) -> object:
    found = JSON_OBJECT.search(reply)
    return json.loads(found.group(0)).get("playlists") if found else None


def shown_order(rows: Iterable[Row], user_id: str) -> list[Row]:
    rank = {user_id: 0, BOTH: 1}
    return sorted(rows, key=lambda row: (rank.get(row["for_user"], 2), row["slot"]))


class DailyStore(Protocol):
    async def exists(self, day: str) -> bool: ...

    async def past_titles(self, day: str, limit: int) -> list[str]: ...

    async def replace(
        self, day: str, drafts: Sequence[DailyDraft], model: str, now: int
    ) -> None: ...

    async def get(self, playlist_id: int) -> Row | None: ...

    async def latest_day(self, today: str) -> str | None: ...

    async def of_day(self, day: str) -> list[Row]: ...


class TasteSource(Protocol):
    async def likes(self, user_id: str) -> list[int]: ...

    async def play_counts(self, user_id: str, since_ms: int) -> dict[int, int]: ...

    async def heard(self) -> set[int]: ...
