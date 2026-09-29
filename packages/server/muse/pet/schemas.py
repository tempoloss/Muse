import msgspec


class PetNameBody(msgspec.Struct):
    name: str
