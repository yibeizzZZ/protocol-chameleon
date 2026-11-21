# Protocol Chameleon

Protocol Chameleon is FoRG's prototype for a reprogrammable protocol emulator on the Tiny Tapeout IHP 130 nm platform. The research question is how much protocol behavior a chip can learn after fabrication while still responding on the device's clock. Protocol execution, transaction history, and checking logic must share an **8×4-tile budget** (roughly 1 mm² nominal).

The GPIO engine runs a protocol written after its RTL was frozen. Two independent AI authors used the public instructions to implement a previously withheld two-vote handshake. A pin-level peer checked 114 frames. Build and run this example and four others with `make -C test p1`. [Programming guide](docs/P1_PROGRAMMING.md) · [Held-out protocol, authorship and negative control](docs/P1_HELDOUT.md)

A second experiment loads different peripheral models into the same SPI byte engine. One A write can authorize a B read, or a program can require two successive affirmative writes. A completed B read consumes the authorization. A trial can schedule another event from the reply actually observed on MISO, check it against a separately loaded expectation and change the next trial's model parameter. [Peripheral model sources](examples/) · [Pin tests](test/test_models.py) · [Physical acceptance and artifacts](docs/PHYSICAL_ACCEPTANCE.md)

## The experiment

Imagine a flight controller reading sensor A over SPI when sensor B signals that new data is ready. The emulator must finish A's reply on the live bus. To determine whether the controller handled B correctly, it must also remember both notifications, associate each read with its source, and track two independent deadlines. If the controller misses B, the next trial can repeat the event at a different offset to narrow down when the failure occurs.

The design proposal divides that experiment into two research goals.

- **Part A — Reprogrammable protocol emulation.** Load a description that changes framing, pin direction, timing, transaction boundaries, and legal transitions on the same chip. The proposed acceptance test includes a clocked protocol disclosed only after the hardware design is frozen.
- **Part B — Autonomous real-time testing.** Relate traffic to earlier events, classify the result, and choose the next response or trial locally. The proposed programming model covers the protocol (P1), peripheral behavior (P2), stimuli and trial timing (P3), checking rules (P4), and feedback policy (P5).

The sequencer implements a subset of P1. The SPI peripheral supplies per-address status history and four bits of shared state for loaded P2 models. P3/P4 support one programmable event per sensor with independent service deadlines. P5 can select among four loaded parameter profiles. General transaction models, full trace replay and the concealed-variant benchmark remain research goals. [Design proposal (Word)](FoRG%20%E2%80%94%20Causal%20Feedback%20Protocol%20Emulator%20_%20Research%20Proposal%20v0.7.docx)

## What the RTL implements

| Interface | Behavior |
| --- | --- |
| I²C controller write | A 16-byte timed GPIO program generates START, a seven-bit write address, one data byte and STOP. It samples both ACK slots and skips the payload on address NACK. An independent target verified 100 and 400 kHz. [Programming and reproduction](docs/info.md#timed-open-drain-gpio-and-i2c-write) |
| UART | Independent TX and RX. Reset selects 8N1 at 434 clocks per bit, approximately 115200 baud with a 50 MHz clock. Runtime configuration selects 7 or 8 data bits, 1 or 2 stop bits, and 8–4096 clocks per bit. Each direction snapshots its settings at the start of a frame. |
| Programmable sequencer | Up to 16 one-byte instructions control four bidirectional pins. A program can set levels and directions, sample an input, delay, wait for a rising or falling edge on one pin while sampling another, and branch on the latest sample. The host can read the four most recent sample bits. |
| SPI target | The host selects CPOL/CPHA and programs four status registers and their read-to-clear masks. A separate serial shifter returns the addressed byte within the same CS window. See the [SPI programming interface](docs/info.md#spi-status-peripheral) and [RTL](src/spi_target.v). |
| Byte transaction program | The same 16-byte instruction store can supply eight two-byte rules to the SPI shifter. Each completed byte can select the next state and schedule the next reply. See the [rule encoding and example programs](docs/info.md#load-a-byte-transaction-program). |

For example, the ten-byte program below describes a repeating, externally clocked one-bit exchange. On a rising edge of P0, it samples P1 and branches to drive the sampled value on P2. It holds P2 through the falling edge, releases the pin, and returns to wait for the next request.

```text
81 65 10 24 77 14 24 91 20 70
```

To load it from reset, present each byte on `ui_in[7:0]` and strobe `uio[0]` once per byte, with at least one sampled low clock between strobes. Set `uio[3]=1` and write `00 83` to enter the engine, set `uio[3]=0` for the program bytes, then set `uio[3]=1` and write `02` to run. The same sequencer can instead generate a self-timed two-pulse burst by loading a different program. Pin ownership matters when switching modes because P0–P3 are outputs in UART mode. The [interface guide](docs/info.md) documents the pin mapping, both byte sequences, instruction timing, and turnaround procedure.

## What would establish success

The proposal calls for independent reference traces for UART, SPI modes 0–3, and I²C at 100/400 kHz, followed by the withheld-protocol test. Two timing targets are a history-dependent SPI target reply on the first required edge at 5 MHz and SWD-style turnaround and acknowledgement at 1 MHz. The current sequencer synchronizes external edges and observes them only while the matching wait instruction is active. Edges can be missed during a branch or delay, so the one-bit example does not establish either timing target.

For Part B, the proposal calls for checking at least 100 deterministic valid traces and reproducing a failure on at least eight of ten concealed device variants within 128 valid trials per variant. The planned comparison uses RP2040 PIO with CPU/DMA and a compact FPGA under the same device behavior and deadlines. Physical area, worst-case latency, supported history depth, and host involvement will show which capabilities fit together within the tile budget.

## Source files

- [Tiny Tapeout top level](src/project.v) and [project manifest](info.yaml) define the external interface, pin multiplexing, source list, and tile allocation.
- [UART transmitter](src/uart_tx.v), [receiver](src/uart_rx.v), and [runtime configuration](src/serial_config.v) implement the UART path.
- [Protocol engine](src/protocol_engine.v) contains the instruction store, pin controls, edge sampling, and branch logic.
- [Transaction observer](src/transaction_observer.v) captures marked fields from MOSI and MISO and closes records on the byte program's end mark.
- [Trial checker](src/trial_checker.v) schedules notifications and classifies SPI service. The [feedback policy](src/feedback_policy.v) records each result and selects the next trial.
