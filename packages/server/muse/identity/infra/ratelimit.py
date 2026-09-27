import time
from collections import deque
from collections.abc import Callable, Sequence

WINDOW_S = 900.0
LIMITS = {"ip": 5, "login": 10}


class LoginRateLimiter:
    def __init__(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._attempts: dict[str, deque[float]] = {}

    def hit(self, keys: Sequence[str]) -> float:
        now = self._monotonic()
        wait = 0.0
        for key in keys:
            attempts = self._attempts.setdefault(key, deque())
            while attempts and attempts[0] <= now - WINDOW_S:
                attempts.popleft()
            if len(attempts) >= LIMITS[key.split(":", 1)[0]]:
                wait = max(wait, attempts[0] + WINDOW_S - now)
        if wait:
            return wait
        for key in keys:
            self._attempts[key].append(now)
        return 0.0

    def clear(self, keys: Sequence[str]) -> None:
        for key in keys:
            self._attempts.pop(key, None)
