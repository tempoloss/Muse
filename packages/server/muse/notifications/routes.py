from typing import Any

from dishka.integrations.litestar import FromDishka, inject
from litestar import Request, Router, get, post

from muse.identity.domain import User
from muse.notifications.domain import BAD_ENDPOINT, PushSender, Subscription
from muse.notifications.schemas import SubscribeBody, UnsubscribeBody
from muse.notifications.service import PushSubscriptions
from muse.shared.errors import domain_errors

ERRORS = {BAD_ENDPOINT: 422}


@get("/push/key")
@inject
async def push_key(sender: FromDishka[PushSender]) -> dict[str, str | None]:
    return {"key": sender.public_key}


@post("/push/subscribe", status_code=204)
@inject
async def subscribe(
    data: SubscribeBody,
    request: Request[User, str, Any],
    subscriptions: FromDishka[PushSubscriptions],
) -> None:
    subscription = Subscription(data.endpoint, data.keys.p256dh, data.keys.auth)
    await subscriptions.subscribe(request.user.id, subscription)


@post("/push/unsubscribe", status_code=204)
@inject
async def unsubscribe(
    data: UnsubscribeBody,
    request: Request[User, str, Any],
    subscriptions: FromDishka[PushSubscriptions],
) -> None:
    await subscriptions.unsubscribe(request.user.id, data.endpoint)


router = Router(
    "/api",
    route_handlers=[push_key, subscribe, unsubscribe],
    exception_handlers=domain_errors(ERRORS),
)
