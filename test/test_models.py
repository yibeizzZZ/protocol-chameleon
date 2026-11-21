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


async def install_program(p, name, mode=0):
    await p.enter()
    run = await load_source(p, ROOT / "examples" / f"{name}.p1")
    await p.write(run)
    p.inputs |= 0x10
    p.peer_mask |= 0x70
    await p.tick(5)
    await p.write(0x10 + mode)


async def install_model(p, name, mode=0):
    await install_program(p, f"grant_{name}", mode)


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


@cocotb.test()
async def cross_device_byte_mailbox(dut):
    p = Pins(dut)
    await p.reset()
    poll = [B, 0, 0]
    for mode in range(4):
        await install_program(p, "mailbox", mode)
        await p.write(0x30)  # expose both physical selects
        await transaction(p, mode, poll, [0, 0, 0], sensor=1)
        delays = []
        for n, phase in enumerate(sorted({i*1000 for i in range(20)} | {9900, 10100})):
            token = (0xff - 73*n) & 255
            await transaction(p, mode, [A, token], [0, 0], phase)
            await transaction(p, mode, [A, token ^ 255], [0, 0], phase, bit_count=15)
            await transaction(p, mode, poll, [0, 0, token], phase, bit_count=23, sensor=1)
            edges, _ = await transaction(p, mode, poll, [0, 0, token], phase, sensor=1)
            delays.extend(edges)
            await transaction(p, mode, poll, [0, 0, 0], phase, sensor=1)
        dut._log.info("mailbox mode %d: launch %.3f..%.3f ns", mode,
                      min(delays)/1000, max(delays)/1000)
        await transaction(p, mode, [A, 0xff], [0, 0])  # next image must start empty
        await p.write(0x31)
        await exit_peripheral(p)


async def param_snapshot(p, trial):
    nibbles = [await page(p, 0xe0 + 4*trial + i) for i in range(4)]
    return nibbles[0] + 16*nibbles[1], nibbles[2] + 16*nibbles[3]


@cocotb.test()
async def failure_policy_updates_program_operands(dut):
    p = Pins(dut)
    await p.reset()
    await install_program(p, "adaptive_poll")
    await p.write(0x30)
    trial = Trial(p)
    await trial.plan(descriptor(0, 400, checks=0), descriptor(0, 400, checks=0), policy=0)
    for selector, value in ((0x5c, 0xfe), (0x5d, 0x19), (0x5a, 1), (0x5b, 0x88),
                            (0x51, 2)):
        await field(p, selector, value)
    await rule(p, 0, TIMEOUT, 0, source=2, prev=TIMEOUT)
    await field(p, 0x63, 0xe0)  # copy A's observed command into operand 1
    await rule(p, 1, TIMEOUT, 0, source=2)
    for add_action, snapshots, replies in (
            (0x83, [(0xfe, 0x19), (1, 0x19), (1, 0x6d)], [0, 0x19, 0x6d]),
            (0xc3, [(0xfe, 0x19), (0xfe, 0x1c), (0xfe, 0x6d)], [0, 0, 0])):
        # Change only the policy destination. The DUT always polls A with
        # identical bits and never services B. RUN reseeds both operands.
        await field(p, 0x67, add_action)
        await launch(trial)
        for reply in replies:
            await p.tick(5)
            await transaction(p, 0, [1, 0x6d, 0], [0, 0, reply])
            await p.tick(165)
        assert await page(p, 0xc0) == 3
        for n, values in enumerate(snapshots):
            assert await param_snapshot(p, n) == values
            evidence = await record(p, n)
            assert (evidence['verdict'], evidence['source'], evidence['rule']) == (
                TIMEOUT, 2, 1 if n == 0 else 0)
        assert await param_snapshot(p, 3) == (0, 0)


@cocotb.test()
async def terminal_frame_uses_selected_trial_operands(dut):
    p = Pins(dut)
    await p.reset()
    await install_program(p, "adaptive_poll")
    await p.write(0x30)
    trial = Trial(p)
    await trial.plan(descriptor(0, 40, checks=0), descriptor(0, 0, enabled=False), policy=0)
    await field(p, 0x51, 1)
    await field(p, 0x5c, 1)
    await field(p, 0x5d, 0)
    await rule(p, 0, TIMEOUT, 0, source=1)
    for action, expected in ((0xdf, 0xff), (0xe0, 0)):
        # Subtract one modulo 256, or copy an absent binding (hold).
        await field(p, 0x63, action)
        await launch(trial)
        await trial.until(46)
        # Trial 1 ends during the first wire byte. Its snapshotted parameter
        # still determines the third wire byte after the campaign is over.
        await transaction(p, 0, [1, 0, 0], [0, 0, expected])
        assert await page(p, 0xc0) == 2
        assert await param_snapshot(p, 1) == (1, expected)
        await transaction(p, 0, [1, 0, 0], [0, 0, 0])


@cocotb.test()
async def shared_byte_cells_have_independent_contents(dut):
    p = Pins(dut)
    await p.reset()
    await p.enter()
    # Store two wire bytes. Return cell 1, then cell 0; clear only cell 1
    # and return the two again. Each READ sends its result one byte later.
    await p.load(bytes.fromhex("C1 00 C2 01 D3 01 D4 00 E5 01 D6 01 D7 00 00 00"))
    await p.write(4)
    p.inputs |= 0x10
    p.peer_mask |= 0x70
    await p.tick(5)
    for first, second in ((0x92, 0x6f), (0xff, 0), (0, 0xe7)):
        await transaction(p, 0, [first, second] + [0]*6,
                          [0, 0, 0, second, first, 0, 0, first])


@cocotb.test()
async def edited_operand_latency(dut):
    """Time two winning actions through the next trial and its first changed MISO bit."""
    import os
    from cocotb.triggers import ValueChange
    from test_spi import now, miso

    async def first_high_reply():
        # Both header reply bytes are zero. Bit 7 of the edited reply is one.
        while miso(dut) != "1":
            await ValueChange(dut.pads)
        return now()

    p = Pins(dut)
    await p.reset()
    rtl_feedback = None if os.environ.get("GATES") == "yes" else dut.user_project.trials.feedback
    for mode in range(4):
        await install_program(p, "adaptive_poll", mode)
        await p.write(0x30)
        trial = Trial(p)
        await trial.plan(descriptor(0, 330, checks=0), descriptor(0, 330, checks=0), policy=0)
        for selector, value in ((0x5c, 1), (0x5d, 0x7f), (0x5a, 1), (0x5b, 0x88), (0x51, 1)):
            await field(p, selector, value)
        for slot, verdict in enumerate((PASS, WRONG, TIMEOUT)):
            await rule(p, slot, verdict, 0, source=1)
        await rule(p, 3, TIMEOUT, 0, source=2)
        for edit, updated in ((0xc1, 0x80), (0xe0, 0xa5)):
            await field(p, 0x6f, edit)
            launches, first_bits = [], []
            for phase in sorted({i*1000 for i in range(20)} | {9900, 10100}):
                await launch(trial)
                dut.ui_in.value = 0  # verdict page, no strobe
                await p.tick(5)
                await transaction(p, mode, [1, 0xa5, 0], [0, 0, 0x7f])
                for _ in range(100):
                    await p.tick()
                    if p.uo >> 4 == TIMEOUT:
                        break
                assert p.uo >> 4 == TIMEOUT
                # Pins.tick returns 10 ns after its rising edge.
                verdict_edge = now() - 10000
                if rtl_feedback is not None:
                    assert int(rtl_feedback.live_operands.value) >> 8 == 0x7f
                dut.ui_in.value = 0xc0
                await p.tick()
                assert p.uo >> 4 == 9  # campaign busy, one trial archived
                if rtl_feedback is not None:
                    assert int(rtl_feedback.live_operands.value) >> 8 == updated
                assert now() - 10000 - verdict_edge == 20000
                dut.ui_in.value = 0
                await p.tick()
                assert p.uo >> 4 == 0 and p.uo & 3 == 0
                await p.tick()
                assert p.uo & 3 == 3 and now() - 10000 - verdict_edge == 60000
                pad_edge = cocotb.start_soon(first_high_reply())
                edges, _ = await transaction(p, mode, [1, 0xa5, 0], [0, 0, updated], phase)
                first_bits.append((await pad_edge) - verdict_edge)
                launches.extend(edges)
                await p.tick(100)
                assert await param_snapshot(p, 1) == (1, updated)
                assert (await record(p, 0))['rule'] == 3
            assert max(launches) <= 60000
            dut._log.info("P5 edit %02x mode %d: archive 20 ns, restart 40 ns, IRQ 60 ns; "
                          "launch %.3f..%.3f ns; verdict-to-first-MISO %.3f..%.3f ns",
                          edit, mode, min(launches)/1000, max(launches)/1000,
                          min(first_bits)/1000, max(first_bits)/1000)
        await p.write(0x31)
        await exit_peripheral(p)
