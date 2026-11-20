"""Public-pin acceptance test for the shared-wire register program."""

from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, ValueChange
from cocotb.utils import get_sim_time

from pins import Pins


PROGRAM = Path(__file__).resolve().parents[1] / "examples" / "shared_wire_register.hex"
HALF_PERIOD_PS = 500_000
TURNAROUND_PS = 100_000
IDLE_OE = 0x04  # Existing engine status output. All four GPIOs are released.
CLOCK = 0x10
DATA = 0x20


def now_ps():
    return int(get_sim_time(unit="ps"))


def data_pad(dut):
    return str(dut.pads.value)[::-1][5].lower()


async def record_changes(signal, read, changes):
    while True:
        await ValueChange(signal)
        value = read()
        if value != changes[-1][1]:
            changes.append((now_ps(), value))


def drive(pins, clock, data=None):
    """The controller owns P0 throughout and releases P1 when data is None."""
    pins.inputs &= ~(CLOCK | DATA)
    pins.peer_mask = (pins.peer_mask | CLOCK) & ~DATA
    if clock:
        pins.inputs |= CLOCK
    if data is not None:
        pins.peer_mask |= DATA
        if data:
            pins.inputs |= DATA
    pins.dut.uio_in.value = pins.inputs
    pins.dut.peer_oe.value = pins.peer_mask


async def run_exchanges(pins, phase_ps, *, run_control=2):
    dut = pins.dut
    await pins.write(run_control)  # RUN initializes the stored bit to zero.
    pins.host(0, 0, 0)
    drive(pins, 0)
    await pins.tick(3)
    assert pins.running and pins.oe == IDLE_OE and data_pad(dut) == "z"

    enables = [(now_ps(), pins.oe)]
    levels = [(now_ps(), data_pad(dut))]
    oe_monitor = cocotb.start_soon(record_changes(dut.uio_oe, lambda: pins.oe, enables))
    pad_monitor = cocotb.start_soon(record_changes(dut.pads, lambda: data_pad(dut), levels))
    clock = Clock(dut.clk, 20, unit="ns")
    clock.start(start_high=False)
    replies = []
    stored = 0
    try:
        await Timer(200_000 + phase_ps, unit="ps")
        # None is a READ. An integer is a WRITE carrying that bit.
        for payload in (None, 1, None, None, 0, None, 0, 1, None):
            await Timer(TURNAROUND_PS, unit="ps")
            assert pins.oe == IDLE_OE and data_pad(dut) == "z", "bus still driven"
            command = int(payload is not None)
            drive(pins, 0, command)
            await Timer(HALF_PERIOD_PS - TURNAROUND_PS, unit="ps")
            drive(pins, 1, command)
            await Timer(HALF_PERIOD_PS, unit="ps")
            if payload is not None:
                drive(pins, 0, payload)
                await Timer(HALF_PERIOD_PS, unit="ps")
                drive(pins, 1, payload)
                await Timer(HALF_PERIOD_PS, unit="ps")
                stored = payload

            launch = now_ps()
            drive(pins, 0)  # End of the request. The peer releases DATA.
            await Timer(HALF_PERIOD_PS, unit="ps")
            assert data_pad(dut) == str(stored), (
                f"reply mismatch at phase {phase_ps} ps, payload={payload}: "
                f"expected {stored}, observed {data_pad(dut)}"
            )
            drive(pins, 1)  # Controller samples the reply on this rising edge.
            await Timer(HALF_PERIOD_PS, unit="ps")
            end = now_ps()
            drive(pins, 0)
            replies.append((launch, end, str(stored)))
        await Timer(200_000, unit="ps")
        assert pins.running and pins.oe == IDLE_OE and data_pad(dut) == "z"
    finally:
        clock.stop()
        pad_monitor.cancel()
        oe_monitor.cancel()

    # Check every output-enable transition, including equal-value bus contention.
    assert len(enables) == 1 + 2 * len(replies), enables
    drive_delays, release_delays = [], []
    for i, (launch, end, expected) in enumerate(replies):
        on, active = enables[1 + 2*i]
        off, idle = enables[2 + 2*i]
        assert active == (IDLE_OE | DATA) and idle == IDLE_OE
        assert 0 < on - launch <= TURNAROUND_PS, (on, launch)
        assert 0 < off - end <= TURNAROUND_PS, (off, end)
        # From the validity deadline to the closing edge the wire must stay stable.
        deadline = launch + TURNAROUND_PS
        assert next(v for t, v in reversed(levels) if t <= deadline) == expected
        assert not any(deadline < t < end for t, _ in levels), "unstable reply"
        drive_delays.append(on - launch)
        release_delays.append(off - end)
    return drive_delays, release_delays


@cocotb.test()
async def read_write_turnaround(dut):
    pins = Pins(dut)
    await pins.reset()
    await pins.enter()
    program = bytes.fromhex(" ".join(
        line.partition("//")[0] for line in PROGRAM.read_text(encoding="ascii").splitlines()
    ))
    assert 0 < len(program) <= 16
    await pins.load(program)
    drives, releases = [], []
    # Include controller edges 100 ps on either side of a system rising edge.
    phases = sorted({i * 1000 for i in range(20)} | {9900, 10100})
    for phase in phases:
        on, off = await run_exchanges(pins, phase)
        drives.extend(on)
        releases.extend(off)
        await pins.write(3)  # STOP. The next RUN reuses the same image.
    dut._log.info(
        "%d bytes, %d phases, %d replies; drive %.1f..%.1f ns, release %.1f..%.1f ns",
        len(program), len(phases), len(drives), min(drives)/1000, max(drives)/1000,
        min(releases)/1000, max(releases)/1000,
    )
