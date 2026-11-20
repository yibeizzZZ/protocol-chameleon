"""SPI wires in, DRDY edges and host-visible trial records out."""
import cocotb
from cocotb.triggers import ReadOnly, ValueChange

from pins import Pins
from test_byte_program import STREAM, exit_peripheral
from test_feedback import field, launch, page, profile, record, rule
from test_spi import configure, now, transaction
from test_transactions import REQUEST, STREAM_FIELDS, setup, tagged_plan
from test_trials import PASS, TIMEOUT, UNKNOWN, WRONG, descriptor


async def load_trigger(p, control, tag, delay, window=0):
    for index, value in enumerate((control, tag, delay, window)):
        await field(p, 0x54 + index, value)


async def witness(p):
    return await page(p, 0xd0), await page(p, 0xd1)


@cocotb.test()
async def ordinal_and_input_time_control_notification(dut):
    p = Pins(dut)
    await p.reset()
    trial = await setup(p, STREAM, STREAM_FIELDS)
    await tagged_plan(trial, order=0)
    await load_trigger(p, 0xe0, 1, 12)
    for ordinal, start in [(1, 5), (2, 5), (1, 35)]:
        await field(p, 0x54, 0xe0 | (ordinal - 1))
        await trial.start()
        await trial.until(start)
        await trial.frame(0, REQUEST[:4])  # both A reads share one CS
        await trial.until(start + 340)
        await trial.frame(0, REQUEST[4:])
        await trial.until(601)
        # The master samples the final bits at start+155 and start+315.
        # Three rising edges observe the bit, then the loaded 12-tick delay.
        issue = start + 158 + 160*(ordinal - 1) + 12
        assert (issue, 3 if ordinal == 1 else 2) in trial.notifications, trial.notifications
        assert [t for t, bits in trial.notifications if bits & 2][0] == issue
        rec = await trial.result()
        assert (rec[:3], rec[5:]) == ((PASS, 0, 601), (2, 1))
        assert await witness(p) == (3, ordinal)

    await trial.start()
    await trial.until(601)
    assert trial.notifications == [(0, 1), (601, 0)]
    assert (await trial.result())[:3] == (TIMEOUT, 3, 601)
    assert await witness(p) == (0, 0)


@cocotb.test()
async def observed_vs_accepted_and_pending_cancellation(dut):
    p = Pins(dut)
    await p.reset()
    trial = await setup(p, STREAM, STREAM_FIELDS)
    await tagged_plan(trial, order=0)
    # A wrong command is still a complete record tagged 1. Raw observations
    # count it, accepted-only observations do not. Neither may mask WRONG.
    for control, expected in [(0xa0, (1, 1)), (0xe0, (0, 0))]:
        await load_trigger(p, control, 1, 0)
        await trial.start()
        await trial.until(5)
        await trial.frame(0, [1, 0x37])
        assert (await trial.result())[:3] == (WRONG, 1, 163)
        assert await witness(p) == expected
        assert all(not (bits & 2) for _, bits in trial.notifications)

    await load_trigger(p, 0xe0, 1, 255)
    await trial.start()
    await trial.until(5)
    await trial.frame(0, [1, 0x36, 1, 0x37])
    await trial.until(601)
    assert (await trial.result())[:3] == (WRONG, 1, 323)
    assert await witness(p) == (1, 1)
    assert all(not (bits & 2) for _, bits in trial.notifications)


@cocotb.test()
async def reverse_target_and_relative_deadline(dut):
    p = Pins(dut)
    await p.reset()
    trial = await setup(p, STREAM, STREAM_FIELDS)
    await trial.plan(descriptor(0, 900, cmd=0x36, addr=1, length=2),
                     descriptor(0, 900, cmd=0x47, addr=2, length=2), policy=8)
    await field(p, 0x47, 1)
    await field(p, 0x4f, 2)
    # B triggers A. Both travel on CS_A. A's deadline is counted from DRDY_A.
    for delay, budget, verdict in [(0, 180, PASS), (255, 180, PASS),
                                   (12, 179, TIMEOUT), (0, 0, TIMEOUT)]:
        await load_trigger(p, 0xd0, 2, delay, budget)
        await trial.start()
        await trial.until(5)
        await trial.frame(0, [2, 0x47])
        issue = 163 + delay
        await trial.until(issue + 22)
        await trial.frame(0, [1, 0x36])
        await trial.until(901)
        assert (issue, 1) in trial.notifications
        rec = await trial.result()
        assert rec[:3] == ((PASS, 0, 901) if verdict == PASS else
                           (TIMEOUT, 1, issue + budget + 1)), rec
        assert await witness(p) == (3, 1)


@cocotb.test()
async def fourth_match_horizon_and_replay(dut):
    p = Pins(dut)
    await p.reset()
    trial = await setup(p, STREAM, STREAM_FIELDS)
    # Long absolute issue values are unused for the reactive slot.
    await trial.plan(descriptor(0, 1000, quota=4, length=2, checks=0),
                     descriptor(5000, 700, length=2, checks=0), policy=8)
    await field(p, 0x47, 1)
    await field(p, 0x4f, 2)
    await load_trigger(p, 0xe3, 1, 255)
    await trial.start()
    await trial.until(4)
    await trial.frame(0, REQUEST[:2] * 4)
    await trial.until(701)
    assert (await trial.result())[:3] == (TIMEOUT, 2, 701)
    assert await witness(p) == (1, 4)
    assert all(not (bits & 2) for _, bits in trial.notifications)

    # Replay cancels the old queue and partial record counts. A truncated
    # fourth match does not qualify and retains the three complete matches.
    await trial.start()
    await trial.until(4)
    await trial.frame(0, REQUEST[:2] * 4, nbits=63)
    assert (await trial.result())[0] == UNKNOWN
    assert await witness(p) == (0, 3)

    await field(p, 0x48, 0)  # cannot notify a disabled target slot
    await trial.start()
    assert (await trial.result())[:3] == (UNKNOWN, 0, 0)

    # Without an annotated definition the requested trigger has no source.
    await p.write(0x31)
    await exit_peripheral(p)
    trial = await setup(p, STREAM, [])
    await tagged_plan(trial)
    await trial.start()
    assert (await trial.result())[:3] == (UNKNOWN, 0, 0)


@cocotb.test()
async def final_wire_sample_to_wrong_verdict(dut):
    p = Pins(dut)
    await p.reset()
    for mode in range(4):
        trial = await setup(p, STREAM, STREAM_FIELDS, mode)
        await tagged_plan(trial)
        await load_trigger(p, 0xa0, 1, 0)
        latencies = []
        for phase in sorted({1000*i for i in range(20)} | {9900, 10100}):
            await trial.start()
            await trial.tick(3)
            dut.ui_in.value = 0  # page 0 presents the P4 verdict

            async def sample_completion():
                # Observe the master's SCLK pin across the actual CS window.
                prev = p.inputs
                samples = 0
                while samples < 16:
                    await ValueChange(dut.uio_in)
                    curr = int(dut.uio_in.value)
                    if not curr & 0x10 and (prev ^ curr) & 0x20:
                        if bool(curr & 0x20) == (mode in (0, 3)):
                            samples += 1
                    prev = curr
                return now()

            async def terminal():
                while True:
                    await ValueChange(dut.uo_out)
                    await ReadOnly()
                    if p.uo & 8:
                        assert p.uo >> 4 == WRONG
                        return now()

            edge = cocotb.start_soon(sample_completion())
            verdict = cocotb.start_soon(terminal())
            await transaction(p, mode, [1, 0x37], [0, 0x55], phase, payload_start=8)
            assert edge.done() and verdict.done()
            latencies.append(verdict.result() - edge.result())
            assert await witness(p) == (1, 1)
        assert 40000 <= min(latencies) <= max(latencies) <= 60000
        dut._log.info("P4 mode %d: final SCLK sample to WRONG %.3f..%.3f ns",
                      mode, min(latencies)/1000, max(latencies)/1000)
        await p.write(0x31)
        await exit_peripheral(p)


@cocotb.test()
async def reactive_campaign_spi_timing(dut):
    p = Pins(dut)
    await p.reset()
    for mode in range(4):
        trial = await setup(p, STREAM, STREAM_FIELDS, mode)
        await tagged_plan(trial)
        # First/repeat A replies differ. Check B data, both commands/addresses
        # and A-before-B order. The external oracle checks every MISO bit.
        await field(p, 0x50, 0x29)
        await load_trigger(p, 0xe1, 1, 12)
        # No reads in trial one. In trial two the profile sets a 4-tick lag
        # after the second accepted A, early enough for the following B byte.
        await profile(p, 0, 0, 12, 0)
        await profile(p, 1, 0, 4, 0)
        for i, verdict in enumerate((PASS, WRONG, UNKNOWN)):
            await rule(p, i, verdict, 0)
        await rule(p, 3, TIMEOUT, 1, source=3)
        await field(p, 0x51, 1)
        delays, enables = [], []
        for phase in sorted({1000*i for i in range(20)} | {9900, 10100}):
            await p.write(0x31)
            await configure(p, 1, 0x55, 0x10)
            await p.write(0x30)
            await launch(trial)
            await trial.until(600)
            assert await page(p, 0xc0) == 8
            await trial.tick(1)  # 601, missing evidence conclusive
            assert await page(p, 0) == TIMEOUT
            await trial.tick(1)  # 602, action selected and first record readable
            assert await page(p, 0xc0) == 9
            await trial.tick(1)  # 603, checker restarted
            assert await page(p, 0) == 0
            await trial.tick(1)  # 604, new trial tick 0 issues A
            assert p.uo & 3 == 1
            edges, enable = await transaction(p, mode, REQUEST, [0, 0x55, 0, 0x45, 0, 0xaa],
                                              phase, payload_start=8)
            delays.extend(edges)
            enables.append(enable)
            await p.tick(150)
            assert (await record(p, 0))['rule'] == 3
            assert (await record(p, 1))['verdict'] == PASS
            assert await witness(p) == (3, 2)
        assert max(delays) <= 60000 and max(enables) <= 60000
        dut._log.info("reactive mode %d: %d transitions, launch %.3f..%.3f ns, "
                      "min setup %.3f ns, CS to OE %.3f..%.3f ns", mode, len(delays),
                      min(delays)/1000, max(delays)/1000, 100-max(delays)/1000,
                      min(enables)/1000, max(enables)/1000)
        await p.write(0x31)
        await exit_peripheral(p)
