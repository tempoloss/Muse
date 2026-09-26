from typing import Annotated

from litestar import Litestar, get
from litestar.params import QueryParameter
from litestar.testing import AsyncTestClient
from structlog.testing import capture_logs

from muse.http.errors import EXCEPTION_HANDLERS


@get("/api/stats")
async def stats(days: Annotated[int, QueryParameter(ge=1, le=365)] = 30) -> dict[str, int]:
    return {"days": days}


@get("/api/boom")
async def boom() -> dict[str, int]:
    raise ZeroDivisionError("secret internals")


def make_app() -> Litestar:
    return Litestar([stats, boom], exception_handlers=EXCEPTION_HANDLERS, openapi_config=None)


async def test_invalid_parameters_are_422_with_their_location() -> None:
    async with AsyncTestClient(make_app()) as client:
        response = await client.get("/api/stats?days=0")

    assert response.status_code == 422
    [issue] = response.json()["detail"]
    assert issue["loc"] == ["query", "days"]
    assert issue["msg"]


async def test_unhandled_errors_are_500_without_internals_and_logged() -> None:
    with capture_logs() as logs:
        async with AsyncTestClient(make_app()) as client:
            response = await client.get("/api/boom")

    assert (response.status_code, response.json()) == (500, {"detail": "internal error"})
    assert "secret" not in response.text
    assert [entry["event"] for entry in logs] == ["unhandled error"]


async def test_framework_errors_keep_their_status_and_headers() -> None:
    async with AsyncTestClient(make_app()) as client:
        response = await client.post("/api/stats")

    assert (response.status_code, response.json()) == (405, {"detail": "Method Not Allowed"})
    assert "GET" in response.headers["allow"]
