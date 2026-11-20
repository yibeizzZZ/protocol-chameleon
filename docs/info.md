<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

UART TX and RX operate independently and can run simultaneously. Reset selects
8N1 at 434 clocks per bit (approximately 115200 baud with the provisional
50 MHz clock). A runtime descriptor sets the bit period, data width, and stop
count for both directions. Frames idle high and carry one low start bit,
seven or eight data bits, least significant first, and one or two high stop
bits. Seven-bit TX uses the low seven input bits; seven-bit RX returns bit 7
as zero.

## Pin interface

Reset selects the UART pin mapping below. See [Programmable pin execution](#programmable-pin-execution)
for the alternate mapping and host commands.

| Pin | Direction | Function |
| --- | --- | --- |
| `ui_in[7:0]` | Input | TX byte or configuration command, selected by `uio[3]` |
| `uio[0]` | Input | Send or configuration write strobe, synchronous to `clk` |
| `uio[3]` | Input | Mode sampled with strobe: low sends a byte, high writes configuration |
| `uo_out[0]` | Output | UART TX |
| `uo_out[1]` | Output | Busy from acceptance through the full stop bit |
| `uo_out[2]` | Output | Done pulse lasting one clock after the stop bit |
| `uio[1]` | Input | UART RX serial line; drive high when idle |
| `uo_out[7:4]` | Output | Received byte, bits 7 through 4 |
| `uio[7:4]` | Output | Received byte, bits 3 through 0 (bit 0 on `uio[4]`) |
| `uo_out[3]` | Output | RX valid, one clock when a byte is accepted |
| `uio[2]` | Output | RX framing error, one clock for a low stop bit |

### Load timing and framing

Drive `uio[3]` low for ordinary UART use. To program, drive it high and write
the following two commands in order on `ui_in[7:0]`. For each write, present
the command and mode, then raise `uio[0]` across a rising clock edge. Let the
chip sample the strobe low for at least one clock between writes. Return the
strobe low before switching back to transmit mode.

| Command | Bit 7 | Bits 6 through 0 |
| --- | --- | --- |
| Stage timing | 0 | Low seven bits of the reload value |
| Apply descriptor | 1 | Bits 6:2 = high five bits of reload, bit 1 = two stops if set, bit 0 = seven data bits if set |

For a period of N clocks, encode reload = N − 1. The supported register range
is 8 to 4096 clocks per bit; baud = input clock frequency / N. A smaller
period leaves the active UART descriptor unchanged. With zero staged low
bits, `0x83` enters the programmable engine and `0x82` enters the SPI peripheral. The staged low bits persist until
rewritten or reset. Apply updates all three settings on one edge. Configuration
writes can occur while busy and never request a transmission.

| Behavior at 50 MHz | N | Stage | Apply | Frame on the wire |
| --- | ---: | --- | --- | --- |
| 115200 baud nominal, 8N1 (reset default) | 434 | `0x31` | `0x8C` | Start + 8 data + 1 stop |
| 57600 baud nominal, 7N2 | 868 | `0x63` | `0x9B` | Start + 7 data + 2 stops |

For example, sending `0x01` makes the eighth data slot low in 8N1. In 7N2
that slot is the first high stop bit, and RX checks both stop bits before
publishing the byte. Timing and framing fields can also be varied independently.

TX uses the settings active when it accepts a send. RX uses the settings
active when it first detects a possible start on the synchronized line. An
apply takes effect after its rising edge, so RX detecting a start on that edge
uses the previous settings. Coordinate the switch with the peer between frames.

### Transmit

Hold `rst_n` low across a rising clock edge to abort any frame, drive TX high,
and clear busy and done. Keep send low during reset. When busy is low, present
the byte and raise send. Both inputs must be stable at the rising clock edge
that accepts the request. The transmitter latches the byte on that edge.

Holding send high issues only one request. A rising strobe sampled while busy
is discarded. To send another byte, let the chip sample send low for at least
one clock, then raise it while idle. A new request can be accepted on the edge
ending the done pulse.

### Receive

The receiver synchronizes the serial input through two flip-flops. When it
detects a low level, it waits half a bit and confirms the start bit is still
low. A false start is discarded silently. It samples each configured data
and stop bit at one-bit intervals, near their centers.

The final high stop bit publishes the received byte and pulses RX valid on the same
clock. The byte stays on the pins until the next accepted frame or reset.
A low stop bit pulses RX framing error and preserves the last accepted byte.
After an error, RX waits for the line to return high before accepting another
start bit. A synchronous active-low reset discards any partial frame and
clears the received byte and both RX status outputs.

## Programmable pin execution

The host can load up to 16 one-byte instructions. One sequencer controls four
bidirectional pins. Pin roles, the order of operations, and the path taken
after a sample come from the loaded bytes. The system clock drives the engine.

### Enter, load, run, stop

Use the same synchronous strobe as UART. Set `ui_in` and `uio[3]` before the
rising system clock edge that samples `uio[0]` high; let the chip sample
`uio[0]` low between writes.

1. In UART mode, with `uio[3]=1`, write `00 83` (hex, two strobes). This
   stages zero in the UART timing-low register and uses a previously invalid
   UART apply command to enter the engine. The active UART descriptor survives.
   Entry starts an empty program and releases P0–P3.
2. With `uio[3]=0`, write one instruction per strobe in address order starting
   at 0. While stopped, writes append. Bytes beyond slot 15 are ignored.
3. With `uio[3]=1`, write `02` to run from address 0. RUN clears samples,
   output values, enables, and delay state. The first instruction executes on
   the next rising clock. An empty program does not start.
4. With `uio[3]=1`, write `03` to stop even during a delay or edge wait.
   HALT and STOP release all four pins and retain the samples and program.
   Use `02` to replay, or `01` while stopped to clear the loaded length and
   start a replacement. Appends, CLEAR and RUN are ignored while running.
5. With `uio[3]=1`, write `00` to exit from any state. The old UART pin
   mapping returns on that clock edge. The next engine entry starts empty.
   For a UART timing update after exit, stage its low byte again before apply.

| Engine signal | Tiny Tapeout pins | Meaning while selected |
| --- | --- | --- |
| P0, P1, P2, P3 | `uio[4]`, `uio[5]`, `uio[6]`, `uio[7]` | Each bit can be driven or released |
| RUNNING | `uio[2]` | High during execution, including delays and waits |
| Sample history | `uo_out[7:4]` | Latest four sampled bits; newest on `uo_out[4]` |

UART TX can finish a frame and RX continues listening on its original input.
New host writes address the engine until exit. RX byte and error readout return
on exit. P0–P3 are dedicated RX-data **outputs in UART mode**, including after
reset. Keep external drivers released until engine entry; release them before
exit or reset. During execution the program and peer must agree on pin ownership.

### Instructions

The high nibble is the opcode; `n` is the low nibble. Each ordinary instruction
executes on one rising clock edge. Pin value and enable latches are independent.
HALT, a reserved opcode, or fetching outside the loaded prefix stops execution
and releases the pins. Falling past address 15 also stops. Branch addresses
are absolute (0–15).

| Hex | Operation | Effect |
| --- | --- | --- |
| `00` | HALT | Stop, retain samples |
| `1n` | DRIVE | Set four output values to mask n, bit 0 = P0 |
| `2n` | DIR | Set four enables to mask n, 1 = drive, 0 = release |
| `3n` | SAMPLE | Shift the synchronized level of pin `n[1:0]` into history |
| `5n` | DELAY | Wait n additional system clocks; next instruction executes n+1 clocks after this instruction |
| `6n` | JUMP_ONE | Jump to n if the newest sampled bit is 1, otherwise advance |
| `7n` | JUMP | Jump to n |
| `8n`, `9n` | RISE_SAMPLE, FALL_SAMPLE | Wait for the chosen edge on pin `n[3:2]`; on detection shift pin `n[1:0]` into history and advance |

### Two program images

Both images use the same instruction store, pin latches, and sequencer. Load
each row as instruction bytes with `uio[3]=0`, then issue RUN with `uio[3]=1`.
Stop and clear before loading the other row.

| Interaction | Bytes in address order | Pin behavior |
| --- | --- | --- |
| Externally clocked one-bit request/reply, repeating | `81 65 10 24 77 14 24 91 20 70` | Sample P1 on rising P0. If zero, preload P2 low; if one, jump to address 5 and preload P2 high. Enable P2, hold the reply through falling P0, release it, then return to the rising-edge wait. |
| Self-timed two-pulse burst, one shot | `10 24 55 14 53 10 57 14 53 10 00` | Drive P2 low, then emit two high pulses separated by a low gap and halt. Each high lasts five system clocks from DRIVE high to DRIVE low. P0 is unused. |

In the first program, the peer sets P1 before rising P0, reads P2 at falling
P0, and never drives P2. The falling-edge instruction also captures P1; if the
peer only needs its request echoed, that second sample can be ignored.

### External edges and turnaround

Each pin passes through two sampling flip-flops. RISE/FALL compare consecutive
synchronized clock levels and capture the synchronized data on the matching
system clock. This captures a system-clock observation of the bus. An edge is
consumed only if its instruction is executing when the transition is detected.
There is no edge queue; short pulses, or edges during another instruction,
can be missed. Keep external inputs stable across the sampling window and let
the pin synchronizers settle before starting the external clock.

With a stable input and no extra synchronizer delay, an already waiting
instruction typically consumes the edge about two to three system periods
after the external transition. Each subsequent branch, DRIVE, or DIR takes
another clock. Paths of different lengths have different response latency.
Budget both external half-periods for the executed path, pad delay, skew, and
the peer's setup/hold requirements. A future SPI target may need the first bit
preloaded before its sampling edge. For a shared data line, use DIR to release
before the peer drives, then preload the next value with DRIVE and enable it
only after the peer releases. The engine does not insert a turnaround interval.

The 16 × 8 store contains 128 program bits; its physical implementation and read
mux cost are unmeasured. This revision has four bits of sample history, no
byte serializer in the sequencer, queued edge capture, transaction memory, or
P2–P5 rule and feedback execution. Neither fit in 8×4 tiles nor a maximum
external clock rate for the instruction sequencer has been established.

## SPI status peripheral

The host selects a dedicated SPI bit shifter with the UART configuration writes
`00 82` (hex, two strobes with `uio[3]=1`). The sequencer entry remains `00 83`.
The UART descriptor survives both transitions. Release all external drivers on
`uio[7:4]` while entering from UART; these four pins are UART outputs at reset.
After entry the controller drives `uio[4]=CS_n`, `uio[5]=SCLK`, and
`uio[6]=MOSI`. The target drives only `uio[7]=MISO` in an active transaction.
Start with CS high and SCLK at the mode's idle level.

**Host programming.** Use the usual synchronous `uio[0]` strobe and `ui_in[7:0]`
byte bus. Keep CS high and allow at least 100 ns for idle to be observed before
programming. All values below are hexadecimal.

| Control byte (`uio[3]=1`) | Effect |
| --- | --- |
| `10`–`13` | Select SPI mode 0–3. Bit 1 is CPOL, bit 0 is CPHA. |
| `20`–`23` | Select the base byte of status register 0–3. |
| `24`–`27` | Select the read-to-clear mask of status register 0–3. |
| `01` | Rearm the first-read behavior at all addresses. |
| `00` | Exit to UART. Deassert CS, then release the peer drivers before this write or system reset. |

Supply one data strobe with `uio[3]=0` after a register selector. Writing either
field rearms just that address. Another control write replaces or cancels an
incomplete selector. Register programming is ignored during an active frame.
Reset selects UART, clears the table and history, and sets SPI mode 0. Exit
and re-entry preserve the table, mode and history; the pending selector is discarded.

**Default wire transaction (`00 82` entry).** Keep CS low for three MSB-first bytes. Send opcode
`A6`, an address from `00` through `03`, then a dummy byte. MISO carries zero
during the first two bytes and returns the status during the third. On the
last sample edge of a valid read, that address becomes seen. Later reads
return `base & ~clear_mask`. An incomplete read, unknown command or address
does not consume first-read state. Extra clocks after the third byte return
zeros until deselection. Start a fresh CS window for the next command.

For example, in SPI mode 0 write control `22`, data `ED`, control `26`, data
`48`. Two successive controller transfers of `A6 02 00` return `00 00 ED`
and `00 00 A5`. No host strobe occurs during either transfer.

**Timing envelope exercised.** At 50 MHz system clock and 5 MHz SCLK, allow
100 ns in each SCLK half-period, at least 100 ns from CS assertion to the first
edge, and 100 ns after the last edge before deselecting. Keep CS high for at
least 100 ns between transactions. The controller changes MOSI on launch
edges (preload the first bit for CPHA=0) and samples MISO on the opposite edge.
CS, clock and data pass through two-stage synchronizers. The address sample
preloads the shifter; detecting a launch edge updates MISO in one registered
operation. Raw CS deassertion gates the output enable for immediate release
in RTL. See the [timing measurements and limits](../test/README.md).

## Load a byte transaction program

The GPIO engine's 16-byte store also holds up to eight two-byte state rules.
In byte execution mode the SPI shifter handles every bit. On the final sample
edge of each byte, exactly one rule consumes that byte, selects the next state,
and preloads the reply for the next byte. The first outgoing byte after CS
assertion is zero. The host does not intervene between bytes.

1. From UART, enter the GPIO loader with control writes `00 83`. Keep external
   drivers released until the loader owns the pins. It starts with an empty image.
2. Write rule bytes in address order, one strobe per byte with `uio[3]=0`.
   While stopped, control `01` clears the image for a retry.
3. Write control `04` to select byte execution. Empty or odd-length images,
   and requests while a GPIO program is running, are ignored. Control `02`
   still runs the same store as GPIO instructions. The image is immutable
   during byte execution.
4. Use the SPI pins, mode selection, table and history controls documented
   above. Before the first CS window, drive CS high and SCLK idle for at least
   100 ns. To replace the image, deselect, release the controller's drivers,
   exit to UART with control `00`, then repeat from step 1. Table values and
   committed history survive this sequence. Direct UART entry `00 82` always
   selects the original M5 transaction profile.

**Rule encoding.** In the first byte, bits 7:4 select the operation, bit 3
must be zero, and bits 2:0 select the target state. The second byte is the
argument. CS assertion starts at state 0. Unless a rule emits a reply, the
next outgoing byte is zero.

| High nibble | Operation on the just-received byte | Next state |
| --- | --- | --- |
| 0 | End this logical frame; emit zeros while CS remains low | Quiet until deselect |
| 1 | Compare the received byte with the argument | Target on equality, otherwise following state |
| 2 | Schedule status from the received register address (0–3); remember the address for commit | Target, or quiet on invalid address |
| 3 | Schedule status from the register in argument bits 1:0; remember its address | Target |
| 4 | Mark the remembered address as seen and discard the pending address; no effect if none | Target |
| 5 | Schedule the argument byte as a literal reply | Target |
| 6 | Check the seen bit of the register in argument bits 1:0 | Target if seen, otherwise following state |
| 7 | Consume one byte without emitting a reply | Target |

A branch back to state 0 can start a new logical request while CS stays low.
A pending address refers to the most recent status read. Only operation 4
commits it. Deselecting discards any partial byte and uncommitted address.
Falling through state 7, reaching an unloaded state, or executing a reserved
encoding enters quiet behavior. A reply already scheduled on the preceding
byte still shifts out. The quiet state continues to drive zero until CS rises.

**Two example images.** Configure register 1 with base `ED` and clear mask
`48`. Control `01` in SPI mode rearms the history before each example.

| Image (hex, in load order) | Controller exchange and expected MISO |
| --- | --- |
| Command poll: `12 CA 00 00 65 01 34 01 41 00 76 00 51 3C` | Only command `CA` is recognized. With register 1 unseen, `CA 00 00 00` returns `00 00 00 ED` and commits on byte four. On the next poll, a different state path consumes an extra byte: `CA 00 00 00 00` returns `00 00 00 00 3C`. Deselect between polls. |
| Address stream: `21 00 40 00` | Every pair is an independent address/status request under the same CS. With CS held low, `01 00 01 00` returns `00 ED 00 A5`. There is no command prefix; a commit returns directly to the address state. |

These programs share the shifter, state decoder, program storage and four
history bits. Their envelope is an eight-bit MSB-first SPI transport with
fixed external pin roles. Arbitrary bit-length fields, a new electrical
protocol and the design proposal's withheld-protocol test remain outside
the demonstrated behavior.

## P3/P4 trials

Select the desired SPI profile and program its mode, status values and clear
masks first. With the bus idle, write control `30` in SPI mode to open the
trial interface. It works with both the M5 default and a loaded M6 byte
program. The host uses the same byte bus, mode pin and synchronous strobe as
the loader. One RUN executes one trial locally.

| Trial pins | Role |
| --- | --- |
| `uo[0]`, `uo[1]` | Independent active-high DRDY_A and DRDY_B. Each stays high from its issue tick until its required service count is satisfied or the trial ends. |
| `uio[4]`, `uio[1]` | Active-low CS_A and CS_B. The latter borrows UART RX, which is held idle internally during trial mode. |
| `uio[5]`, `uio[6]`, `uio[7]` | Shared SCLK, MOSI and MISO, respectively. The controller drives exactly one CS low at a time and deasserts both between frames. MISO releases when both are high. |
| `uo[2]`, `uo[3]` | RUNNING and RESULT_VALID. IRQ and RUNNING clear on a terminal decision. |
| `ui[3:0]`, `uo[7:4]` | Readback page address and four-bit page value. Reading requires no strobe. |

**Plan and rules.** While stopped, select a field with a control write, then
write its value once with the mode pin low. A new control write cancels an
incomplete field selection. Use base `40` for A and `48` for B (hex).

| Offset | Field |
| --- | --- |
| 0 | Bit 0 enables this event. Bits 2:1 encode required count minus one (1–4 reads). Bits 3 and 4 independently enable command and address comparisons. Bits 7:5 encode the expected whole-byte frame length minus two (2–9). |
| 1, 2 | Expected first and second MOSI bytes (command and address). Contents of subsequent bytes are outside this rule. |
| 3, 4 | Issue time, low byte then high byte. |
| 5, 6 | Inclusive completion deadline, low byte then high byte. Offset 7 is reserved. |

Control selector `50` takes one policy byte. Bits 1:0 select unordered (0),
A's quota must be satisfied before B's first service (1), or B before A (2).
Bit 2 enables sensor banking: logical register bit 0 selects a register within
the sensor, and CS selects physical slots 0–1 for A or 2–3 for B. With banking
off both use the original four-slot table. Each sensor's checker always uses
its physical CS identity and compares the unmodified MOSI bytes.

**Example.** For M5's `A6 00 xx` register read, configure physical register 0
with sensor A's data and physical register 2 with B's data. Enter trial mode.
Write the following bytes to successive field selectors (one selector/data
pair per field), then issue RUN:

| Selectors | Data bytes (hex) | Meaning |
| --- | --- | --- |
| `40`–`46` | `39 A6 00 00 00 2C 01` | Notify A at tick 0; one three-byte read due by tick 300. |
| `48`–`4E` | `39 A6 00 50 00 58 02` | Notify B at tick 80, potentially during A's read; B due by tick 600. |
| `50` | `05` | Bank by sensor; service A before B. |

**Trial time.** With both CS lines high and settled for at least 100 ns,
control `32` starts (or replays) the plan. Tick 0 is the first system rising
edge after RUN. Times are absolute 16-bit clock counts from that origin; use
deadline = issue + allowed service interval, up to 65534. The frame starts
and completes at the SPI shifter's synchronized CS assertion and release.
These are sampled observations, typically two to three clocks after the
external transitions. A selection observed on the issue tick is eligible.
A completion observed on the deadline counts; an unmet quota at deadline + 1
times out. Both events may issue together. After all quotas are satisfied,
checking continues through the last enabled deadline to catch extra reads.
The observation window is defined by completed frames.

**Results.** The first terminal decision latches the record until RUN or reset.
Read page 0 for the verdict. Page 1 is a source mask (A=1, B=2, both=3,
neither=0). Pages 2–5 give the decision tick, least-significant nibble first.
Pages 6–7 and 8–9 give the captured command and address if an open implicated
frame supplied them (zero otherwise). Pages A and B give accepted counts for
the two sensors. This compact witness is not a full trace buffer.

| Code | Verdict and condition |
| ---: | --- |
| 1 | PASS at the end of the observation window. |
| 2 | MISSED/TIMEOUT; source mask identifies all unsatisfied, expired slots on that tick. |
| 3 | DUPLICATE; the selected source already met its quota. |
| 4 | WRONG_CONTENT; wrong complete-byte length, command or address. |
| 5 | ORDER_ERROR; disabled/unissued source, or predecessor's quota not satisfied. |
| 6 | UNKNOWN; invalid plan, abort, a sensed CS collision or owner change without deselect, or an incomplete capture (partial byte or fewer than two whole bytes). |

Invalid/ambiguous capture takes priority over expiry, then expiry over frame
checks. For a well-captured frame the priority is eligibility at selection,
multiplicity, content, then predecessor order. A timeout is recorded even if
the controller completes late. Noise or transitions too short for the input
synchronizers cannot be diagnosed reliably.

Control `33` aborts a running trial as UNKNOWN. Configuration writes and
additional RUN requests are ignored during execution. Control `31` while
stopped returns to the same SPI profile with its history intact. Deselect
both sensors before leaving trial mode or resetting. A plan needs at least one
enabled slot, a deadline at or after issue for each enabled slot, and both
slots enabled for an ordered trial. Order code 3 and deadline 65535 are
invalid for an active plan. RUN resets trial counts and the previous witness;
use the SPI rearm command separately if the peripheral history must also reset.
