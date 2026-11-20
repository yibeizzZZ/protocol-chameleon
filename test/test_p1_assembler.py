"""Host-side checks for source programs targeting the frozen P1 loader."""

from pathlib import Path
import unittest

from p1 import compile_source


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class AssemblerTests(unittest.TestCase):
    def test_all_gpio_operations_and_labels(self):
        source = """
            start: HALT
            DRIVE 0xf
            DIR 2
            SAMPLE P3
            DELAY 15
            JUMP_ONE end
            JUMP start
            RISE_SAMPLE P1 P2
            end: FALL_SAMPLE P3 P0
        """
        self.assertEqual(compile_source(source), {
            "image": [0, 31, 34, 51, 95, 104, 112, 134, 156], "settings": [], "run": 2,
        })

    def test_existing_example_matches_public_image(self):
        rows = (EXAMPLES / "shared_wire_register.hex").read_text().splitlines()
        expected = bytes.fromhex(" ".join(row.partition("//")[0] for row in rows))
        source = (EXAMPLES / "shared_wire_register.p1").read_text()
        self.assertEqual(bytes(compile_source(source)["image"]), expected)

    def test_i2c_matches_documented_loader_sequence(self):
        source = (EXAMPLES / "i2c_write.p1").read_text()
        program = compile_source(source)
        self.assertEqual(program["run"], 5)
        self.assertEqual(bytes(program["image"]).hex(), "e0d11eed7bb4ef51b447fb1eed51b400")
        self.assertEqual(program["settings"], [[32, 32], [33, 58], [34, 93], [35, 120], [36, 57]])

    def test_bounds_and_diagnostics(self):
        self.assertEqual(len(compile_source("HALT\n" * 16)["image"]), 16)
        for source in ("DRIVE 16", "SAMPLE P4", "JUMP missing", "JUMP 1",
                       "JUMP end\nend:", "a: HALT\na: HALT", "HALT 1", "FLY",
                       "RISE_SAMPLE P0", "HALT\n" * 17, "I2C_WRITE 0x80 0 400"):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "line "):
                compile_source(source)
