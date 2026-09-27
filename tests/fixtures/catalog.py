import itertools
import random
import sqlite3
import uuid
from collections import defaultdict
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, replace
from pathlib import Path

from tests.fixtures.audio import cover_jpeg, mp3_bytes, with_cover

SCHEMA = Path(__file__).with_name("catalog_schema.sql")
SEED = 1971

SINGLES_ALBUM = "Одиночные и синглы"
SINGLES_ARTIST = "Kiro Delta"
SINGLES_PARTNER = "Wexa"
SINGLES_CREDIT = f"{SINGLES_ARTIST} & {SINGLES_PARTNER}"
SINGLES_DISPLAY = f"Синглы · {SINGLES_CREDIT}"
RENAMED_TAG = "Pyrometr"
RENAMED_CANONICAL = "Пирометр"
DRIFTED_CANONICAL = "Pyrometer"
COVER_ARTIST = "Paper Lighthouse"
COVER_ALBUM = "Glass Orchard"
SHORT_ARTIST = "Choir of Kettles"
SHORT_ALBUM = "Interludes"
UNTIMED_ARTIST = "Кирпич Луны"
UNCANONICAL = frozenset({"Gutterfern", "Nimble Fog", "Шуруп", "Kazoo Senate"})

PLAYLISTS_DIR = "_Playlists"
PLAYLISTS = ("Mix", "Вечер")
IGNORED_PLAYLIST = "Archive.m3u"
DEVICE_MUSIC = "/storage/emulated/0/Music/"
STRAY_ENTRY = "Rap/Nobody Here/Lost Tapes/01 - Gone.mp3"

ARTISTS = {
    "Rap": (
        "Brisk Okapi",
        SINGLES_ARTIST,
        SINGLES_PARTNER,
        "MC Varnish",
        "lil gravlax",
        "Yung Pemmican",
        "Tarmac Saint",
        "DJ Quokka",
        "Ozzle Prime",
        "Parsnip Gang",
        "Kopek Dune",
        "Stucco Mane",
        "Rizzo Tamarind",
        "Baron Kelp",
        "ZEPHYR KILO",
        "Nimbus Vix",
        "Gutterfern",
        "Lo-Fi Ombudsman",
        "Sixty Moths",
        "Trenchcoat Nebula",
        "Quiet Kumquat",
        "Vandal Pistachio",
        "Mezzo Brick",
        "Cassette Ghoul",
        "Orbit Dumpling",
        "Sable Pylon",
        "Hexa Lobster",
        "Prairie Static",
        "Velcro Pharaoh",
        "Granite Juno",
        "Plaza Mongoose",
        "Chrome Turnip",
        "Dusty Vortex",
        "Kettle Monarch",
    ),
    "Indie": (
        "Swan Radiator",
        "mOTH club",
        "The Lint Collectors",
        COVER_ARTIST,
        "Cardigan Weather",
        "Hollow Pear",
        "Tin Canary",
        "Velvet Sleet",
        "The Quiet Ferrets",
        "Marmalade Static",
        "Lake Tremolo",
        "Saltwater Toasters",
        "Fern Telegraph",
        "Nectar Pylons",
        "Drowsy Comet",
        "Pale Gondola",
        "Attic Lanterns",
        "Wool & Thunder",
        "Signal Orchard",
        "Crayon Harbor",
        "The Sundial Kids",
        "Opal Bicycle",
        "Nimble Fog",
        "Шёпот Сирени",
    ),
    "RU Rap": (
        "Бетонный Ёж",
        UNTIMED_ARTIST,
        RENAMED_TAG,
        "Тихий Кальмар",
        "МС Сквозняк",
        "Ржавый Кит",
        "Лёд Кефир",
        "Дым Пломбир",
        "ночной самокат",
        "ГРОЗОВОЙ ФОНАРЬ",
        "Шуруп",
        "Кисель Дельта",
        "Пыльный Компас",
        "Мятный Барсук",
        "Лимонный Пёс",
        "Сирена Пустыря",
        "Тень Батарейки",
        "Кот Бетон",
        "Пятый Подъезд",
        "Рыжий Модем",
        "Зелёный Шифер",
        "Хрустальный Ёрш",
        "Варежка Рэп",
        "Мокрый Глобус",
        "Фонарщик Тыква",
        "Кедровый Дрон",
    ),
    "Other": (
        "Orchestral Spoon",
        "Ambient Dishwasher",
        SHORT_ARTIST,
        "Lounge Iguana",
        "Bossa Paperclip",
        "Gamelan Radiator",
        "Synth Lemur",
        "Тромбон и Тапки",
        "Dub Pelican",
        "Polka Satellite",
        "Kazoo Senate",
        "Harp Tractor",
    ),
}
GENRES = tuple(ARTISTS)
RUSSIAN_GENRE = "RU Rap"

EN_ADJECTIVES = (
    "Amber",
    "Static",
    "Paper",
    "Velvet",
    "Hollow",
    "Neon",
    "Quiet",
    "Rusty",
    "Silver",
    "Midnight",
    "Copper",
    "Golden",
    "Sleepy",
    "Nobody's",
)
EN_NOUNS = (
    "Harbor",
    "Engine",
    "Signal",
    "Garden",
    "Comet",
    "Ladder",
    "Window",
    "Highway",
    "Lantern",
    "Mirror",
    "Satellite",
    "Weather",
    "Rooftops",
    "Letters",
)
RU_WORDS = (
    "Туман",
    "Провода",
    "Окна",
    "Дворы",
    "Метель",
    "Сквозняк",
    "Фонари",
    "Крыши",
    "Трамваи",
    "Сирень",
    "Гаражи",
    "Ветер",
    "Электричка",
    "Ливень",
)

LEAD_ALBUM_SIZE = 8
COVER_ALBUM_SIZE = 6
SINGLES_SIZE = 4
SHORT_ALBUM_SIZE = 4
ALBUM_SIZES = (2, 2, 2, 3, 3, 3, 4, 4, 6)
BROKEN_PER_ALBUM = (0, 0, 0, 1, 2)
SONG_SECONDS = (61, 360)
INTERLUDE_SECONDS = (20, 50)
SECOND_ALBUM_ODDS = 0.25
SINGLE_WORD_ODDS = 0.3
MISSING_YEAR_ODDS = 0.08
MISSING_MBID_ODDS = 0.1
RELATIVE_PATH_EVERY = 10
FRAME_COUNTS = (8, 9, 10, 11, 12)
BROKEN_STATUSES = ("pending", "nomatch", "fail", "wrong")
PATHLESS_STATUSES = frozenset({"pending", "nomatch"})
STATUS_ERRORS = {"nomatch": "no match", "fail": "download failed", "wrong": "duration mismatch"}
MIX_SIZE = 30
EVENING_SHARED = 14
EVENING_EXTRA = 8
EVENING_SIZE = 20
STRAY_AFTER = 11

ARTIST_INSERT = (
    "INSERT INTO artists(name, mbid, count, genre, tier, canonical) VALUES (?, ?, ?, ?, ?, ?)"
)
ALBUM_INSERT = (
    "INSERT INTO albums(id, artist, mbid, name, year, genre, tier, ntracks, canonical) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
)
TRACK_INSERT = (
    "INSERT INTO tracks(id, album_id, num, artist, album, title, dur, tier, status, path, err) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)

type Row = tuple[int | str | None, ...]


@dataclass(frozen=True)
class FixtureCatalog:
    library_dir: Path
    catalog_db: Path
    cover_jpeg: bytes
    playlists: dict[str, tuple[int, ...]]


@dataclass(frozen=True)
class AlbumPlan:
    genre: str
    credit: str
    artist: str
    name: str
    tier: int
    size: int
    broken: int
    seconds: tuple[int, int] = SONG_SECONDS
    untimed: bool = False
    cover: bool = False


@dataclass(frozen=True)
class TrackRow:
    track_id: int
    album_id: int
    num: int
    artist: str
    album: str
    title: str
    dur: int | None
    tier: int
    status: str
    rel: str
    path: str | None

    def values(self) -> Row:
        return (
            self.track_id,
            self.album_id,
            self.num,
            self.artist,
            self.album,
            self.title,
            self.dur,
            self.tier,
            self.status,
            self.path,
            STATUS_ERRORS.get(self.status),
        )


@dataclass(frozen=True)
class AlbumRow:
    album_id: int
    plan: AlbumPlan
    mbid: str | None
    year: str | None
    tracks: tuple[TrackRow, ...]

    def values(self) -> Row:
        playable = sum(track.status == "ok" for track in self.tracks)
        return (
            self.album_id,
            self.plan.credit,
            self.mbid,
            self.plan.name,
            self.year,
            self.plan.genre,
            self.plan.tier,
            playable,
            album_canonical(self.plan.artist),
        )


def artist_canonical(artist: str) -> str | None:
    if artist == RENAMED_TAG:
        return RENAMED_CANONICAL
    return None if artist in UNCANONICAL else artist


def album_canonical(artist: str) -> str | None:
    return DRIFTED_CANONICAL if artist == RENAMED_TAG else artist_canonical(artist)


def random_mbid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def draw_title(rng: random.Random, genre: str) -> str:
    if genre != RUSSIAN_GENRE:
        return f"{rng.choice(EN_ADJECTIVES)} {rng.choice(EN_NOUNS)}"
    first, second = rng.sample(RU_WORDS, 2)
    return first if rng.random() < SINGLE_WORD_ODDS else f"{first} и {second.lower()}"


def distinct_titles(rng: random.Random, genre: str, count: int) -> list[str]:
    titles: dict[str, str] = {}
    while len(titles) < count:
        title = draw_title(rng, genre)
        titles.setdefault(title.casefold(), title)
    return list(titles.values())


def with_singles(plans: list[AlbumPlan]) -> list[AlbumPlan]:
    lead = plans[0]
    singles = replace(lead, credit=SINGLES_CREDIT, name=SINGLES_ALBUM, size=SINGLES_SIZE, broken=0)
    return [lead, singles]


def with_cover_album(plans: list[AlbumPlan]) -> list[AlbumPlan]:
    cover = replace(plans[0], name=COVER_ALBUM, size=COVER_ALBUM_SIZE, cover=True)
    return [cover, *plans[1:]]


def with_short_album(plans: list[AlbumPlan]) -> list[AlbumPlan]:
    short = replace(plans[0], name=SHORT_ALBUM, size=SHORT_ALBUM_SIZE, seconds=INTERLUDE_SECONDS)
    return [short, *plans[1:]]


def with_untimed_track(plans: list[AlbumPlan]) -> list[AlbumPlan]:
    return [replace(plans[0], broken=0, untimed=True), *plans[1:]]


def with_one_album(plans: list[AlbumPlan]) -> list[AlbumPlan]:
    return plans[:1]


SPECIALS: dict[str, Callable[[list[AlbumPlan]], list[AlbumPlan]]] = {
    SINGLES_ARTIST: with_singles,
    COVER_ARTIST: with_cover_album,
    SHORT_ARTIST: with_short_album,
    UNTIMED_ARTIST: with_untimed_track,
    RENAMED_TAG: with_one_album,
}


def plan_artist(rng: random.Random, genre: str, artist: str, *, lead: bool) -> list[AlbumPlan]:
    tier = rng.randint(1, 4)
    names = distinct_titles(rng, genre, 2)
    sizes = (LEAD_ALBUM_SIZE if lead else rng.choice(ALBUM_SIZES), rng.choice(ALBUM_SIZES))
    plans = [
        AlbumPlan(genre, artist, artist, name, tier, size, rng.choice(BROKEN_PER_ALBUM))
        for name, size in zip(names, sizes, strict=True)
    ]
    kept = plans[: 2 if rng.random() < SECOND_ALBUM_ODDS else 1]
    special = SPECIALS.get(artist)
    return special(kept) if special else kept


def plan_library(rng: random.Random) -> list[AlbumPlan]:
    plans: list[AlbumPlan] = []
    for genre, artists in ARTISTS.items():
        for index, artist in enumerate(artists):
            plans += plan_artist(rng, genre, artist, lead=index == 0)
    return plans


class Layout:
    def __init__(self, rng: random.Random, library_dir: Path) -> None:
        self.rng = rng
        self.library_dir = library_dir
        self.track_ids = itertools.count(1)
        self.playable = itertools.count()
        self.statuses = itertools.cycle(BROKEN_STATUSES)

    def album(self, album_id: int, plan: AlbumPlan) -> AlbumRow:
        count = plan.size + plan.broken
        broken = set(self.rng.sample(range(1, count + 1), plan.broken))
        tracks = []
        for num, title in enumerate(distinct_titles(self.rng, plan.genre, count), start=1):
            status = next(self.statuses) if num in broken else "ok"
            untimed = plan.untimed and num == count
            dur = None if untimed else self.rng.randint(*plan.seconds)
            tracks.append(self.track(album_id, plan, num, title, dur, status))
        return AlbumRow(album_id, plan, self.album_mbid(plan), self.year(), tuple(tracks))

    def track(
        self, album_id: int, plan: AlbumPlan, num: int, title: str, dur: int | None, status: str
    ) -> TrackRow:
        rel = f"{plan.genre}/{plan.credit}/{plan.name}/{num:02d} - {title}.mp3"
        path = self.stored_path(rel, status)
        return TrackRow(
            next(self.track_ids),
            album_id,
            num,
            plan.artist,
            plan.name,
            title,
            dur,
            plan.tier,
            status,
            rel,
            path,
        )

    def stored_path(self, rel: str, status: str) -> str | None:
        if status in PATHLESS_STATUSES:
            return None
        if status == "ok" and next(self.playable) % RELATIVE_PATH_EVERY == RELATIVE_PATH_EVERY - 1:
            return rel
        return str(self.library_dir / rel)

    def album_mbid(self, plan: AlbumPlan) -> str | None:
        if plan.name == SINGLES_ALBUM or self.rng.random() < MISSING_MBID_ODDS:
            return None
        return random_mbid(self.rng)

    def year(self) -> str | None:
        if self.rng.random() < MISSING_YEAR_ODDS:
            return None
        return str(self.rng.randint(1998, 2025))


def artist_rows(rng: random.Random, albums: list[AlbumRow]) -> list[Row]:
    firsts: dict[str, AlbumPlan] = {}
    for album in albums:
        firsts.setdefault(album.plan.artist, album.plan)
    rows: list[Row] = []
    for name, plan in firsts.items():
        canonical = artist_canonical(name)
        mbid = random_mbid(rng) if canonical else None
        rows.append((name, mbid, rng.randint(1, 40), plan.genre, plan.tier, canonical))
    return rows


def write_track(path: Path, track_id: int, cover: bytes | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    audio = mp3_bytes(FRAME_COUNTS[track_id % len(FRAME_COUNTS)])
    path.write_bytes(with_cover(audio, cover) if cover else audio)


def write_audio(library_dir: Path, albums: list[AlbumRow], cover: bytes) -> None:
    for album in albums:
        for track in album.tracks:
            if track.status == "ok":
                write_track(
                    library_dir / track.rel, track.track_id, cover if album.plan.cover else None
                )


def extinf(track: TrackRow) -> str:
    return f"#EXTINF:{track.dur or -1},{track.artist} - {track.title}"


def recased(index: int, rel: str) -> str:
    if index % 10 == 4:
        return rel.upper()
    if index % 10 == 7:
        return rel.lower()
    return rel


def mix_text(tracks: list[TrackRow]) -> str:
    lines = ["#EXTM3U", ""]
    for index, track in enumerate(tracks):
        if index % 2 == 0:
            lines.append(extinf(track))
        lines.append(DEVICE_MUSIC + recased(index, track.rel))
        if index == STRAY_AFTER:
            lines.append(DEVICE_MUSIC + STRAY_ENTRY)
    return "\n".join(lines) + "\n"


def evening_text(tracks: list[TrackRow]) -> str:
    lines = ["#EXTM3U"]
    for track in tracks:
        lines += [extinf(track), DEVICE_MUSIC + track.rel]
    return "\n".join(lines) + "\n"


def write_playlists(
    rng: random.Random, library_dir: Path, albums: list[AlbumRow]
) -> dict[str, tuple[int, ...]]:
    playable = [track for album in albums for track in album.tracks if track.status == "ok"]
    by_artist: dict[str, list[TrackRow]] = defaultdict(list)
    for track in playable:
        by_artist[track.artist].append(track)
    mix = rng.sample(playable, MIX_SIZE)
    shared = [rng.choice(by_artist[track.artist]) for track in mix[:EVENING_SHARED]]
    evening = list(dict.fromkeys([*shared, *rng.sample(playable, EVENING_EXTRA)]))[:EVENING_SIZE]
    folder = library_dir / PLAYLISTS_DIR
    folder.mkdir()
    mix_name, evening_name = PLAYLISTS
    (folder / f"{mix_name}.m3u8").write_bytes(mix_text(mix).encode("utf-8-sig"))
    (folder / f"{evening_name}.m3u8").write_bytes(evening_text(evening).encode())
    (folder / IGNORED_PLAYLIST).write_bytes(evening_text(mix[:3]).encode())
    return {
        mix_name: tuple(track.track_id for track in mix),
        evening_name: tuple(track.track_id for track in evening),
    }


def write_catalog(path: Path, albums: list[AlbumRow], artists: list[Row]) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.executescript(SCHEMA.read_text(encoding="utf-8"))
        connection.execute("PRAGMA journal_mode=DELETE")
        with connection:
            connection.executemany(ARTIST_INSERT, artists)
            connection.executemany(ALBUM_INSERT, [album.values() for album in albums])
            connection.executemany(
                TRACK_INSERT, [track.values() for album in albums for track in album.tracks]
            )


def build_catalog(root: Path) -> FixtureCatalog:
    base = root.resolve()
    library_dir = base / "lib"
    catalog_db = base / "state.sqlite"
    library_dir.mkdir(parents=True)
    rng = random.Random(SEED)
    layout = Layout(rng, library_dir)
    albums = [layout.album(index, plan) for index, plan in enumerate(plan_library(rng), start=1)]
    cover = cover_jpeg()
    write_audio(library_dir, albums, cover)
    playlists = write_playlists(rng, library_dir, albums)
    write_catalog(catalog_db, albums, artist_rows(rng, albums))
    return FixtureCatalog(library_dir, catalog_db, cover, playlists)
