# RTL verification

For the integrated logic at `86d9f79` and its project-named release at `59f32fd`, all **58 pin-level tests and nine assembler tests passed**. Five peripheral-model cases extend the 53-case P1 baseline. The shared-wire peer establishes the idle clock before RUN in test revision `4f1325e`. Run `make -C test p1` for the assembler and five compiled P1 pin tests. [Physical and gate-level evidence](../docs/PHYSICAL_ACCEPTANCE.md)

The subsequent wire-field capture extension passes **61/61 RTL tests** and **9/9 assembler tests**. Three new pin tests check a DUT-chosen token under continuous CS, schedule an event using the previous payload, and exercise trial-local capture across autonomous feedback. On the previous RTL, replaying a changed contract wrongly passed and the notification fired on the first record. With capture enabled in the reactive example, the second record schedules the notification at tick 483. Run `make -C test COCOTB_TEST_MODULES=test_transactions` for the focused suite. [Programming contract](../docs/info.md#capture-a-wire-field-for-use-in-a-later-transaction)

The comparable typical-library estimate increased from 112,217.351 to 115,381.249 µm² (+2.82%) and from 1,263 to 1,288 flip-flops. Ideal 20 ns register-to-register setup slack was +13.147 ns. The SPI model RTL sweep still observed 40.1–60.0 ns to MISO in all four modes. The archived routed results apply to `59f32fd`; this extension has only RTL simulation and pre-layout mapping/STA.

## Reproduce the functional tests

The M10 run used Ubuntu 26.04 under WSL, Python 3.11, Icarus Verilog 12.0, GNU Make 4.4.1 and Cocotb 2.0.1. From the repository root on Linux with Python 3.11 and its venv support installed, use the same Makefile, simulator and result check as the [repository's Tiny Tapeout workflow](../.github/workflows/test.yaml).

```sh
sudo apt-get install -y make iverilog
python3.11 -m venv /tmp/chameleon-verify
. /tmp/chameleon-verify/bin/activate
python -m pip install -r test/requirements.txt
cd test
make clean && make && python -m cocotb_tools.check_results results.xml
```

`results.xml` records each case and `tb.fst` contains the waveform. The [testbench](tb.v) resolves external and DUT drivers on the same digital pads. The [host driver](pins.py) also checks for simultaneous enables every sampled clock, so even two drivers producing the same value are detectable in the driven scenarios.

| Suite | Passed | Externally observed behavior |
| --- | ---: | --- |
| [UART and runtime configuration](test_uart.py) | 7 | Independent TX and RX messages in full duplex, bit-cell lengths and order, busy/done timing, held and busy strobes, valid/error pulses, both bad stop positions, false start, break recovery, consecutive frames and reset mid-frame. Covers 8N1, 7N2, 8N2, 7N1, 8–4096 clocks/bit endpoints, incomplete and invalid descriptor writes, reconfiguration during TX/RX, and UART operation across an engine handoff. An independently timed peer sends at 315 and 325 ns/bit with RX configured for 320 ns/bit. |
| [Programmable sequencer](test_engine.py) | 5 | Exact two-pulse waveform and replay, both conditional reply paths, rising/falling edge samples, sample history, GPIO value and direction, held-level versus edge detection, and a missed edge during delay. Covers empty RUN, 16th and excess bytes, stale addresses after CLEAR, reserved opcode, writes while running, STOP during delay/wait, EXIT and reset. A deliberate opposing drive produces an X on the resolved pad and clears when the peer releases it. |
| [SPI peripheral](test_spi.py) | 4 | Modes 0–3 with independently clocked transactions and pad-level setup/hold checks, address-local history, aborted and extra clocks, invalid headers, live reprogramming, ignored busy writes, CS release, UART handoff and reset. |
| [SPI byte programs](test_byte_program.py) | 3 | Runtime transaction-format replacement, timing across all modes, incomplete images and stale targets. |
| [Trial planning and checking](test_trials.py) | 5 | Dual-source notification and deadlines, 112 deterministic traces, rule changes on the same traffic, invalid frames and active-checker SPI timing. |
| [Feedback campaigns](test_feedback.py) | 6 | Four-trial autonomous execution, two-verdict history, policy-only replay, stopping and retention, deadlines inside a selected frame, and SPI timing with a feedback-selected status mode. |
| [Logical transactions](test_transactions.py) | 12 | STREAM mismatch and compatibility, contract-only replay, boundary-only replay, input-dependent lengths and truncated tails, exact deadlines and start eligibility, read-history scope, missing fields, autonomous feedback and SPI timing. |
| [Transaction-triggered P3](test_reactive.py) | 6 | Rule-only and input-time replays, reverse target, omission, rejection and cancellation, hard and relative deadlines, four matches, partial records, feedback and SPI timing. |
| [Shared-wire GPIO register](test_shared_wire_register.py) | 1 | Two- and three-clock frames, read-after-write history, pin ownership and turnaround at 1 MHz across 22 phases. |
| [I²C write and timed GPIO](test_i2c_write.py) | 2 | Standard/Fast-mode writes and target NACKs, timed-mode loader settings, slot order, STOP, replay, sample readback and jumps beyond the loaded image. |
| [Compiled P1 examples](test_p1_sources.py) | 4 | Load editable GPIO, I²C, timed-pulse and annotated SPI sources. Check changed payloads and transaction boundaries on the pins. |
| [Held-out two-vote interlock](test_p1_heldout.py) | 1 | Check pin ownership, response deadline and vote history across 114 frames. [Protocol and seal](../docs/P1_HELDOUT.md) |
| [Runtime peripheral models](test_models.py) | 5 | Swap one- and two-vote models on the same wires, handle truncated writes and reads, gate notification on captured MISO, change the next trial's state predicate, freeze that parameter during CS, and exercise 5 MHz SPI in four modes across 22 phases. |

## I2C controller write

The independent target decodes START, MSB-first address and data, the ninth
clock of each byte and STOP from the two resolved pads. It drives only SDA
low using its own address match and ACK policy. The monitor checks pull-low
or release, the controller's SDA release on ACK, START hold, STOP setup, bus
free time, SCL periods and widths, data setup and the latest data/ACK transition
during SCL low. The timing limits come from the Standard- and Fast-mode columns
of the [NXP I²C specification](https://www.nxp.com/docs/en/user-guide/UM10204.pdf).

| SCL | Measured low / high | Transactions at this rate |
| --- | --- | --- |
| 100 kHz | 5.00 / 5.00 µs | Four accepted writes, one address NACK, one data NACK |
| 400 kHz | 1.32 / 1.18 µs | Four accepted writes, one address NACK, one data NACK |

Accepted address/data pairs (hex) were `52/A5`, `29/5A`, `37/00` and `68/FF`.
The target normally responded 360 ns after SCL fell. For the zero-data case
it delayed its response to 3.00 µs at 100 kHz and 0.80 µs at 400 kHz. The
same loaded image produced distinct pin readbacks for success, address NACK
and data NACK. The timing measurements use a 50 MHz clock and ideal digital
pull-ups. Run `make COCOTB_TEST_MODULES=test_i2c_write` in `test/` with the
environment above. [Host programming steps](../docs/info.md#write-one-byte)

Using the same typical IHP library and pre-layout estimation flow as M10,
timed GPIO maps to 6,018 standard cells including 1,210 flip-flops. Mapped
area is 106,765.457 µm² (+4.11% over M10). Worst register-to-register setup
slack at an ideal 20 ns clock is +13.074 ns (M10 was +12.677 ns).
The metadata-complete P1 checkpoint and subsequent shared-state design are compared in the [physical report](../docs/PHYSICAL_ACCEPTANCE.md).

## Transaction-triggered scheduling and latency

With the master asserting CS at trial tick 5, B rose at tick 175 for the
first accepted A and at 335 for the second. Only the occurrence selector
changed. Moving CS to tick 35 moved the first-trigger notification to 205.
A and B were both outstanding at the first-trigger notification. Omitting
the reads produced no B notification and timed out at tick 601. The suite
also reverses source and target, checks inclusive relative deadlines, and
observes queued notifications being suppressed after a terminal decision.
Run these cases alone with `make COCOTB_TEST_MODULES=test_reactive` in `test/`.

At 50 MHz system clock and 5 MHz SPI, each of the four modes ran at 22 phase
offsets. The campaign had four enabled P5 rules, selected rule 3 after a
timeout, used different first/repeat A responses, and triggered B while CS
remained low. The independent master checked every returned bit and its
20 ns setup / 10 ns hold window.

| RTL latency | Measurement points | Observed range |
| --- | --- | --- |
| L1 | External launch edge to changing MISO pad, 484 transitions per mode | 40.1–60.0 ns (2.005–3 system periods), minimum setup 40.0 ns. CS assertion to first drive also took 40.1–60.0 ns. |
| L2 | Final external command sample edge to stable WRONG_CONTENT and RESULT_VALID on the pins | 40.1–60.0 ns in every mode. With synchronized evidence ready, P4 registers the verdict on the closing tick. An unmet inclusive deadline at 600 produced TIMEOUT at 601. |
| L3 | P4 verdict to action record, checker restart and next trial tick zero | 1, 2 and 3 clocks respectively (20, 40 and 60 ns). In the tested campaign the new trial issued A at tick zero. |

These maxima cover the tested phases and histories in zero-delay RTL. The
deliberate P3 delay of 0–255 clocks starts at the synchronized transaction
end and is additional to the pin observation latency.

## Logical transaction results

On M8, three valid STREAM replies in one CS window produced only one service
under a six-byte contract (then TIMEOUT), or zero under a two-byte contract
(WRONG_CONTENT). Both results remain reproducible with an unannotated image.
On M9 the annotated image credits two A services and one B on that same CS.
Changing only the expected B response, tag, quota ordering, command, address
or length changes the verdict while all wire bytes remain identical.

Moving only the end marks in another six-state image recognizes either three
pairs or two triples in identical traffic. A conditional program also mixes
two- and three-byte records within one selection. In a two-trial autonomous
campaign, a logical PASS selected a status change, and the unchanged checker
then reported WRONG_CONTENT on the first read and captured the changed MISO byte.
To run just these cases, use `make COCOTB_TEST_MODULES=test_transactions` in `test/`.

## Feedback results

One RUN produced PASS → missed B → duplicate A → PASS. The master sent
only scheduled SPI transactions between trials. The scoreboard checked both
notification times, all decision ticks, source masks, selected rules, profiles
and history. A separate experiment held the current verdict at PASS. Histories
(PASS, TIMEOUT), (WRONG_CONTENT, TIMEOUT) and (PASS, WRONG_CONTENT), oldest
first, produced three distinct next-trial notification times. In another
replay the same timed A/B reads produced PASS in both runs. Changing one
rule's destination byte reversed the observed notification order in trial two.

Other cases exercised the four-trial bound, explicit STOP, no match, invalid
issue/deadline combinations, ignored busy writes and retention after profile
edits. When a deadline fell inside an SPI command byte, the checker recorded
TIMEOUT and the attempted restart on the still-selected CS recorded UNKNOWN.
The original frame delivered its selected status through the last bit.

## SPI measurements

With annotated STREAM and both reply comparisons enabled, the 5 MHz SPI
master swept 22 phases per mode against a 50 MHz system clock. All four modes
each produced 528 measured payload transitions. Launch to valid and CS to
first drive both took 40.1–60.0 ns (2.005–3 system periods). Minimum setup
was 40.0 ns. The oracle checked a 20 ns setup and 10 ns hold window at each
sample. These are zero-delay RTL measurements.

With P5 active, a timeout in trial one selected a different status mode for
sensor B in trial two. The test read A and B at 5 MHz through the loaded M6
stream program. In **each** SPI mode, 22 relative phases and 308 changing
payload bits gave 40.1–60.0 ns from launch to MISO valid (2.005–3.000 system
periods), at least 40.0 ns of setup, and 40.1–60.0 ns from CS to drive.
The pin oracle also checked a 20 ns setup / 10 ns hold window at each sample.

With the trial checker running, the [P3/P4 suite](test_trials.py) exercised
both physical chip selects at the same logical address with independent status
history. The loaded M6 stream program ran at 5 MHz against a 50 MHz system
clock in modes 0–3 and 22 relative phases per mode. Across 969 changing
payload bits, launch-to-MISO-valid measured 40.1–60.0 ns; the minimum
setup before sampling was 40.0 ns in each mode.

The independent transaction oracle also ran 112 deterministic captures
(16 schedules × seven scenarios), deriving verdict, source and exact tick
from the external CS schedule. These include simultaneous and overlapping
notifications, a missing B service, a late A service, duplicates, incorrect command or
address, out-of-order reads and completions exactly on the deadline.
Additional cases replay identical B/B/A traffic with changed rules, reverse
the event sequence, disable one source, check latched evidence after further
traffic, and distinguish invalid plans, short captures and colliding selects
as UNKNOWN. The matrix produces a timeout for a completion one clock late.

The [byte program suite](test_byte_program.py) replaces an image through the pins without resetting the DUT. It checks history-dependent command length, read completion versus abort, multiple requests under one CS, invalid commands and addresses, incomplete images, branch targets outside a shortened image, and return to the original M5 profile. Both loaded images were also swept across all four modes and the same 22 phases per mode.

| Loaded image | Changing MISO bits measured over four modes | Launch to valid | Minimum setup | CS assertion to drive |
| --- | ---: | ---: | ---: | ---: |
| Command poll | 616 | 40.1–60.0 ns | 40.0 ns | 40.1–60.0 ns |
| Address stream | 1,144 | 40.1–60.0 ns | 40.0 ns | 40.1–60.0 ns |

The following per-mode figures are for the M5 compatibility image, rerun in the same M6 regression.

The independent SPI master ran 5 MHz SCLK against the 50 MHz system clock. Each mode was exercised at 22 launch offsets across one 20 ns system period, including offsets 0.1 ns before and after a system rising edge. Each offset included a first read and a repeat read. The monitor recorded resolved MISO transitions and checked the expected bit throughout a 20 ns setup / 10 ns hold window, including header bits and adjacent equal bits.

| SPI mode | Measured payload transitions | Launch edge to valid MISO | Minimum setup before sample | CS assertion to first MISO drive |
| --- | ---: | ---: | ---: | ---: |
| 0 | 264 | 40.1–60.0 ns | 40.0 ns | 40.1–60.0 ns |
| 1 | 264 | 40.1–60.0 ns | 40.0 ns | 40.1–60.0 ns |
| 2 | 264 | 40.1–60.0 ns | 40.0 ns | 40.1–60.0 ns |
| 3 | 264 | 40.1–60.0 ns | 40.0 ns | 40.1–60.0 ns |

Launch-to-valid spans 2.005–3.000 system periods depending on phase. The target selects the byte on the last address sample, one half-period before the first response launch. Timing above starts at the launch edge and uses only bits whose value changes. CS deassertion released the resolved MISO pad by the check 1 ps later in zero-delay RTL.

## Synthesis and basic timing

The commands below reproduce the M10 Yosys/ABC mapping and standalone prelayout OpenSTA estimate from the repository root using the same tool image and typical cell library as M9.

```sh
out=$(mktemp -d)
pdk_rev=2bbec755dc67ca3db0261c3d6163e15735d66710
lib=ihp-sg13cmos5l/libs.ref/sg13cmos5l_stdcell/lib/sg13cmos5l_stdcell_typ_1p20V_25C.lib
curl -fLsS "https://raw.githubusercontent.com/IHP-GmbH/IHP-Open-PDK/$pdk_rev/$lib" -o "$out/cells.lib"
echo "34163f3e7de9f854afac57332ba06f1739b78e7ac35660a8a5ddd39c570124ad  $out/cells.lib" | sha256sum -c -
docker run --rm --entrypoint bash -v "$PWD:/work:ro" -v "$out:/out" -w /work \
  -e LIBERTY=/out/cells.lib -e ESTIMATE_DIR=/out \
  ghcr.io/librelane/librelane@sha256:d109140b8f17fc54f4fca998beb8124f4949404ec52e339eebd2250854a18b5a \
  test/synth_estimate.sh
```

The [synthesis script](synth_estimate.sh) writes the mapped netlist and `yosys.log` in the output directory. Yosys 0.66 completed the structural check and mapped the flattened top to the IHP SG13 CMOS5L typical library (1.20 V, 25 °C). M4 and M5 also have historical [prelayout STA](prelayout_sta.tcl) results at an ideal 20 ns clock; STA was not run for M6.

| Quantity | M4 baseline | M5 | M6 | M7 | M8 | M9 | M10 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Mapped standard cells (excluding Yosys metadata) | 1,209 | 1,761 | 1,948 | 3,244 | 4,837 | 5,524 | 5,774 |
| Flip-flops | 286 | 390 | 388 | 601 | 982 | 1,122 | 1,165 |
| Sum of library cell areas | 24,464.727 µm² | 33,109.322 µm² | 34,346.857 µm² | 54,630.072 µm² | 86,161.055 µm² | 98,186.218 µm² | 102,546.070 µm² |
| Sequential cell area | 14,010.797 µm² | 19,105.632 µm² | 19,007.654 µm² | 29,442.269 µm² | 48,107.002 µm² | 54,965.434 µm² | 57,071.952 µm² |
| Worst reported register-to-register setup slack | +16.978 ns | +17.144 ns | — | +15.232 ns | +15.237 ns | +12.905 ns | +12.677 ns |
| Register to bit-7 data / enable block-port arrival | — | 0.807 ns / 0.761 ns | — | 0.769 ns / 0.810 ns | 0.760 ns / 0.805 ns | 0.907 ns / 0.860 ns | 0.787 ns / 0.894 ns |

Relative to M9 the mapped area increased by 4,359.852 µm² (4.44%).
The estimates use an ideal 20 ns clock before placement, routing and pad
delays. The separate M8 physical measurements below apply only to M8.

## External timing and remaining risks

For the documented clocked reply program, both request values enabled P2 on the **sixth system rising edge** after P0 rose in the exercised phase. At 50 MHz, with the peer changing P0 halfway between system rising edges, that sixth edge occurs 110 ns later. A 5 MHz peer sampling on the next falling edge gives only 100 ns. This particular program and phase already miss that deadline before pad delays or peer setup time. The positive internal setup slack does not resolve this protocol latency.

The sequencer has no edge queue. An external transition during another instruction can be lost, and the suite does not exhaust program images or input phases. Reset and EXIT restore UART output enables, so the peer must release shared pins beforehand. Digital X resolution can flag ownership errors; it cannot measure pad skew, electrical contention, or metastability.

The accelerated byte interpreter executes one rule per eight clocks on the external bus. The measured timing covers a digital controller using a 50% duty cycle and changing MOSI on launch edges. The minimum MOSI setup/hold aperture, synchronizer metastability, noisy clocks, arbitrary duty cycles and worst-case physical delay through the new rule decoder remain uncharacterized.

## M8 physical feasibility

A subsequent Tiny Tapeout `ttihp27a` run on IHP SG13 CMOS5L routed the 8×4 macro at 50 MHz. The build copy supplied the three empty submission fields in `info.yaml` (title, author and description). Official synthesis mapped 105,248.619 µm² of cells. Post-route core utilization before filler was 10.73%. Across three cell corners with nominal extracted RC, worst setup slack was +4.902 ns and worst hold slack was +0.114 ns.

Magic GDS DRC reported zero errors, configured Netgen LVS matched uniquely, and all 10 Tiny Tapeout Precheck checks passed. The hardening run took 55 min 35 s. STA reported 67 clock-tree fanout violations outside the flow's pass/fail gates. The system-clock constraints and macro-level extraction leave the external 5 MHz SPI timing budget open.
