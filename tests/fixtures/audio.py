import io

from mutagen.id3 import APIC, ID3, Encoding, PictureType
from PIL import Image

FRAME_HEADER = bytes.fromhex("fffb9404")
FRAME_LENGTH = 384
COVER_SIDE = 600
COVER_COLOR = (184, 92, 56)


def mp3_bytes(frames: int) -> bytes:
    return (FRAME_HEADER + bytes(FRAME_LENGTH - len(FRAME_HEADER))) * frames


def cover_jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (COVER_SIDE, COVER_SIDE), COVER_COLOR).save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def with_cover(audio: bytes, jpeg: bytes) -> bytes:
    buffer = io.BytesIO(audio)
    tags = ID3()
    tags.add(
        APIC(
            encoding=Encoding.UTF8,
            mime="image/jpeg",
            type=PictureType.COVER_FRONT,
            desc="cover",
            data=jpeg,
        )
    )
    tags.save(buffer)
    return buffer.getvalue()
