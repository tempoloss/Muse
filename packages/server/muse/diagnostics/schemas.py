import msgspec


class PlayerLogBody(msgspec.Struct):
    event: str
    track_id: int | None = None
