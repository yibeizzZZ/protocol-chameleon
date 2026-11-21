"""Read cross-device state using only program loads and resolved SPI pins."""
import cocotb

from pins import Pins
from test_byte_program import exit_peripheral
from test_p1_sources import ROOT, load_source
from test_spi import transaction


A = 0xa1
B = 0xb2
READ = [B, B, 0, 0, 0]


async def install_model(p, name, mode=0):
    await p.enter()
    run = await load_source(p, ROOT / "examples" / f"grant_{name}.p1")
    await p.write(run)
    p.inputs |= 0x10
    p.peer_mask |= 0x70
    await p.tick(5)
    await p.write(0x10 + mode)


@cocotb.test()
async def same_wire_history_different_peripheral_models(dut):
    p = Pins(dut)
    await p.reset()
    for name, threshold in (("one", 1), ("two", 2)):
        await install_model(p, name)
        # This oracle counts consecutive affirmative votes since a complete
        # read. All reads and writes are distinct physical transactions.
        for votes in ([], [1], [], [1, 1], [1, 0], [0, 1], [1, 1, 1]):
            consecutive = 0
            for vote in votes:
                await transaction(p, 0, [A, vote], [0, 0])
                consecutive = consecutive + 1 if vote else 0
            response = 0xa5 if consecutive >= threshold else 0
            await transaction(p, 0, [A, 1], [0, 0], bit_count=15)
            await transaction(p, 0, READ, [0, 0, 0, 0, response], bit_count=39)
            await transaction(p, 0, READ, [0, 0, 0, 0, response])
            await transaction(p, 0, READ, [0]*5)
        # Reloading an image starts a fresh model even with pending votes.
        for _ in range(2):
            await transaction(p, 0, [A, 1], [0, 0])
        await exit_peripheral(p)
