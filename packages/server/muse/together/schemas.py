import msgspec


class LiveBody(msgspec.Struct):
    track_id: int | None = None
    position: float = 0.0
    playing: bool = False


class LetterBody(msgspec.Struct):
    track_id: int
    text: str
