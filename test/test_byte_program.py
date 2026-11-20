"""Wire-level examples for two programs, loaded via the existing GPIO loader."""
import cocotb

from pins import Pins
from test_spi import configure, setup_spi, transaction


# First CA poll replies at byte 4; subsequent polls defer and reply at byte 5.
POLL = bytes.fromhex("12 CA 00 00 65 01 34 01 41 00 76 00 51 3C")
# An address and a dummy byte form one logical transaction; repeat under CS.
STREAM = bytes.fromhex("21 00 40 00")


async def install(p, image):
    await p.enter()
    await p.load(image)
    await p.write(4)
    p.inputs |= 0x10
    p.peer_mask |= 0x70
    await p.tick(5)


async def exit_peripheral(p):
    p.peer_mask &= ~0x70
    await p.write(0)
    assert p.oe == 0xF4


@cocotb.test()
async def replace_format_without_reset(dut):
    p = Pins(dut)
    await p.reset()
    await install(p, POLL)
    await configure(p, 1, 0xED, 0x48)
    await transaction(p, 0, [0xCB, 1, 0, 0, 0], [0]*5)
    request = [0xCA, 0, 0, 0, 0, 0]
    first = [0, 0, 0, 0xED, 0, 0]
    await transaction(p, 0, request, first, bit_count=31)  # abort before COMMIT
    await transaction(p, 0, request, first)
    await transaction(p, 0, request, [0, 0, 0, 0, 0x3C, 0])

    # Same silicon, table and history, different transaction language.
    await exit_peripheral(p)
    await install(p, STREAM)
    await configure(p, 2, 0xAB, 0x0F)
    await transaction(p, 0, request, [0]*6)  # CA is an invalid stream address
    await transaction(p, 0, [1, 0, 2, 0, 2, 0], [0, 0xA5, 0, 0xAB, 0, 0xA0],
                      payload_start=8)

    # Compatibility entry must use its original image, even after a custom run.
    await exit_peripheral(p)
    await setup_spi(p)
    await transaction(p, 0, [0xA6, 1, 0], [0, 0, 0xA5])


@cocotb.test()
async def programmed_timing_all_modes(dut):
    p = Pins(dut)
    await p.reset()
    phases = sorted({i*1000 for i in range(20)} | {9900, 10100})
    for image in (POLL, STREAM):
        await install(p, image)
        await configure(p, 1, 0xED, 0x48)
        for mode in range(4):
            await p.write(0x10 + mode)
            edges, enables = [], []
            for phase in phases:
                await p.write(1)
                if image == POLL:
                    messages = [([0xCA, 0, 0, 0], [0, 0, 0, 0xED]),
                                ([0xCA, 0, 0, 0, 0], [0, 0, 0, 0, 0x3C])]
                else:
                    messages = [([1, 0, 1, 0], [0, 0xED, 0, 0xA5])]
                for request, expected in messages:
                    times, enable = await transaction(p, mode, request, expected, phase,
                                                      payload_start=8)
                    edges.extend(times)
                    enables.append(enable)
            assert edges and max(edges) <= 60000 and max(enables) <= 60000
            dut._log.info("%s mode %d: %d transitions, launch %.3f..%.3f ns, "
                          "minimum setup %.3f ns, CS enable %.3f..%.3f ns",
                          "poll" if image == POLL else "stream", mode, len(edges),
                          min(edges)/1000, max(edges)/1000, 100-max(edges)/1000,
                          min(enables)/1000, max(enables)/1000)
        await exit_peripheral(p)


@cocotb.test()
async def incomplete_images_and_stale_targets(dut):
    p = Pins(dut)
    await p.reset()
    await p.enter()
    await p.write(4)  # empty handoff rejected; loader remains selected
    await p.write(0x50, mode=0)
    await p.write(4)  # odd length rejected
    await p.write(0xD5, mode=0)
    await p.write(4)  # one complete rule: send D5 on every following byte
    p.peer_mask |= 0x70
    p.inputs |= 0x10
    await p.tick(5)
    await transaction(p, 0, [0, 0, 0], [0, 0xD5, 0xD5], payload_start=8)
    await exit_peripheral(p)
    # A full image seeds the last address. Then a shorter image jumps there.
    await install(p, bytes.fromhex("77 00") + bytes(12) + bytes.fromhex("57 A5"))
    await transaction(p, 0, [0]*4, [0, 0, 0xA5, 0xA5])
    await exit_peripheral(p)
    await install(p, bytes.fromhex("77 00"))
    await transaction(p, 0, [0]*4, [0]*4)
