from datetime import date

from muse.activity.domain import LikeChanged, PlayRecorded
from muse.catalog.domain import NO_ALBUM
from muse.catalog.service import Catalog
from muse.identity.domain import Users
from muse.notifications.service import Notifier
from muse.pet.domain import (
    BAD_NAME,
    CARE,
    CARE_BONUS,
    DONE,
    GIFT_JOY,
    HUNGER_PUSH_EVERY_MS,
    MUSIC_FOOD,
    NO_SUCH_ACTION,
    PET_MUSIC_DAY,
    QUEST_REWARD,
    QUESTS,
    TAKES_TURNS,
    TREAT,
    TURN_MS,
    ListeningTogether,
    Pet,
    PetRepository,
    QuestAlbumChosen,
    QuestPick,
    QuestProgress,
    QuestRepository,
    Row,
    added,
    album_progress,
    any_album,
    cared,
    drawn_album,
    hungry,
    pet_view,
    quest_kind,
    quest_view,
    sampled_likes,
    ticked,
    together_joy,
    together_progress,
    turn_share,
    valid_name,
)
from muse.shared.clock import Clock
from muse.shared.db import UnitOfWork
from muse.shared.errors import DomainError
from muse.shared.events import EventBus
from muse.together.domain import LetterSent, TogetherAccrued


class PetKeeper:
    def __init__(self, pets: PetRepository) -> None:
        self.pets = pets

    async def tick(self, now: int) -> Pet:
        await self.pets.lock()
        pet = ticked(await self.pets.load(), now)
        await self.pets.save(pet)
        return pet

    async def add(self, now: int, **deltas: float) -> Pet:
        pet = added(await self.tick(now), **deltas)
        await self.pets.save(pet)
        return pet


class Quests:
    def __init__(
        self, catalog: Catalog, quests: QuestRepository, users: Users, clock: Clock
    ) -> None:
        self.catalog = catalog
        self.quests = quests
        self.users = users
        self.clock = clock

    async def today(self, user_id: str) -> Row:
        today = self.clock.today()
        picked = await self.quests.picked(today.isoformat())
        kind = picked.kind if picked else quest_kind(today)
        return quest_view(kind, await self._progress(kind, picked, user_id, today), picked)

    async def playable_album(self, album_id: int) -> Row:
        found = next((a for a in await self.catalog.albums() if a["id"] == album_id), None)
        if found is None:
            raise DomainError(NO_ALBUM)
        return found

    async def choose_album(self, user_id: str, album_id: int, now: int) -> None:
        chosen = QuestPick("same_album", album_id, user_id)
        await self.quests.pick(self.clock.today().isoformat(), chosen, now)

    async def _progress(
        self, kind: str, picked: QuestPick | None, user_id: str, today: date
    ) -> QuestProgress:
        since = self.clock.day_start_ms(today)
        if kind == "same_album":
            return await self._same_album(picked, today, since)
        if kind == "shared_like":
            return await self._shared_like(user_id, today, since)
        text, goal = QUESTS[kind]
        if kind == "letters":
            return QuestProgress(text, await self.quests.letter_senders_since(since), goal)
        seconds = await self.quests.together_seconds(today.isoformat())
        return QuestProgress(text, together_progress(seconds), goal)

    async def _same_album(self, picked: QuestPick | None, today: date, since: int) -> QuestProgress:
        albums = await self.catalog.albums()
        chosen = next((a for a in albums if picked and a["id"] == picked.album_id), None)
        album = chosen or drawn_album(albums, today)
        if album is None:
            return any_album()
        heard = await self.quests.album_heard(since, album["id"])
        return album_progress(album, heard, [user.id for user in self.users.all])

    async def _shared_like(self, user_id: str, today: date, since: int) -> QuestProgress:
        text, goal = QUESTS["shared_like"]
        progress = 1 if await self.quests.shared_like_since(since) else 0
        theirs = await self.quests.liked_only_by(self.users.partner_id(user_id), user_id)
        rows = await self.catalog.track_rows(sampled_likes(user_id, today, theirs))
        return QuestProgress(text, progress, goal, track=next(iter(rows.values()), None))


class PetViews:
    def __init__(
        self,
        keeper: PetKeeper,
        pets: PetRepository,
        quests: Quests,
        together: ListeningTogether,
        clock: Clock,
    ) -> None:
        self.keeper = keeper
        self.pets = pets
        self.quests = quests
        self.together = together
        self.clock = clock

    async def view(self, user_id: str, now: int) -> Row:
        pet = await self.keeper.tick(now)
        quest = await self.quests.today(user_id)
        day = self.clock.today().isoformat()
        if quest["done"] and not await self.pets.logged("quest", day):
            pet = await self.keeper.add(now, **QUEST_REWARD)
            await self.pets.log(now, None, "quest", day)
        together = self.together.together_now(now)
        return pet_view(pet, together, quest, await self.pets.recent_log())


class PetCare:
    def __init__(
        self,
        keeper: PetKeeper,
        pets: PetRepository,
        views: PetViews,
        users: Users,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self.keeper = keeper
        self.pets = pets
        self.views = views
        self.users = users
        self.clock = clock
        self.uow = uow

    async def show(self, user_id: str) -> Row:
        view = await self.views.view(user_id, self.clock.now_ms())
        await self.uow.commit()
        return view

    async def rename(self, user_id: str, name: str) -> Row:
        name = name.strip()
        if not valid_name(name):
            raise DomainError(BAD_NAME)
        now = self.clock.now_ms()
        await self.pets.rename(name)
        await self.pets.log(now, user_id, "name", name)
        view = await self.views.view(user_id, now)
        await self.uow.commit()
        return view

    async def act(self, user_id: str, action: str) -> Row:
        if action not in CARE:
            raise DomainError(NO_SUCH_ACTION)
        now = self.clock.now_ms()
        pet = await self.keeper.tick(now)
        last = await self.pets.last_carer(action, now - TURN_MS) if action in TAKES_TURNS else None
        half = turn_share(action, last, user_id)
        care = cared(pet, action, half, now)
        await self.pets.save(care.pet)
        await self.pets.log(now, user_id, care.logged_as)
        await self._bonus(now)
        view = await self.views.view(user_id, now)
        await self.uow.commit()
        return {**view, "halved": half < 1}

    async def _bonus(self, now: int) -> None:
        today = self.clock.today()
        user_ids = [user.id for user in self.users.all]
        carers = await self.pets.carers_since(self.clock.day_start_ms(today), user_ids)
        day = today.isoformat()
        if carers == len(user_ids) and not await self.pets.logged("bonus", day):
            await self.keeper.add(now, **CARE_BONUS)
            await self.pets.log(now, None, "bonus", day)


class PetReactions:
    def __init__(self, keeper: PetKeeper, pets: PetRepository, clock: Clock) -> None:
        self.keeper = keeper
        self.pets = pets
        self.clock = clock

    async def music(self, event: PlayRecorded) -> None:
        if not event.reached_now:
            return
        fed = await self.pets.music_fed_since(self.clock.day_start_ms(self.clock.today()))
        if fed < PET_MUSIC_DAY:
            amount = min(MUSIC_FOOD, PET_MUSIC_DAY - fed)
            await self.keeper.add(event.at, food=amount)
            await self.pets.log(event.at, event.user, "music", str(amount))

    async def treat(self, event: LikeChanged) -> None:
        if not event.mutual_new:
            return
        now = self.clock.now_ms()
        await self.keeper.add(now, **TREAT)
        await self.pets.log(now, event.user, "treat", str(event.track_id))

    async def together(self, event: TogetherAccrued) -> None:
        joy = together_joy(event.seconds_before, event.seconds_after)
        if joy > 0:
            await self.keeper.add(self.clock.now_ms(), joy=joy)

    async def gift(self, event: LetterSent) -> None:
        now = self.clock.now_ms()
        await self.keeper.add(now, joy=GIFT_JOY)
        await self.pets.log(now, event.sender, "gift", str(event.letter_id))


class QuestAlbums:
    def __init__(
        self,
        quests: Quests,
        pets: PetRepository,
        views: PetViews,
        bus: EventBus,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self.quests = quests
        self.pets = pets
        self.views = views
        self.bus = bus
        self.clock = clock
        self.uow = uow

    async def choose(self, user_id: str, album_id: int) -> Row:
        album = await self.quests.playable_album(album_id)
        now = self.clock.now_ms()
        await self.pets.lock()
        if (await self.quests.today(user_id))["done"]:
            raise DomainError(DONE)
        await self.quests.choose_album(user_id, album["id"], now)
        chosen = QuestAlbumChosen(user_id, album["id"], album["name"], album["artist"])
        await self.bus.publish(chosen)
        view = await self.views.view(user_id, now)
        await self.uow.commit()
        return view


class PetPushes:
    def __init__(self, notifier: Notifier, users: Users, clock: Clock) -> None:
        self.notifier = notifier
        self.users = users
        self.clock = clock

    async def quest_album(self, event: QuestAlbumChosen) -> None:
        chooser = self.users.get(event.user)
        if chooser is None:
            return
        await self.notifier.notify(
            self.users.partner_id(event.user),
            f"{chooser.beast} выбрал альбом дня",
            f"Слушаем вместе\n🎵 {event.name} · {event.artist}",
            "/us",
            f"quest-{self.clock.today().isoformat()}",
        )

    async def hungry(self) -> None:
        first, second = self.users.all
        for user in self.users.all:
            await self.notifier.notify(
                user.id,
                f"{first.emoji}{second.emoji} {first.nick} и {second.nick} проголодались",
                "Покорми их во вкладке «Мы» или просто включи музыку",
                "/us",
                "pet-hungry",
            )


class HungerWatch:
    def __init__(
        self,
        keeper: PetKeeper,
        pets: PetRepository,
        pushes: PetPushes,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self.keeper = keeper
        self.pets = pets
        self.pushes = pushes
        self.clock = clock
        self.uow = uow

    async def check(self) -> None:
        now = self.clock.now_ms()
        pet = await self.keeper.tick(now)
        if hungry(pet) and not await self.pets.hungry_pushed_since(now - HUNGER_PUSH_EVERY_MS):
            await self.pets.log(now, None, "hungry_push")
            await self.pushes.hungry()
        await self.uow.commit()
