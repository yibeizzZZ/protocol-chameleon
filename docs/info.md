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

Reset selects the UART pin mapping below. See the Programmable pin execution section
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

## Timed open-drain GPIO and I2C write

Control `05` runs the GPIO loader's current image as a sequence of open-drain
pin masks. Each byte holds four two-bit masks, least-significant pair first,
for up to 64 time slots. A one pulls P0 (bit 0) or P1 (bit 1) low; a zero
releases it. P2 and P3 stay released. Supply external pull-ups on P0 and P1.
Use an idle bus with the host and target configured for this pin assignment.
At reset and after EXIT the UART owns these pins, so isolate the bus during
that handoff.

While the GPIO loader is stopped, write a control selector followed by one
data byte. A new control cancels a pending selector. CLEAR resets the settings.

| Selector | Timed GPIO setting |
| --- | --- |
| `20`, `21` | Hold time when P0 is pulled low or released, respectively. The duration is one plus the data byte in system clocks, with a minimum of two clocks. Both default to two. |
| `22`, `23` | Optional sample points. Bit 6 enables a comparison to the six-bit slot address in bits 5:0. Both start disabled. At a matching slot the engine reads synchronized P1 one system clock before the next mask. Allow for the input synchronizer when choosing a dwell. |
| `24` | Six-bit branch destination. A sampled one jumps there after the current dwell. A sampled zero continues to the next slot. Each sampled bit shifts into `uo_out[7:4]`, newest at bit 4. |

RUN_TIMED (`05`) initializes the four-bit history to `0001`, clears the output
latches and starts at slot zero on the next clock. Reaching the end of the
loaded image (including a jump past its end) stops and releases both wires.
STOP (`03`) also releases the wires. The host can read history after either stop.
Regular GPIO RUN (`02`) retains its original instruction and history semantics.

### Write one byte

At 50 MHz, P0 is SCL (`uio[4]`) and P1 is SDA (`uio[5]`). Generate a program
for seven-bit address `0x52`, data `0xA5`, and a 400 kHz bus with the command
below. Use `100` as the last argument for Standard-mode.

```sh
python3 examples/i2c_write.py 0x52 0xA5 400
```

1. Enter the GPIO loader with controls `00 83`, then CLEAR (`01`).
2. Load the printed 16 image bytes as data. For each printed selector/data
   pair, send the selector as control and its value as data.
3. Issue `05` and leave the host idle. The program transmits the address with
   R/W=0 and releases SDA on the ninth clock. An ACK proceeds to DATA, while
   an address NACK jumps directly to STOP. The data ACK slot also records the
   target's response. When RUNNING falls, read `uo_out[7:4]`.

| Readback (hex) | Result for this image |
| --- | --- |
| `4` | Target acknowledged address and data. |
| `3` | Target rejected the address. The controller omitted the data byte. |
| `5` | Target acknowledged the address and rejected the data. |

Address, data, START/STOP and ACK slots come from the program. Speed uses two
loaded dwell values. This example covers one controller, one data byte and a
target that never stretches SCL. Reads, repeated START, multi-byte transfers,
multi-controller arbitration and analog rise times are outside its verified
scope. [Image generator](../examples/i2c_write.py) · [Pin-level evidence](../test/README.md#i2c-controller-write)

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
3. Optionally load logical transaction fields (described below)
   for the completed states. Write control `04` to select byte execution. Empty or odd-length images,
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
| 0 | Enter the quiet state and emit zeros while CS remains low | Quiet until deselect |
| 1 | Compare the received byte with the argument | Target on equality, otherwise following state |
| 2 | Schedule status from the received register address (0–3); remember the address for commit | Target, or quiet on invalid address |
| 3 | Schedule status from the register in argument bits 1:0; remember its address | Target |
| 4 | Mark the remembered address as seen and discard the pending address; no effect if none | Target |
| 5 | Schedule the argument byte as a literal reply | Target |
| 6 | Check the seen bit of the register in argument bits 1:0 | Target if seen, otherwise following state |
| 7 | Consume one byte without emitting a reply | Target |
| 8 | Compare the shared four-bit model register masked by argument bits 7:4 with bits 3:0 | Target on equality, otherwise following state |
| 9 | Set shared model register to argument bits 3:0 | Target |
| A | Shift shared model register left and insert MOSI bit 0 | Target |
| B | Compare model register and frame parameter on bits selected by argument bits 3:0 | Target on equality, otherwise following state |

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
| 1, 2 | Expected command and address. Unannotated profiles take these from the first and second MOSI bytes. |
| 3, 4 | Issue time, low byte then high byte. |
| 5, 6 | Inclusive completion deadline, low byte then high byte. |
| 7 | Expected logical identity tag when tag matching is enabled. |

Control selector `50` takes one policy byte. Bits 1:0 select unordered (0),
A's quota must be satisfied before B's first service (1), or B before A (2).
Bit 2 enables sensor banking: logical register bit 0 selects a register within
the sensor, and CS selects physical slots 0–1 for A or 2–3 for B. With banking
off both use the original four-slot table. By default, physical CS identifies
the source. An annotated program can also identify the source from a wire tag.

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
deadline = issue + allowed service interval, up to 65534. An unannotated frame starts
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
| 4 | WRONG_CONTENT for a length, command, address or enabled data mismatch, or an unmapped observed tag. |
| 5 | ORDER_ERROR; disabled/unissued source, or predecessor's quota not satisfied. |
| 6 | UNKNOWN for an invalid plan, abort, sensed CS collision, owner change without deselect or incomplete capture. Unannotated profiles require at least two whole bytes. |

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

### Logical transaction fields

In the stopped GPIO loader, write the two instruction bytes for a state,
then optionally select that state with control `10`–`17` (state 0–7) and
write one data byte. You can also annotate multiple states after loading the
whole image. One control write cancels any pending selector. A data write to
an incomplete or unloaded state is consumed and ignored. New states start
with zero field bits. Any successful annotation, including a zero, enables
logical checking for this image. CLEAR or loading a new image resets that
choice. Images without annotations retain one service per physical CS frame.

| Annotation bit | Meaning on the final sampled bit of this state's byte |
| --- | --- |
| 5 | End the current logical transaction, including this byte. |
| 4, 3, 2 | Capture the MOSI byte as identity tag, command or address respectively. |
| 1 | Capture a data byte. |
| 0 | Select the sampled MISO pad for data when set, or MOSI when clear. |

Bits 7:6 are ignored. A byte may fill multiple fields. The latest capture
within the transaction wins for each field. An input-dependent state branch
can put the closing byte at a different position for different commands.
The end mark expires an uncommitted peripheral read after the current
operation. A COMMIT on that byte still takes effect. SPI continues with the
program's selected next state and reply under the same CS.

P4 snapshots both slots' eligibility on the first synchronized bit sample of
each transaction. The synchronized final sample of a marked byte is its
inclusive completion tick. An empty CS window, partial byte or unfinished
transaction at deselect yields UNKNOWN during observation. Releasing CS after
a completed transaction adds no service. CS ownership, collision detection,
physical register banking and MISO release still apply to the whole window.

In the trial interface the following `50` policy bits apply to annotated
images. Bits 2:0 keep their original meaning.

| Bit | Independent checking contract |
| --- | --- |
| 3 | Match the captured tag against A/B selectors `47` and `4F` to identify the source. When clear, use physical CS. Tag mode requires two distinct configured tags. A missing tag gives UNKNOWN. A present, unmapped tag gives WRONG_CONTENT with source mask zero. |
| 4, 5 | Enable data equality separately for A and B. Write expected data to selectors `52` and `53`. |
| 6, 7 | Require length one for A or B respectively. Otherwise the descriptor selects 2–9 bytes. The observed length saturates at 10, so excess bytes cannot wrap to a valid length. |

An enabled content comparison requires the field to be present, including
when the expected value is zero. Pages A/B report accepted service counts,
pages C/D report the captured failure data, and E/F report the captured tag,
low nibble first. As with command and address, empty witness registers read
zero. The P5 campaign uses the same P4 verdict, source and decision tick.

**STREAM example.** Load `21 00 40 00`, annotate state 0 with `14` (tag
and address) and state 1 with `2B` (command, MISO data and end), then issue
`04`. Set SPI status slots 1 and 2 to `55` and `AA` with zero clear masks.
Enter trials with `30` and load the selector/data bytes below. All values
are hexadecimal.

| Selectors | Data in selector order |
| --- | --- |
| `40`–`47` | `1B 36 01 00 00 58 02 01` |
| `48`–`4F` | `19 47 02 00 00 58 02 02` |
| `50`, `52`, `53` | `39 55 AA` |

After RUN (`32`), send `01 36 01 36 02 47` under one continuous CS_A
assertion. MISO returns `00 55 00 55 00 AA`. Each pair completes a
transaction. A is credited twice and B once. PASS is reported at tick 601
if service finishes by tick 600. Changing only selector `53` to `AB` makes
the same final reply fail as WRONG_CONTENT for B. This interface checks
whole-byte fields on the SPI datapath, with two service slots and their
existing quotas and ordering rules.

### Capture a wire field for use in a later transaction

A trial can remember one byte from an accepted, tagged logical record. A later
record can compare any of its annotated fields with that byte. The host can
load both field selectors before the trial and leave the actual byte value to
the DUT. P3 and P4 can apply this equality condition separately or together.

| Selector | Value |
| --- | --- |
| `5A` | Producer tag. An accepted logical record with this tag replaces the stored operand at its END. |
| `5B` | Bit 7 enables capture and use. Bit 6 adds equality to the existing P3 trigger. Bits 5 and 4 add equality to the P4 checks for slots B and A respectively. Bits 3:2 select the producer field and bits 1:0 select the consumer field. |
| Field selectors | 0 = data, 1 = address, 2 = command, 3 = tag. The byte-program annotation selects MOSI or MISO for data. |
| Read pages `D2`, `D3`, `D4` | Low nibble, high nibble and valid bit of the captured operand. Read the nibbles when valid. |

Set selectors through the ordinary stopped-trial control/data strobe pair.
Reset disables the feature. Enabling it on a physical-frame-only image makes
the plan invalid (UNKNOWN). Each manual or automatic trial starts with an
empty operand. A missing producer field invalidates the operand when that
producer is accepted. Until a field is captured, or if the consumer field is
missing, equality is false even for a zero byte. A record that both consumes
and produces compares against the previous value before replacing it. A
rejected record leaves the operand intact. An unsatisfied P3 equality
suppresses that match. An unsatisfied P4 equality follows the existing
WRONG_CONTENT and verdict-priority rules.

**Example.** Load a repeating three-byte SPI program (`71 00 72 00 70 00`)
with annotations `10 08 22` (tag, command, then MOSI data plus END). Configure
both slots for one three-byte service from tick 0 with deadline 1000, disable
literal command/address checks, set policy `50=08`, and set slot tags
`47=01`, `4F=02`. Load `5A=01`, `5B=A2`. Within one CS window send
`01 00 6D 02 6D 00`. The first record supplies the value 6D and the second
echoes it in its command field. Changing only `5B` to `AA` captures the
first command (00) and the same trace produces WRONG_CONTENT for slot B.

For reactive scheduling, load `5B=C2`, set A's quota to two, and set
`54=E0`, `55=01`, `56=00`. The first A record captures its payload.
A second A record whose command equals that payload issues B's notification
on its closing tick. The resulting verdict is available to the usual feedback
rules.

### Transaction-triggered P3 notifications

With an annotated byte program loaded, either notification slot can wait
for the Nth completed record carrying a chosen wire tag. The other slot
keeps its absolute issue time. Each trial starts with a fresh count and
can issue one such notification. Both service quotas can be outstanding
at once. A record follows the program's END mark even when CS stays low.

In the stopped trial interface, use the usual control-selector/data writes.
All selectors and encoded values below are hexadecimal.

| Selector | Meaning |
| --- | --- |
| `54` | Bit 7 enables the rule (reset = 0). Bit 6 counts only services accepted by P4 when set, or all complete matching observations when clear. Bit 5 selects target DRDY_B (1) or DRDY_A (0). Bit 4 enables the additional relative service deadline. Bit 2 also requires captured data to equal selector `59`. Bits 1:0 select occurrence 1–4 as N minus one. Bit 3 is ignored. |
| `55` | Exact eight-bit identity tag captured by the protocol program. The P4 contract can independently associate services by tag or physical CS. |
| `56` | Manual delay D, 0–255 system clocks from the synchronized closing sample to the notification. Zero issues on the closing tick. During a P5 campaign the selected profile supplies D in the target slot's time byte. |
| `57` | Inclusive service window W, 0–255 clocks from notification, enabled by bit 4 of `54`. An outstanding quota times out at issue + W + 1. |
| `58` | Manual four-bit model parameter, sampled on physical CS assertion. A running campaign supplies the applied profile's parameter instead. |
| `59` | Expected wire data for a P3 trigger with bit 2 set. An absent field cannot qualify. P4 retains its separate comparisons at selectors `52` and `53`. |

The target slot must be enabled. Its absolute issue value is ignored. Its
absolute deadline remains a hard limit, including when the trigger never
occurs. The earliest applicable deadline governs service. After successful
service the trial still observes through the normal absolute horizons for
duplicates. An unannotated program or disabled target gives UNKNOWN at RUN.
Records without a tag, partial records and ambiguous CS ownership cannot
match. The original P4 checks continue to apply to all services.

A terminal P4 decision suppresses any notification due on that edge and
cancels a pending delay. In observation mode a matching record can still
leave evidence on a WRONG_CONTENT decision. Accepted-only mode excludes it.
Read `D0` without a strobe for the latest trial's trigger witness (bit 0 =
selected occurrence reached, bit 1 = notification actually issued).
Page `D1` counts qualifying observations up to N. Both freeze at trial end
and clear on reset or the next trial start, including a P5 restart.

**Example.** With the annotated STREAM image and descriptors above, write
`50=38` for unordered service, then `54=E0`, `55=01`, `56=0C`. After RUN
the first accepted tag-01 transaction schedules B twelve clocks later,
while A can still need its second read. Change only `54` to `E1` and the
second accepted tag-01 transaction schedules B instead. At 50 MHz the same
12-clock delay is 240 ns. To give B a 200-clock service window as well,
set bit 4 (`54=F1`) and write `57=C8`. The two DRDY pins, logical SPI
transport and P4 checking predicates retain their existing roles.

### P5 feedback campaigns

Enter the P3/P4 trial interface with SPI control `30` and load the checker
descriptors as above. In this interface control `32` still runs one manual
trial. Control `34` starts a new campaign and replaces its previous log.
The host can leave its pins alone until completion. During a campaign
`uo[2]` stays high across trials, `uo[3]` goes high after the last record,
and `uo[1:0]` continue to carry the two independent notifications.

Use one control strobe with the selector followed by one data strobe per
field. All selectors and examples below use hexadecimal. Control strobes
cancel incomplete writes. Set unused bits to zero.

| Selector | Data |
| --- | --- |
| `51` | Bits 3:2 select the initial profile. Bits 1:0 give the trial bound minus one (1–4 trials). |
| `70 + 4*p + 0,1` | Profile p's timing values for A and B, each 0–255 clocks. Each absolute slot uses ticks from trial start. A transaction-triggered slot uses clocks after its qualifying record. Deadlines, order, quotas and checks come from P4. |
| `70 + 4*p + 2` | Bit 0 inverts returned status bit 7 for CS_A. Bit 1 does so for CS_B. This applies to status reads after read-to-clear masking, including the M6 byte program. Each frame samples its mode at synchronized CS assertion. Literal replies and the underlying status registers retain their values. |
| `70 + 4*p + 3` | Four-bit model parameter. Its meaning comes from the loaded SPI program. Read pages `C4`–`C7` for the value logged in trials 0–3. An unfilled row reads zero. |
| `60 + 4*r + 0` | Rule r's current verdict in bits 2:0 (0 = any, 1–6 per the P4 table). Bit 5 enables the rule. Bit 6 requests an exact match between bits 4:3 and the P4 source mask. |
| `60 + 4*r + 1` | Bits 2:0 match the immediately preceding verdict. Bits 5:3 match the verdict two trials back. In each field 0 = any, 1–6 = exact, 7 = no such trial yet. |
| `60 + 4*r + 2` | Bits 1:0 select the next profile. Bit 2 requests STOP. Rule offset 3 is reserved. |

All fields reset to zero. Each decision uses the first matching enabled rule
(0 before 1 before 2 before 3). No match, explicit STOP, or reaching the
bound ends the campaign. Each completed trial counts, including UNKNOWN.
The engine accepts the initial trial one system clock after campaign RUN.
For a valid trial tick 0 is the following clock. After a verdict the next
clock archives the record and selects the action, the following clock
accepts the new trial, and the third clock is its tick 0. A CS still observed
active at acceptance or an issue time outside its deadline gives UNKNOWN at
tick zero. There is no unbounded wait for a stalled controller. SPI read
history persists across trials. Control `33` during an executing trial
feeds UNKNOWN to the policy. Campaign configuration, exit and restart are
locked until completion. Reset discards the campaign, policies and records.

**Dual-sensor example.** Use the banked, unordered checker (selector `50`,
data `04`), three-byte `A6 00 xx` reads with quotas of one, and absolute
deadlines 650 and 700 clocks. Load the following triples at offsets 0–2 of
the indicated base. Write selector `51` with data `03`, then control `34`.

| Base | Data at offsets 0, 1, 2 | Effect |
| --- | --- | --- |
| `70` | `02 50 00` | Initially issue A at tick 2 and B at 80. |
| `74` | `04 20 00` | Tighten the notification gap. |
| `78` | `04 20 02` | Repeat those times with B's status flag inverted. |
| `7C` | `46 08 01` | Issue B before A and invert A's flag. |
| `60` | `61 00 01` | PASS with empty source mask selects profile 1. |
| `64` | `72 00 02` | TIMEOUT of B alone selects profile 2. |
| `68` | `6B 00 03` | DUPLICATE of A alone selects profile 3. |

To explore repeated missed-B outcomes, load `72 02 03` in rule 0 and move
the three example rules down one slot. A current missed B preceded by any
TIMEOUT now takes profile 3. A first missed B still takes profile 2. The two
history predicates examine verdict classes; only the current event has a
source-mask predicate.

**Readback.** Present the address on `ui_in` without a strobe and read the
nibble on `uo[7:4]`. Page `C0` returns busy in bit 3 and the number of
archived trials in bits 2:0 (0–4). Pages `80–8F`, `90–9F`, `A0–AF` and
`B0–BF` return records 0–3 in execution order. An unfilled row reads as
zero. The following offsets are relative to the start of a row.

| Offset | Nibble |
| --- | --- |
| 0, 1 | Valid bit 3 and verdict bits 2:0; then implicated source mask. |
| 2–5 | 16-bit decision tick, least significant nibble first. |
| 6–7, 8–9, A | Applied A and B timing parameters (absolute issue tick or trigger delay, low nibble first) and the two status-inversion bits. |
| B, C | Previous verdict and verdict two trials back. Zero indicates absent history. |
| D | Applied profile in bits 3:2, selected destination in bits 1:0 (applied profile if unmatched). |
| E | Bit 3 means a subsequent trial was launched, bit 2 means a rule matched, bits 1:0 identify that rule when matched. |
| F | Bit 0 records an explicit STOP from the winning rule. A matched non-STOP action with continuation clear reached the configured bound. |

Parameter snapshots survive later profile edits and manual runs. The P4
pages at `00–0B` retain the detailed witness for the latest trial. To replay
a campaign, retain the loaded P1–P4 settings, policy, starting SPI history
and controller traffic alongside the compact log.
