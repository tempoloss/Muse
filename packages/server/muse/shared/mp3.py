from dataclasses import dataclass, field

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
ID3_HEADER = 10
SYNC_LIMIT = 1 << 20


@dataclass(frozen=True, slots=True)
class Kind:
    version: int
    rate: int
    mono: bool

    @property
    def samples(self) -> int:
        return 1152 if self.version == MPEG1 else 576


STREAM_KIND = Kind(MPEG1, 48000, mono=False)


def frame_at(data: bytes | bytearray, at: int) -> tuple[Kind, int] | None:
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


def first_frame(data: bytes | bytearray, at: int) -> int | None:
    while (at := data.find(b"\xff", at)) >= 0:
        found = frame_at(data, at)
        if found is not None:
            following = frame_at(data, at + found[1])
            if following is not None and following[0] == found[0]:
                return at
        at += 1
    return None


def info_frame(data: bytes | bytearray, at: int, kind: Kind) -> bool:
    side = SIDE_INFO[(kind.version == MPEG1, kind.mono)]
    tag = data[at + 4 + side : at + 8 + side]
    return tag in INFO_TAGS or data[at + VBRI_AT : at + VBRI_AT + 4] == b"VBRI"


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
class FrameReader:
    kind: Kind | None = None
    done: bool = False
    buffer: bytearray = field(default_factory=bytearray)
    skip: int = 0
    tagged: bool = False

    def push(self, data: bytes) -> list[bytes]:
        if self.done:
            return []
        self.buffer += data
        if self.kind is None and not self._start():
            return []
        return self._frames()

    def _start(self) -> bool:
        while not self.tagged:
            dropped = min(self.skip, len(self.buffer))
            del self.buffer[:dropped]
            self.skip -= dropped
            if self.skip or len(self.buffer) < ID3_HEADER:
                return False
            if self.buffer[:3] != b"ID3":
                self.tagged = True
                break
            head = self.buffer
            size = head[6] << 21 | head[7] << 14 | head[8] << 7 | head[9]
            self.skip = ID3_HEADER + size + (ID3_HEADER if head[5] & 0x10 else 0)
        at = first_frame(self.buffer, 0)
        if at is None:
            if len(self.buffer) > SYNC_LIMIT:
                self.done = True
            return False
        found = frame_at(self.buffer, at)
        if found is None:
            return False
        kind, size = found
        del self.buffer[:at]
        if info_frame(self.buffer, 0, kind):
            del self.buffer[:size]
        self.kind = kind
        return True

    def _frames(self) -> list[bytes]:
        frames: list[bytes] = []
        at = 0
        while (found := frame_at(self.buffer, at)) is not None and found[0] == self.kind:
            if at + found[1] > len(self.buffer):
                break
            frames.append(bytes(self.buffer[at : at + found[1]]))
            at += found[1]
        else:
            if len(self.buffer) - at >= 4:
                self.done = True
        del self.buffer[:at]
        return frames


@dataclass(slots=True)
class Joiner:
    kind: Kind
    planned: float = 0.0
    emitted: int = 0
    skip: int = 0
    left: int = 0

    def song(self, seconds: float, start: float = 0.0) -> None:
        per_second = self.kind.rate / self.kind.samples
        self.planned += seconds - start
        count = max(0, round(self.planned * per_second) - self.emitted)
        self.emitted += count
        self.skip = round(start * per_second)
        self.left = count

    def take(self, frames: list[bytes]) -> bytes:
        dropped = min(self.skip, len(frames))
        self.skip -= dropped
        kept = frames[dropped : dropped + self.left]
        self.left -= len(kept)
        return b"".join(kept)

    def finish(self) -> bytes:
        missing, self.left = self.left, 0
        return silent_frame(self.kind) * missing
