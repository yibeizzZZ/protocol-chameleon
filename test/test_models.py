"""Read cross-device state using only program loads and resolved SPI pins."""
import cocotb

from pins import Pins
from test_byte_program import exit_peripheral
from test_feedback import field, launch, page, profile, record, rule
from test_p1_sources import ROOT, load_source
from test_spi import transaction
from test_trials import PASS, TIMEOUT, WRONG, Trial, descriptor


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


async def load_contract(p):
    await p.write(0x30)
    trial = Trial(p)
    await trial.plan(descriptor(0, 650, cmd=1, length=2, checks=8),
                     descriptor(0, 650, cmd=B, length=5, checks=8), policy=0x39)
    for selector, value in [(0x47, A), (0x4f, B), (0x52, 1), (0x53, 0),
                            (0x54, 0xe4), (0x55, A), (0x56, 4), (0x59, 1)]:
        await field(p, selector, value)
    return trial


@cocotb.test()
async def feedback_changes_shared_state_predicate(dut):
    p = Pins(dut)
    await p.reset()
    await install_model(p, "profile")
    trial = await load_contract(p)
    await profile(p, 0, 0, 4, 0)
    await profile(p, 1, 0, 4, 0)
    await field(p, 0x73, 3)
    await field(p, 0x51, 1)
    await rule(p, 0, PASS, 1)
    for next_parameter, final in ((3, PASS), (1, WRONG)):
        await field(p, 0x77, next_parameter)
        await launch(trial)
        for base in (0, 654):
            await trial.until(base + 5)
            await trial.frame(0, [A, 1])
            await trial.until(base + 200)
            await trial.frame(1, READ)
            assert (base + 167, 2) in trial.notifications
        await trial.until(1307)
        first, second = await record(p, 0), await record(p, 1)
        assert (first['verdict'], first['target'], second['verdict']) == (PASS, 1, final)
        assert await page(p, 0xc4) == 3 and await page(p, 0xc5) == next_parameter
        if final == WRONG:
            assert (second['source'], second['tick']) == (2, 598)
            assert (await page(p, 12)) + 16 * (await page(p, 13)) == 0xa5
    await field(p, 0x77, 9)
    assert await page(p, 0xc5) == 1 and await page(p, 0xc6) == 0


@cocotb.test()
async def observed_model_reply_triggers_another_device(dut):
    p = Pins(dut)
    await p.reset()
    await install_model(p, "profile")
    trial = await load_contract(p)
    # B is issued at tick zero. Observe its MISO data to decide whether to
    # notify A. The P4 contract accepts the same B reply in both replays.
    await field(p, 0x50, 0x38)
    await field(p, 0x54, 0xc4)
    await field(p, 0x55, B)
    await field(p, 0x58, 0)
    await field(p, 0x53, 0xa5)
    for expected, verdict in ((0, TIMEOUT), (0xa5, PASS)):
        await field(p, 0x59, expected)
        await trial.start()
        await trial.until(5)
        await trial.frame(1, READ)
        if verdict == PASS:
            assert (407, 1) in trial.notifications
            await trial.frame(0, [A, 1])
        await trial.until(651)
        rec = await trial.result()
        assert (rec[0], rec[5:]) == (verdict, (int(verdict == PASS), 1))


@cocotb.test()
async def parameter_lasts_until_chip_deselect(dut):
    p = Pins(dut)
    await p.reset()
    await install_model(p, "profile")
    trial = await load_contract(p)
    await field(p, 0x54, 0)
    await field(p, 0x58, 1)
    await trial.plan(descriptor(0, 40, checks=0), descriptor(0, 0, enabled=False), policy=0)
    await transaction(p, 0, [A, 1], [0, 0])
    await field(p, 0x73, 3)
    await launch(trial)
    await trial.tick(2)
    # The campaign finishes during the first byte. The predicate executes
    # on byte three and must still see the original profile value.
    await transaction(p, 0, READ, [0]*5, sensor=1)
    assert (await record(p, 0))['verdict'] == TIMEOUT
    await transaction(p, 0, [A, 1], [0, 0])
    await transaction(p, 0, READ, [0, 0, 0, 0, 0xa5], sensor=1)


@cocotb.test()
async def shared_history_at_five_mhz(dut):
    p = Pins(dut)
    await p.reset()
    for mode in range(4):
        await install_model(p, "profile", mode)
        trial = await load_contract(p)
        await field(p, 0x58, 1)
        await field(p, 0x53, 0xa5)
        delays = []
        for phase in sorted({1000*i for i in range(20)} | {9900, 10100}):
            await trial.start()
            await trial.tick(4)
            await transaction(p, mode, [A, 1], [0, 0], phase)
            edges, _ = await transaction(p, mode, READ, [0, 0, 0, 0, 0xa5], phase,
                                         sensor=1, payload_start=32)
            delays.extend(edges)
            await p.tick(120)
            assert (await trial.result())[0] == PASS
        assert delays and max(delays) <= 60000
        dut._log.info("model mode %d: %d toggles, %.3f..%.3f ns, setup %.3f ns",
                      mode, len(delays), min(delays)/1000, max(delays)/1000,
                      100-max(delays)/1000)
        await p.write(0x31)
        await exit_peripheral(p)
