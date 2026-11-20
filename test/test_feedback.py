"""Autonomous campaigns observed through DRDY, MISO and host readback only."""
import cocotb
from cocotb.triggers import Timer

from pins import Pins
from test_byte_program import STREAM, install
from test_spi import configure, setup_spi, transaction
from test_trials import PASS, TIMEOUT, DUPLICATE, WRONG, UNKNOWN, Trial, bench, descriptor


async def field(p, selector, value):
    await p.write(selector)
    await p.write(value, mode=0)


async def profile(p, n, a, b, status):
    for offset, value in enumerate((a, b, status)):
        await field(p, 0x70 + 4*n + offset, value)


async def rule(p, n, verdict, target, source=None, prev=0, older=0, stop=False):
    pred = 0x20 | verdict
    if source is not None:
        pred |= 0x40 | (source << 3)
    for offset, value in enumerate((pred, prev | (older << 3), target | (int(stop) << 2))):
        await field(p, 0x60 + 4*n + offset, value)


async def page(p, address):
    p.dut.ui_in.value = address
    await Timer(1, unit="ps")
    return p.uo >> 4


async def record(p, n):
    v = [await page(p, 0x80 + 16*n + i) for i in range(16)]
    assert v[0] & 8
    return dict(verdict=v[0] & 7, source=v[1], tick=sum(v[2+i] << (4*i) for i in range(4)),
                settings=(v[6]+16*v[7], v[8]+16*v[9], v[10]),
                prev=v[11], older=v[12], applied=v[13] >> 2, target=v[13] & 3,
                matched=bool(v[14] & 4), rule=v[14] & 3, continued=bool(v[14] & 8),
                stop=bool(v[15]))


async def launch(trial):
    # The only host write in the execution phase. Keep strobe and ui_in fixed.
    await trial.p.write(0x34)
    assert trial.p.uo & 12 == 4
    await trial.p.tick()
    trial.t, trial.last, trial.notifications = -1, 0, []


async def service(trial, base, at, sensor, cmd=0xA6):
    await trial.until(base+at)
    await trial.frame(sensor, [cmd, 0, 0])


@cocotb.test()
async def autonomous_dual_sensor_branches(dut):
    trial = await bench(dut)
    p = trial.p
    settings = [(2, 80, 0), (4, 32, 0), (4, 32, 2), (70, 8, 1)]
    await trial.plan(descriptor(0, 650), descriptor(0, 700))
    for i, params in enumerate(settings):
        await profile(p, i, *params)
    for i, (v, src) in enumerate(((PASS, 0), (TIMEOUT, 2), (DUPLICATE, 1))):
        await rule(p, i, v, i+1, source=src)
    await field(p, 0x51, 3)
    await launch(trial)
    base = 0
    expected = [(PASS, 0, 701), (TIMEOUT, 2, 701), (DUPLICATE, 1, 508), (PASS, 0, 701)]
    for n, (_, _, end) in enumerate(expected):
        if n == 3:
            await service(trial, base, 10, 1)
            await service(trial, base, 260, 0)
        else:
            await service(trial, base, 10, 0)
            if n != 1:
                await service(trial, base, 260, int(n == 0))
        await trial.until(base+end+2)
        for src, issue in enumerate(settings[n][:2]):
            assert any(t == base+issue and level & (1 << src)
                       for t, level in trial.notifications)
        base += end+3
    assert p.uo & 15 == 8 and await page(p, 0xc0) == 4
    for n, observation in enumerate(expected):
        rec = await record(p, n)
        assert (rec['verdict'], rec['source'], rec['tick']) == observation
        assert rec['settings'] == settings[n] and rec['applied'] == n
        assert (rec['rule'], rec['target']) == [(0,1), (1,2), (2,3), (0,1)][n]
        assert rec['matched'] and rec['continued'] == (n < 3) and not rec['stop']
        assert rec['prev'] == (expected[n-1][0] if n >= 1 else 0)
        assert rec['older'] == (expected[n-2][0] if n >= 2 else 0)


@cocotb.test()
async def both_prior_verdicts_select_next_trial(dut):
    trial = await bench(dut)
    p = trial.p
    await trial.plan(descriptor(0, 300), descriptor(0, 0, enabled=False))
    await field(p, 0x51, 3)
    for i, (prev, older) in enumerate(((TIMEOUT, PASS), (TIMEOUT, WRONG), (WRONG, PASS))):
        await rule(p, i, PASS, i+1, prev=prev, older=older)
        await profile(p, i+1, 8*(i+1), 0, 0)
    await rule(p, 3, 0, 0)  # lower-priority fallback
    for first, second, target in [(PASS,TIMEOUT,1), (WRONG,TIMEOUT,2), (PASS,WRONG,3)]:
        await launch(trial)
        base = 0
        for v in (first, second, PASS):
            if v != TIMEOUT:
                await service(trial, base, 10, 0, 0 if v == WRONG else 0xA6)
            end = 258 if v == WRONG else 301
            await trial.until(base+end+2)
            base += end+3
        await trial.until(base+302)
        assert (base+8*target, 1) in trial.notifications
        rec = await record(p, 2)
        assert (rec['verdict'], rec['prev'], rec['older'], rec['target']) == (
            PASS, second, first, target)
        assert (await record(p, 3))['applied'] == target


@cocotb.test()
async def identical_master_trace_different_policy(dut):
    trial = await bench(dut)
    p = trial.p
    await trial.plan(descriptor(0, 600), descriptor(0, 600))
    for i, params in enumerate(((0,0,0), (3,9,0), (10,5,2))):
        await profile(p, i, *params)
    await field(p, 0x51, 1)
    await rule(p, 0, PASS, 1)
    for destination in (1, 2):
        if destination == 2:
            await field(p, 0x62, 2)  # Only this policy byte changes.
        await launch(trial)
        for base in (0, 604):
            await service(trial, base, 20, 0)
            await service(trial, base, 270, 1)
        await trial.until(1206)
        a, b = await record(p, 0), await record(p, 1)
        assert a['verdict'] == b['verdict'] == PASS
        assert a['target'] == b['applied'] == destination
        rises = [(607,1), (613,3)] if destination == 1 else [(609,2), (614,3)]
        assert all(edge in trial.notifications for edge in rises)


@cocotb.test()
async def campaign_bounds_invalid_and_retention(dut):
    trial = await bench(dut)
    p = trial.p
    await trial.plan(descriptor(0, 10), descriptor(0, 0, enabled=False))
    await profile(p, 3, 255, 73, 3)  # start rejected by P4 immediately
    await field(p, 0x51, 15)  # initial profile 3, bound four
    await rule(p, 0, UNKNOWN, 0, prev=7, older=7)
    await rule(p, 1, TIMEOUT, 2, source=1, stop=True)
    await launch(trial)
    await p.tick(40)
    assert p.uo & 15 == 8 and await page(p, 0xc0) == 2
    a, b = await record(p, 0), await record(p, 1)
    assert (a['verdict'], a['tick'], a['continued']) == (UNKNOWN, 0, True)
    assert (b['verdict'], b['tick'], b['stop'], b['continued']) == (TIMEOUT, 11, True, False)
    await profile(p, 3, 0, 0, 0)
    assert (await record(p, 0))['settings'] == (255, 73, 3)
    assert await page(p, 0xa0) == 0
    await field(p, 0x64, 0)  # disable the timeout rule
    await launch(trial)
    await p.tick(40)
    assert await page(p, 0xc0) == 1 and await page(p, 0x90) == 0
    assert not (await record(p, 0))['matched']
    p.peer_mask = 0x0b
    await p.reset()


@cocotb.test()
async def timeout_during_selected_spi_frame(dut):
    p = Pins(dut)
    await p.reset()
    await setup_spi(p)
    await configure(p, 0, 0x55, 0)
    await p.write(0x30)
    trial = Trial(p)
    await trial.plan(descriptor(0, 30), descriptor(0, 0, enabled=False))
    await profile(p, 1, 0, 0, 1)
    await rule(p, 0, TIMEOUT, 0, source=1)
    await field(p, 0x51, 5)  # start in profile 1, two trials
    await launch(trial)
    await trial.tick(1)
    # Attempts to edit a profile, restart, or leave during the run are ignored.
    await field(p, 0x76, 0)
    await p.write(0x34)
    await p.write(0x31)
    # The first deadline expires within the command byte; the next trial
    # starts with CS still low. MISO must finish using the CS-time status.
    await transaction(p, 0, [0xa6, 0, 0], [0, 0, 0xd5])
    assert p.uo & 15 == 8 and await page(p, 0xc0) == 2
    a, b = await record(p, 0), await record(p, 1)
    assert (a['verdict'], a['source'], a['tick'], a['settings']) == (TIMEOUT, 1, 31, (0,0,1))
    assert (b['verdict'], b['source'], b['tick'], b['matched']) == (UNKNOWN, 1, 0, False)
    await transaction(p, 0, [0xa6, 0, 0], [0, 0, 0x55])


@cocotb.test()
async def active_feedback_spi_latency(dut):
    p = Pins(dut)
    await p.reset()
    await install(p, STREAM)
    await configure(p, 0, 0x55, 0)
    await configure(p, 2, 0x55, 0)
    for mode in range(4):
        await p.write(0x10+mode)
        await p.write(0x30)
        trial = Trial(p)
        await trial.plan(descriptor(0, 500, cmd=0, length=2),
                         descriptor(0, 500, cmd=0, length=2))
        await profile(p, 1, 1, 2, 2)  # only CS_B inverts status bit 7
        await rule(p, 0, TIMEOUT, 1, source=3)
        await field(p, 0x51, 1)
        delays, enables = [], []
        for phase in sorted({1000*i for i in range(20)} | {9900,10100}):
            await launch(trial)
            await trial.until(506)
            assert p.uo & 15 == 7
            for sensor, value in enumerate((0x55, 0xd5)):
                ts, oe = await transaction(p, mode, [0,0], [0,value], phase,
                                           payload_start=8, sensor=sensor)
                delays.extend(ts)
                enables.append(oe)
            await p.tick(210)
            assert (await record(p, 1))['verdict'] == PASS
        assert max(delays) <= 60000 and max(enables) <= 60000
        dut._log.info("P5 mode %d: %d transitions, launch %.3f..%.3f ns, setup %.3f ns, "
                      "CS to OE %.3f..%.3f ns", mode, len(delays), min(delays)/1000,
                      max(delays)/1000, 100-max(delays)/1000, min(enables)/1000, max(enables)/1000)
        await p.write(0x31)
