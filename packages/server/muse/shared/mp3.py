from dataclasses import dataclass

V1_KBPS = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
V2_KBPS = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}
MPEG1 = 3
LAYER3 = 1
MONO = 3
QUIET_BITRATE = 1
INFO_TAGS = (b"Xing", b"Info")
VBRI_AT = 36
SIDE_INFO = {(True, False): 32, (True, True): 17, (False, False): 17, (False, True): 9}


@dataclass(frozen=True, slots=True)
class Kind:
    version: int
    rate: int
    mono: bool

    @property
    def samples(self) -> int:
        return 1152 if self.version == MPEG1 else 576


@dataclass(frozen=True, slots=True)
class Audio:
    kind: Kind
    frames: list[int]


STREAM_KIND = Kind(MPEG1, 48000, mono=False)


def frame_at(data: bytes, at: int) -> tuple[Kind, int] | None:
    if at < 0 or at + 4 > len(data) or data[at] != 0xFF or data[at + 1] & 0xE0 != 0xE0:
        return None
    b1, b2, b3 = data[at + 1], data[at + 2], data[at + 3]
    version, layer, index, rate_index = (b1 >> 3) & 3, (b1 >> 1) & 3, b2 >> 4, (b2 >> 2) & 3
    if version == 1 or layer != LAYER3 or index in (0, 15) or rate_index == 3:
        return None
    rate = RATES[version][rate_index]
    padding = (b2 >> 1) & 1
    if version == MPEG1:
        size = 144000 * V1_KBPS[index] // rate + padding
    else:
        size = 72000 * V2_KBPS[index] // rate + padding
    return Kind(version, rate, b3 >> 6 == MONO), size


def tags_end(data: bytes) -> int:
    at = 0
    while data[at : at + 3] == b"ID3" and at + 10 <= len(data):
        size = data[at + 6] << 21 | data[at + 7] << 14 | data[at + 8] << 7 | data[at + 9]
        at += 10 + size + (10 if data[at + 5] & 0x10 else 0)
    return at


def first_frame(data: bytes, at: int) -> int | None:
    while (at := data.find(b"\xff", at)) >= 0:
        found = frame_at(data, at)
        if found is not None:
            following = frame_at(data, at + found[1])
            if following is not None and following[0] == found[0]:
                return at
        at += 1
    return None


def info_frame(data: bytes, at: int, kind: Kind) -> bool:
    side = SIDE_INFO[(kind.version == MPEG1, kind.mono)]
    tag = data[at + 4 + side : at + 8 + side]
    return tag in INFO_TAGS or data[at + VBRI_AT : at + VBRI_AT + 4] == b"VBRI"


def audio_of(data: bytes) -> Audio | None:
    start = first_frame(data, tags_end(data))
    if start is None:
        return None
    head = frame_at(data, start)
    if head is None:
        return None
    kind, size = head
    if info_frame(data, start, kind):
        start += size
    frames: list[int] = []
    at = start
    while (found := frame_at(data, at)) is not None and found[0] == kind:
        if at + found[1] > len(data):
            break
        frames.append(at)
        at += found[1]
    if not frames:
        return None
    frames.append(at)
    return Audio(kind, frames)


def silent_frame(kind: Kind) -> bytes:
    mpeg1 = kind.version == MPEG1
    head = bytes(
        (
            0xFF,
            0xE0 | kind.version << 3 | LAYER3 << 1 | 1,
            QUIET_BITRATE << 4 | RATES[kind.version].index(kind.rate) << 2,
            MONO << 6 if kind.mono else 0,
        )
    )
    kbps = (V1_KBPS if mpeg1 else V2_KBPS)[QUIET_BITRATE]
    size = (144000 if mpeg1 else 72000) * kbps // kind.rate
    return head + bytes(size - len(head))


@dataclass(slots=True)
class Joiner:
    kind: Kind | None = None
    planned: float = 0.0
    emitted: int = 0

    def add(self, data: bytes, seconds: float, start: float = 0.0) -> bytes | None:
        audio = audio_of(data)
        if audio is None or (self.kind is not None and audio.kind != self.kind):
            return None
        kind = self.kind = audio.kind
        per_second = kind.rate / kind.samples
        self.planned += seconds - start
        count = max(0, round(self.planned * per_second) - self.emitted)
        self.emitted += count
        skip = round(start * per_second)
        have = max(0, min(count, len(audio.frames) - 1 - skip))
        body = data[audio.frames[skip] : audio.frames[skip + have]] if have else b""
        return body + silent_frame(kind) * (count - have)
