import threading

from muse.identity.domain import Users
from muse.together.domain import Beat, follows, fresh


class LiveRegistry:
    def __init__(self, users: Users) -> None:
        self._user_ids = tuple(user.id for user in users.all)
        self._beats: dict[str, Beat] = {}
        self._following: dict[str, int] = {}
        self._lock = threading.Lock()

    def report(self, user_id: str, partner_id: str, beat: Beat) -> tuple[Beat | None, Beat | None]:
        with self._lock:
            previous = self._beats.get(user_id)
            self._beats[user_id] = beat
            return previous, self._beats.get(partner_id)

    def beat_of(self, user_id: str) -> Beat | None:
        with self._lock:
            return self._beats.get(user_id)

    def partner_state(self, partner_id: str, now: int) -> tuple[Beat | None, bool]:
        with self._lock:
            beat = self._beats.get(partner_id)
            following = follows(self._following.get(partner_id), now)
        return (beat if fresh(beat, now) else None), following

    def start_following(self, user_id: str, partner_id: str, now: int) -> bool:
        with self._lock:
            if follows(self._following.get(partner_id), now):
                return False
            self._following[user_id] = now
            return True

    def stop_following(self, user_id: str) -> None:
        with self._lock:
            self._following.pop(user_id, None)

    def together_now(self, now_ms: int) -> bool:
        with self._lock:
            return all(fresh(self._beats.get(user_id), now_ms) for user_id in self._user_ids)
