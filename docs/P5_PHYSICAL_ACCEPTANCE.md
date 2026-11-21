# Feedback operand release

The GDS, post-route timing reports and regression results in this release were built from commit `6fd555b7e008227d7bcdaa2b921525284ff5e062`. The last RTL change was `46af4d2`. The freeze commit added one latency test. Its RTL and manifest match `46af4d2` byte-for-byte. The build used a detached, clean checkout, the existing nine Verilog files and the 8×4 IHP CMOS5L macro `tt_um_forg_protocol_chameleon`. [Submission and evidence ZIP](../release/protocol-chameleon-6fd555b.zip)

## Acceptance

Before hardening, 11/11 assembler tests and 66/66 pin-level RTL tests passed. After routing, the same 66/66 tests passed on the packaged functional gate netlist. The suite covers full and interrupted cross-device mailbox reads, transaction-field capture, two independently writable device cells, rule-only replay on identical wire traffic, operand reseeding, wraparound, missing captured data, and trial completion during an active SPI frame. Campaigns ran autonomously between trials. [Model and latency cases](../test/test_models.py)

| Official 50 MHz implementation | Previous release `59f32fd` | Feedback operands `6fd555b` |
| --- | ---: | ---: |
| Mapped cells / mapped area (µm²) | 8,782 / 135,059.135 | 10,246 / 155,696.310 |
| Routed standard-cell area before filler (µm²) | 166,250 | 191,515 |
| Pre-filler core utilization | 13.7604% | 15.8517% |
| Worst setup / hold slack (ns) | +2.795 / +0.116 | +1.788 / +0.104 |
| Violating setup / hold paths | 0 / 0 | 0 / 0 |
| Detailed routing / antenna / Magic DRC / LVS errors | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| Tiny Tapeout precheck | 10/10 | 10/10 |
| Hardening / precheck wall time | 49:21 / 30:25 | 45:17 / 32:39 |

All three cell corners used nominal extracted interconnect. Setup and hold TNS are zero. Netgen reported a unique circuit match. The official configuration runs the SG13 CMOS5L KLayout DRC deck in the separate Tiny Tapeout precheck. Setup, hold, slew, capacitance and physical checks passed. STA reports 104 max-fanout advisories. Two are outside the clock tree (`fanout476/X` and `fanout471/X`). The per-corner checks are archived under `evidence/sta/`. The worst setup path runs from `ui_in[6]` to `uo_out[7]`. [Previous release and tool versions](PHYSICAL_ACCEPTANCE.md)

## Measured P5 latency

The independent master left B unserviced, causing P4 to register TIMEOUT. All four feedback rules were enabled and rule 3 won. Two separate loaded policies exercised a carry-producing add (`7F + 1 = 80`) and copying a captured MOSI byte (`A5`). For each operation the peer swept 22 launch offsets in each of the four 5 MHz SPI modes at a 50 MHz system clock, giving 176 campaigns. Each campaign checked the old and new reply independently on the resolved MISO pin.

| Measured interval | Result |
| --- | ---: |
| P4 verdict rising clock edge → working operand updated and trial archived | 1 clock / 20 ns |
| Verdict → next trial accepted (verdict page clears) | 2 clocks / 40 ns |
| Verdict → next trial tick zero (both notifications active) | 3 clocks / 60 ns |
| External launch edge → changing edited reply bit on MISO | 40.1–60.0 ns (2.005–3 clocks), at least 40.0 ns before sampling |
| Verdict → first changed reply bit in this poll, modes 0 and 2 | 3.360–3.380 µs |
| Same interval, modes 1 and 3 | 3.460–3.480 µs |

The first row uses direct observation of the working operand in RTL. The gate run observed the archive count, trial restart, notifications, edited reply and logged operand through pins. The last two rows include the controller's tested CS schedule, header and command bytes. Delaying the next poll delays that visible response. Gate simulation used the functional PDK models without SDF.

## Extracted P5 register paths

Each row below reports the slow-corner path selected for worst setup between the indicated register groups. Delay runs from the launching flip-flop clock pin through clock-to-Q and extracted logic/interconnect to the destination D pin (or macro port). Slack uses the official propagated clock, uncertainty and SDC. The tightest setup path into a working operand starts at the P4 event-source mask. The tightest register-to-working-operand hold check was +0.139 ns at the fast corner. These arcs operate on different cycles. The archive includes all 15 groups at three corners, both max and min, including source mask, two verdict histories, edit descriptor, validity, trial log and shifter launch. [STA extraction tool](../test/report_p5_sta.py)

| Path | Clock pin → endpoint (ns) | Setup slack (ns) |
| --- | ---: | ---: |
| Worst register into either working operand | 8.278 | +11.209 |
| P4 verdict → P5 working operand | 7.705 | +11.771 |
| P4 event-source mask → working operand | 8.278 | +11.209 |
| Previous verdict → working operand | 7.856 | +11.632 |
| Loaded edit descriptor → working operand | 4.087 | +15.405 |
| Working operand → working operand (update cone) | 3.461 | +16.067 |
| Captured wire byte → working operand | 2.907 | +16.587 |
| Working operand → trial record | 2.284 | +17.195 |
| Working operand → CS-time snapshot | 2.695 | +16.830 |
| Snapshot → SPI branch state | 2.882 | +16.592 |
| Snapshot → SPI reply shift register | 2.177 | +17.281 |
| Reply shift register → MISO register | 2.454 | +17.024 |
| MISO register → macro output | 0.965 | +13.978 |

At the slow corner, system-clock-to-macro arrival was 1.772 ns at MISO and 2.509 ns at its enable. Raw deselect to enable took 1.079 / 1.218 ns from the two select inputs after subtracting the SDC's 4 ns input allowance. The external SPI clock is asynchronous to the system clock. The digital phase sweep and extracted macro reports leave synchronizer metastability, pad and board loads, peer setup/hold and silicon measurements open.

## Reproduce and verify

Use the official action `ttihp27a` and the pinned tools, PDK and 20 ns constraints described in the [physical setup](PHYSICAL_ACCEPTANCE.md#reproduce). Check out `6fd555b` for the design and tests. Run the RTL regression first, then `--create-user-config`, `--harden` and `--create-tt-submission`. Precheck and gate simulation were started on immutable stage outputs while Magic DRC was running. Their GDS, LEF and gate netlist were compared byte-for-byte with the official submission after hardening. The netlist and SPEF read by all three STA corners were also compared to the submission. The archive contains the exact design/test sources, their Git tree IDs, JUnit results, logs, generated timing commands, extracted path CSV, datasheet and submission views.

```sh
# Linux, from the checkout with the simulation dependencies active
python -m unittest discover -s test -p test_p1_assembler.py
make -C test FST=-none
python -m cocotb_tools.check_results test/results.xml
# After hardening, with PDK and PDK_ROOT set, use Icarus 13 for PDK gate models
cp tt_submission/tt_um_forg_protocol_chameleon.v test/gate_level_netlist.v
GATES=yes make -C test FST=-none COCOTB_RESULTS_FILE=gate-results.xml
python -m cocotb_tools.check_results test/gate-results.xml
# Use the script shipped under evidence/ in the ZIP, or the linked repository copy
python3 /path/to/report_p5_sta.py runs/wokwi /absolute/path/to/p5-sta --container YOUR_FLOW_CONTAINER
# After extracting the release ZIP
sha256sum -c SHA256SUMS
```

The external human replication and ten concealed DUT evaluations in the product specification remain open. [Acceptance demonstrations](PRODUCT_SPEC.md#5-required-acceptance-demonstrations)

The timing reporter uses the original absolute PDK, run and constraint paths recorded by LibreLane. Mount them at the same paths in the flow container. Omit `--container` when running inside the flow environment.

| SHA-256 | Digest |
| --- | --- |
| Release ZIP | `86ed81c937e7577b344e058e88c956ec0ac8c959e2c3e6bedb9aca31c4310946` |
| GDS | `3978cdc0c98c1cc9a42be2a66fe5b0d8231e41944d0affa9c13743ce3c541af3` |
| Routed functional netlist | `5fec6aa225ae05acdc470a4c8cbafd209660146c5c1ee7116d81456d3c41cd06` |
