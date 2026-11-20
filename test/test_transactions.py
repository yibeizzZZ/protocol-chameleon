"""Transaction oracles use only host writes, SPI pins, IRQs and result pages."""
import cocotb

from pins import Pins
from test_byte_program import STREAM, exit_peripheral
from test_feedback import field, launch, page, profile, record, rule
from test_spi import configure, transaction
from test_trials import PASS, TIMEOUT, WRONG, ORDER, UNKNOWN, Trial, descriptor


END, TAG, CMD, ADDR, DATA, FROM_MISO = 32, 16, 8, 4, 2, 1
STREAM_FIELDS = [TAG | ADDR, END | CMD | DATA | FROM_MISO]
REQUEST = [1, 0x36, 1, 0x36, 2, 0x47]
REPLY = [0, 0x55, 0, 0x55, 0, 0xaa]


async def setup(p, image, fields, mode=0):
    await p.enter()
    await p.load(image)
    for index, value in enumerate(fields):
        await field(p, 0x10 + index, value)
    await p.write(4)
    p.inputs |= 0x10
    p.peer_mask |= 0x70
    await p.tick(5)
    await configure(p, 1, 0x55, 0)
    await configure(p, 2, 0xaa, 0)
    await p.write(0x10 + mode)
    await p.write(0x30)
    return Trial(p)


async def run_wire(trial, mode=0, phase=0):
    await trial.start()
    await trial.tick(3)
    timing = await transaction(trial.p, mode, REQUEST, REPLY, phase, payload_start=8)
    await trial.p.tick(150)  # deadline 600 is past
    return await trial.result(), timing


@cocotb.test()
async def reproduce_physical_stream_mismatch(dut):
    p = Pins(dut)
    await p.reset()
    trial = await setup(p, STREAM, [])
    for length, verdict, count in ((6, TIMEOUT, 1), (2, WRONG, 0)):
        await trial.plan(descriptor(0, 600, length=length, checks=0, quota=3),
                         descriptor(0, 600, enabled=False), policy=0)
        rec, _ = await run_wire(trial)
        assert (rec[0], rec[1], rec[5:]) == (verdict, 1, (count, 0))
        dut._log.info("Unannotated STREAM: three replies, checked length %d, verdict %d, count %d",
                      length, rec[0], rec[5])


async def tagged_plan(trial, order=1, length=2, data_b=0xaa):
    # Both identities travel on CS_A. The address is byte 0, the command
    # byte 1, and the checked data is physically transmitted on MISO.
    await trial.plan(descriptor(0, 600, cmd=0x36, addr=1, quota=2, length=length),
                     descriptor(0, 600, cmd=0x47, addr=2, length=2), policy=0x38 | order)
    for selector, value in ((0x47,1), (0x4f,2), (0x52,0x55), (0x53,data_b)):
        await field(trial.p, selector, value)


@cocotb.test()
async def independent_stream_contracts(dut):
    p = Pins(dut)
    await p.reset()
    trial = await setup(p, STREAM, STREAM_FIELDS)
    await tagged_plan(trial)
    # Initial expectation reproduces the missing M8 capability.
    rec, _ = await run_wire(trial)
    assert (rec[0], rec[1], rec[5:]) == (PASS, 0, (2, 1)), rec
    # For every replay keep the program, CS, MOSI and MISO identical.
    for selector, value, expected in [
        (0x53, 0xab, (WRONG, 2, 2, 0)),   # observed B response
        (0x50, 0x3a, (ORDER, 1, 0, 0)),  # B is now required first
        (0x40, 0x3b, (WRONG, 1, 0, 0)),  # A must contain three bytes
        (0x4f, 3, (WRONG, 0, 2, 0)),     # unrecognized wire tag
        (0x41, 0x35, (WRONG, 1, 0, 0)),  # A command
        (0x42, 2, (WRONG, 1, 0, 0)),     # A address
    ]:
        await tagged_plan(trial)
        await field(p, selector, value)
        rec, _ = await run_wire(trial)
        assert (rec[0], rec[1], *rec[5:]) == expected, rec
        if selector in (0x53, 0x4f):
            assert rec[3:5] == (0x47, 2)
            assert await page(p, 12) + 16 * await page(p, 13) == 0xaa
            assert await page(p, 14) + 16 * await page(p, 15) == 2


@cocotb.test()
async def only_boundary_annotations_change(dut):
    p = Pins(dut)
    await p.reset()
    # Six advancing states; every byte preloads the same next reply. Use
    # identical instructions, bits and checker contract for both definitions.
    image = bytes.fromhex("51 55 52 55 53 55 54 55 55 55 50 55")
    for ends, expected in [({1,3,5}, (PASS,3)), ({2,5}, (WRONG,0))]:
        trial = await setup(p, image, [END if i in ends else 0 for i in range(6)])
        await trial.plan(descriptor(0, 600, quota=3, length=2, checks=0),
                         descriptor(0, 0, enabled=False), policy=0)
        await trial.start()
        await trial.tick(3)
        await transaction(p, 0, REQUEST, [0]+[0x55]*5, payload_start=8)
        await p.tick(150)
        rec = await trial.result()
        assert (rec[0], rec[5]) == expected
        if ends == {2,5}:
            # The same six bytes really are two triples, not just a rejection.
            await trial.plan(descriptor(0, 600, quota=2, length=3, checks=0),
                             descriptor(0, 0, enabled=False), policy=0)
            await trial.start()
            await trial.tick(3)
            await transaction(p, 0, REQUEST, [0]+[0x55]*5, payload_start=8)
            await p.tick(150)
            rec = await trial.result()
            assert (rec[0], rec[5]) == (PASS,2)
        await p.write(0x31)
        await exit_peripheral(p)


@cocotb.test()
async def input_dependent_boundaries_and_incomplete_records(dut):
    p = Pins(dut)
    await p.reset()
    # C1 takes a two-byte path. Other commands take a three-byte path.
    # The final MOSI byte identifies the event and is also the data field.
    image = bytes.fromhex("13 C1 72 00 70 00 70 00")
    trial = await setup(p, image, [CMD, ADDR, END|TAG|DATA, END|TAG|DATA])
    await trial.plan(descriptor(0, 550, cmd=0xc1, length=2, checks=8),
                     descriptor(0, 550, cmd=0x66, addr=0x77, length=3), policy=0x39)
    for selector, value in [(0x47,1),(0x4f,2),(0x52,1),(0x53,2)]:
        await field(p, selector, value)
    msg = [0xc1,1,0x66,0x77,2]
    for nbits, verdict, counts in [(40,PASS,(1,1)), (24,UNKNOWN,(1,0)),
                                   (19,UNKNOWN,(1,0)), (8,UNKNOWN,(0,0))]:
        await trial.start()
        await trial.until(4)
        await trial.frame(0, msg, nbits)
        await trial.until(551)
        rec = await trial.result()
        assert (rec[0], rec[5:]) == (verdict, counts), rec


@cocotb.test()
async def logical_deadline_and_eligibility_boundaries(dut):
    p = Pins(dut)
    await p.reset()
    trial = await setup(p, STREAM, STREAM_FIELDS)
    start = 4
    # First synchronized sample at start+8, then 10 ticks per bit. B's
    # first bit is sample 33; B's closing bit is sample 48, before CS rises.
    begin_b, end_a, end_b = start+328, start+318, start+478
    for issue_b, deadline_b, verdict in [
        (begin_b,end_b,PASS), (begin_b+1,end_b,ORDER), (begin_b,end_b-1,TIMEOUT)
    ]:
        await trial.plan(descriptor(0, end_a, quota=2, length=2, checks=0),
                         descriptor(issue_b, deadline_b, length=2, checks=0), policy=9)
        await field(p, 0x47, 1)
        await field(p, 0x4f, 2)
        await trial.start()
        await trial.until(start)
        await trial.frame(0, REQUEST)
        rec = await trial.result()
        assert (rec[0], rec[1], rec[2], *rec[5:]) == (
            verdict, 0 if verdict == PASS else 2, end_b + int(verdict == PASS),
            2, int(verdict == PASS)), rec


@cocotb.test()
async def marked_end_scopes_peripheral_read_history(dut):
    p = Pins(dut)
    await p.reset()
    for ends_on_read, final_reply in [(True,0x55), (False,0x05)]:
        # A marked READ expires its pending handle. An unmarked READ and
        # the following marked COMMIT form one transaction and clear bits.
        fields = [END,END] if ends_on_read else [0,END]
        trial = await setup(p, STREAM, fields)
        await p.write(0x31)
        await configure(p, 1, 0x55, 0x50)
        await p.write(0x30)
        quota, policy = (4,0x40) if ends_on_read else (2,0)
        await trial.plan(descriptor(0, 400, quota=quota, length=2, checks=0),
                         descriptor(0, 0, enabled=False), policy=policy)
        await trial.start()
        await trial.tick(2)
        await transaction(p, 0, [1,0,1,0], [0,0x55,0,final_reply], payload_start=8)
        await p.tick(100)
        rec = await trial.result()
        assert (rec[0], rec[5]) == (PASS, quota)
        await p.write(0x31)
        await exit_peripheral(p)


@cocotb.test()
async def missing_fields_cannot_match_zero(dut):
    p = Pins(dut)
    await p.reset()
    trial = await setup(p, STREAM, [ADDR, END | CMD])
    await tagged_plan(trial)
    rec, _ = await run_wire(trial)
    assert (rec[0], rec[1], rec[5:]) == (UNKNOWN, 0, (0, 0))

    # Identify A by physical CS. No data field exists, even though its
    # empty register and the configured comparison byte would both be zero.
    await field(p, 0x50, 0x10)
    await field(p, 0x52, 0)
    rec, _ = await run_wire(trial)
    assert (rec[0], rec[1], rec[5:]) == (WRONG, 1, (0, 0))

    await field(p, 0x50, 8)
    await field(p, 0x4f, 1)  # two descriptors claim the same tag
    await trial.start()
    rec = await trial.result()
    assert rec[:3] == (UNKNOWN, 0, 0)


@cocotb.test()
async def logical_verdict_drives_existing_feedback(dut):
    p = Pins(dut)
    await p.reset()
    trial = await setup(p, STREAM, STREAM_FIELDS)
    await tagged_plan(trial)
    await profile(p, 0, 0, 0, 0)
    await profile(p, 1, 3, 7, 1)  # invert the physical A status MSB
    await rule(p, 0, PASS, 1)
    await field(p, 0x51, 1)  # two trials
    await launch(trial)
    # The master repeats exactly one CS assertion per trial. No host writes.
    for base in (0, 604):
        await trial.until(base + 10)
        await trial.frame(0, REQUEST)
    assert p.uo & 15 == 8 and await page(p, 0xc0) == 2
    first, second = await record(p, 0), await record(p, 1)
    assert (first['verdict'], first['tick'], first['target']) == (PASS, 601, 1)
    assert (second['verdict'], second['source'], second['tick']) == (WRONG, 1, 168)
    assert (second['settings'], second['prev']) == ((3, 7, 1), PASS)
    assert await page(p, 12) + 16 * await page(p, 13) == 0xd5


@cocotb.test()
async def marked_stream_timing_all_modes(dut):
    p = Pins(dut)
    await p.reset()
    for mode in range(4):
        trial = await setup(p, STREAM, STREAM_FIELDS, mode)
        await tagged_plan(trial)
        delays, enables = [], []
        for phase in sorted({1000*i for i in range(20)} | {9900, 10100}):
            rec, (edges, enable) = await run_wire(trial, mode, phase)
            assert (rec[0], rec[5:]) == (PASS, (2,1))
            delays.extend(edges)
            enables.append(enable)
        assert max(delays) <= 60000 and max(enables) <= 60000
        dut._log.info("logical mode %d: %d transitions, launch %.3f..%.3f ns, setup %.3f ns, "
                      "CS to OE %.3f..%.3f ns", mode, len(delays), min(delays)/1000,
                      max(delays)/1000, 100-max(delays)/1000, min(enables)/1000, max(enables)/1000)
        await p.write(0x31)
        await exit_peripheral(p)
