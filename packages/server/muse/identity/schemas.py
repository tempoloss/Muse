import msgspec


class LoginBody(msgspec.Struct):
    login: str
    password: str
