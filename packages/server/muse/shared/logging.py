import logging
import sys
from typing import TextIO

import structlog


def configure_logging(stream: TextIO | None = None) -> None:
    target = sys.stdout if stream is None else stream
    logging.basicConfig(format="%(message)s", stream=target, level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(target),
        cache_logger_on_first_use=False,
    )
