"""Pin-level contract test for the clocked two-vote interlock."""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

from pins import Pins
from test_p1_sources import ROOT, load_source


def set_pads(pins, clock, commit, vote):
    pins.inputs = (pins.inputs & 0x0F) | (clock << 4) | (commit << 5) | (vote << 6)
    pins.dut.uio_in.value = pins.inputs


def observe(pins, grant, where):
    assert pins.oe & 0xF0 == 0x80, f"{where}: GPIO enables 0x{pins.oe:02x}"
    if grant is not None:
        assert pins.out >> 7 == grant, f"{where}: GRANT {pins.out >> 7}, expected {grant}"


async def hold(pins, cycles, grant, where):
    for _ in range(cycles):
        await Timer(20, unit="ns")
        observe(pins, grant, where)


def frames():
    # The initial stream includes sustained grants, denials and immediate reversals.
    prefix = (1, 1, 1, 0, 1, 0, 0, 1, 1, 0, 0, 0, 1, 1, 1, 1, 0)
    waits = (0, 0, 23, 0, 1, 6, 0, 3, 0, 19, 1, 0, 0, 2, 0, 1, 7)
    rng = random.Random(0x54DA)
    for n, (vote, length) in enumerate(zip(prefix, waits)):
        yield vote, [(i + n) & 1 for i in range(length)]
    for _ in range(40):
        vote = rng.randrange(2)
        yield vote, [rng.randrange(2) for _ in range(rng.randrange(6))]


@cocotb.test()
async def two_vote_interlock_on_pads(dut):
    for phase_ns in (3, 13):
        pins = Pins(dut)
        await pins.reset()
        await pins.enter()
        run = await load_source(pins, ROOT / "examples/heldout.p1")
        pins.peer_mask |= 0x70
        await pins.write(run)
        pins.host(0, 1, 0)
        dut.uio_in.value = pins.inputs
        dut.peer_oe.value = pins.peer_mask

        system_clock = Clock(dut.clk, 20, unit="ns")
        system_clock.start(start_high=False)
        try:
            await Timer(phase_ns, unit="ns")
            for _ in range(25):
                await Timer(20, unit="ns")
                assert pins.oe & 0x70 == 0
            observe(pins, 0, "startup")
            previous = grant = 0
            for frame, (vote, waits) in enumerate(frames()):
                for cell, value in enumerate(waits + [vote]):
                    commit = int(cell == len(waits))
                    where = f"phase={phase_ns}ns frame={frame} cell={cell}"
                    set_pads(pins, 0, commit, 1 - value)
                    await hold(pins, 15, grant, where)
                    set_pads(pins, 1, commit, 1 - value)
                    await hold(pins, 8, grant, where)
                    set_pads(pins, 1, 1 - commit, 1 - value)
                    await hold(pins, 8, grant, where)
                    set_pads(pins, 1, 1 - commit, value)
                    await hold(pins, 9, grant, where)

                    set_pads(pins, 0, 1 - commit, value)
                    next_grant = previous & value if commit else grant
                    await hold(pins, 10, grant if grant == next_grant else None, where)
                    observe(pins, next_grant, where)
                    if commit:
                        previous = value
                    grant = next_grant
        finally:
            system_clock.stop()
