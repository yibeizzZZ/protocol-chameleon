"""Supplementary persistent-history probe. Run with the experiment C environment."""
import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import cocotb
from cocotb.triggers import ValueChange

from run_boundary import FREEZE, HERE, ROOT


SOURCE_NAMES = ("grant_one", "grant_two")
PHASE_PS = 10100


async def poll(p, mode, expected):
    from test_spi import transaction
    samples = []
    sample_level = str(1 ^ (mode >> 1) ^ (mode & 1))

    async def observe():
        # Decode physical CS_B and SCLK transitions independently of the
        # peer's expected transaction; record the resolved MISO level.
        last_clock = str(p.dut.pads.value)[2]
        while True:
            await ValueChange(p.dut.pads)
            levels = str(p.dut.pads.value)
            clock = levels[2]
            if levels[6] == "0" and clock == sample_level and clock != last_clock:
                samples.append(levels[0])
            last_clock = clock

    monitor = cocotb.start_soon(observe())
    try:
        edges, _ = await transaction(p, mode, [0xB2, 0xB2, 0, 0, 0],
                                     [0, 0, 0, 0, expected], PHASE_PS,
                                     sensor=1, payload_start=32)
    finally:
        monitor.cancel()
    assert len(samples) == 40
    return int("".join(samples[-8:]), 2), edges


@cocotb.test()
async def persistent_votes(dut):
    from pins import Pins
    from test_spi import transaction
    rows = []
    p = Pins(dut)
    for name, threshold in zip(SOURCE_NAMES, (1, 2)):
        artifact = json.loads((Path(__file__).parent / f"{name}.json").read_text())
        for mode in range(4):
            await p.reset()
            await p.enter()
            await p.load(artifact["image"])
            for selector, value in artifact["settings"]:
                await p.write(selector)
                await p.write(value, mode=0)
            await p.write(artifact["run"])
            p.inputs |= 0x10
            p.peer_mask |= 0x70
            await p.tick(5)
            await p.write(0x10 + mode)
            await p.write(0x30)  # physical A/B selects
            for count in range(3):
                for _ in range(count):
                    await transaction(p, mode, [0xA1, 1], [0, 0], PHASE_PS)
                expected = 0xA5 if count >= threshold else 0
                reply, edges = await poll(p, mode, expected)
                after, _ = await poll(p, mode, 0)
                assert (reply, after) == (expected, 0)
                rows.append(dict(model=name, mode=mode, phase_ps=PHASE_PS, a_votes=count,
                                 image=bytes(artifact["image"]).hex(),
                                 loaded_rules=len(artifact["image"]) // 2,
                                 shared_register_bits=4, predicate_mask=hex((1 << threshold)-1),
                                 relevant_history_bits=threshold, expected=f"{expected:02x}",
                                 b_reply=f"{reply:02x}", repeated_b_reply=f"{after:02x}",
                                 toggles=len(edges), launch_to_miso_ps=" ".join(map(str, edges)),
                                 max_l1_ps=max(edges) if edges else "",
                                 min_setup_ps=100000-max(edges) if edges else ""))
    with Path(os.environ["HISTORY_OUTPUT"]).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=HERE / "results" / "boundary" / "history.csv")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="forg-supplement-history-") as name:
        temp = Path(name)
        files = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", FREEZE, "src"],
                                        cwd=ROOT, text=True).splitlines()
        files += ["test/Makefile", "test/tb.v", "test/pins.py", "test/test_spi.py", "p1.py"]
        files.append("examples/i2c_write.py")  # imported by the frozen assembler
        files += [f"examples/{source}.p1" for source in SOURCE_NAMES]
        for fname in files:
            path = temp / fname
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(subprocess.check_output(["git", "show", f"{FREEZE}:{fname}"], cwd=ROOT))
        tests = temp / "test"
        for source in SOURCE_NAMES:
            artifact = subprocess.check_output([sys.executable, "p1.py", f"examples/{source}.p1"],
                                               cwd=temp)
            (tests / f"{source}.json").write_bytes(artifact)
        for script in ("history_probe.py", "run_boundary.py"):
            (tests / script).write_bytes((HERE / script).read_bytes())
        env = dict(os.environ, HISTORY_OUTPUT=str(temp / "history.csv"), COCOTB_RANDOM_SEED="452")
        subprocess.run(["make", "sim", "SIM=icarus", "COCOTB_TEST_MODULES=history_probe"],
                       cwd=tests, env=env, check=True)
        subprocess.run([sys.executable, "-m", "cocotb_tools.check_results", "results.xml"],
                       cwd=tests, check=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes((temp / "history.csv").read_bytes())


if __name__ == "__main__":
    main()
