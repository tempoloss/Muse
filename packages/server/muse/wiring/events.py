from dishka import Provider, Scope, decorate, provide

from muse.activity.domain import LikeChanged, PlayRecorded
from muse.notifications.service import PushReactions
from muse.pet.domain import QuestAlbumChosen
from muse.pet.service import PetPushes, PetReactions
from muse.shared.events import EventBus
from muse.together.domain import TogetherAccrued


class EventsProvider(Provider):
    scope = Scope.REQUEST

    bus = provide(EventBus)

    @decorate
    def notifications(self, bus: EventBus, pushes: PushReactions) -> EventBus:
        bus.subscribe(LikeChanged, pushes.mutual_like)
        return bus

    @decorate
    def pet(self, bus: EventBus, reactions: PetReactions, pushes: PetPushes) -> EventBus:
        bus.subscribe(PlayRecorded, reactions.music)
        bus.subscribe(LikeChanged, reactions.treat)
        bus.subscribe(QuestAlbumChosen, pushes.quest_album)
        bus.subscribe(TogetherAccrued, reactions.together)
        return bus
