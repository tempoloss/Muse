import base64
from pathlib import Path

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid01


def application_server_key(key_file: Path) -> str:
    if key_file.is_file():
        vapid = Vapid01.from_file(str(key_file))
    else:
        vapid = Vapid01()
        vapid.generate_keys()
        vapid.save_key(str(key_file))
    raw = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
