"""Closed-loop discovery and reset replay on the frozen RTL, using only chip pins."""
import hashlib
import importlib
import json
import os
from pathlib import Path

import cocotb

from pins import Pins
from test_feedback import field, launch, page, record, rule
from test_models import install_program, param_snapshot
from test_trials import DUPLICATE, PASS, TIMEOUT, WRONG, Trial, descriptor


DEADLINE = 800
ACK = 0x55


class Recorder(Pins):
    def __init__(self, dut):
        super().__init__(dut)
        self.elapsed = 0
        self.recording = False
        self.changes = []
        self.previous = None

    async def tick(self, count=1):
        for _ in range(count):
            await super().tick()
            if self.recording:
                self.elapsed += 1
                # Check the host data, strobe and mode are constant from RUN to DONE.
                assert int(self.dut.ui_in.value) == 0x34 and self.inputs & 9 == 9
                state = (self.inputs, str(self.dut.pads.value), self.uo, self.oe)
                if state != self.previous:
                    self.changes.append([self.elapsed, *state])
                    self.previous = state


async def load_campaign(p, adaptive):
    await p.reset()
    await install_program(p, "adaptive_poll")
    await p.write(0x30)
    trial = Trial(p)
    await trial.plan(descriptor(0, DEADLINE, checks=0),
                     descriptor(0, DEADLINE, cmd=ACK, checks=8), policy=0)
    # A's second MOSI byte supplies the next reply. Both images use two trials.
    for addr, value in ((0x5a, 1), (0x5b, 0x88), (0x5c, 1), (0x5d, 0), (0x51, 1)):
        await field(p, addr, value)
    await rule(p, 0, PASS, 0)
    await field(p, 0x63, 0xe0 if adaptive else 0)
    return trial


async def exchange(p, slot, request):
    """Drive a mode-0 controller and decode both data pins at each sampling edge."""
    assert slot in (0, 1) and len(request) == 3 and all(0 <= byte <= 255 for byte in request)
    select = (0x10, 2)[slot]
    start = p.elapsed
    p.inputs &= ~select
    mosi, miso = [], []
    for byte in request:
        sent = received = 0
        for bit in range(7, -1, -1):
            p.inputs = (p.inputs & ~0x60) | (((byte >> bit) & 1) << 6)
            await p.tick(5)
            pads = str(p.dut.pads.value)
            assert pads[-5] + pads[-2] == ("01", "10")[slot]
            sent = (sent << 1) | int(pads[-7])
            received = (received << 1) | int(pads[-8])
            p.inputs |= 0x20
            await p.tick(5)
        mosi.append(sent)
        miso.append(received)
    p.inputs &= ~0x20
    await p.tick(5)
    p.inputs |= select
    await p.tick(5)
    return dict(start=start, end=p.elapsed, slot=slot, mosi=mosi, miso=miso)


class ExamplePeer:
    """Public synthetic controller. Its only inputs are notifications and SPI replies."""
    def __init__(self, token, defect):
        self.token = token
        self.defect = defect
        self.previous_token = None

    def poll(self):
        return [1, self.token, 0]

    def after_reply(self, reply):
        armed = reply[-1] == self.previous_token
        self.previous_token = self.token
        if armed:
            if self.defect == "omit":
                return []
            if self.defect == "repeat":
                return [(0, self.poll())]
            if self.defect == "corrupt":
                return [(1, [2, ACK ^ 1, 0])]
        return [(1, [2, ACK, 0])]


def wire_verdict(frames):
    """Public contract: exactly one poll on each select, B carries the ACK byte."""
    seen = set()
    for frame in frames:
        slot = frame["slot"]
        if slot in seen:
            return DUPLICATE, 1 << slot
        seen.add(slot)
        if slot == 1 and frame["mosi"][1] != ACK:
            return WRONG, 2
    missing = sum(1 << slot for slot in {0, 1} - seen)
    return (TIMEOUT, missing) if missing else (PASS, 0)


async def campaign(dut, peer, adaptive, playback=None):
    p = Recorder(dut)
    trial = await load_campaign(p, adaptive)
    await launch(trial)
    p.recording = True
    frames = []
    for index in range(2):
        if playback is None:
            for _ in range(DEADLINE + 8):
                if p.uo & 3 == 3 or p.uo & 15 == 8:
                    break
                await p.tick()
            if p.uo & 15 == 8:
                break
            assert p.uo & 3 == 3
            poll = await exchange(p, 0, peer.poll())
            observed = [poll]
            for slot, packet in peer.after_reply(poll["miso"]):
                observed.append(await exchange(p, slot, packet))
        else:
            if index == len(playback):
                break
            observed = []
            for frame in playback[index]:
                assert p.elapsed <= frame["start"]
                await p.tick(frame["start"] - p.elapsed)
                observed.append(await exchange(p, frame["slot"], frame["mosi"]))
        frames.append(observed)
    for _ in range(DEADLINE + 8):
        if p.uo & 15 == 8:
            break
        await p.tick()
    assert p.uo & 15 == 8
    p.recording = False
    assert await page(p, 0xc0) == len(frames) and frames
    records = []
    for index, observed in enumerate(frames):
        row = await record(p, index)
        row["settings"] = list(row["settings"])
        assert (row["verdict"], row["source"]) == wire_verdict(observed)
        if row["verdict"] in (PASS, TIMEOUT):
            assert row["tick"] == DEADLINE + 1
        row["operands"] = list(await param_snapshot(p, index))
        records.append(row)
    digest = hashlib.sha256(json.dumps(p.changes, separators=(",", ":")).encode()).hexdigest()
    return dict(records=records, frames=frames, duration_clocks=p.elapsed, pin_sha256=digest)


def verdicts(result):
    return [r["verdict"] for r in result["records"]]


async def evaluate(dut, factory):
    control = await campaign(dut, factory(), False)
    discovery = await campaign(dut, factory(), True)
    confirmations = []
    differences = {}
    for attempt in range(3):
        repeat = await campaign(dut, factory(), True)
        confirmations.append(repeat["pin_sha256"])
        if repeat != discovery:
            differences[f"confirmation_{attempt + 1}"] = repeat
    replay = await campaign(dut, None, True, playback=discovery["frames"])
    if replay != discovery:
        differences["playback"] = replay
    causal = (verdicts(control) == [PASS, PASS] and verdicts(discovery)[:1] == [PASS]
              and len(discovery["records"]) == 2 and verdicts(discovery)[1] in (TIMEOUT, DUPLICATE, WRONG)
              and control["frames"][0] == discovery["frames"][0]
              and control["frames"][1][0]["miso"] != discovery["frames"][1][0]["miso"])
    return dict(control=control, discovery=discovery, confirmations=confirmations,
                playback_sha256=replay["pin_sha256"], differences=differences,
                confirmed_discovery=causal and not differences)


@cocotb.test()
async def discover_confirm_and_replay(dut):
    replay_path = os.environ.get("DISCOVERY_REPLAY")
    if replay_path:
        saved = json.loads(Path(replay_path).read_text())
        assert saved["cases"]
        for case in saved["cases"].values():
            for key, adaptive in (("control", False), ("discovery", True)):
                run = case[key]
                assert await campaign(dut, None, adaptive, playback=run["frames"]) == run
        return

    cases = {}
    external = os.environ.get("DISCOVERY_PEERS")
    if external:
        suite = importlib.import_module(external)
        identifiers = list(suite.case_ids())
        assert len(identifiers) == len(set(identifiers)) == 10 and all(isinstance(i, str) for i in identifiers)
        for name in identifiers:
            cases[name] = await evaluate(dut, lambda: suite.new_peer(name))
    else:
        for name, token, verdict in (("healthy", 0x37, PASS), ("omit", 0xa3, TIMEOUT),
                                     ("repeat", 0x59, DUPLICATE), ("corrupt", 0xce, WRONG)):
            case = await evaluate(dut, lambda: ExamplePeer(token, name))
            cases[name] = case
            assert not case["differences"]
            assert case["confirmed_discovery"] == (name != "healthy")
            discovery = case["discovery"]
            assert verdicts(discovery) == [PASS, verdict]
            assert discovery["records"][0]["matched"] and discovery["records"][0]["continued"]
            assert [r["operands"][1] for r in discovery["records"]] == [0, token]
            assert [trial[0]["miso"][-1] for trial in discovery["frames"]] == [0, token]
    evidence = dict(suite=external or "public-calibration", cases=cases)
    target = os.environ.get("DISCOVERY_EVIDENCE")
    if target:
        Path(target).write_text(json.dumps(evidence, indent=2) + "\n")
    if external:
        count = sum(case["confirmed_discovery"] for case in cases.values())
        dut._log.info("Confirmed discoveries on the supplied panel: %d/10", count)
        assert count >= 8
