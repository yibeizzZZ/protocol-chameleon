"""Synthetic two-window SPI service peers. Run directly for the panel audit."""

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from itertools import product


GAPS = (0, 16, 64, 128)
B_FRAME = bytes((2, 0x55, 0))
B = (1, B_FRAME)


@lru_cache(maxsize=2048)
def _token(seed, run_index, window):
    data = f"spi-panel-v1/{seed}/{run_index}/{window}".encode("ascii")
    return 1 + int.from_bytes(sha256(data).digest()[:8], "big") % 255


@dataclass(frozen=True)
class Window:
    token: int
    reply: int
    gap: int

    def retry_a(self):
        return (0, bytes((1, self.token, 0)))


def _healthy(current, previous):
    return [B]


def _select_wiring(current, previous):
    return [(0, B_FRAME)]


def _level_enqueue(current, previous):
    return [B, B]


def _irq_merge(current, previous):
    if current.gap == 0:
        return []
    return [B]


def _backoff_carry(current, previous):
    # A four-bit scheduler index discards the service event on carry.
    elapsed_quanta = current.gap // 16
    status_delay = current.reply & 0x0F
    if elapsed_quanta + status_delay >= 16:
        return []
    return [B]


def _echo_completion(current, previous):
    if current.reply == current.token:
        return []
    return [B]


def _status_alias(current, previous):
    # Five response bits alias a replay instruction in the dispatch decoder.
    if current.reply >> 3 == 0b11010:
        return [B, current.retry_a()]
    return [B]


def _stale_tag(current, previous):
    if previous and current.reply == previous.token and current.token != previous.token:
        return [current.retry_a()]
    return [B]


def _sequence_wrap(current, previous):
    # Sequence tracking erroneously treats the first sample after wrap as resync.
    if previous and previous.reply == 255 and current.reply == 0:
        return []
    return [B]


def _sample_dedup(current, previous):
    if previous and previous.reply == current.reply:
        return []
    return [B]


def _stale_irq_filter(current, previous):
    # A retained qualification time rejects a sufficiently early next edge.
    if previous and previous.gap - current.gap >= 64:
        return []
    return [B]


_CASES = {
    "c-4c": _sample_dedup,
    "c-78": _backoff_carry,
    "c-ad": _select_wiring,
    "c-32": _stale_tag,
    "c-f1": _irq_merge,
    "c-6b": _sequence_wrap,
    "c-95": _level_enqueue,
    "c-27": _status_alias,
    "c-b3": _stale_irq_filter,
    "c-50": _echo_completion,
}


def case_ids():
    return list(_CASES)


class _Peer:
    def __init__(self, dispatch, seed, run_index):
        self._dispatch = dispatch
        self._seed = seed
        self._run_index = run_index
        self._window = 0
        self._pending = None
        self._previous = None

    def poll(self):
        if self._pending is not None or self._window >= 2:
            raise ValueError("poll requires an available service window")
        self._pending = _token(self._seed, self._run_index, self._window)
        return bytes((1, self._pending, 0))

    def after_reply(self, miso_bytes, gap):
        if self._pending is None:
            raise ValueError("an A poll must precede the reply")
        packet = bytes(miso_bytes)
        if len(packet) != 3 or gap not in GAPS:
            raise ValueError("expected three MISO bytes and a legal IRQ gap")
        current = Window(self._pending, packet[2], gap)
        followups = self._dispatch(current, self._previous)
        self._previous = current
        self._pending = None
        self._window += 1
        return followups


def new_peer(case_id, seed, run_index):
    dispatch = _healthy if case_id == "healthy" else _CASES[case_id]
    return _Peer(dispatch, seed, run_index)


def _witnesses():
    # Markers stand for a token observed on the public bus.
    return {
        "c-4c": [(16, 0x35), (16, 0x35)],
        "c-78": [(128, 8)],
        "c-ad": [(16, 0)],
        "c-32": [(16, 0), (16, "previous")],
        "c-f1": [(0, 0)],
        "c-6b": [(16, 255), (16, 0)],
        "c-95": [(16, 0)],
        "c-27": [(16, 0xD0)],
        "c-b3": [(128, 0), (64, 0)],
        "c-50": [(16, "current")],
    }


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


def _check_witness(case_id, script):
    peer = new_peer(case_id, 0, 0)
    previous_token = None
    for index, (gap, value) in enumerate(script):
        poll = peer.poll()
        _require(len(poll) == 3 and poll[0] == 1 and poll[1] and poll[2] == 0, "A poll")
        reply = {"previous": previous_token, "current": poll[1]}.get(value, value)
        frames = peer.after_reply(bytes((0, 0, reply)), gap)
        _require(len(frames) <= 2, "followup count")
        _require(all(slot in (0, 1) and len(frame) == 3 for slot, frame in frames), "frame shape")
        _require((frames == [B]) == (index < len(script) - 1), f"witness failed for {case_id}")
        previous_token = poll[1]


def _audit():
    stimuli = list(product(GAPS, range(256)))
    checked = 0
    for first, second in product(stimuli, repeat=2):
        peer = new_peer("healthy", 0, 0)
        for gap, reply in (first, second):
            poll = peer.poll()
            _require(len(poll) == 3 and poll[0] == 1 and poll[1] and poll[2] == 0, "A poll")
            frames = peer.after_reply(bytes((0, 0, reply)), gap)
            _require(frames == [(1, bytes((2, 0x55, 0)))], "B service")
        checked += 1
    witnesses = _witnesses()
    _require(set(witnesses) == set(case_ids()) and len(witnesses) == 10, "panel membership")
    for case_id, script in witnesses.items():
        _check_witness(case_id, script)
    print(f"Healthy legal reply/gap histories checked: {checked}")
    print(f"Fault witnesses reproduced: {len(witnesses)}")


if __name__ == "__main__":
    _audit()
