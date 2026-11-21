"""Paired offline RTL experiments. Peer modules are imported only for formal runs."""
import argparse
import ctypes as ct
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import random
import sys
import tempfile
from multiprocessing import Pool


ROOT = Path(__file__).resolve().parent
DEST = ROOT / "results"
METHODS = ("chip", "scan", "random", "host0", "host1", "host10", "host100")
GAPS = (0, 16, 64, 128)
COUNTERS = ("clocks", "resets", "strobes", "runs", "frames", "reads", "reset_clocks")
DEV_BYTES = (0xa3, 0x59, 0xce)
SWEEPS = {
    "linear": tuple(range(256)),
    "stride": tuple((i * 73 + 17) % 256 for i in range(256)),
    "trained": DEV_BYTES + tuple(i for i in range(256) if i not in DEV_BYTES),
}


def settings(seed, block, sweep):
    # Domain-separated PRNGs. No method or peer observation changes the draws.
    key = 65537 * seed + block
    first = random.Random(2 * key).randrange(256)
    random_byte = random.Random(2 * key + 1).randrange(256)
    pair = (block + seed) % 16
    return first, SWEEPS[sweep][block % 256], random_byte, GAPS[pair // 4], GAPS[pair % 4]


class Chip:
    def __init__(self, library):
        self.lib = ct.CDLL(str(library))
        self.lib.wire_new.argtypes = []
        self.lib.wire_new.restype = ct.c_void_p
        self.handle = self.lib.wire_new()
        assert self.handle
        for name, args in dict(reset_load=0, setup=6, run=0, frame=2, done=0, page=1, idle=1,
                               count=1, error=0, free=0, wait=0).items():
            fn = getattr(self.lib, "wire_" + name)
            fn.argtypes = [ct.c_void_p] + [ct.c_int] * args
            if name == "wait":
                fn.argtypes.append(ct.POINTER(ct.c_int))
            fn.restype = {"count": ct.c_uint64, "error": ct.c_char_p, "free": None}.get(name, ct.c_int)
            setattr(self, "_" + name, fn)

    def call(self, name, *args):
        n = getattr(self, "_" + name)(self.handle, *args)
        if n < 0:
            raise ValueError(f"{name}: {self._error(self.handle)!r}")
        return n

    def clock(self):
        return self._count(self.handle, 0)

    def totals(self):
        return {k: self._count(self.handle, i) for i, k in enumerate(COUNTERS)}

    def frame(self, slot, packet, origin):
        if slot not in (0, 1) or len(packet) != 3 or any(not 0 <= v <= 255 for v in packet):
            raise ValueError(f"unsupported service {slot}, {packet}")
        start = self.clock() - origin
        rx = self.call("frame", slot, int.from_bytes(bytes(packet), "big"))
        return [start, slot, list(packet), list(rx.to_bytes(3, "big"))]

    def read_record(self, slot):
        base = 0x80 + 16 * slot
        status = self.call("page", base)
        if not status & 8:
            raise ValueError("trial record missing")
        src = self.call("page", base + 1)
        tick = sum(self.call("page", base + 2 + i) << (4*i) for i in range(4))
        return [status & 7, src, tick]

    def close(self):
        self._free(self.handle)


def delta(end, start):
    return {k: end[k] - start[k] for k in end}


def empty_cost():
    return dict.fromkeys((*COUNTERS, "windows"), 0)


def add_cost(total, part):
    for k in total:
        total[k] += part[k]


def wire_oracle(frames):
    seen = set()
    for _, slot, packet, _ in frames:
        if slot in seen:
            return [3, 1 << slot]
        seen.add(slot)
        if slot == 1 and packet[1] != 0x55:
            return [4, 2]
    missing = sum(1 << i for i in {0, 1} - seen)
    return [2, missing] if missing else [1, 0]


def run_block(chip, peer, method, params, playback=None):
    before = chip.totals()
    windows = []
    first, scanned, random_byte, gap0, gap1 = params
    second = random_byte if method == "random" else scanned
    adaptive = method == "chip"
    host = method.startswith("host")
    chip.call("reset_load")
    chip.call("setup", 2 if adaptive else 1, gap0, gap1, first, first, int(adaptive))
    chip.call("run")
    origin = before["clocks"]
    for i, gap in enumerate((gap0, gap1)):
        measured = ct.c_int()
        if chip.call("wait", ct.byref(measured)) != 1 or measured.value != gap:
            raise ValueError(f"notification spacing/window mismatch: wanted {gap} got {measured.value}")
        if playback is None:
            poll = chip.frame(0, peer.poll(), origin)
            frames = [poll]
            following = list(peer.after_reply(poll[3], measured.value))
            if len(following) > 2:
                raise ValueError("peer exceeded the service envelope")
            for slot, packet in following:
                frames.append(chip.frame(slot, packet, origin))
        else:
            frames = []
            for at, slot, packet, _ in playback[i]["frames"]:
                if chip.clock() - origin != at:
                    raise ValueError("replay traffic offset changed")
                frames.append(chip.frame(slot, packet, origin))
        oracle = wire_oracle(frames)
        windows.append(dict(gap=measured.value, frames=frames, oracle=oracle))
        if not adaptive:
            chip.call("done")
            windows[i]["record"] = chip.read_record(0)
            if i == 0 and windows[0]["record"][0] == 1:
                if host:
                    valid = chip.call("page", 0xd4)
                    lo = chip.call("page", 0xd2)
                    hi = chip.call("page", 0xd3)
                    second = (lo | hi << 4) if valid & 1 else first
                    chip.call("idle", 50 * int(method[4:]))
                chip.call("setup", 1, gap1, gap1, second, second, 0)
                chip.call("run")
        if oracle[0] != 1 or (not adaptive and windows[i]["record"][0] != 1):
            break
    if adaptive:
        chip.call("done")
        for i, w in enumerate(windows):
            w["record"] = chip.read_record(i)
    costs = delta(chip.totals(), before)
    costs["windows"] = len(windows)
    for i, w in enumerate(windows):
        if w["record"][:2] != w["oracle"] or (
                w["record"][0] in (1, 2) and w["record"][2] != 1001):
            raise ValueError(f"wire/checker disagreement: {w}")
        expected_reply = first if i == 0 else (
            windows[0]["frames"][0][2][1] if (adaptive or host) and
            windows[0]["frames"][0][2][0] == 1 else (first if adaptive else second))
        if w["frames"][0][2][0] == 1 and w["frames"][0][3][2] != expected_reply:
            raise ValueError(f"wire reply mismatch for window {i}: {w}, wanted {expected_reply}")
    return windows, costs


def search(chip, case, seed, method, factory, sweep, budget):
    result = dict(case=case, seed=seed, method=method, status="miss", first=None,
                  first_run_hit=False, search=empty_cost(), confirmation=empty_cost(),
                  replay=empty_cost(), confirms=0, replay_ok=None, deadlines_missed=0)
    raw = []
    witness = None
    for block in range(budget // 2):
        params = settings(seed, block, sweep)
        def fresh():
            return factory(case, seed, block)
        before = chip.totals()
        try:
            windows, costs = run_block(chip, fresh(), method, params)
        except (ValueError, AssertionError) as exc:
            cost = delta(chip.totals(), before)
            add_cost(result["search"], dict(cost, windows=0))
            result.update(status="inconclusive", error=str(exc), block=block)
            break
        raw.append([block, params, windows, costs])
        add_cost(result["search"], costs)
        v = windows[-1]["record"][0]
        if v == 1:
            continue
        result["deadlines_missed"] += int(v == 2)
        result["first"] = result["search"]["windows"]
        result["first_run_hit"] = block == 0 and (method == "chip" or len(windows) == 1)
        witness = dict(block=block, params=params, discovery=windows, confirmation=[], replay=None)
        for stage in ("confirmation",) * 3 + ("replay",):
            before = chip.totals()
            try:
                actual, spent = run_block(chip, fresh() if stage == "confirmation" else None,
                                          method, params, windows if stage == "replay" else None)
                ok = actual == windows
            except (ValueError, AssertionError) as exc:
                actual = {"error": str(exc)}
                spent = dict(delta(chip.totals(), before), windows=0)
                ok = False
            add_cost(result[stage], spent)
            if stage == "confirmation":
                result["confirms"] += int(ok)
                witness[stage].append(actual)
            else:
                result["replay_ok"] = ok
                witness["replay"] = actual
        result["status"] = ("false_alarm" if case == "healthy" else "confirmed"
                            if result["confirms"] == 3 and result["replay_ok"] else "unconfirmed")
        break
    # Absolute host idle intervals differ by placement. Compare only timing
    # relative to the first poll in each window, plus the trial's IRQ spacing.
    normalized = [
        [w["gap"], w["record"], [[f[0] - w["frames"][0][0], *f[1:]] for f in w["frames"]]]
        for _, _, windows, _ in raw for w in windows
    ]
    result["wire_digest"] = hashlib.sha256(json.dumps(normalized, separators=(",", ":")).encode()).hexdigest()
    return result, raw, witness


def development_peer(case, seed, block):
    # Use the existing public models without adding Cocotb to the benchmark process.
    from test_discovery import ExamplePeer
    raw = ExamplePeer(dict(healthy=0x37, omit=0xa3, repeat=0x59, corrupt=0xce)[case], case)
    class Adapter:
        poll = raw.poll
        def after_reply(self, reply, gap):
            return raw.after_reply(reply)
    return Adapter()


def train(library):
    sys.path.insert(0, str(ROOT.parent / "test"))
    chip = Chip(library)
    scores = {}
    for sweep in SWEEPS:
        hits = [0, 0, 0]
        for case, seed in itertools.product(("healthy", "omit", "repeat", "corrupt"), range(30)):
            r, _, _ = search(chip, case, seed, "scan", development_peer, sweep, 8)
            assert r["status"] in ("miss", "confirmed"), r
            for i, cutoff in enumerate((2, 4, 8)):
                hits[i] += int(r["status"] == "confirmed" and r["first"] <= cutoff)
        scores[sweep] = hits
    chip.close()
    best = max(SWEEPS, key=lambda k: sum(scores[k]))
    return dict(selected=best, thresholds=[2, 4, 8], hits=scores, seeds=30, faulty_cases=3)


def dump(stream, obj):
    stream.write(json.dumps(obj, separators=(",", ":")) + "\n")


def evaluate_group(args):
    import panel
    case, method, library, sweep, directory = args
    chip = Chip(library)
    prefix = Path(directory) / (case + "-" + method)
    with gzip.open(str(prefix) + ".s.gz", "wt") as sums, gzip.open(str(prefix) + ".t.gz", "wt") as traces, gzip.open(str(prefix) + ".w.gz", "wt") as witnesses:
        for seed in range(30):
            r, trace, w = search(chip, case, seed, method, panel.new_peer, sweep, 128)
            dump(sums, r)
            dump(traces, [case, method, seed, trace])
            if w:
                dump(witnesses, [case, method, seed, w])
    chip.close()
    return prefix


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["train", "run", "replay"])
    parser.add_argument("library", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    lib = args.library.resolve()
    if args.action == "replay":
        chip = Chip(lib)
        count = 0
        with gzip.open(DEST / "witnesses.jsonl.gz", "rt") as src:
            for line in src:
                case, method, seed, w = json.loads(line)
                observed, _ = run_block(chip, None, method, w["params"], w["discovery"])
                assert observed == w["discovery"], (case, method, seed)
                count += 1
        chip.close()
        print(f"Replayed {count} saved candidate blocks")
        return
    if args.action == "train":
        data = train(lib)
        (ROOT / "development.json").write_text(json.dumps(data, indent=2) + "\n")
        print(data)
        return
    import panel
    expected = "3a2f14cbf5be47cd38cfbf52a3b9b7b23d636ca6419cd9d6e5eba181f7d4abb4"
    assert hashlib.sha256(Path(panel.__file__).read_bytes()).hexdigest() == expected
    ids = list(panel.case_ids()) + ["healthy"]
    assert len(set(ids)) == len(ids) == 11
    sweep = json.loads((ROOT / "development.json").read_text())["selected"]
    DEST.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tasks = [(case, method, lib, sweep, tmp) for case, method in itertools.product(ids, METHODS)]
        with Pool(args.workers) as pool:
            groups = list(pool.imap_unordered(evaluate_group, tasks))
        for name, suffix in (("search", "s"), ("traces", "t"), ("witnesses", "w")):
            with gzip.open(DEST / (name + ".jsonl.gz"), "wt", compresslevel=7) as dest:
                for g in sorted(groups):
                    with gzip.open(str(g) + "." + suffix + ".gz", "rt") as src:
                        for line in src:
                            dest.write(line)


if __name__ == "__main__":
    main()
