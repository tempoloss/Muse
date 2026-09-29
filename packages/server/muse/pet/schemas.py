import msgspec


class PetNameBody(msgspec.Struct):
    name: str


class QuestAlbumBody(msgspec.Struct):
    album_id: int
