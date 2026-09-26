from typing import Any

import structlog
from litestar import Request, Response
from litestar.exceptions import HTTPException, ValidationException
from litestar.types import ExceptionHandlersMap

from muse.shared.errors import detail_response

log = structlog.get_logger()


def http_error(_: Request, error: HTTPException) -> Response[dict[str, object]]:
    return detail_response(error.status_code, error.detail, error.headers)


def validation_error(_: Request, error: ValidationException) -> Response[dict[str, object]]:
    issues: list[Any] = error.extra if isinstance(error.extra, list) else []
    detail = [
        {
            "loc": [issue.get("source", "body"), issue.get("key", "")],
            "msg": issue.get("message", ""),
        }
        for issue in issues
        if isinstance(issue, dict)
    ]
    return detail_response(422, detail)


def internal_error(request: Request, error: Exception) -> Response[dict[str, object]]:
    log.error("unhandled error", method=request.method, path=request.url.path, exc_info=error)
    return detail_response(500, "internal error")


EXCEPTION_HANDLERS: ExceptionHandlersMap = {
    ValidationException: validation_error,
    HTTPException: http_error,
    Exception: internal_error,
}
