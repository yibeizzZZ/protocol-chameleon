"""Pin-level trial oracle. All timestamps below are measured from host RUN."""
import cocotb
from cocotb.triggers import Timer

from pins import Pins
from test_spi import configure, setup_spi, transaction
from test_byte_program import install, STREAM


PASS, TIMEOUT, DUPLICATE, WRONG, ORDER, UNKNOWN = range(1, 7)


def descriptor(issue, deadline, cmd=0xA6, addr=0, quota=1, length=3,
               checks=0x18, enabled=True):
    flags = ((length-2) << 5) | checks | ((quota-1) << 1) | int(enabled)
    return [flags, cmd, addr, issue & 255, issue >> 8, deadline & 255, deadline >> 8]


class Trial:
    def __init__(self, p):
        self.p = p

    async def plan(self, a, b, policy=4):
        for base, values in [(0x40, a), (0x48, b), (0x50, [policy])]:
            for offset, value in enumerate(values):
                await self.p.write(base+offset)
                await self.p.write(value, mode=0)

    async def start(self):
        await self.p.write(0x32)
        self.t = -1
        self.notifications = []
        self.last = 0

    async def tick(self, clocks):
        for _ in range(clocks):
            await self.p.tick()
            self.t += 1
            level = self.p.uo & 3
            if level != self.last:
                self.notifications.append((self.t, level))
                self.last = level

    async def until(self, t):
        assert t >= self.t
        await self.tick(t - self.t)

    async def frame(self, sensor, packet, nbits=None):
        # Mode 0, 5 MHz. Change controls halfway between system rising edges.
        # CS release is observed on the third rising edge (two synchronizers).
        bits = [int(x) for byte in packet for x in f"{byte:08b}"][:nbits]
        cs = (0x10, 0x02)[sensor]
        self.p.inputs &= ~cs
        self.p.inputs = (self.p.inputs & ~0x40) | (bits[0] << 6)
        await self.tick(5)
        for i in range(len(bits)):
            self.p.inputs |= 0x20
            await self.tick(5)
            self.p.inputs &= ~0x60
            if i+1 < len(bits):
                self.p.inputs |= bits[i+1] << 6
            await self.tick(5)
        self.p.inputs |= cs
        await self.tick(3)
        # Keep CS idle for the rest of the 100 ns inter-frame interval.
        await self.tick(2)

    async def result(self):
        assert self.p.uo & 15 == 8, f"incomplete trial, outputs={self.p.uo:02x}"
        pages = []
        for selector in range(12):
            self.p.dut.ui_in.value = selector
            await Timer(1, unit="ps")
            pages.append(self.p.uo >> 4)
        stamp = sum(pages[2+i] << (4*i) for i in range(4))
        return (pages[0], pages[1], stamp, pages[6] + 16*pages[7],
                pages[8] + 16*pages[9], pages[10], pages[11])


async def bench(dut):
    p = Pins(dut)
    await p.reset()
    await setup_spi(p)
    await p.write(0x30)
    return Trial(p)


@cocotb.test()
async def trial_trace_matrix(dut):
    trial = await bench(dut)
    # 112 valid captures. Expected times derive from the external bus schedule:
    # 24 bits * 10 system clocks, 5 clocks CS lead, 3 clocks to observe release.
    for seed in range(16):
        start = 4 + seed
        end_a, end_b = start+248, start+498
        addr_a, addr_b = seed & 1, (seed >> 1) & 1
        for case in ("overlap", "simultaneous", "missing", "duplicate", "wrong",
                     "order", "late"):
            issue_b = 0 if case in ("simultaneous", "order") else 50+seed
            da = end_a-1 if case == "late" else end_a
            db = end_b
            await trial.plan(descriptor(0, da, addr=addr_a),
                             descriptor(issue_b, db, addr=addr_b), policy=5)
            await trial.start()
            await trial.until(start)
            pkt_a, pkt_b = [0xA6, addr_a, 0], [0xA6, addr_b, 0]
            if case == "order":
                await trial.frame(1, pkt_b)
                expected = ORDER, 2, end_a
            else:
                await trial.frame(0, pkt_a)
                if case == "missing":
                    expected = TIMEOUT, 2, db+1
                elif case == "late":
                    expected = TIMEOUT, 1, da+1
                elif case == "duplicate":
                    await trial.frame(0, pkt_a)
                    expected = DUPLICATE, 1, end_b
                elif case == "wrong":
                    bad = [0xA7, addr_b, 0] if seed % 2 else [0xA6, addr_b^1, 0]
                    await trial.frame(1, bad)
                    expected = WRONG, 2, end_b
                else:
                    await trial.frame(1, pkt_b)
                    expected = PASS, 0, db+1
            await trial.until(max(trial.t, db+1))
            record = await trial.result()
            assert record[:3] == expected, (case, seed, record, expected)
            if case == "wrong":
                assert record[3:5] == tuple(bad[:2])
            if case in ("overlap", "simultaneous"):
                issued = [(0, 3)] if issue_b == 0 else [(0, 1), (issue_b, 3)]
                assert trial.notifications == issued + [(end_a, 2), (end_b, 0)]
                assert record[5:] == (1, 1)


@cocotb.test()
async def change_rules_replay_identical_wire_trace(dut):
    trial = await bench(dut)
    # Wire trace B, B, A; same timing and content for every run.
    for quota, order, check_cmd, expected in [
        (2, 2, False, (PASS, 0, 801)), (1, 2, False, (DUPLICATE, 2, 502)),
        (2, 1, False, (ORDER, 2, 252)), (2, 2, True, (WRONG, 2, 252))
    ]:
        await trial.plan(descriptor(0, 800), descriptor(0, 700, cmd=0x91, quota=quota,
                         checks=0x18 if check_cmd else 0x10), policy=order)
        await trial.start()
        await trial.until(4)
        for sensor in (1, 1, 0):
            await trial.frame(sensor, [0xA6, 0, 0])
        await trial.until(801)
        assert (await trial.result())[:3] == expected


@cocotb.test()
async def invalid_capture_and_plan(dut):
    trial = await bench(dut)
    await trial.plan(descriptor(0, 600), descriptor(0, 600))
    for nbits in (8, 17, 23):
        await trial.start()
        await trial.until(3)
        await trial.frame(0, [0xA6, 0, 0], nbits)
        assert (await trial.result())[:3] == (UNKNOWN, 1, 3+8+10*nbits)
    await trial.start()
    trial.p.inputs &= ~0x12  # both chip selects simultaneously active
    await trial.tick(4)
    assert (await trial.result())[:2] == (UNKNOWN, 3)
    trial.p.inputs |= 0x12
    await trial.tick(5)
    await trial.plan(descriptor(8, 7), descriptor(0, 600))
    await trial.start()
    assert (await trial.result())[:3] == (UNKNOWN, 0, 0)

    await trial.plan(descriptor(0, 20), descriptor(7, 20))
    await trial.start()
    await trial.until(21)
    assert (await trial.result())[:3] == (TIMEOUT, 3, 21)

    await trial.plan(descriptor(0, 600), descriptor(0, 600))
    await trial.start()
    await trial.until(5)
    await trial.frame(0, [0xA6, 0, 0])
    await trial.p.write(0x33)  # abort idle, without blaming the previous CS
    assert (await trial.result())[:3] == (UNKNOWN, 0, 257)


@cocotb.test()
async def reverse_single_source_and_latched_result(dut):
    trial = await bench(dut)
    # B notifies first. A arrives during B's service. B's quota is two.
    await trial.plan(descriptor(100, 800), descriptor(2, 600, quota=2), policy=6)
    await trial.start()
    await trial.until(5)
    for src in (1, 1, 0):
        await trial.frame(src, [0xA6, 0, 0])
    await trial.until(801)
    assert (await trial.result()) == (PASS, 0, 801, 0, 0, 1, 2)
    assert trial.notifications == [(2, 2), (100, 3), (503, 1), (753, 0)]

    # Keep watching after success until the observation window closes.
    await trial.plan(descriptor(0, 40, enabled=False), descriptor(0, 600))
    await trial.start()
    await trial.until(5)
    await trial.frame(1, [0xA6, 0, 0])
    await trial.frame(1, [0xA6, 0, 0])
    witness = await trial.result()
    assert witness == (DUPLICATE, 2, 503, 0xA6, 0, 0, 1)
    await trial.frame(0, [0x33, 2, 0])
    assert await trial.result() == witness

    # A frame selected before notification cannot satisfy the event by ending later.
    await trial.plan(descriptor(100, 600), descriptor(0, 600, enabled=False))
    await trial.start()
    await trial.until(5)
    await trial.frame(0, [0xA6, 0, 0])
    assert (await trial.result())[:3] == (ORDER, 1, 253)


@cocotb.test()
async def loaded_spi_timing_with_trial_active(dut):
    p = Pins(dut)
    await p.reset()
    await install(p, STREAM)
    await configure(p, 0, 0xED, 0x48)
    await configure(p, 2, 0xD5, 0x11)
    for mode in range(4):
        await p.write(0x10+mode)
        await p.write(0x30)
        trial = Trial(p)
        # Two-byte M6 stream profile, same wire address, separate sensor banks.
        await trial.plan(descriptor(0, 500, cmd=0, addr=0, length=2),
                         descriptor(0, 500, cmd=0, addr=0, length=2))
        delays = []
        for phase in sorted({1000*i for i in range(20)} | {9900, 10100}):
            await trial.start()
            await trial.tick(2)
            assert p.uo & 7 == 7
            for s, response in [(0, 0xA5), (1, 0xC4)]:
                # History persists through trials, independent in each bank.
                if phase == 0 and mode == 0:
                    response = (0xED, 0xD5)[s]
                ts, _ = await transaction(p, mode, [0, 0], [0, response],
                                          phase, payload_start=8, sensor=s)
                delays.extend(ts)
            await p.tick(200)
            assert (await trial.result())[:3] == (PASS, 0, 501)
        assert max(delays) <= 60000
        dut._log.info("active trial mode %d: %d transitions, launch %.3f..%.3f ns; setup %.3f ns",
                      mode, len(delays), min(delays)/1000, max(delays)/1000, 100-max(delays)/1000)
        await p.write(0x31)
