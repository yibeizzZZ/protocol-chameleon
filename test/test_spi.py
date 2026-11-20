"""Independent 5 MHz SPI master. Timing observations use the resolved MISO pad."""

from bisect import bisect_right

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, ValueChange
from cocotb.utils import get_sim_time

from pins import Pins


def now():
    return int(get_sim_time(unit="ps"))


def miso(dut):
    return str(dut.pads.value)[0].lower()


def bits(data):
    return [int(bit) for byte in data for bit in f"{byte:08b}"]


async def setup_spi(p):
    await p.write(0)
    await p.write(0x82)
    assert p.oe == 4
    p.inputs |= 0x10  # peer holds CS high before programming
    p.peer_mask |= 0x70
    await p.tick(5)


async def configure(p, addr, value, mask):
    await p.write(0x20 + addr)
    await p.write(value, mode=0)
    await p.write(0x24 + addr)
    await p.write(mask, mode=0)


async def transaction(p, mode, request, expected, phase=0, bit_count=None, payload_start=16,
                      sensor=0):
    """One CS window. Return clock-to-valid times on toggling payload bits and CS-to-OE."""
    dut = p.dut
    idle, cpha = divmod(mode, 2)
    tx = bits(request)[:bit_count]
    rx = bits(expected)[:bit_count]
    assert len(tx) == len(rx) and tx
    changes = [(now(), miso(dut))]

    async def observe_pad():
        while True:
            await ValueChange(dut.pads)
            value = miso(dut)
            if changes[-1][1] != value:
                changes.append((now(), value))

    def drive(cs, sclk, mosi):
        p.inputs = (p.inputs & 0x0F) | ((1 if sensor else cs) << 4) | (sclk << 5) | (mosi << 6)
        if sensor:
            p.inputs = (p.inputs & ~2) | (cs << 1)
        dut.uio_in.value = p.inputs

    drive(1, idle, 0)
    clock = Clock(dut.clk, 20, unit="ns")
    clock.start(start_high=False)
    monitor = cocotb.start_soon(observe_pad())
    samples = []
    try:
        # Previous transfer leaves CS high for 60 ns; consecutive calls
        # with phase zero therefore exercise exactly 100 ns of deselection.
        await Timer(40000 + phase, unit="ps")
        assert miso(dut) == "z"
        select = launch = now()
        drive(0, idle, tx[0])
        await Timer(100, unit="ns")
        for i, bit in enumerate(tx):
            if cpha:
                launch = now()
                drive(0, 1-idle, bit)
                await Timer(100, unit="ns")
            sample = now()
            samples.append((launch, sample, rx[i]))
            assert miso(dut) == str(rx[i]), (mode, phase, i, miso(dut), rx[i])
            drive(0, idle if cpha else 1-idle, bit)
            await Timer(100, unit="ns")
            if not cpha:
                launch = now()
                drive(0, idle, tx[i+1] if i+1 < len(tx) else 0)
                await Timer(100, unit="ns")
        drive(1, idle, 0)
        await Timer(1, unit="ps")
        assert miso(dut) == "z" and p.oe == 4
        await Timer(59999, unit="ps")
    finally:
        monitor.cancel()
        clock.stop()

    # Check the entire setup/hold window, including glitches between samples.
    times = [t for t, _ in changes]
    delays = []
    for i, (launch, sample, value) in enumerate(samples):
        k = bisect_right(times, sample) - 1
        valid_at, level = changes[k]
        assert level == str(value) and valid_at <= sample - 20000
        assert k+1 == len(times) or times[k+1] >= sample + 10000
        if i >= payload_start and rx[i] != rx[i-1]:
            assert valid_at >= launch, "MISO changed before the specified launch edge"
            delays.append(valid_at - launch)
    first_drive = next(t for t, v in changes if t >= select and v == "0")
    return delays, first_drive - select


@cocotb.test()
async def modes_phase_and_setup(dut):
    p = Pins(dut)
    await p.reset()
    await setup_spi(p)
    # Sweep a complete 20 ns system period, including either side of its rising edge.
    phases = sorted({i*1000 for i in range(20)} | {9900, 10100})
    for mode in range(4):
        await p.write(0x10 + mode)
        await configure(p, 2, 0xED, 0x48)
        delays, enables = [], []
        for phase in phases:
            await p.write(1)  # rearm for an independent first/repeat pair
            for response in (0xED, 0xA5):
                edges, enable = await transaction(p, mode, [0xA6, 2, 0x35],
                                                  [0, 0, response], phase)
                delays.extend(edges)
                enables.append(enable)
        dut._log.info("mode %d: %d phases, %d payload transitions, launch-to-valid "
                      "%.3f..%.3f ns, min setup %.3f ns, CS-to-drive %.3f..%.3f ns",
                      mode, len(phases), len(delays), min(delays)/1000, max(delays)/1000,
                      100-max(delays)/1000, min(enables)/1000, max(enables)/1000)


@cocotb.test()
async def history_abort_and_register_isolation(dut):
    p = Pins(dut)
    await p.reset()
    await setup_spi(p)
    await configure(p, 0, 0xDA, 0x5A)
    await configure(p, 3, 0x75, 0x31)
    for length in (7, 15, 16, 23):
        await transaction(p, 0, [0xA6, 0, 0], [0, 0, 0xDA], bit_count=length)
    await transaction(p, 0, [0xA7, 0, 0], [0, 0, 0])
    await transaction(p, 0, [0xA6, 4, 0], [0, 0, 0])
    for addr, expected in [(0, 0xDA), (3, 0x75), (0, 0x80), (3, 0x44), (0, 0x80)]:
        await transaction(p, 0, [0xA6, addr, 0xFF, 0x12], [0, 0, expected, 0])
    await configure(p, 0, 0xC3, 3)
    await transaction(p, 0, [0xA6, 0, 0], [0, 0, 0xC3])
    await transaction(p, 0, [0xA6, 3, 0], [0, 0, 0x44])


@cocotb.test()
async def spi_uart_ownership_and_reset(dut):
    p = Pins(dut)
    await p.reset()
    await p.write(7)
    await p.write(0x80)  # UART 8 clocks per bit
    await setup_spi(p)
    await configure(p, 1, 0xAB, 0x0F)
    await transaction(p, 0, [0xA6, 1, 0], [0, 0, 0xAB])
    p.peer_mask &= ~0x70  # release before returning to UART outputs
    await p.write(0)
    assert p.oe == 0xF4
    await p.write(0x55, mode=0)
    for bit in [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]:
        for _ in range(8):
            assert p.uo & 7 == 2 | bit
            await p.tick()
    assert p.uo & 7 == 5
    await setup_spi(p)
    await transaction(p, 0, [0xA6, 1, 0], [0, 0, 0xA0])
    await p.reset()
    await setup_spi(p)
    await transaction(p, 0, [0xA6, 1, 0], [0, 0, 0])


@cocotb.test()
async def busy_programming_and_partial_write(dut):
    p = Pins(dut)
    await p.reset()
    await setup_spi(p)
    await configure(p, 2, 0xA9, 0x29)
    await transaction(p, 0, [0xA6, 2, 0], [0, 0, 0xA9])
    await p.write(0x22)  # no data byte; it must not change the register yet
    p.inputs &= ~0x10  # assert CS and pause the serial controller
    await p.tick(5)
    assert p.oe == 0x84
    await p.write(0xFF, mode=0)
    await p.write(0x01)  # attempt to rearm history during the frame
    await p.write(0x13)  # attempt to change CPOL and CPHA
    p.inputs |= 0x10
    await p.tick(5)
    assert p.oe == 0x04
    await transaction(p, 0, [0xA6, 2, 0], [0, 0, 0x80])
    await p.write(0xFF)  # reserved control cancels the pending selector
    await p.write(0, mode=0)
    await transaction(p, 0, [0xA6, 2, 0], [0, 0, 0x80])
