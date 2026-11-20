import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadOnly, RisingEdge, Timer

from pins import Pins


def frame(byte, width, stops):
    return [0] + [(byte >> i) & 1 for i in range(width)] + [1] * stops


async def duplex(p, period, width, stops, tx_byte, rx_byte, writes=None):
    """Independent peer transmits one message while checking every TX bit cell."""
    tx = frame(tx_byte, width, stops)
    rx = frame(rx_byte, width, stops)
    total = len(tx) * period
    previous = p.rx_byte
    received = []
    p.host(0, 0, 0)
    await p.tick()
    for cycle in range(total + 3):
        slot = cycle // period
        line = rx[slot] if slot < len(rx) else 1
        p.inputs = (p.inputs & ~2) | (line << 1)
        if cycle == 0:
            p.host(tx_byte, 0, 1)
        elif writes and cycle in writes:
            p.host(*writes[cycle])
        await p.tick()

        expected = (2 | tx[slot]) if cycle < total else (5 if cycle == total else 1)
        assert p.uo & 7 == expected, f"TX at clock {cycle}, bit {slot}"
        assert p.oe == 0xF4 and not (p.out & 4)
        if p.uo & 8:
            received.append(cycle)
        expected_byte = rx_byte & ((1 << width) - 1) if received else previous
        assert p.rx_byte == expected_byte
    assert len(received) == 1, f"RX valid cycles: {received}"
    # The peer changes data half a clock before a DUT edge. Allow a few
    # sampling clocks around the center of the final stop bit.
    center = total - period / 2
    assert abs(received[0] - center) <= 4, (received, center)


@cocotb.test()
async def default_full_duplex(dut):
    p = Pins(dut)
    await p.reset()
    # Held strobe across completion must not launch a second frame.
    await duplex(p, 434, 8, 1, 0x55, 0xA6)


@cocotb.test()
async def active_descriptor_change(dut):
    p = Pins(dut)
    await p.reset()
    # A second send during busy, then the documented 57600/7N2 command pair
    # while both directions are in flight. The old frame must finish intact.
    writes = {100: (0, 0, 0), 101: (0xEF, 0, 1),
              300: (0x63, 1, 0), 301: (0x63, 1, 1),
              302: (0x9B, 1, 0), 303: (0x9B, 1, 1)}
    await duplex(p, 434, 8, 1, 0x80, 0xD2, writes)
    await duplex(p, 868, 7, 2, 0xD5, 0xC7)


@cocotb.test()
async def descriptor_limits_and_partial_writes(dut):
    p = Pins(dut)
    await p.reset()
    await p.write(0x06)  # staged only
    await duplex(p, 434, 8, 1, 0xAA, 0xA5)
    await p.write(0x81)  # seven clocks is below the supported range
    await duplex(p, 434, 8, 1, 0x00, 0xFF)
    await p.write(0x07)
    await p.write(0x82)  # minimum period, 8N2
    await duplex(p, 8, 8, 2, 0xAA, 0x81)
    await p.write(0x7F)
    await p.write(0xFD)  # maximum period, 7N1
    await duplex(p, 4096, 7, 1, 0x55, 0xFE)


async def peer_bits(p, segments):
    events = []
    for level, clocks in segments:
        p.inputs = (p.inputs & ~2) | (level << 1)
        for _ in range(clocks):
            await p.tick()
            if p.uo & 8:
                events.append(("valid", p.rx_byte))
            if p.out & 4:
                events.append(("error", p.rx_byte))
    return events


@cocotb.test()
async def rx_errors_break_and_recovery(dut):
    p = Pins(dut)
    await p.reset()
    await p.write(15)
    await p.write(0x83)  # valid 16-clock 7N2 descriptor, not engine entry
    assert await peer_bits(p, [(0, 3), (1, 180)]) == []
    good = frame(0x52, 7, 2)
    # Consecutive frames without an extra idle cell.
    assert await peer_bits(p, [(b, 16) for b in good * 2]) == [("valid", 0x52)] * 2
    for stops in ([0, 1], [1, 0]):
        bad = frame(0x0B, 7, 2)[:-2] + stops
        assert await peer_bits(p, [(b, 16) for b in bad] + [(1, 32)]) == [("error", 0x52)]
    assert await peer_bits(p, [(0, 360), (1, 32)]) == [("error", 0x52)]
    assert await peer_bits(p, [(b, 16) for b in good]) == [("valid", 0x52)]


@cocotb.test()
async def reset_aborts_both_frames(dut):
    p = Pins(dut)
    await p.reset()
    await p.write(7)
    await p.write(0x81)
    p.inputs &= ~2
    await p.write(0x55, mode=0)
    await p.tick(20)
    assert p.uo & 2
    await p.reset()
    assert await peer_bits(p, [(1, 100)]) == []
    await duplex(p, 434, 8, 1, 0x5A, 0x91)


@cocotb.test()
async def asynchronous_peer_phase_and_drift(dut):
    p = Pins(dut)
    await p.reset()
    await p.write(15)
    await p.write(0x80)  # 8N1 at 320 ns per bit
    seen = []

    async def observe():
        while True:
            await RisingEdge(dut.clk)
            await ReadOnly()
            assert not (p.out & 4)
            if p.uo & 8:
                seen.append(p.rx_byte)

    # Independent transmitter deadlines in nanoseconds, off the system edges.
    clock = Clock(dut.clk, 20, unit="ns")
    clock.start(start_high=False)
    observer = cocotb.start_soon(observe())
    await Timer(7, unit="ns")
    for bit_ns, byte in [(315, 0x96), (325, 0x69)]:
        for level in frame(byte, 8, 1):
            dut.uio_in.value = (p.inputs & ~2) | (level << 1)
            await Timer(bit_ns, unit="ns")
    await Timer(400, unit="ns")
    observer.cancel()
    clock.stop()
    assert seen == [0x96, 0x69]


@cocotb.test()
async def engine_handoff_during_uart_frame(dut):
    p = Pins(dut)
    await p.reset()
    await p.write(15)
    await p.write(0x83)  # 16 clocks, 7N2
    cells = frame(0x55, 7, 2)
    incoming = frame(0x2E, 7, 2)
    p.host(0, 0, 0)
    await p.tick()
    # Enter engine after UART starts; load HALT and RUN while UART is busy.
    actions = {0: (0x55, 0, 1), 4: (0, 1, 0), 5: (0, 1, 1),
               6: (0x83, 1, 0), 7: (0x83, 1, 1), 8: (0, 0, 0),
               9: (0, 0, 1), 10: (2, 1, 0), 11: (2, 1, 1)}
    for cycle in range(164):
        slot = cycle // 16
        line = incoming[slot] if slot < len(cells) else 1
        p.inputs = (p.inputs & ~2) | (line << 1)
        if cycle in actions:
            p.host(*actions[cycle])
        await p.tick()
        assert p.oe == (4 if cycle >= 7 else 0xF4)
        assert p.uo & 7 == ((2 | cells[slot]) if slot < len(cells) else (5 if cycle == 160 else 1))
    await p.write(0)
    assert p.rx_byte == 0x2E and p.oe == 0xF4
    await duplex(p, 16, 7, 2, 0xE6, 0x4D)
