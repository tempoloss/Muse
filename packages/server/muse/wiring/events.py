from dishka import Provider, Scope, provide

from muse.shared.events import EventBus


class EventsProvider(Provider):
    scope = Scope.REQUEST

    bus = provide(EventBus)
