import msgspec


class PlayBody(msgspec.Struct):
    track_id: int
    started_at: int
    listened_ms: int
    completed: bool
    skipped: bool
    source: str
