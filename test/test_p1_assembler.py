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
        program = compile_source("I2C_WRITE 0x52 0xA5 400")
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

    def test_all_spi_rules_and_flags(self):
        p = compile_source("""SPI
            first: IF_BYTE 0xa6 reply
            QUIET | NONE
            STATUS_ADDR first | TAG ADDR
            STATUS_REG 3 first | MOSI_DATA
            COMMIT first | END
            reply: REPLY 255 first | CMD MISO_DATA
            IF_SEEN 2 first
            NEXT first
        """)
        self.assertEqual(p["run"], 4)
        self.assertEqual(p["image"], [21, 166, 0, 0, 32, 0, 48, 3, 64, 0, 80, 255, 96, 2, 112, 0])
        self.assertEqual(p["settings"], [[17, 0], [18, 20], [19, 2], [20, 32], [21, 11]])

    def test_timed_limits_labels_and_padding(self):
        timed = compile_source("TIMED 2 256\nCHECK 0 end\nSLOT 3\nend: CHECK 1 end")
        self.assertEqual(timed, {"image": [28], "run": 5,
                                 "settings": [[32, 1], [33, 255], [34, 64], [35, 66], [36, 2]]})
        self.assertEqual(len(compile_source("TIMED 2 2\n" + "SLOT 3\n"*64)["image"]), 16)
        for source in ("TIMED 1 256\nSLOT 0", "TIMED 2 2\nSLOT 4", "TIMED 2 2\n"+"SLOT 0\n"*65,
                       "TIMED 2 2\nCHECK 0 0\nCHECK 0 1", "TIMED 2 2\n"+"CHECK 0 0\n"*3,
                       "SPI\n"+"QUIET\n"*9, "SPI\nNEXT somewhere", "SPI\nQUIET |",
                       "SPI\nQUIET | MOSI_DATA MISO_DATA", "SPI\nSTATUS_REG 4 0"):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, "line "):
                compile_source(source)

    def test_utf8_bom_and_decimal_literals(self):
        p = compile_source("\ufeffDELAY 08\nDIR 0b10\nDRIVE 0x0A")
        self.assertEqual(p["image"], [0x58, 0x22, 0x1A])

    def test_numeric_timed_branches_can_reach_padding_or_stop(self):
        for slot in (1, 4, 63):
            with self.subTest(slot=slot):
                program = compile_source(f"TIMED 2 2\nCHECK 0 {slot}")
                self.assertEqual(program["settings"][-1], [0x24, slot])
        with self.assertRaisesRegex(ValueError, "line 2"):
            compile_source("TIMED 2 2\nCHECK 0 64")

    def test_model_instructions(self):
        result = compile_source("SPI\nloop: IF_STATE 3 1 loop\nSET_STATE 12 loop\n"
                                "SHIFT_BIT loop\nIF_STATE_PARAM 7 loop")
        self.assertEqual(result["image"], [0x80, 0x31, 0x90, 12, 0xa0, 0, 0xb0, 7])
        for op in ("IF_STATE 2 1 0", "IF_STATE 16 1 0", "SHIFT_BIT 1 0",
                   "SET_STATE 16 0", "IF_STATE_PARAM 3 nowhere"):
            with self.subTest(op=op), self.assertRaises(ValueError):
                compile_source("SPI\n" + op)

    def test_byte_cells(self):
        result = compile_source("SPI\nSTORE_BYTE 1 1\nREAD_BYTE 0 2\nCLEAR_BYTE 1 0")
        self.assertEqual(result["image"], [0xc1, 1, 0xd2, 0, 0xe0, 1])
        with self.assertRaises(ValueError):
            compile_source("SPI\nREAD_BYTE 2 0")
