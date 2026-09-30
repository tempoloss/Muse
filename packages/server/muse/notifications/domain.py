import json
from dataclasses import dataclass
from typing import Protocol

ENDPOINT_SCHEME = "https://"
ENDPOINT_MAX_CHARS = 1000
BAD_ENDPOINT = "bad endpoint"
LETTER_TITLES = ("{} принёс записку", "{} прибежал с запиской", "{} оставил тебе записку")
LETTER_BODY_CHARS = 120


@dataclass(frozen=True, slots=True)
class PushMessage:
    title: str
    body: str
    url: str
    tag: str

    def payload(self) -> str:
        return json.dumps(
            {"title": self.title, "body": self.body, "url": self.url, "tag": self.tag},
            ensure_ascii=False,
        )


@dataclass(frozen=True, slots=True)
class Subscription:
    endpoint: str
    p256dh: str
    auth: str


def valid_endpoint(endpoint: str) -> bool:
    return endpoint.startswith(ENDPOINT_SCHEME) and len(endpoint) <= ENDPOINT_MAX_CHARS


class PushSender(Protocol):
    @property
    def public_key(self) -> str | None: ...

    async def send(self, user_id: str, message: PushMessage) -> None: ...


class SubscriptionRepository(Protocol):
    async def save(self, user_id: str, subscription: Subscription, at: int) -> None: ...

    async def remove(self, user_id: str, endpoint: str) -> None: ...
