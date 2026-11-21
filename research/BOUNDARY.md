# Experiment C — Frozen SPI emulator operating boundaries

The experiment uses fixed synthetic SPI traffic and the Icarus model of commit `6fd555b7e008227d7bcdaa2b921525284ff5e062`. The system clock is 50 MHz (20 ns). The serial clock is 5 MHz (100 ns between launch and sample). A tick is the checker’s system-clock index from trial start. Timing values describe this digital simulation.

## Test design

| Sweep | Loaded program and external checks |
| --- | --- |
| CS framing | A two-rule stream program tags the address and closes each record after its second byte. The peer sends the same six MOSI bytes and expects the same six MISO bytes for three logical records, A, A, B. Group sizes per CS assertion are 3, 2+1 and 1+1+1. Multiple windows have 100 or 500 ns deselection. Checker quotas are 2 and 1, with lengths, identities, command, address, reply data and order checked. |
| Event overlap | With CS held low, A issues at tick 0 and B issues at 0, 1, 160, 322, 331, 332 or 333. A’s two-record quota closes at its deadline of 322. B’s first synchronized sample is 332 and its closing sample is 482. Each B issue is crossed with deadlines 481, 482 and 483. The peer reads terminal verdict, source mask, stamp and counts, and records IRQ changes. |
| Program complexity | Four images occupy 2, 4, 6 or 8 rules. Each comparison checks a distinct byte and restarts at state 0 on a match. A mismatch advances to the next comparison. After 1, 3, 5 or 7 comparisons the final literal instruction schedules A5 on the next byte. Each image takes a full fall-through path and a second path that restarts on its last comparison. Both paths cross modes 0–3 with phases 0, 9.9, 10.1 and 19 ns. The resolved pad must match every expected bit, including the first bit of A5. |
| Capacity | Submit a fifth, 18-byte image to the same loader. Its eight comparisons would require a ninth instruction to emit A5. Observe the tenth MISO byte after eight mismatches and a dummy byte. |
| Checking and feedback | A one-byte command mismatch at the end of a marked two-byte record produces WRONG. A separate two-trial campaign lets a fixed synthetic service window expire. A loaded TIMEOUT rule selects profile 1, whose A event is scheduled at tick zero. |

Phase is the additional delay after a fixed 40 ns lead-in from the start of the 20 ns core clock waveform. Its rising edge is at phase 10 ns. The frozen pin monitor checks the complete response, at least 20 ns of setup and 10 ns of hold at each sample. Its per-transition L1 measurement starts at the external launch edge and ends at the last transition to the correct resolved MISO level before sampling. The first A5 bit rises from the preceding zero and is directly measurable on every complexity path. Unchanged bits contribute to correctness and stability checks.

## Resource limits

| Resource | Frozen capacity | Use in this experiment |
| --- | --- | --- |
| SPI rule storage | Eight 16-bit rules in the shared 16-byte instruction store, three-bit branch target, six annotation bits per rule | Two annotated rules for framing and timing overlap. The four complexity images occupy 4, 8, 12 and 16 bytes. The capacity probe submits 18 bytes. |
| SPI model memory | Four 8-bit status entries with per-entry masks and seen bits, four shared state bits and two writable bytes | STREAM reads configured status data. Complexity chains exercise serial byte state and branch depth. |
| Event checker | Two event descriptors, independently timed, one to four records per source; a single open stream record | A and B quotas of two and one. A and B can be simultaneously outstanding. Records share one SPI wire and execute serially. |
| Feedback | Four policy rules, four parameter profiles, four stored trial records, two previous verdicts; two writable 8-bit operands | One rule, two profiles and two trials for the new L3 probe. The archived operand test also exercises a four-rule match. |
| Whole design area and timing | Frozen release reports 10,246 mapped cells, 155,696.310 µm² mapped area, 191,515 µm² pre-filler routed cell area, 15.8517% core utilization, +1.788/+0.104 ns setup/hold slack | All sweeps load the same hardware. Area is a release figure for the full macro. Per-program logic area and new place-and-route measurements are outside this experiment. |

Capacity and implementation figures come from the [byte-program and trial interface](../docs/info.md), [program storage RTL](../src/protocol_engine.v), [SPI target](../src/spi_target.v), [feedback policy](../src/feedback_policy.v) and [frozen physical release](../docs/P5_PHYSICAL_ACCEPTANCE.md).

## Reproduce

On Linux or WSL, use Git, GNU Make and Icarus Verilog 12.0. From the repository root, with a Python 3.11 virtual environment active, run

```sh
python -m pip install cocotb==2.0.1 matplotlib==3.10.3
python research/run_boundary.py --out research/results/boundary
```

The runner exports the frozen source files and public test helpers into a new temporary directory. It compiles the RTL, runs the matrix, checks the Cocotb result XML, writes the [case-level CSV](results/boundary/cases.csv) and renders the [boundary plot](results/boundary/boundary.png). A development subset can be selected with `--smoke --out /tmp/boundary-smoke`. The CSV records every eligible transition delay for each transfer in picoseconds. MOSI and MISO byte strings are hexadecimal, and the MISO strings contain the values checked against the pad on every sampled bit. IRQ transitions are tick/mask pairs, with bit 0 for A and bit 1 for B.
