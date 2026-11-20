# Programming the P1 pin engines

Run `python3 p1.py examples/shared_wire_register.p1` or `python3 p1.py examples/i2c_write.p1` from the repository root. The compiler needs only Python 3. The JSON result contains integer `image` bytes, ordered `settings` pairs and the `run` control byte. To apply it from UART mode, enter the GPIO loader with control writes `00 83`, clear with `01`, write the image as data, send each selector as control and its value as data, then send `run` as control. [Pin strobes and ownership](info.md#enter-load-run-stop)

## GPIO assembly

Each instruction occupies one of 16 bytes. Use one instruction per line, whitespace-separated operands, and `#` for a comment. Branches accept a loaded instruction address or a case-sensitive label such as `reply:`. A label may share a line with an instruction. Mnemonics and pin names are case-insensitive. Numbers accept decimal, `0x` hex and `0b` binary.

| Assembly | Meaning |
| --- | --- |
| `HALT` | Stop and release all GPIOs. |
| `DRIVE mask`, `DIR mask` | Set output levels or output enables. Bit 0 controls P0. |
| `SAMPLE P1`, `DELAY 3` | Sample a synchronized pin or wait the specified additional clocks. |
| `JUMP reply`, `JUMP_ONE reply` | Branch unconditionally or when the most recent sample was one. |
| `RISE_SAMPLE P0 P1`, `FALL_SAMPLE P0 P1` | Wait for the edge on the first pin and sample the second. |

## I2C controller write

A source containing `I2C_WRITE address data rate_khz` uses the existing timed-GPIO image builder. Supply a seven-bit address, one data byte, and 100 or 400 kHz at a 50 MHz system clock. [Wire contract and readback](info.md#write-one-byte)
