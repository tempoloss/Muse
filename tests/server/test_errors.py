from litestar import Litestar, Router, get
from litestar.params import FromPath
from litestar.testing import AsyncTestClient

from muse.shared.errors import DomainError, domain_errors


@get("/thing/{number:int}")
async def thing(number: FromPath[int]) -> dict[str, int]:
    if number == 0:
        raise DomainError("no thing")
    if number == 1:
        raise DomainError("busy")
    return {"number": number}


def make_app() -> Litestar:
    router = Router(
        "/api",
        route_handlers=[thing],
        exception_handlers=domain_errors({"no thing": 404, "busy": 409}),
    )
    return Litestar([router], openapi_config=None)


async def test_domain_errors_become_their_mapped_status_with_the_code_as_detail() -> None:
    async with AsyncTestClient(make_app()) as client:
        missing = await client.get("/api/thing/0")
        busy = await client.get("/api/thing/1")
        fine = await client.get("/api/thing/2")

    assert (missing.status_code, missing.json()) == (404, {"detail": "no thing"})
    assert (busy.status_code, busy.json()) == (409, {"detail": "busy"})
    assert (fine.status_code, fine.json()) == (200, {"number": 2})
