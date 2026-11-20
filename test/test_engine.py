import cocotb
from cocotb.triggers import Timer

from pins import Pins


BURST = bytes.fromhex("10 24 55 14 53 10 57 14 53 10 00")
REPLY = bytes.fromhex("81 65 10 24 77 14 24 91 20 70")


async def engine(dut):
    p = Pins(dut)
    await p.reset()
    await p.enter()
    return p


@cocotb.test()
async def burst_waveform_and_replay(dut):
    p = await engine(dut)
    await p.load(BURST)
    for _ in range(2):
        await p.write(2)
        trace = []
        for _ in range(40):
            await p.tick()
            level = str(dut.pads.value)[::-1][6]  # P2 on physical pad 6
            trace.append(level.lower())
            assert p.oe == (0x04 if level.lower() == "z" else 0x44)
            if not p.running:
                break
        assert not p.running
        assert "".join(trace) == "z" + "0"*7 + "1"*5 + "0"*9 + "1"*5 + "0z"


@cocotb.test()
async def clocked_reply_both_branches(dut):
    p = await engine(dut)
    p.peer_mask |= 0x30  # Peer owns P0 clock and P1 request; P2 is DUT reply.
    await p.load(REPLY)
    await p.write(2)
    history = 0
    for request in (1, 0, 1, 1):
        p.inputs = (p.inputs & ~0x30) | (request << 5)
        await p.tick(8)
        assert p.oe == 0x04
        p.inputs |= 0x10
        for cycles in range(1, 13):
            await p.tick()
            if p.oe == 0x44:
                break
        assert p.oe == 0x44 and (p.out >> 6) & 1 == request
        dut._log.info("P0 rise to P2 drive: request=%d, %d sampled clocks", request, cycles)
        history = ((history << 1) | request) & 15
        assert p.uo >> 4 == history
        # Change P1 during the high phase; only the falling edge may sample it.
        p.inputs ^= 0x20
        await p.tick(8)
        assert p.uo >> 4 == history and p.oe == 0x44
        p.inputs &= ~0x10
        await p.tick(6)
        history = ((history << 1) | (1 - request)) & 15
        assert p.uo >> 4 == history and p.oe == 0x04 and p.running
    await p.write(3)
    assert not p.running and p.oe == 0x04
    assert p.uo >> 4 == history


@cocotb.test()
async def sample_gpio_and_bus_ownership(dut):
    p = await engine(dut)
    p.inputs |= 0x80
    p.peer_mask |= 0x80  # P3 alone driven high by peer
    await p.load(bytes.fromhex("33 11 21 5F 20 33 00"))
    await p.write(2)
    await p.tick(4)
    assert p.uo >> 4 == 1 and p.oe == 0x14 and p.out & 0x10
    # Negative control for the pad model: deliberately oppose the DUT on P0,
    # between clock edges, then relinquish before any further sampling.
    dut.peer_oe.value = p.peer_mask | 0x10
    await Timer(1, unit="ns")
    assert str(dut.pads.value)[::-1][4].lower() == "x"
    dut.peer_oe.value = p.peer_mask
    await Timer(1, unit="ns")
    assert str(dut.pads.value)[::-1][4] == "1"
    await p.tick(19)
    assert not p.running and p.oe == 4 and p.uo >> 4 == 3
    # Before EXIT, the peer must stop driving: UART immediately owns P0..P3.
    p.peer_mask &= ~0x80
    await p.write(0)
    assert p.oe == 0xF4


@cocotb.test()
async def loader_bounds_and_invalid_commands(dut):
    p = await engine(dut)
    await p.write(2)  # empty RUN
    assert not p.running
    await p.load([0x50]*13 + [0x13, 0x23, 0x50])
    await p.write(0x70, mode=0)  # 17th byte would loop if executed
    await p.write(2)
    await p.tick(15)
    assert p.oe == 0x34 and p.out & 0x30 == 0x30
    await p.tick(2)
    assert not p.running and p.oe == 4
    # CLEAR must prevent jumps into stale storage. Reserved opcode must stop.
    for image in ([0x7D], [0x25, 0xF0]):
        await p.load(image)
        await p.write(2)
        await p.tick(2)
        assert not p.running and p.oe == 4
    # Writes while running must not replace or extend an edge-wait program.
    p.peer_mask |= 0x10
    await p.load([0x80])
    await p.write(2)
    for byte, mode in [(0x70, 0), (1, 1), (2, 1), (0xFE, 1)]:
        await p.write(byte, mode)
        assert p.running and p.oe == 4
    p.inputs |= 0x10
    await p.tick(8)
    assert not p.running and p.uo >> 4 == 1


@cocotb.test()
async def late_edge_stop_reset_and_exit(dut):
    p = await engine(dut)
    p.peer_mask |= 0x10
    await p.load([0x24, 0x5F, 0x80])  # drive P2, delay, wait for rising P0
    await p.write(2)
    await p.tick(3)
    p.inputs |= 0x10
    await p.tick(24)  # a rise during DELAY is not buffered
    assert p.running and p.oe == 0x44 and p.uo >> 4 == 0
    await p.write(3)  # Stop during wait
    assert not p.running and p.oe == 4
    await p.write(2)
    await p.tick(3)
    await p.write(3)  # Stop during delay
    assert not p.running and p.oe == 4
    await p.write(2)
    await p.tick(3)
    p.peer_mask &= ~0x10
    await p.write(0)  # EXIT while driving
    assert p.oe == 0xF4
    await p.enter()
    await p.write(2)
    assert not p.running
    await p.load([0x2F, 0x71])
    await p.write(2)
    await p.tick(3)
    assert p.running and p.oe == 0xF4
    await p.reset()
    await p.enter()
    await p.write(2)
    assert not p.running and p.oe == 4
