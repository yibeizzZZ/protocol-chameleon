<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

UART TX and RX operate independently and can run simultaneously. The provisional 50 MHz
clock matches the template's 20 ns clock period. Each bit lasts 434 clocks,
giving approximately 115200 baud. The TX line idles high. A frame consists
of one low start bit, eight data bits (least significant first), and one high
stop bit.

## Pin interface

| Pin | Direction | Function |
| --- | --- | --- |
| `ui_in[7:0]` | Input | Byte to send, with bit 0 transmitted first |
| `uio[0]` | Input | Send strobe, synchronous to `clk` |
| `uo_out[0]` | Output | UART TX |
| `uo_out[1]` | Output | Busy from acceptance through the full stop bit |
| `uo_out[2]` | Output | Done pulse lasting one clock after the stop bit |
| `uio[1]` | Input | UART RX serial line; drive high when idle |
| `uo_out[7:4]` | Output | Received byte, bits 7 through 4 |
| `uio[7:4]` | Output | Received byte, bits 3 through 0 (bit 0 on `uio[4]`) |
| `uo_out[3]` | Output | RX valid, one clock when a byte is accepted |
| `uio[2]` | Output | RX framing error, one clock for a low stop bit |

`uio[3]` is unused and configured as an input.

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
low. A false start is discarded silently. It then samples the eight data bits
and the stop bit at one-bit intervals, near their centers.

A high stop bit publishes the received byte and pulses RX valid on the same
clock. The byte stays on the pins until the next accepted frame or reset.
A low stop bit pulses RX framing error and preserves the last accepted byte.
After an error, RX waits for the line to return high before accepting another
start bit. A synchronous active-low reset discards any partial frame and
clears the received byte and both RX status outputs.
