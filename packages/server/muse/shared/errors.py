from collections.abc import Mapping

from litestar import Request, Response
from litestar.types import ExceptionHandlersMap


class DomainError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def detail_response(
    status: int, detail: object, headers: Mapping[str, str] | None = None
) -> Response[dict[str, object]]:
    return Response({"detail": detail}, status_code=status, headers=dict(headers or {}))


def domain_errors(statuses: Mapping[str, int]) -> ExceptionHandlersMap:
    def handle(_: Request, error: DomainError) -> Response[dict[str, object]]:
        return detail_response(statuses[error.code], error.code)

    return {DomainError: handle}
