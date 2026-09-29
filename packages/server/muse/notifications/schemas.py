import msgspec


class PushKeysBody(msgspec.Struct):
    p256dh: str
    auth: str


class SubscribeBody(msgspec.Struct):
    endpoint: str
    keys: PushKeysBody


class UnsubscribeBody(msgspec.Struct):
    endpoint: str
