"""Independent I2C target observing the resolved bus at 50 MHz."""

from pathlib import Path
from runpy import run_path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

from pins import Pins


build_write = run_path(str(Path(__file__).resolve().parents[1] / "examples" /
                           "i2c_write.py"))["build_write"]
SCL, SDA = 0x10, 0x20


async def install(p, address, value, rate):
    image, settings = build_write(address, value, rate)
    await p.load(image)
    for selector, setting in settings:
        await p.write(selector)
        await p.write(setting, mode=0)


async def target(p, address, accept_data, rate, target_delay=18, *, run_control=5):
    # Timing minima in 20 ns system cycles. DATA setup is rounded up.
    period, low_min, high_min, setup, start_hold, stop_setup, bus_free = (
        (500, 235, 200, 13, 200, 200, 235) if rate == 100 else
        (125, 65, 30, 5, 30, 30, 65)
    )
    valid_max = 172 if rate == 100 else 45  # 3.45 us or 0.9 us, rounded down.
    dut = p.dut
    await p.write(run_control)
    assert p.running, "timed GPIO did not start"
    p.host(0, 0, 0)
    dut.uio_in.value = p.inputs
    clock = Clock(dut.clk, 20, unit="ns")
    clock.start(start_high=False)
    prev_scl = prev_sda = 1
    target_low = False
    pending = None
    starts, stops, rises, falls = [], [], [], []
    data_edge = 0
    bits, received, acks = [], [], []
    try:
        for tick in range(24 * period):
            await RisingEdge(dut.clk)
            await Timer(1, unit="ns")
            if pending and tick == pending[0]:
                target_low = pending[1]
                dut.peer_oe.value = p.peer_mask | (SDA if target_low else 0)
                await Timer(1, unit="ns")
            assert p.out & p.oe & (SDA | SCL) == 0, "controller drove high"
            assert p.oe & 0xC0 == 0, "unrelated GPIO enabled"
            pins = str(dut.pads.value)[::-1]
            assert pins[4:6] in ("00", "01", "10", "11"), pins
            scl, sda = int(pins[4]), int(pins[5])
            if sda != prev_sda:
                data_edge = tick
                if not scl and not prev_scl:
                    assert tick - falls[-1] <= valid_max, "late data or ACK"
                if scl and prev_scl:
                    if not sda:
                        assert not starts and tick >= bus_free, "early or extra START"
                        starts.append(tick)
                    else:
                        assert starts and not stops and tick - rises[-1] >= stop_setup
                        stops.append(tick)
            if prev_scl and not scl:
                if falls:
                    assert tick - rises[-1] >= high_min
                else:
                    assert starts and tick - starts[0] >= start_hold
                falls.append(tick)
                if len(bits) == 8:
                    byte = sum(bit << (7-i) for i, bit in enumerate(bits))
                    received.append(byte)
                    ack = (byte == address << 1) if len(received) == 1 else accept_data
                    pending = (tick + target_delay, ack)
                elif len(bits) == 9:
                    pending = (tick + target_delay, False)
                    bits.clear()
            if scl and not prev_scl:
                assert falls and tick - falls[-1] >= low_min
                if rises:
                    assert tick - rises[-1] == period, "wrong SCL frequency"
                assert tick - data_edge >= setup, "SDA setup violation"
                rises.append(tick)
                if len(bits) == 8:
                    assert not (p.oe & SDA), "controller owned the ACK slot"
                    acks.append(sda)
                bits.append(sda)
            prev_scl, prev_sda = scl, sda
            if not p.running:
                assert len(starts) == len(stops) == 1 and (scl, sda) == (1, 1)
                assert bits == [0] and len(rises) == 9 * len(received) + 1
                assert p.oe == 4 and not target_low
                return received, acks, p.uo >> 4, rises[0] - falls[0], falls[1] - rises[0]
        raise AssertionError("controller did not finish")
    finally:
        clock.stop()
        dut.peer_oe.value = p.peer_mask


@cocotb.test()
async def standard_and_fast_writes(dut):
    p = Pins(dut)
    await p.reset()
    await p.enter()
    dut.bus_pullups.value = 1
    try:
        for rate in (100, 400):
            for address, value in ((0x52, 0xA5), (0x29, 0x5A), (0x37, 0), (0x68, 255)):
                await install(p, address, value, rate)
                delay = (150 if rate == 100 else 40) if value == 0 else 18
                rx, ack, history, low, high = await target(p, address, True, rate, delay)
                assert (rx, ack, history) == ([address << 1, value], [0, 0], 0b0100)
            # Same image, different target decisions. Address NACK must skip DATA.
            rx, ack, history, _, _ = await target(p, address ^ 1, True, rate)
            assert (rx, ack, history) == ([address << 1], [1], 0b0011)
            rx, ack, history, _, _ = await target(p, address, False, rate)
            assert (rx, ack, history) == ([address << 1, value], [0, 1], 0b0101)
            dut._log.info("%d kHz: four writes, address and data NACK; SCL low/high %d/%d ns",
                          rate, 20 * low, 20 * high)
    finally:
        dut.bus_pullups.value = 0


@cocotb.test()
async def timed_gpio_loader_and_stop(dut):
    p = Pins(dut)
    await p.reset()
    await p.enter()
    await p.write(5)
    assert not p.running

    await p.load([0x55])  # Four pull-P0-low slots.
    await p.write(0x20)
    await p.write(255, mode=0)
    await p.write(5)
    await p.tick(4)
    assert p.running and p.oe == 0x14
    await p.write(0x20)  # Selector and data are ignored while running.
    await p.write(1, mode=0)
    await p.tick(8)
    assert p.running and p.oe == 0x14
    await p.write(3)
    assert not p.running and p.oe == 4
    await p.write(5)
    await p.tick(12)
    assert p.running and p.oe == 0x14  # Busy writes did not shorten future runs.
    await p.write(3)

    await p.load([0xE4])  # CLEAR resets dwell to two clocks and disables sampling.
    await p.write(5)
    for mask in (0, 1, 2, 3):
        for _ in range(2):
            await p.tick()
            assert p.running and p.oe == (4 | mask << 4)
    await p.tick()
    assert not p.running and p.oe == 4 and p.uo >> 4 == 1

    # A positive sample may jump outside a short image. No stale slot may drive.
    p.peer_mask |= SDA
    p.inputs |= SDA
    for selector, value in ((0x22, 0x40), (0x24, 63)):
        await p.write(selector)
        await p.write(value, mode=0)
    await p.write(5)
    await p.tick(3)
    assert not p.running and p.oe == 4 and p.uo >> 4 == 3
