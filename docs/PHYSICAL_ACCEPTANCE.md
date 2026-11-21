# Physical acceptance and verification evidence

For the release with field capture, writable device bytes and feedback operands, see the [acceptance results and GDS for `6fd555b`](P5_PHYSICAL_ACCEPTANCE.md). The comparison below covers the two earlier releases.

The frozen P1 build uses `d95090b`. The integrated peripheral-model logic is `86d9f79`. The release build at `59f32fd` uses the project-specific top name `tt_um_forg_protocol_chameleon`. The frozen P1 checkpoint uses the template top name `tt_um_example`. All builds share the same nine-source file list, 20 ns system clock, 8×4 tile outline and Tiny Tapeout port directions. The title, description and author (FoRG) are present in the committed manifest. Build inputs are identified in each official `tt_submission/commit_id.json`. The testbench and datasheet corrections are in `4f1325e`. The block name follows [Tiny Tapeout integration guidance](https://tinytapeout.com/hdl/important/). [Manifest](../info.yaml) · [Top and pin multiplexing](../src/project.v) · [Programming interface](info.md)

## Measured results

| Measurement | Frozen P1 | Integrated P2–P5 revision |
| --- | ---: | ---: |
| Official Yosys mapped cells | 8,584 | 8,782 |
| Official mapped area, µm² | 129,150.806 | 135,059.135 |
| Routed standard-cell area before filler, µm² | 159,116 | 166,250 |
| Routed core utilization before filler | 13.1699% | 13.7604% |
| Worst extracted setup at 50 MHz, ns | +3.710 | +2.795 |
| Worst extracted hold at 50 MHz, ns | +0.119 | +0.116 |
| Setup / hold violating paths | 0 / 0 | 0 / 0 |
| Detail-route errors / antenna violations | 0 / 0 | 0 / 0 |
| Magic DRC errors / Netgen LVS errors | 0 / 0 | 0 / 0 |
| Tiny Tapeout Precheck | 10/10 | 10/10 |
| Post-route functional gate tests | 53/53 | 58/58 |
| Hardening wall time | 49 min 06 s | 49 min 21 s |
| Precheck wall time (overlapped hardening) | 33 min 54 s | 30 min 25 s |

After normalizing the single top-module identifier, the routed functional netlists for the integrated and renamed builds compare byte-for-byte equal. Both independently routed with identical extracted slack and occupancy.

The official flow's mapped area rose by 5,908.329 µm² (4.57%). The macro measures 1,724.16 × 710.64 µm. Pre-filler utilization divides the standard-cell area by the 1,208,170 µm² placement core. Filler-inclusive occupancy would obscure the useful comparison. The nominal-RC corners are slow 1.08 V / 125 °C, typical 1.20 V / 25 °C and fast 1.32 V / −40 °C. Both builds have zero max-slew and max-capacitance violations. STA still reports 86 and 90 max-fanout violations respectively. One integrated violation is outside the clock tree (`fanout306/X`). The official pass/fail checks allow these advisories.

For comparison with earlier milestones, the standalone typical-library mapping increased from 6,018 to 6,217 cells (1,210 to 1,263 flip-flops), and from 106,765.457 to 112,217.351 µm². Ideal-clock register setup slack went from +13.074 to +12.195 ns. These are pre-layout estimates from the [lightweight synthesis script](../test/synth_estimate.sh). The table uses the official physical flow throughout.

In the integrated revision the overall slow-corner setup path runs from host input `ui_in[6]` to readback output `uo_out[4]`, with 4 ns input and output delays. Worst register-to-register setup is +10.848 ns, from the engine input synchronizer to the feedback timestamp. The smallest hold margin occurs at the fast corner between bits 0 and 2 of the UART transmitter countdown. The archive includes the full setup and hold path reports.

## What can be programmed

- **P1.** Two authors independently encoded a withheld protocol after the GPIO hardware freeze. The sealed peer checks variable wait counts, edge polarity, two-frame state and a 200 ns output deadline over 114 frames. The general GPIO store has 16 instructions. There is a dedicated UART and an accelerated SPI byte engine. [Held-out test and provenance](P1_HELDOUT.md)
- **P2.** Load the one-vote and two-vote programs into the same SPI engine. On the same wire request, the response depends on earlier writes to a different device. A completed read consumes the grant. Truncated votes and reads do not update the relevant state. The SPI engine offers eight byte rules, a shared four-bit state register and a four-bit model parameter captured per physical selection. [Public instructions and sources](P1_PROGRAMMING.md#spi-byte-programs-and-logical-transactions)
- **P3 and P4.** A loaded event rule can look at a byte captured from MOSI or MISO, then schedule a notification. The checker independently compares observed wire fields with its own contract. In the model test, selecting a different expected trigger byte makes the same reply either schedule A at tick 407 or leave it unissued. The design has two event slots, one reactive trigger and a fixed vocabulary of observation fields, predicates and verdicts. [Event registers](info.md#transaction-triggered-p3-notifications)
- **P5.** A loaded feedback profile changes the model predicate for the next trial, in addition to its timing controls. For the same DUT requests, changing the profile parameter alone makes the second trial return `A5` instead of `00`. The independent P4 contract reports WRONG_CONTENT for B at tick 598 and captures `A5`. The host can read back the trial parameters. The ASIC made both trial decisions autonomously. The campaign is bounded to four rules, four profiles and four trials. [Pin-level experiments](../test/test_models.py)

## I/O timing and board operation

At 50 MHz system clock, the 5 MHz SPI model test swept 22 launch offsets in each of modes 0–3, recording 154 MISO payload transitions per mode. RTL and the routed functional netlist gave 40.1–60.0 ns from external launch edge to changing MISO (2.005–3.000 system periods), with at least 40.0 ns before sampling. The 1 MHz shared-wire register test observed 60.1–80.0 ns drive and release across 198 replies; it exercises custom turnaround, and full SWD framing/ACK remains open.

With extracted interconnect and the official clock constraint, slow-corner arrival from the system clock to the MISO block port was 1.727 ns, and to its enable was 3.085 ns. Combinational release from the two CS inputs to enable measured 1.276 / 1.328 ns inside the macro after subtracting the 4 ns input delay. These measurements bound individual modeled paths. SCLK, CS and MOSI enter asynchronous synchronizers. Clock phase, metastability, relative input skew, pad delays, I2C pull-up rise time, board loading and the controller's actual setup/hold determine the external margin. Functional gate simulation used the PDK cell models without SDF. Silicon-level SPI timing is open.

On the board, supply pull-ups for timed open-drain P0/P1, release shared host drivers before changing ownership, and establish idle clock before starting an edge-wait program. After power loss or tile reselection, reset and reload the volatile image and descriptors through the documented strobe. [Pin ownership and host loading](info.md)

## Reproduce

The repository workflow uses the Tiny Tapeout IHP GDS action `ttihp27a` (action commit `e7a50f8f46f9f8df4b2c9935bfeb1cbc6b6ae4f6`). Local runs used its support tools at `0922544e6c7f6126047c3fba720b0437fa32a1b8`, LibreLane `3.1.0.dev4` (container digest `sha256:af2405f5d48d8fe14d406ecce913811177a95e365e3b625859677307cace2469`), IHP PDK `89d42ee6d2fd9b50b86a1aada6fee6673c3e6008` and KLayout 0.30.8. Use a checkout of the RTL revision, the action's Python/PDK prerequisites and commands below. For the earlier template-name checkouts, apply the shared-wire idle-clock correction from `4f1325e` to the test harness. The release already includes both the test fix and the two corrected datasheet references. Use the top name belonging to that revision for the GDS and routed netlist. [Official workflow](../.github/workflows/gds.yaml) · [Cocotb prerequisites](../test/README.md#reproduce-the-functional-tests)

```sh
export PDK=ihp-sg13cmos5l PDK_ROOT=/path/to/installed/pdk CI=1
git clone https://github.com/TinyTapeout/tt-support-tools tt
git -C tt checkout 0922544e6c7f6126047c3fba720b0437fa32a1b8
./tt/tt_tool.py --create-user-config --pdk "$PDK"
./tt/tt_tool.py --harden --pdk "$PDK"
./tt/tt_tool.py --create-tt-submission --pdk "$PDK"
gds="$PWD/tt_submission/tt_um_forg_protocol_chameleon.gds"
(cd tt/precheck && python precheck.py --gds "$gds" --tech "$PDK")
./tt/tt_tool.py --check-docs
./tt/tt_tool.py --create-pdf
python -m unittest discover -s test -p test_p1_assembler.py
make -C test FST=-none
python -m cocotb_tools.check_results test/results.xml
cp tt_submission/tt_um_forg_protocol_chameleon.v test/gate_level_netlist.v
make -C test GATES=yes FST=-none COCOTB_RESULTS_FILE=gate-results.xml
python -m cocotb_tools.check_results test/gate-results.xml
```

The project-specific release used its committed sources directly. Use Icarus 13 for the PDK gate models and Cocotb 2.0.1. The integrated RTL suite also passed on Icarus 12. The initial baseline gate run on Icarus 13 passed 51/53. Both failures came from the same external peer driving idle clock after RUN; establishing that level three system clocks before RUN fixed both cases with their waveform expectations intact. Tiny Tapeout's PDF build also exposed two unresolved section links. The corrected datasheets rendered to 24 and 25 pages for the two revisions. A local KLayout container invocation initially failed to start with an explicit Unix UID; using its default user ran the original precheck decks. Neither the layout nor the rule decks were edited for these corrections.

## Release evidence

[Integrated official submission and evidence ZIP](../release/protocol-chameleon-59f32fd.zip) includes the GDS, LEF, routed netlist, SPEF, OASIS, synthesis statistics, flow configuration, datasheet, timing reports, tests and precheck. Files inside `tt_submission/` are the official tool outputs. The precheck inputs (GDS, LEF and netlist) and gate-test netlist were compared byte-for-byte with their packaged counterparts. Extract the ZIP and run `sha256sum -c SHA256SUMS` in its root.

| Digest | SHA-256 |
| --- | --- |
| Integrated release ZIP | `7413d33314f2e82c246c3ca03b3a642a489e64c9e12e937205a3bbfa96a4adee` |
| Integrated GDS | `ec52450ad302d5c336f80c8b181bd8785a5b8a36faa97ddcdb4cf1d863fea903` |
| Frozen P1 GDS | `b004f9da6e55b30a02786e05d9eff83454b3eddbea9b47ffde182d9694254754` |

The release supplies local evidence for the published competition baseline. External human replication, the ten concealed DUT variants with confirmation runs, board timing and organizer acceptance remain open. [Project acceptance criteria](PRODUCT_SPEC.md#5-required-acceptance-demonstrations) · [Competition requirements](JANE_STREET_COMPETITION.md)
