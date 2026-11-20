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
