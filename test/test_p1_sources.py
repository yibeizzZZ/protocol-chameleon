"""Build editable sources with the public CLI and test its output at the pins."""

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import cocotb

from pins import Pins
from test_i2c_write import target
from test_spi import configure
from test_transactions import tagged_plan, run_wire
from test_trials import Trial, PASS
from test_shared_wire_register import run_exchanges


ROOT = Path(__file__).resolve().parents[1]


async def load_source(pins, path):
    built = subprocess.run([sys.executable, str(ROOT / "p1.py"), str(path)],
                           capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    artifact = json.loads(built.stdout)
    await pins.load(artifact["image"])
    for selector, value in artifact["settings"]:
        await pins.write(selector)
        await pins.write(value, mode=0)
    return artifact["run"]


@cocotb.test()
async def assembled_register_on_pins(dut):
    pins = Pins(dut)
    await pins.reset()
    await pins.enter()
    run = await load_source(pins, ROOT / "examples/shared_wire_register.p1")
    for phase in (0, 9900, 10100):
        drives, releases = await run_exchanges(pins, phase, run_control=run)
        assert len(drives) == len(releases) == 9
        await pins.write(3)


@cocotb.test()
async def edited_i2c_source_on_pins(dut):
    source = ROOT / os.environ.get("P1_I2C_SOURCE", "examples/i2c_write.p1")
    address = int(os.environ.get("P1_EXPECT_ADDRESS", "0x52"), 0)
    expected = int(os.environ.get("P1_EXPECT_DATA", "0xA5"), 0)
    rate = int(os.environ.get("P1_EXPECT_RATE", "400"))
    assert rate in (100, 400)
    pins = Pins(dut)
    await pins.reset()
    await pins.enter()
    dut.bus_pullups.value = 1
    try:
        with TemporaryDirectory() as tmp:
            alternate = 0x3C if expected != 0x3C else 0xA5
            edited = Path(tmp) / "edited.p1"
            edited.write_text(f"I2C_WRITE {address} {alternate} {rate}\n", encoding="utf-8")
            for path, payload in ((source, expected), (edited, alternate)):
                run = await load_source(pins, path)
                actual, acks, history, _, _ = await target(
                    pins, address, True, rate, run_control=run)
                assert actual == [address << 1, payload], (actual, payload)
                assert acks == [0, 0] and history == 4
                dut._log.info("Target received address 0x%02X, data 0x%02X at %d kHz",
                              actual[0] >> 1, actual[1], rate)
    finally:
        dut.bus_pullups.value = 0


@cocotb.test()
async def programmed_open_drain_pulse(dut):
    pins = Pins(dut)
    await pins.reset()
    await pins.enter()
    run = await load_source(pins, ROOT / "examples/conditional_pulse.p1")
    pins.peer_mask |= 0x20
    for selection in (0, 1):
        pins.inputs = (pins.inputs & ~0x20) | (selection << 5)
        await pins.tick(4)
        await pins.write(run)
        trace = []
        for _ in range(24):
            await pins.tick()
            if not pins.running:
                break
            assert pins.out & pins.oe & 0xf0 == 0
            trace.append(pins.oe >> 4)
        assert not pins.running and pins.oe == 4
        assert trace == [0]*12 + ([1]*3 if selection == 0 else []) + [0]*6
        assert pins.uo >> 4 == 2 + selection


@cocotb.test()
async def assembled_spi_boundaries(dut):
    pins = Pins(dut)
    await pins.reset()
    await pins.enter()
    run = await load_source(pins, ROOT / "examples/spi_stream.p1")
    await pins.write(run)
    pins.inputs |= 0x10
    pins.peer_mask |= 0x70
    await pins.tick(5)
    await configure(pins, 1, 0x55, 0)
    await configure(pins, 2, 0xaa, 0)
    await pins.write(0x30)  # Open the independently configured trial checker.
    trial = Trial(pins)
    await tagged_plan(trial)
    record, _ = await run_wire(trial)
    assert record[0] == PASS and record[5:] == (2, 1), record
