# Programming the P1 pin engines

Run `python3 p1.py examples/shared_wire_register.p1` or `python3 p1.py examples/i2c_write.p1` from the repository root. The compiler uses the Python 3.9+ standard library. The JSON result contains integer `image` bytes, ordered `settings` pairs and the `run` control byte. To apply it from UART mode, enter the GPIO loader with control writes `00 83`, clear with `01`, write the image as data, send each selector as control and its value as data, then send `run` as control. [Pin strobes and ownership](info.md#enter-load-run-stop)

## GPIO assembly

Each instruction occupies one of 16 bytes. Use one instruction per line, whitespace-separated operands, and `#` for a comment. Branches accept a loaded instruction address or a case-sensitive label such as `reply:`. A label may share a line with an instruction. Mnemonics and pin names are case-insensitive. Numbers accept decimal, `0x` hex and `0b` binary.

| Assembly | Meaning |
| --- | --- |
| `HALT` | Stop and release all GPIOs. |
| `DRIVE mask`, `DIR mask` | Set output levels or output enables. Bit 0 controls P0. |
| `SAMPLE P1`, `DELAY 3` | Sample a synchronized pin or wait the specified additional clocks. |
| `JUMP reply`, `JUMP_ONE reply` | Branch unconditionally or when the most recent sample was one. |
| `RISE_SAMPLE P0 P1`, `FALL_SAMPLE P0 P1` | Wait for the edge on the first pin and sample the second. |

At 50 MHz a system clock is 20 ns. RUN clears the output latches and enables. Edge waits see synchronized inputs and can miss an edge while another instruction is executing. When designing a clocked peripheral, specify both half-periods and count the instructions from input detection to output and back to the next wait. [Sequencer timing and examples](info.md#external-edges-and-turnaround)

## I2C controller write

A source containing `I2C_WRITE address data rate_khz` uses the existing timed-GPIO image builder. Supply a seven-bit address, one data byte, and 100 or 400 kHz at a 50 MHz system clock. [Wire contract and readback](info.md#write-one-byte)

## Reproduce from source

With the [simulation dependencies](../test/README.md#reproduce-the-functional-tests) installed and the Python environment active, run this from the repository root:

```sh
make -C test p1
```

The target checks the assembler, invokes the public compiler CLI, parses its JSON output and sends the image, selector/data pairs and RUN command through the top-level pins. A controller reads and writes the shared-wire register. A separate I2C target decodes the address and payload and returns an ACK. The log reports the observed bytes, including a second run with a changed payload. The same command runs a custom timed pulse, an annotated SPI stream and the [held-out two-vote interlock](P1_HELDOUT.md).

To try your own I2C source, create a file containing e.g. `I2C_WRITE 0x52 0x3C 100`. Supply the expected wire values separately to the monitor. A relative source path is resolved from the repository root.

```sh
make -C test p1 P1_I2C_SOURCE=/path/to/my-write.p1 P1_EXPECT_ADDRESS=0x52 P1_EXPECT_DATA=0x3C P1_EXPECT_RATE=100
```

## Custom timed GPIO

Start with `TIMED low_clocks released_clocks`. Each duration is 2–256 system clocks and is selected by P0's output enable. Each `SLOT mask` pulls low the named mask bits (P0 is bit 0, P1 is bit 1); unset bits release the pins. `CHECK mask label` emits the same slot, samples synchronized P1 near the end and branches on one. Up to two CHECK slots may share one destination. Labels address individual slots. Four slots pack into each byte. Unused slots in the final byte release both lines for the released-P0 dwell. A numeric branch destination may select any slot from 0 to 63, including padding. A branch past the last loaded byte stops the engine and releases the pins. [Conditional pulse example](../examples/conditional_pulse.p1)

## SPI byte programs and logical transactions

Start with `SPI`. Each of up to eight labeled states consumes one MSB-first SPI byte. `QUIET` silences the target for the rest of the selection. Other rules end in a destination label or state number.

| Rule | Effect |
| --- | --- |
| `IF_BYTE literal target`, `IF_SEEN register target` | Branch when the input byte matches or the register has been seen. Otherwise advance to the next state. |
| `STATUS_ADDR target`, `STATUS_REG register target` | Select the next status reply by the received byte or a fixed register (0–3). |
| `COMMIT target`, `REPLY literal target`, `NEXT target` | Commit the pending read, send a literal byte, or advance without a reply. |
| `SHIFT_BIT target`, `SET_STATE value target` | Append the low MOSI bit to a four-bit shared model register, or replace the register with a four-bit value. Effects occur on the last sampled bit of this operation's byte. |
| `IF_STATE mask value target` | Jump if the masked four-bit register equals value, otherwise fall through. Both arguments are nibbles and value must fit mask. |
| `IF_STATE_PARAM mask target` | Compare model state and the current experiment parameter on bits selected by mask. Jump on equality. The peripheral samples the parameter on CS assertion. |

The model register starts at zero on reset and on a new byte-program handoff.
It persists across logical records, chip deselections and manual trials.
[One-vote](../examples/grant_one.p1) and [two-vote](../examples/grant_two.p1)
models accept the same wire format. An A write (`A1 vote`) appends bit 0.
A B read (`B2 B2 00 00 00`) returns `A5` on its last byte for either one
or two consecutive affirmative writes, depending on the loaded program.
Completing the last read byte clears the history even after a denial.
The example decoder also accepts non-A1 first-byte aliases with the B2
second byte. An independent checking contract can require the exact B tag.

After a rule, add a whitespace-separated `|` followed by `TAG`, `CMD`, `ADDR`, `MOSI_DATA` or `MISO_DATA`, and/or `END` to mark a logical transaction boundary. Use `| NONE` for an explicit zero annotation. An image without annotations retains physical chip-select framing. The JSON settings encode annotations for the public loader, and run command 4 enters the SPI byte engine. The stream example lets the checker count three logical records during a single physical selection. [SPI example](../examples/spi_stream.p1) · [SPI rules and wire timing](info.md#load-a-byte-transaction-program)

### Shared device bytes

`STORE_BYTE index target` saves the eight MOSI bits just received.
`READ_BYTE index target` schedules the saved byte on the next eight MISO
bits. `CLEAR_BYTE index target` writes zero. Index 0 or 1 selects one of
two independent cells shared across devices, selects and trials. Reset and
starting a new SPI program clear both cells. Each instruction takes effect
on its last sampled bit.

In the [mailbox program](../examples/mailbox.p1), send `A1 6D` on CS_A and
`B2 00 00` on CS_B. The final reply byte is `6D`. Completing the reply
executes CLEAR, so the next poll returns zero. Cutting the reply short
preserves the value for a retry. Replacing CLEAR with NEXT makes reads
repeatable. The image treats any first byte other than A1 as a read.

### Experiment operands

`IF_BYTE_PARAM index target` compares the received byte with experiment
operand 0 or 1. Equality jumps to the target, otherwise execution falls
through. `REPLY_PARAM index target` shifts the selected operand out on the
next byte. The target captures both operands once per CS. The loaded program
defines what each operand means. In the [adaptive poll](../examples/adaptive_poll.p1)
they serve as the accepted header and its response. The host sets their seeds
through trial selectors 5C and 5D. A feedback rule can update either value
between trials. [Policy encoding and experiment](info.md#p5-feedback-campaigns)
