"""Experiment C. Fixed synthetic peers, pin oracles, nominal RTL time."""
import csv
import os
from pathlib import Path

import cocotb
from cocotb.triggers import ValueChange

from pins import Pins
from test_byte_program import STREAM, install
from test_feedback import field, launch, profile, record, rule
from test_spi import now, transaction
from test_transactions import STREAM_FIELDS, REQUEST, REPLY, setup, tagged_plan
from test_trials import ORDER, PASS, TIMEOUT, WRONG, descriptor


NAMES = {PASS: "PASS", TIMEOUT: "TIMEOUT", WRONG: "WRONG", ORDER: "ORDER"}
PHASE_PS = (0, 9900, 10100, 19000)
COUNTS = (2, 4, 6, 8)
ISSUES = (0, 1, 160, 322, 331, 332, 333)
DEADLINES = (481, 482, 483)
SMOKE = os.environ.get("BOUNDARY_SMOKE") == "1"


def observed(rec):
    return dict(verdict=NAMES[rec[0]], mask=rec[1], terminal_tick=rec[2],
                count_a=rec[5], count_b=rec[6])


def edge_stats(edges):
    return dict(toggle_count=len(edges), launch_to_miso_ps=" ".join(map(str, edges)),
                max_l1_ps=max(edges), min_setup_ps=100000 - max(edges))


async def framing(p, rows):
    groups = [((3,), 0), ((2, 1), 100), ((2, 1), 500),
              ((1, 1, 1), 100), ((1, 1, 1), 500)]
    for windows, high_ns in groups[:2] if SMOKE else groups:
        await p.reset()
        trial = await setup(p, STREAM, STREAM_FIELDS)
        await tagged_plan(trial)
        await trial.start()
        await trial.until(4)
        pos = 0
        edges = []
        for idx, width in enumerate(windows):
            # Frozen transaction() gives exactly 100 ns high at phase zero.
            if idx and high_ns > 100:
                await p.tick((high_ns - 100) // 20)
            stop = pos + 2 * width
            launches, _ = await transaction(p, 0, REQUEST[pos:stop], REPLY[pos:stop],
                                           payload_start=8)
            edges.extend(launches)
            pos = stop
        await p.tick(200)
        rec = await trial.result()
        assert (rec[0], rec[5:]) == (PASS, (2, 1)), (windows, high_ns, rec)
        rows.append(dict(family="framing", windows="+".join(map(str, windows)), gap_ns=high_ns,
                         image=STREAM.hex(), mode=0, phase_ps=0, **observed(rec), **edge_stats(edges)))


async def overlap(p, rows):
    await p.reset()
    trial = await setup(p, STREAM, STREAM_FIELDS)
    for issue in (332, 333) if SMOKE else ISSUES:
        for deadline in DEADLINES:
            await trial.plan(descriptor(0, 322, quota=2, length=2, checks=0),
                             descriptor(issue, deadline, length=2, checks=0), policy=9)
            await field(p, 0x47, 1)
            await field(p, 0x4f, 2)
            await trial.start()
            await trial.until(4)
            await trial.frame(0, REQUEST)
            rec = await trial.result()
            expected = TIMEOUT if deadline < 482 else ORDER if issue > 332 else PASS
            terminal = deadline + 1 if expected != ORDER else 482
            assert (rec[0], rec[1], rec[2], rec[5:]) == (
                expected, 0 if expected == PASS else 2, terminal, (2, int(expected == PASS))
            ), (issue, deadline, rec)
            assert next(t for t, level in trial.notifications if level & 2) == issue
            rows.append(dict(family="overlap", windows="3", mode=0, issue_b=issue,
                             deadline_b=deadline, expected=NAMES[expected],
                             irq_tick_mask=" ".join(f"{t}/{level}" for t, level in trial.notifications),
                             **observed(rec)))


def chain(n):
    # Matching the state-specific byte restarts recognition. Each mismatch
    # advances one slot. Reaching the last slot schedules an alternating reply.
    image = bytearray()
    for state in range(n - 1):
        image.extend((0x10, 0xC0 + state))
    return bytes(image) + bytes((0x50, 0xA5))


async def complexity(p, rows):
    for size in (2, 8) if SMOKE else COUNTS:
        for mode in (0,) if SMOKE else range(4):
            await p.reset()
            image = chain(size)
            await install(p, image)
            await p.write(0x10 + mode)
            for phase in (0,) if SMOKE else PHASE_PS:
                # Restart at the final comparison; then traverse every state.
                # A missing taken transition would put A5 at a different byte.
                prefix = [0] * (size - 2) + [0xC0 + size - 2]
                for path, start in (("fallthrough", []), ("restart", prefix)):
                    tx = start + [0] * (size + 1)
                    rx = [0] * (len(tx) - 1) + [0xA5]
                    edges, cs = await transaction(p, mode, tx, rx, phase,
                                                  payload_start=8 * (len(tx) - 1))
                    assert edges
                    rows.append(dict(family="complexity", image=image.hex(), rules=size,
                                     compares=size-1, mode=mode, phase_ps=phase, path=path,
                                     mosi=bytes(tx).hex(), miso=bytes(rx).hex(), cs_to_oe_ps=cs,
                                     first_payload_l1_ps=edges[0], verdict="PASS", **edge_stats(edges)))
    # Deliberately send all 18 bytes through the real loader. Its first 16
    # bytes are eight comparisons; falling off state 7 cannot reach a literal.
    await p.reset()
    image = chain(9)
    await install(p, image)
    tx = [0] * 10
    await transaction(p, 0, tx, [0] * len(tx))
    rows.append(dict(family="capacity", rules=9, compares=8, mode=0, phase_ps=0,
                     image=image.hex(), mosi=bytes(tx).hex(), miso=bytes(len(tx)).hex(),
                     expected="A5 on byte 10", verdict="UNREPRESENTABLE"))


async def wait_verdict(p, code):
    while (p.uo >> 4) != code:
        await ValueChange(p.dut.uo_out)
    return now()


async def latencies(p, rows):
    await p.reset()
    trial = await setup(p, STREAM, STREAM_FIELDS)
    await tagged_plan(trial)
    await trial.start()
    p.dut.ui_in.value = 0
    await trial.until(4)
    mismatch = cocotb.start_soon(wait_verdict(p, WRONG))
    # Trial.frame drives leading sample edge i at start + 100 ns + 200 ns*i.
    last_sample = now() + 100000 + 15 * 200000
    await trial.frame(0, [1, 0x37])
    assert (p.uo >> 4) == WRONG
    verdict = await mismatch
    rec = await trial.result()
    assert (rec[0], rec[1]) == (WRONG, 1)
    rows.append(dict(family="checking", path="mismatch_closing_sample", mode=0,
                     start_ps=last_sample, end_ps=verdict, latency_ps=verdict-last_sample,
                     **observed(rec)))

    # Both profiles use the same absolute deadline. Profile 1 makes a
    # distinct effective P5 selection and changes the A event to tick zero.
    await p.reset()
    trial = await setup(p, STREAM, STREAM_FIELDS)
    await trial.plan(descriptor(0, 12, length=2, checks=0),
                     descriptor(0, 12, enabled=False), policy=0)
    await profile(p, 0, 4, 0, 0)
    await profile(p, 1, 0, 0, 1)
    await field(p, 0x51, 1)
    await rule(p, 0, TIMEOUT, 1, source=1)
    await launch(trial)
    p.dut.ui_in.value = 0
    await trial.until(12)
    last_allowed = now() - 10000  # Pins.tick returns half a clock after posedge.
    assert p.uo >> 4 == 0
    await trial.tick(1)
    assert p.uo >> 4 == TIMEOUT
    verdict = now() - 10000
    rows.append(dict(family="checking", path="last_allowed_deadline_edge", mode=0,
                     start_ps=last_allowed, end_ps=verdict, latency_ps=verdict-last_allowed,
                     verdict="TIMEOUT"))
    p.dut.ui_in.value = 0xC0
    await trial.tick(1)
    assert p.uo >> 4 == 9 and int(p.dut.user_project.trials.feedback.profile.value) == 1
    rows.append(dict(family="feedback", path="profile_effective_and_archive", start_ps=verdict,
                     end_ps=now()-10000, latency_ps=now()-10000-verdict))
    p.dut.ui_in.value = 0
    await trial.tick(1)
    assert p.uo >> 4 == 0 and p.uo & 3 == 0
    rows.append(dict(family="feedback", path="next_trial_accepted", start_ps=verdict,
                     end_ps=now()-10000, latency_ps=now()-10000-verdict))
    await trial.tick(1)
    assert p.uo & 3 == 1
    rows.append(dict(family="feedback", path="next_a_notification", start_ps=verdict,
                     end_ps=now()-10000, latency_ps=now()-10000-verdict))
    await trial.tick(20)
    assert (await record(p, 0))["target"] == 1 and (await record(p, 1))["applied"] == 1


@cocotb.test()
async def boundary_matrix(dut):
    rows = []
    p = Pins(dut)
    await framing(p, rows)
    await overlap(p, rows)
    await complexity(p, rows)
    await latencies(p, rows)
    with (Path(os.environ["BOUNDARY_OUTPUT"]) / "cases.csv").open("w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(dict.fromkeys(k for row in rows for k in row)))
        writer.writeheader()
        writer.writerows(rows)
