from datetime import date

from muse.activity.domain import LikeChanged, PlayRecorded
from muse.catalog.service import Catalog
from muse.identity.domain import Users
from muse.pet.domain import (
    BAD_NAME,
    CARE,
    CARE_BONUS,
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
    QuestPick,
    QuestProgress,
    QuestRepository,
    Row,
    added,
    album_progress,
    any_album,
    cared,
    drawn_album,
    pet_view,
    quest_kind,
    quest_view,
    sampled_likes,
    ticked,
    together_progress,
    turn_share,
    valid_name,
)
from muse.shared.clock import Clock
from muse.shared.db import UnitOfWork
from muse.shared.errors import DomainError


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
